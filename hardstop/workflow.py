"""Journaled real-API workflow; successful receipts are point-in-time evidence."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import uuid
import configure
from .interpret import interpret_brief, InterpretationError
from .media import make_demo_assets, probe, render_cut, sha256_file
from .planner import plan, verify_selection
from .providers import Providers, ProviderError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / '.state'

def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

def read_json(path, default=None):
    try: return json.loads(Path(path).read_text())
    except FileNotFoundError: return default

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with open(temporary, 'x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)

@contextmanager
def exclusive(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a+') as stream:
        try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another workflow operation is already running') from None
        try: yield
        finally: fcntl.flock(stream, fcntl.LOCK_UN)

def safe_error(exc):
    if isinstance(exc, (ProviderError, configure.SetupError, InterpretationError, ValueError)):
        return str(exc)[:500]
    return f'{type(exc).__name__}: operation failed; inspect local diagnostics before retrying'

class StaleInput(ValueError): pass

class Workflow:
    def __init__(self, state_dir=DEFAULT_STATE, *, providers=None, interpreter=None, renderer=None):
        self.state = Path(state_dir).resolve()
        self.state.mkdir(parents=True, exist_ok=True)
        self.providers = providers or Providers()
        self.interpreter = interpreter or interpret_brief
        self.renderer = renderer or render_cut

    def fixtures(self): return read_json(ROOT / 'fixtures/briefs.json')

    def source(self):
        source = read_json(self.state / 'source.json')
        if source is None: raise ValueError('Run demo setup first: python3 -m hardstop.cli seed')
        return source

    def seed(self):
        with exclusive(self.state / 'run.lock'):
            existing = read_json(self.state / 'source.json')
            if existing: return existing
            manifest = make_demo_assets(ROOT / 'fixtures/catalog.json', self.state / 'demo-assets')
            journal_path = self.state / 'seed.json'
            journal = read_json(journal_path, {'id': uuid.uuid4().hex[:12], 'uploads': {}, 'created_at': now()})
            if journal.get('pending') == 'create_draft' and not journal.get('draft_id'):
                raise ValueError('A prior Gmail draft creation is unresolved. Reconcile it before setup continues.')
            def save(**values):
                journal.update(values)
                atomic_json(journal_path, journal)
            try:
                if not journal.get('deck'):
                    if journal.get('pending') == 'create_deck' and not journal.get('presentation_id'):
                        raise ValueError('A prior source deck creation is unresolved; reconcile before continuing')
                    save(pending='create_deck')
                    deck = self.providers.create_source_deck(manifest, presentation_id=journal.get('presentation_id'),
                        on_created=lambda value: save(presentation_id=value))
                    save(deck=deck, pending=None)
                remote = {key: value for key, value in manifest.items() if key != 'segments'}
                remote['segments'] = []
                for segment in manifest['segments']:
                    item = {key: value for key, value in segment.items() if key not in ('media_path', 'card_path')}
                    path = f"/hardstop-source-{journal['id']}-{item['id']}-{item['sha256'][:8]}.mp4"
                    item['dropbox_path'] = path
                    if item['id'] not in journal['uploads']:
                        if journal.get('pending') == path:
                            check = self.state / 'reconcile.mp4'
                            meta = self.providers.download(path, check)
                            if meta['sha256'] != item['sha256']: raise ValueError('Unresolved source upload has unexpected content')
                            check.unlink()
                        else:
                            save(pending=path)
                            meta = self.providers.upload(path, segment['media_path'])
                        journal['uploads'][item['id']] = {'rev': meta['rev'], 'sha256': item['sha256'], 'path': path}
                        save(pending=None)
                    item['dropbox_rev'] = journal['uploads'][item['id']]['rev']
                    remote['segments'].append(item)
                remote['presentation_id'] = journal['deck']['presentation_id']
                remote['deck_fingerprint'] = journal['deck']['fingerprint']
                catalog_path = self.state / 'cloud-catalog.json'
                atomic_json(catalog_path, remote)
                cloud_path = f"/hardstop-catalog-{journal['id']}.json"
                if not journal.get('catalog'):
                    if journal.get('pending') == cloud_path:
                        meta = self.providers.download(cloud_path, self.state / 'reconcile-catalog.json')
                        if meta['sha256'] != sha256_file(catalog_path): raise ValueError('Unresolved catalog upload differs from expected source')
                    else:
                        save(pending=cloud_path)
                        meta = self.providers.upload(cloud_path, catalog_path)
                    save(catalog={'path': cloud_path, 'rev': meta['rev'], 'sha256': sha256_file(catalog_path)}, pending=None)
                if not journal.get('draft_id'):
                    fixture = self.fixtures()['original']
                    save(pending='create_draft')
                    draft = self.providers.create_draft(fixture['subject'], fixture['body'])
                    save(draft_id=draft['draft_id'], pending=None)
                    atomic_json(self.state / 'brief-cache.json', draft)
                source = dict(remote, brief_draft_id=journal['draft_id'], catalog=journal['catalog'], seed_id=journal['id'])
                atomic_json(self.state / 'source.json', source)
                save(completed_at=now(), pending=None)
                return source
            except ProviderError as exc:
                if exc.presentation_id: journal['presentation_id'] = exc.presentation_id
                if exc.draft_id: journal['draft_id'] = exc.draft_id
                save(error=safe_error(exc))
                raise

    def set_brief(self, scenario):
        fixtures = self.fixtures()
        if scenario not in fixtures: raise ValueError('Unknown demo scenario')
        fixture = fixtures[scenario]
        return self.set_custom_brief(fixture['subject'], fixture['body'])

    def set_custom_brief(self, subject, body):
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 200 or any(c in subject for c in ('\r', '\n', '\x00')):
            raise ValueError('Use a single-line subject of 1–200 characters')
        if not isinstance(body, str) or not body.strip() or len(body) > 20000 or '\x00' in body:
            raise ValueError('Use a brief of 1–20000 characters')
        with exclusive(self.state / 'brief.lock'):
            result = self.providers.update_draft(self.source()['brief_draft_id'], subject, body)
            atomic_json(self.state / 'brief-cache.json', result)
            return result

    def reserve_run(self, run_id=None):
        run_id = run_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id): raise ValueError('Invalid run ID')
        path = self.state / 'runs' / run_id
        path.mkdir(parents=True, exist_ok=False)
        report = {'id': run_id, 'status': 'running', 'stage': 'queued', 'started_at': now(),
                  'events': [], 'checks': [], 'outputs': {}, 'source': {}}
        atomic_json(path / 'report.json', report)
        return run_id

    def run(self, run_id=None, *, reserved=False):
        if run_id and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id): raise ValueError('Invalid run ID')
        with exclusive(self.state / 'run.lock'):
            if run_id and not reserved:
                existing = read_json(self.state / 'runs' / run_id / 'report.json')
                if existing:
                    if existing['status'] == 'running':
                        existing.update(status='unknown', error='Interrupted run requires reconciliation; no writes retried', finished_at=now())
                        atomic_json(self.state / 'runs' / run_id / 'report.json', existing)
                    return existing
            run_id = run_id if reserved else self.reserve_run(run_id)
            folder = self.state / 'runs' / run_id
            report = read_json(folder / 'report.json')
            if not report or report['status'] != 'running': raise ValueError('Run is not reserved for execution')
            def save(): atomic_json(folder / 'report.json', report)
            def event(stage, message):
                report['stage'] = stage
                report['events'].append({'at': now(), 'stage': stage, 'message': message})
                save()
            def check(name, passed, detail):
                report['checks'].append({'name': name, 'passed': bool(passed), 'detail': detail})
                save()
                if not passed: raise ValueError('Verification failed (' + name + '): expected ' + detail)
            def record_output(key, value):
                report['outputs'][key] = value
                save()
            try:
                registered = self.source()
                event('reading', 'Reading the current Gmail brief, Google Slides source, and Dropbox catalog')
                brief = self.providers.read_draft(registered['brief_draft_id'])
                if brief.get('has_recipients'): raise ValueError('The demo brief must remain an unaddressed draft')
                atomic_json(self.state / 'brief-cache.json', brief)
                deck = self.providers.read_deck(registered['presentation_id'])
                catalog_meta = self.providers.download(registered['catalog']['path'], folder / 'catalog.json')
                check('catalog_integrity', catalog_meta['sha256'] == registered['catalog']['sha256'], 'Dropbox catalog matches the registered source SHA-256')
                catalog = read_json(folder / 'catalog.json')
                segments = catalog['segments']
                check('source_deck', deck['fingerprint'] == catalog['deck_fingerprint'] and deck['slide_ids'] == [s['slide_id'] for s in segments],
                      'Source deck content and slide order match the registered recording')
                report['source'] = {'brief': brief, 'deck_id': registered['presentation_id'], 'deck_fingerprint': deck['fingerprint'],
                    'catalog_rev': catalog_meta['rev'], 'catalog_sha256': catalog_meta['sha256'], 'segments': segments}
                event('interpreting', 'The model is extracting the deadline, mandatory content, exclusions, and evidence quotes')
                interpretation = self.interpreter(brief['body'], segments)
                report['constraints'] = interpretation['constraints']
                report['model'] = interpretation.get('receipt', {})
                report['interpretation'] = interpretation.get('interpretation', {})
                selection = plan(segments, report['constraints'])
                report['plan'] = selection
                report['checks'].extend(selection['checks'])
                save()
                if selection['status'] != 'feasible':
                    report['status'] = selection['status']
                    event('blocked', '; '.join(selection['reasons']) or 'The brief needs review')
                    return self._finish(report, folder)
                selected = [s for s in segments if s['id'] in selection['selected_ids']]
                verified = verify_selection(segments, report['constraints'], selection['selected_ids'])
                check('independent_selection', verified['valid'], 'Selection independently satisfies explicit constraints and declared dependencies')
                event('downloading', f'Downloading {len(selected)} selected source recordings from Dropbox')
                paths, input_revs = [], {}
                for segment in selected:
                    destination = folder / 'inputs' / (segment['id'] + '.mp4')
                    meta = self.providers.download(segment['dropbox_path'], destination)
                    check('source_' + segment['id'], meta['sha256'] == segment['sha256'] and probe(destination)['duration_ms'] == segment['duration_ms'],
                          segment['id'] + ': downloaded hash and measured duration match the source')
                    input_revs[segment['dropbox_path']] = meta['rev']
                    paths.append(destination)
                def fresh():
                    current = self.providers.read_draft(registered['brief_draft_id'])
                    current_deck = self.providers.read_deck(registered['presentation_id'])
                    current_catalog = self.providers.metadata(registered['catalog']['path'])
                    if current['fingerprint'] != brief['fingerprint'] or current_deck['fingerprint'] != deck['fingerprint'] or current_catalog['rev'] != catalog_meta['rev']:
                        raise StaleInput('The brief, source deck, or catalog changed during this run; previous verified delivery is preserved')
                    for path, revision in input_revs.items():
                        if self.providers.metadata(path)['rev'] != revision: raise StaleInput('A selected source recording changed during this run')
                fresh()
                event('rendering', 'Rendering whole clips in source order, then decoding and measuring the completed MP4')
                media = self.renderer(paths, folder / 'cut.mp4')
                report['media'] = media
                check('measured_deadline', media['duration_ms'] <= report['constraints']['max_duration_ms'],
                      f"Actual output {media['duration_ms']} ms fits {report['constraints']['max_duration_ms']} ms")
                check('decode_verified', media.get('decode_verified') and media.get('has_audio') and media.get('has_video'), 'Full output decode succeeded with video and audio')
                fresh()
                event('deck', 'Copying the source Google Slides deck and retaining exactly the selected slides')
                copied = self.providers.copy_and_trim_deck(registered['presentation_id'], [s['slide_id'] for s in selected],
                    f"HardStop - {report['constraints']['max_duration_ms']/1000:g}-second version", on_copied=lambda value: record_output('presentation_id', value),
                    expected_source_fingerprint=deck['fingerprint'])
                check('copied_source_content', True, 'Copied deck content matches the captured source for the retained slides')
                record_output('presentation_url', 'https://docs.google.com/presentation/d/' + copied['presentation_id'] + '/edit')
                report['outputs']['deck_fingerprint'] = copied['fingerprint']
                fresh()
                event('uploading', 'Uploading the cut to Dropbox and downloading it again to verify exact bytes')
                remote_path = '/hardstop-cut-' + run_id + '.mp4'
                record_output('dropbox_path', remote_path)
                uploaded = self.providers.upload(remote_path, folder / 'cut.mp4')
                report['outputs']['dropbox_rev'] = uploaded['rev']
                save()
                downloaded = self.providers.download(remote_path, folder / 'readback.mp4')
                check('output_sha256', downloaded['sha256'] == media['sha256'], 'Dropbox output downloaded again with the exact rendered SHA-256')
                (folder / 'readback.mp4').unlink()
                actual_deck = self.providers.read_deck(copied['presentation_id'])
                check('matching_deck', actual_deck['slide_ids'] == [s['slide_id'] for s in selected] and actual_deck['fingerprint'] == copied['fingerprint'],
                      'Copied Google Slides deck matches selected recordings in content and order')
                fresh()
                event('handoff', 'Creating an unaddressed Gmail handoff draft with verified delivery evidence')
                link = self.providers.temporary_link(remote_path)
                included = ', '.join(identifier.replace('_', ' ') for identifier in selection['selected_ids'])
                body = ("Your cut is ready for review.\n\n"
                    f"Finished length: {media['duration_ms']/1000:.3f} seconds.\n"
                    f"Time limit: {report['constraints']['max_duration_ms']/1000:g} seconds.\n"
                    f"Included: {included}.\n\n"
                    "The required clips and their context are intact and in order. The video plays through, the slides match, and the saved video matches the rendered file.\n\n"
                    f"Matching slides: {report['outputs']['presentation_url']}\n"
                    f"Video download: {link}\n\n"
                    f"The download link is temporary. The video is also saved in the Dropbox app folder at {remote_path}.\n\n"
                    "These checks describe the files at the end of this run. Review before sharing.\n"
                    "Fictional example with synthesized narration. No email has been sent.\n")
                draft = self.providers.create_draft(
                    f"HardStop: {report['constraints']['max_duration_ms']/1000:g}-second version ready for review", body)
                record_output('draft_id', draft['draft_id'])
                check('handoff_readback', draft['body'] == body.rstrip('\n') and not draft.get('has_recipients'), 'Handoff draft read back exactly with no recipients')
                fresh()
                final_deck = self.providers.read_deck(copied['presentation_id'])
                final_video = self.providers.metadata(remote_path)
                check('final_outputs', final_deck['fingerprint'] == copied['fingerprint'] and final_video['rev'] == uploaded['rev'], 'Output deck and video revisions are unchanged at final verification')
                check('fresh_inputs', True, 'Brief, source deck, catalog, and media revisions rechecked before promotion')
                report['outputs']['video_url'] = f'/media/{run_id}/cut.mp4'
                report['status'] = 'ready'
                event('ready', 'Verified delivery ready for review. No email sent.')
            except StaleInput as exc:
                report['status'], report['error'] = 'stale', safe_error(exc)
                event('stale', report['error'])
            except Exception as exc:
                report['status'] = 'unknown' if isinstance(exc, ProviderError) and exc.uncertain else 'failed'
                report['error'] = safe_error(exc)
                if isinstance(exc, ProviderError):
                    for key in ('copy_id', 'presentation_id', 'draft_id'):
                        value = getattr(exc, key, None)
                        if value: report['outputs'][key] = value
                event(report['status'], report['error'])
            return self._finish(report, folder)

    def _finish(self, report, folder):
        report['finished_at'] = now()
        atomic_json(folder / 'report.json', report)
        if report['status'] == 'ready': atomic_json(self.state / 'latest_ready.json', {'id': report['id'], 'verified_at': report['finished_at']})
        return report

    def snapshot(self):
        source = read_json(self.state / 'source.json')
        reports = [read_json(path) for path in (self.state / 'runs').glob('*/report.json')]
        reports.sort(key=lambda report: report['started_at'], reverse=True)
        latest = read_json(self.state / 'latest_ready.json', {})
        ready = next((report for report in reports if report['id'] == latest.get('id')), None)
        return {'source': source, 'brief': read_json(self.state / 'brief-cache.json'), 'fixtures': self.fixtures(),
                'current_run': reports[0] if reports else None, 'last_ready': ready, 'runs': reports[:20], 'configured': source is not None}
