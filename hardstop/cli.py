"""HardStop command line."""
import argparse
import json
import sys
from .workflow import Workflow, DEFAULT_STATE, safe_error

def main():
    parser = argparse.ArgumentParser(description='HardStop: deadline-aware recorded presentation delivery')
    parser.add_argument('--state-dir', default=str(DEFAULT_STATE))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('seed', help='Create fictional demo assets in the three connected apps')
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
