"""Local review surface with explicit routes and same-origin mutation controls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit
from .workflow import ROOT, atomic_json, now, read_json, safe_error

class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, workflow, port):
        super().__init__(('127.0.0.1', port), Handler)
        self.workflow = workflow
        self.csrf = secrets.token_urlsafe(32)
        self.worker = None
        self.mutex = threading.Lock()
        self.origin = f'http://127.0.0.1:{self.server_port}'

class Handler(BaseHTTPRequestHandler):
    server_version = 'HardStop'
    def log_message(self, format, *args): pass
    def allowed(self, mutation=False):
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}': return False
        origin = self.headers.get('Origin')
        if origin and origin != self.server.origin: return False
        if self.headers.get('Sec-Fetch-Site') == 'cross-site': return False
        return not mutation or (origin == self.server.origin and secrets.compare_digest(self.headers.get('X-HardStop-CSRF', '').encode('utf-8'), self.server.csrf.encode('utf-8')))
    def response_headers(self, status, length, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
    def json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.response_headers(status, len(body), 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(body)
    def invalid_range(self, size):
        self.response_headers(416, 0, 'video/mp4')
        self.send_header('Content-Range', f'bytes */{size}')
        self.end_headers()
    def do_GET(self):
        if not self.allowed(): return self.json({'error': 'Local origin required'}, 403)
        path = urlsplit(self.path).path
        if path == '/api/state':
            result = self.server.workflow.snapshot()
            result['csrf'] = self.server.csrf
            return self.json(result)
        static = {'/': ('index.html', 'text/html'), '/app.css': ('app.css', 'text/css'), '/app.js': ('app.js', 'text/javascript')}
        if path in static:
            name, kind = static[path]
            data = (ROOT / 'web' / name).read_bytes()
            self.response_headers(200, len(data), kind + '; charset=utf-8')
            self.end_headers()
            return self.wfile.write(data)
        match = re.fullmatch(r'/media/([A-Za-z0-9_-]{1,80})/cut\.mp4', path)
        if match:
            runs = (self.server.workflow.state / 'runs').resolve()
            folder = runs / match[1]
            if folder.is_symlink() or (folder / 'report.json').is_symlink() or folder.resolve().parent != runs:
                return self.json({'error': 'Media not available'}, 404)
            try:
                report = read_json(folder / 'report.json', {})
            except (ValueError, OSError):
                return self.json({'error': 'Media not available'}, 404)
            if not isinstance(report, dict): return self.json({'error': 'Media not available'}, 404)
            if report.get('status') != 'ready': return self.json({'error': 'Verified output not available'}, 404)
            media = folder / 'cut.mp4'
            if not media.is_file() or media.is_symlink(): return self.json({'error': 'Media not available'}, 404)
            size = media.stat().st_size
            if not size: return self.json({'error': 'Media not available'}, 404)
            start, end, status = 0, size - 1, 200
            value = self.headers.get('Range')
            if value:
                if len(value) > 100: return self.invalid_range(size)
                range_match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
                if not range_match or not any(range_match.groups()): return self.invalid_range(size)
                if not range_match[1]: start = max(0, size - int(range_match[2]))
                else:
                    start = int(range_match[1])
                    if range_match[2]: end = min(end, int(range_match[2]))
                if start > end or start >= size: return self.invalid_range(size)
                status = 206
            self.response_headers(status, end - start + 1, 'video/mp4')
            self.send_header('Accept-Ranges', 'bytes')
            if status == 206: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            try:
                with open(media, 'rb') as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        data = stream.read(min(65536, remaining))
                        if not data: break
                        self.wfile.write(data)
                        remaining -= len(data)
            except (BrokenPipeError, ConnectionResetError): pass
            return
        return self.json({'error': 'Not found'}, 404)
    def do_POST(self):
        if not self.allowed(True): return self.json({'error': 'Same-origin request and CSRF token required'}, 403)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json': return self.json({'error': 'JSON required'}, 415)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 1 <= length <= 32768: raise ValueError('Invalid body size')
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict): raise ValueError('JSON object required')
            path = urlsplit(self.path).path
            if path == '/api/brief':
                if 'body' in value:
                    return self.json({'brief': self.server.workflow.set_custom_brief(value.get('subject'), value['body'])})
                return self.json({'brief': self.server.workflow.set_brief(value.get('scenario'))})
            if path == '/api/run':
                with self.server.mutex:
                    if self.server.worker and self.server.worker.is_alive(): return self.json({'error': 'A run is already active'}, 409)
                    run_id = self.server.workflow.reserve_run()
                    def work():
                        try: self.server.workflow.run(run_id, reserved=True)
                        except Exception as exc:
                            file = self.server.workflow.state / 'runs' / run_id / 'report.json'
                            report = read_json(file)
                            report.update(status='failed', error=safe_error(exc), finished_at=now())
                            atomic_json(file, report)
                    self.server.worker = threading.Thread(target=work, daemon=True)
                    self.server.worker.start()
                return self.json({'run_id': run_id}, 202)
            return self.json({'error': 'Not found'}, 404)
        except (ValueError, TypeError) as exc: return self.json({'error': safe_error(exc)}, 400)
        except Exception as exc: return self.json({'error': safe_error(exc)}, 502)

def serve(workflow, port=8766):
    if not 1024 <= port <= 65535: raise ValueError('Port must be between 1024 and 65535')
    server = ReviewServer(workflow, port)
    print(f'HardStop review: {server.origin}', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
