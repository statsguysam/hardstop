"""Registration of independent recordings; remote systems are isolated fakes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hardstop.providers import ProviderError
from hardstop.workflow import Workflow, atomic_json
from test_workflow import FakeProviders


class SourceProviders(FakeProviders):
    def create_source_deck(self, manifest, *, presentation_id=None, on_created=None):
        self.record('create_source_deck', manifest['title'], presentation_id, write=presentation_id is None)
        identifier = presentation_id or 'independent-source'
        if on_created and presentation_id is None:
            on_created(identifier)
        return {'presentation_id': identifier, 'fingerprint': 'source-content',
                'slide_ids': {s['id']: s['slide_id'] for s in manifest['segments']}}


class SourceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.state = self.root / 'workspace'
        self.providers = SourceProviders()
        self.workflow = Workflow(self.state, providers=self.providers)
        self.catalog = self.root / 'catalog.json'
        self.catalog.write_text('{}')
        self.manifest = {'title': 'Independent workshop', 'description': 'Source-owner supplied content',
                         'fictional': False, 'narration': 'Recorded by the source owner',
                         'source_kind': 'user_recordings', 'source_duration_ms': 6000,
                         'catalog_sha256': hashlib.sha256(self.catalog.read_bytes()).hexdigest(), 'segments': []}
        for index, identifier in enumerate(['setting', 'finding', 'next_step']):
            clip = self.root / (identifier + '.mp4')
            clip.write_bytes(('recorded:' + identifier).encode())
            self.manifest['segments'].append({'id': identifier, 'title': identifier, 'slide_text': identifier,
                'transcript': identifier, 'requires': ['setting'] if identifier == 'finding' else [],
                'value': 5, 'duration_ms': 2000, 'slide_id': 'hs_' + identifier,
                'media_path': str(clip), 'sha256': hashlib.sha256(clip.read_bytes()).hexdigest()})
        self.importer = patch('hardstop.source.import_source', return_value=copy.deepcopy(self.manifest))

    def persist_imported_manifest(self):
        assets = self.workflow.state / 'source-assets'
        assets.mkdir()
        manifest = copy.deepcopy(self.manifest)
        for segment in manifest['segments']:
            original = Path(segment['media_path'])
            installed = assets / original.name
            installed.write_bytes(original.read_bytes())
            segment['media_path'] = str(installed)
        atomic_json(assets / 'manifest.json', manifest)
        return assets

    def test_independent_source_registers_all_three_apps_without_demo_presets(self):
        with self.importer:
            result = self.workflow.import_recordings(self.catalog, 'Workshop brief', 'Fit within 6 seconds. Keep finding.')
        self.assertEqual([s['id'] for s in result['segments']], ['setting', 'finding', 'next_step'])
        self.assertFalse(result['fictional'])
        self.assertEqual(self.workflow.fixtures(), {})
        self.assertEqual(self.providers.drafts[result['brief_draft_id']]['subject'], 'Workshop brief')
        remote = json.loads(self.providers.files[result['catalog']['path']])
        self.assertTrue(all('media_path' not in s for s in remote['segments']))
        self.assertEqual(remote['segments'][1]['requires'], ['setting'])
        self.assertEqual(len([name for name, _ in self.providers.writes if name == 'create_source_deck']), 1)

    def test_existing_source_is_preserved_before_import_or_remote_writes(self):
        atomic_json(self.state / 'source.json', {'title': 'Keep this source'})
        with self.importer as imported, self.assertRaisesRegex(ValueError, 'already has a source'):
            self.workflow.import_recordings(self.catalog, 'New source', 'Fit within 60 seconds.')
        imported.assert_not_called()
        self.assertEqual(self.providers.writes, [])
        self.assertEqual(self.workflow.source()['title'], 'Keep this source')

    def test_changed_registration_cannot_resume_an_earlier_remote_write(self):
        original = self.providers.create_source_deck
        def fail_once(*args, **kwargs):
            original(*args, **kwargs)
            raise ProviderError('Populate source deck', uncertain=True, presentation_id='independent-source')
        self.providers.create_source_deck = fail_once
        with self.importer, self.assertRaises(ProviderError):
            self.workflow.import_recordings(self.catalog, 'Workshop brief', 'Fit within 6 seconds.')
        writes = len(self.providers.writes)
        self.providers.create_source_deck = original
        with self.importer, self.assertRaisesRegex(ValueError, 'inputs changed'):
            self.workflow.import_recordings(self.catalog, 'Changed brief', 'Fit within 60 seconds.')
        self.assertEqual(len(self.providers.writes), writes)
        self.assertFalse((self.state / 'source.json').exists())

    def test_changed_media_upload_blocks_registration(self):
        original = self.providers.upload
        def mismatched(path, local_file):
            result = original(path, local_file)
            result['sha256'] = '0' * 64
            return result
        self.providers.upload = mismatched
        with self.importer, self.assertRaisesRegex(ValueError, 'source upload differs'):
            self.workflow.import_recordings(self.catalog, 'Workshop brief', 'Fit within 6 seconds.')
        self.assertFalse((self.state / 'source.json').exists())
        self.assertFalse(self.providers.drafts)

    def test_invalid_initial_brief_does_not_import_or_contact_apps(self):
        with self.importer as imported, self.assertRaises(ValueError):
            self.workflow.import_recordings(self.catalog, 'Subject\nBcc: injected', 'Fit within 6 seconds.')
        imported.assert_not_called()
        self.assertEqual(self.providers.writes, [])

    def test_persisted_source_resumes_known_created_deck_without_reimport_or_duplicate_creation(self):
        assets = self.persist_imported_manifest()
        original = self.providers.create_source_deck
        def fail_after_creation(*args, **kwargs):
            original(*args, **kwargs)
            raise ProviderError('Populate source deck', uncertain=True, presentation_id='independent-source')
        self.providers.create_source_deck = fail_after_creation
        with self.importer as imported, patch('hardstop.workflow.probe', return_value={'duration_ms': 2000}):
            with self.assertRaises(ProviderError):
                self.workflow.import_recordings(self.catalog, 'Workshop brief', 'Fit within 6 seconds.')
            self.providers.create_source_deck = original
            result = self.workflow.import_recordings(self.catalog, 'Workshop brief', 'Fit within 6 seconds.')
            imported.assert_not_called()
        self.assertEqual(result['presentation_id'], 'independent-source')
        self.assertEqual(len([name for name, _ in self.providers.writes if name == 'create_source_deck']), 1)
        self.assertEqual(len([name for name, _ in self.providers.writes if name == 'create_draft']), 1)
        self.assertTrue((assets / 'manifest.json').is_file())
        self.assertTrue((self.workflow.state / 'source.json').is_file())

    def test_resume_rejects_symlinked_asset_directory_before_any_provider_call(self):
        assets = self.persist_imported_manifest()
        outside = self.root / 'outside-assets'
        assets.rename(outside)
        manifest_path = outside / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        for segment in manifest['segments']:
            segment['media_path'] = str(outside / Path(segment['media_path']).name)
        atomic_json(manifest_path, manifest)
        assets.symlink_to(outside, target_is_directory=True)
        with self.importer as imported, self.assertRaisesRegex(ValueError, 'symbolic links'):
            self.workflow.import_recordings(self.catalog, 'Workshop brief', 'Fit within 6 seconds.')
        imported.assert_not_called()
        self.assertEqual(self.providers.calls, [])
        self.assertTrue((outside / 'setting.mp4').is_file())

    def test_resume_rejects_nonregular_catalog_before_hashing_or_provider_calls(self):
        self.persist_imported_manifest()
        self.catalog.unlink()
        os.mkfifo(self.catalog)
        with self.assertRaisesRegex(ValueError, 'regular catalog'):
            self.workflow.import_recordings(self.catalog, 'Workshop brief', 'Fit within 6 seconds.')
        self.assertEqual(self.providers.calls, [])

    def test_resume_rejects_symlinked_recording_without_writes(self):
        assets = self.persist_imported_manifest()
        clip = assets / 'setting.mp4'
        clip.unlink()
        clip.symlink_to(self.root / 'setting.mp4')
        with self.assertRaisesRegex(ValueError, 'inside the source directory'):
            self.workflow.import_recordings(self.catalog, 'Workshop brief', 'Fit within 6 seconds.')
        self.assertEqual(self.providers.calls, [])
