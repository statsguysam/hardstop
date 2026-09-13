#!/usr/bin/env python3
"""One-time loopback form for private browser-to-local credential transfer."""
import argparse
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import time
from urllib.parse import parse_qs, urlsplit

import configure as config


def safe_origin_diagnostic(values, *, host=False):
    """Expose only normalized host/origin, never request body or arbitrary URL data."""
    if values is None:
        return "missing"
    if len(values) != 1:
        return "multiple"
    value = values[0]
    if value == "null" and not host:
        return "null"
    try:
        parsed = urlsplit("//" + value if host else value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            return "malformed"
        if not parsed.hostname or (not host and parsed.scheme not in ("http", "https")):
            return "malformed"
        name = parsed.hostname[:200]
        port = ":" + str(parsed.port) if parsed.port is not None else ""
        return name + port if host else parsed.scheme + "://" + name + port
    except (ValueError, TypeError):
        return "malformed"


def validate_submission(fields, expected_csrf, provider):
    csrf = fields.get("csrf", [])
    if len(csrf) != 1 or not isinstance(csrf[0], str) or not csrf[0].isascii() or not secrets.compare_digest(csrf[0], expected_csrf):
        raise config.SetupError("Form security check failed")
    values = fields.get("credential", [])
    if len(values) != 1:
        raise config.SetupError("Enter exactly one credential")
    credential = config.required_text({"value": values[0].strip()}, "value")
    if provider == "google-client":
        try:
            value = json.loads(credential)
        except (ValueError, TypeError):
            raise config.SetupError("Enter valid Google Desktop client JSON") from None
        config.import_google_client_data(value)
    elif provider == "dropbox":
        config.write_private("dropbox.json", {"access_token": credential})
    elif provider == "openai":
        models = fields.get("model", [])
        if len(models) != 1:
            raise config.SetupError("Enter exactly one model name")
        model = config.required_text({"model": models[0]}, "model")
        config.write_private("openai.json", {"api_key": credential, "model": model})
    else:
        raise config.SetupError("Unsupported credential provider")


def serve(provider, timeout=300, model="gpt-6-astra"):
    if provider not in ("google-client", "dropbox", "openai") or not 1 <= timeout <= 300:
        raise config.SetupError("Unsupported provider or timeout")
    csrf = secrets.token_urlsafe(32)
    outcome = {}
    deadline = time.monotonic() + timeout

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def allowed_host(self):
            return self.headers.get_all("Host") == [host]

        def reply(self, status, body):
            encoded = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            # no-referrer turns browser HTML form POST Origin into null.
            # same-origin preserves this local POST's exact Origin while hiding
            # referrers from cross-origin destinations.
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if not self.allowed_host() or self.path != "/":
                self.reply(403, "Request rejected.")
                return
            label = {"google-client": "Google Desktop client JSON (single line)", "dropbox": "Dropbox generated access token", "openai": "OpenAI API key"}[provider]
            model_field = '<label>Model <input name="model" value="' + html.escape(model, quote=True) + '"></label>' if provider == "openai" else ""
            self.reply(200, '<!doctype html><html><head><title>HardStop private credential transfer</title><style>body{font:18px system-ui;max-width:680px;margin:60px auto;padding:20px}label,input{display:block;margin:16px 0}input{width:95%;padding:12px}button{padding:12px}</style></head><body><h1>HardStop private credential transfer</h1><p>This one-time form stores the credential on this computer. It expires after five minutes. Do not put credentials in chat.</p><form method="post" action="/" autocomplete="off"><input type="hidden" name="csrf" value="' + csrf + '"><label>' + label + '<input type="password" name="credential" required autocomplete="off" spellcheck="false"></label>' + model_field + '<button type="submit">Save privately</button></form></body></html>')

        def do_POST(self):
            if not self.allowed_host() or self.path != "/" or self.headers.get_all("Origin") != [origin]:
                print(json.dumps({"status": "form_request_rejected", "host": safe_origin_diagnostic(self.headers.get_all("Host"), host=True), "origin": safe_origin_diagnostic(self.headers.get_all("Origin")), "expected_origin": origin}), flush=True)
                self.reply(403, "Request rejected.")
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/x-www-form-urlencoded" or self.headers.get("Transfer-Encoding"):
                self.reply(415, "Unsupported request.")
                return
            try:
                lengths = self.headers.get_all("Content-Length") or []
                if len(lengths) != 1:
                    raise ValueError
                length = int(lengths[0])
                if not 1 <= length <= 32768:
                    raise ValueError
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError
                fields = parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=5)
                validate_submission(fields, csrf, provider)
            except (config.SetupError, ValueError, TypeError, UnicodeError, OSError):
                self.reply(400, "Credential was not accepted. Return to the form and check the requested format.")
                return
            outcome["saved"] = True
            self.reply(200, "<!doctype html><title>Credential saved</title><h1>Credential saved privately</h1><p>This one-time receiver is now closed. Live API access has not yet been verified.</p>")

    class LoopbackServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(min(2, max(0.01, deadline - time.monotonic())))
            return connection, address

        def handle_error(self, *_):
            pass

    with LoopbackServer(("127.0.0.1", 0), Handler) as server:
        server.timeout = 0.5
        host = "127.0.0.1:" + str(server.server_port)
        origin = "http://" + host
        print(json.dumps({"status": "waiting_for_private_form", "provider": provider, "url": origin + "/", "timeout_seconds": timeout}), flush=True)
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    if not outcome.get("saved"):
        raise config.SetupError("Credential receiver expired without saving a credential")
    return {"status": "configuration_saved", "provider": provider, "live_verification": "not_performed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=("google-client", "dropbox", "openai"))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--model", default="gpt-6-astra")
    args = parser.parse_args()
    try:
        print(json.dumps(serve(args.provider, args.timeout, args.model)))
        return 0
    except (config.SetupError, OSError, KeyboardInterrupt) as exc:
        message = str(exc) if isinstance(exc, config.SetupError) else "Credential receiver did not complete"
        print(json.dumps({"status": "blocked", "reason": message}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
