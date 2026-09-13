"""HardStop command line."""
import argparse
import json
import os
from pathlib import Path
import stat
import sys
from .workflow import Workflow, DEFAULT_STATE, safe_error


def read_brief_file(path):
    """Read one bounded UTF-8 regular file without blocking on named pipes."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError('The brief must be a regular file')
            if before.st_size > 80000:
                raise ValueError('The brief file exceeds 80,000 bytes')
            raw = stream.read(80001)
            after = os.fstat(stream.fileno())
            if len(raw) > 80000:
                raise ValueError('The brief file exceeds 80,000 bytes')
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError('The brief file changed while being read')
        return raw.decode('utf-8').replace('\r\n', '\n').replace('\r', '\n')
    except UnicodeDecodeError:
        raise ValueError('The brief must be UTF-8 plain text') from None
    except OSError:
        raise ValueError('The brief must be a readable regular file, not a symbolic link') from None

def main():
    parser = argparse.ArgumentParser(description='HardStop: deadline-aware recorded presentation delivery')
    parser.add_argument('--state-dir', default=str(DEFAULT_STATE))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('seed', help='Create fictional demo assets in the three connected apps')
    source = commands.add_parser('source', help='Verify your recordings and register a new three-app workspace')
    source.add_argument('catalog', type=Path, help='Catalog JSON with relative MP4 paths and matching slide text')
    source.add_argument('--brief', type=Path, required=True, help='Plain-text producer brief')
    source.add_argument('--subject', default='HardStop producer brief', help='Subject of the dedicated Gmail draft')
    brief = commands.add_parser('brief', help='Update the actual Gmail demo draft')
    brief.add_argument('scenario', choices=['original', 'amendment', 'impossible', 'ambiguous'])
    run = commands.add_parser('run', help='Execute the real workflow')
    run.add_argument('--id', help='Idempotency key; an existing run is returned without repeating writes')
    commands.add_parser('status')
    serve = commands.add_parser('serve', help='Open a loopback-only review server')
    serve.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    workflow = Workflow(args.state_dir)
    try:
        if args.command == 'seed':
            result = workflow.seed()
            print(json.dumps({'status': 'seeded', 'segments': len(result['segments']), 'source_duration_ms': result['source_duration_ms'],
                              'presentation_id': result['presentation_id'], 'brief_draft_id': result['brief_draft_id']}, indent=2))
        elif args.command == 'source':
            result = workflow.import_recordings(args.catalog, args.subject, read_brief_file(args.brief))
            print(json.dumps({'status': 'registered', 'segments': len(result['segments']),
                              'source_duration_ms': result['source_duration_ms'],
                              'source_kind': result['source_kind']}, indent=2))
        elif args.command == 'brief':
            result = workflow.set_brief(args.scenario)
            print(json.dumps({'scenario': args.scenario, 'draft_id': result['draft_id'], 'fingerprint': result['fingerprint']}, indent=2))
        elif args.command == 'run':
            result = workflow.run(args.id)
            print(json.dumps({key: result.get(key) for key in ('id', 'status', 'stage', 'error', 'plan', 'media', 'outputs', 'model')}, indent=2))
            return 0 if result['status'] in ('ready', 'infeasible', 'needs_review', 'stale') else 1
        elif args.command == 'status':
            result = workflow.snapshot()
            print(json.dumps({'configured': result['configured'], 'current_run': result['current_run'], 'last_ready_id': (result['last_ready'] or {}).get('id')}, indent=2))
        elif args.command == 'serve':
            from .server import serve
            serve(workflow, args.port)
    except Exception as exc:
        print(safe_error(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
