#!/usr/bin/env python3
"""Private, stdlib-only runtime credential setup. Never prints credential values."""
import argparse
import base64
import getpass
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import webbrowser

ROOT = Path(__file__).resolve().parent
CREDENTIALS = Path(os.environ.get("HARDSTOP_CREDENTIALS_DIR", str(ROOT / ".credentials"))).expanduser().resolve()
SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/drive.file",
)
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
DROPBOX_AUTH = "https://www.dropbox.com/oauth2/authorize"
DROPBOX_TOKEN = "https://api.dropboxapi.com/oauth2/token"
DROPBOX_SCOPES = ("files.content.read", "files.content.write", "files.metadata.read")


class SetupError(RuntimeError):
    """Messages must be safe to show without including upstream response bodies."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


HTTP = build_opener(NoRedirect())


class RemoteError(SetupError):
    def __init__(self, status=None, uncertain=False):
        self.status = status
        self.uncertain = uncertain
        super().__init__(f"Remote request failed (HTTP {status})" if status else "Remote request failed; outcome may be unknown")


def private_directory():
    if CREDENTIALS.is_symlink():
        raise SetupError("Credential directory must not be a symbolic link")
    CREDENTIALS.mkdir(mode=0o700, parents=True, exist_ok=True)
    CREDENTIALS.chmod(0o700)
    return CREDENTIALS


def write_private(name, value):
    if Path(name).name != name:
        raise SetupError("Invalid private filename")
    directory = private_directory()
    destination = directory / name
    if destination.is_symlink():
        raise SetupError("Private files must not be symbolic links")
    fd, temporary = tempfile.mkstemp(prefix=".writing-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        destination.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_private(name):
    if Path(name).name != name:
        raise SetupError("Invalid private filename")
    directory = private_directory()
    path = directory / name
    if path.is_symlink():
        raise SetupError("Private files must not be symbolic links")
    try:
        path.chmod(0o600)
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SetupError("Required runtime configuration is missing") from exc
    except (OSError, ValueError, UnicodeError) as exc:
        raise SetupError("Runtime configuration cannot be read") from exc
    if not isinstance(data, dict):
        raise SetupError("Runtime configuration must be a JSON object")
    return data


def required_text(data, key):
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise SetupError("Required runtime configuration is missing or malformed")
    return value


def request_bytes(url, *, method="GET", headers=None, body=None, timeout=30):
    request = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with HTTP.open(request, timeout=timeout) as response:
            data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise RemoteError(uncertain=method != "GET")
            return data
    except HTTPError as exc:
        # Deliberately discard response bodies, URLs, and headers: they may hold secrets.
        status = exc.code
        exc.close()
        raise RemoteError(status, uncertain=status >= 500) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise RemoteError(uncertain=method != "GET") from None


def request_json(url, *, method="GET", headers=None, payload=None, form=None):
    headers = dict(headers or {})
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode()
    elif form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urlencode(form).encode()
    raw = request_bytes(url, method=method, headers=headers, body=body)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise RemoteError(uncertain=method != "GET") from None
    if not isinstance(value, dict):
        raise RemoteError(uncertain=method != "GET")
    return value


def import_google_client(filename):
    try:
        value = json.loads(Path(filename).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise SetupError("Cannot read the downloaded Google Desktop client JSON") from None
    import_google_client_data(value)


def import_google_client_data(value):
    installed = value.get("installed") if isinstance(value, dict) else None
    if not isinstance(installed, dict):
        raise SetupError("Import a Google OAuth Desktop app client, not a web or service-account client")
    client = {key: required_text(installed, key) for key in ("client_id", "client_secret")}
    write_private("google-client.json", client)


def validated_callback(query, expected_state):
    states = query.get("state", [])
    if len(states) != 1 or not isinstance(states[0], str) or not states[0].isascii() or not secrets.compare_digest(states[0], expected_state):
        raise SetupError("OAuth callback state did not match")
    if "error" in query:
        raise SetupError("Authorization was not granted")
    codes = query.get("code", [])
    if len(codes) != 1 or not isinstance(codes[0], str) or not codes[0]:
        raise SetupError("OAuth callback did not contain one authorization code")
    return codes[0]


def token_record(response, *, previous=None):
    access = required_text(response, "access_token")
    try:
        expires = int(response.get("expires_in", 3600))
    except (ValueError, TypeError):
        raise SetupError("Google returned an invalid token lifetime") from None
    if not 0 < expires <= 86400:
        raise SetupError("Google returned an invalid token lifetime")
    scope = response.get("scope", (previous or {}).get("scope", ""))
    if not isinstance(scope, str) or not set(SCOPES).issubset(set(scope.split())):
        raise SetupError("Google did not grant all three required scopes; authorize again")
    refresh = response.get("refresh_token", (previous or {}).get("refresh_token"))
    record = {"access_token": access, "expires_at": time.time() + expires, "scope": scope, "token_type": "Bearer"}
    if refresh:
        record["refresh_token"] = required_text({"refresh_token": refresh}, "refresh_token")
    return record


def receive_oauth_code(provider, auth_endpoint, auth_parameters, callback_path, port, timeout=300, no_browser=False):
    """Receive one validated code, printing only an optional local start URL."""
    if not 1 <= timeout <= 300:
        raise SetupError("OAuth timeout must be between 1 and 300 seconds")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    outcome = {}
    deadline = time.monotonic() + timeout

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Default HTTP logs expose callback codes and state in the URL.

        def reply(self, status, body, location=None):
            encoded = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Connection", "close")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if self.headers.get_all("Host") != [host]:
                self.reply(403, "Request rejected.")
                return
            parsed = urlparse(self.path)
            if parsed.path == "/start" and not parsed.query:
                self.reply(302, "Continue authorization in the provider browser page.", url)
                return
            if parsed.path != callback_path:
                self.reply(404, "Not found.")
                return
            query = parse_qs(parsed.query, keep_blank_values=True)
            try:
                code = validated_callback(query, state)
            except SetupError:
                # A bad-state request must not consume the legitimate pending flow.
                if query.get("state") == [state] and "error" in query:
                    outcome["error"] = True
                self.reply(400, "Authorization could not be accepted. Return to the terminal.")
                return
            outcome["code"] = code
            self.reply(200, "Authorization received. You may close this tab and return to the terminal.")

    class LoopbackServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(min(2, max(0.01, deadline - time.monotonic())))
            return connection, address

        def handle_error(self, *_):
            pass  # Never print a traceback that might include callback request data.

    with LoopbackServer(("127.0.0.1", port), CallbackHandler) as server:
        server.timeout = 0.5
        host = f"127.0.0.1:{server.server_port}"
        redirect = "http://" + host + callback_path
        parameters = dict(auth_parameters, redirect_uri=redirect, response_type="code", state=state,
                          code_challenge=challenge, code_challenge_method="S256")
        url = auth_endpoint + "?" + urlencode(parameters)
        if no_browser:
            print(json.dumps({"status": "waiting_for_oauth", "provider": provider, "url": "http://" + host + "/start", "timeout_seconds": timeout}), flush=True)
        else:
            if not webbrowser.open(url, new=1):
                raise SetupError("Could not open the authorization browser; use --no-browser and open its local start URL")
            print("Complete authorization in the browser. Waiting up to five minutes.", flush=True)
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    if outcome.get("error"):
        raise SetupError("Authorization was not granted")
    if "code" not in outcome:
        raise SetupError("Authorization timed out; no authorization code was saved")
    return outcome["code"], verifier, redirect


def authorize_google(timeout=300, no_browser=False):
    client = read_private("google-client.json")
    client_id = required_text(client, "client_id")
    client_secret = required_text(client, "client_secret")
    code, verifier, redirect = receive_oauth_code("google", GOOGLE_AUTH,
        {"client_id": client_id, "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent"},
        "/oauth/callback", 0, timeout, no_browser)
    response = request_json(GOOGLE_TOKEN, method="POST", form={
        "client_id": client_id, "client_secret": client_secret,
        "code": code, "code_verifier": verifier,
        "redirect_uri": redirect, "grant_type": "authorization_code",
    })
    write_private("google-token.json", token_record(response))


def dropbox_token_record(response, app_key, *, previous=None):
    access = required_text(response, "access_token")
    refresh = required_text({"refresh_token": response.get("refresh_token", (previous or {}).get("refresh_token"))}, "refresh_token")
    app_key = required_text({"app_key": app_key}, "app_key")
    try:
        expires = int(response.get("expires_in", 0))
    except (ValueError, TypeError, OverflowError):
        raise SetupError("Dropbox returned an invalid token lifetime") from None
    if not 0 < expires <= 604800:
        raise SetupError("Dropbox returned an invalid token lifetime")
    scope = response.get("scope", (previous or {}).get("scope", ""))
    if not isinstance(scope, str) or not set(DROPBOX_SCOPES).issubset(set(scope.split())):
        raise SetupError("Dropbox did not grant all three required file scopes")
    return {"access_token": access, "refresh_token": refresh, "app_key": app_key,
            "expires_at": time.time() + expires, "scope": scope, "token_type": "Bearer"}


def authorize_dropbox(app_key, timeout=300, no_browser=False):
    app_key = required_text({"app_key": app_key}, "app_key")
    code, verifier, redirect = receive_oauth_code("dropbox", DROPBOX_AUTH,
        {"client_id": app_key, "scope": " ".join(DROPBOX_SCOPES), "token_access_type": "offline"},
        "/dropbox/callback", 8765, timeout, no_browser)
    response = request_json(DROPBOX_TOKEN, method="POST", form={
        "client_id": app_key, "code": code, "code_verifier": verifier,
        "redirect_uri": redirect, "grant_type": "authorization_code"})
    write_private("dropbox.json", dropbox_token_record(response, app_key))


def dropbox_access_token():
    token = read_private("dropbox.json")
    access = required_text(token, "access_token")
    if "expires_at" not in token and "refresh_token" not in token:
        return access  # Legacy developer token; live check determines its validity.
    try:
        expires = float(token.get("expires_at", 0))
    except (ValueError, TypeError):
        raise SetupError("Dropbox token expiry is malformed; authorize again") from None
    if not math.isfinite(expires):
        raise SetupError("Dropbox token expiry is malformed; authorize again")
    if expires > time.time() + 60:
        return access
    app_key = required_text(token, "app_key")
    response = request_json(DROPBOX_TOKEN, method="POST", form={
        "grant_type": "refresh_token", "refresh_token": required_text(token, "refresh_token"), "client_id": app_key})
    updated = dropbox_token_record(response, app_key, previous=token)
    write_private("dropbox.json", updated)
    return updated["access_token"]


def google_access_token():
    token = read_private("google-token.json")
    access = required_text(token, "access_token")
    try:
        expires = float(token.get("expires_at", 0))
    except (ValueError, TypeError):
        raise SetupError("Google token expiry is malformed; authorize again") from None
    if not math.isfinite(expires):
        raise SetupError("Google token expiry is malformed; authorize again")
    if expires > time.time() + 60:
        return access
    refresh = required_text(token, "refresh_token")
    client = read_private("google-client.json")
    response = request_json(GOOGLE_TOKEN, method="POST", form={
        "client_id": required_text(client, "client_id"),
        "client_secret": required_text(client, "client_secret"),
        "refresh_token": refresh, "grant_type": "refresh_token",
    })
    updated = token_record(response, previous=token)
    write_private("google-token.json", updated)
    return updated["access_token"]


def configuration_status(service):
    try:
        if service in ("gmail", "slides"):
            client = read_private("google-client.json")
            token = read_private("google-token.json")
            required_text(client, "client_id")
            required_text(client, "client_secret")
            required_text(token, "access_token")
            scope = required_text(token, "scope")
            if not set(SCOPES).issubset(set(scope.split())):
                raise SetupError("Required Google scopes are missing")
            expires = float(token.get("expires_at", 0))
            if not math.isfinite(expires):
                raise SetupError("Google token expiry is malformed")
            if expires <= time.time() + 60:
                required_text(token, "refresh_token")
        elif service == "dropbox":
            token = read_private("dropbox.json")
            required_text(token, "access_token")
            if "refresh_token" in token or "expires_at" in token:
                required_text(token, "refresh_token")
                required_text(token, "app_key")
                if not set(DROPBOX_SCOPES).issubset(set(required_text(token, "scope").split())):
                    raise SetupError("Required Dropbox file scopes are missing")
                if not math.isfinite(float(token.get("expires_at", 0))):
                    raise SetupError("Dropbox token expiry is malformed")
        elif service == "openai":
            config = read_private("openai.json")
            required_text(config, "api_key")
            required_text(config, "model")
        else:
            raise SetupError("Unknown service")
        return {"configured": True, "status": "configured_not_verified"}
    except (SetupError, TypeError, ValueError):
        return {"configured": False, "status": "missing_or_invalid_runtime_credentials"}


def main():
    parser = argparse.ArgumentParser(description="Set up private standalone API credentials; never paste secrets in chat.")
    sub = parser.add_subparsers(dest="command", required=True)
    client = sub.add_parser("google-client", help="Import downloaded Desktop OAuth client JSON")
    client.add_argument("file")
    google = sub.add_parser("google", help="Open local browser authorization with PKCE")
    google.add_argument("--timeout", type=int, default=300)
    google.add_argument("--no-browser", action="store_true", help="Print only a local start URL for your preferred browser")
    dropbox = sub.add_parser("dropbox", help="Authorize Dropbox with PKCE and offline refresh")
    dropbox.add_argument("--app-key", required=True, help="Public Dropbox app key (not its secret)")
    dropbox.add_argument("--timeout", type=int, default=300)
    dropbox.add_argument("--no-browser", action="store_true", help="Print only a local start URL for your preferred browser")
    sub.add_parser("dropbox-token", help="Enter a generated Dropbox developer token privately")
    openai = sub.add_parser("openai-key", help="Enter a standalone OpenAI API key privately")
    openai.add_argument("--model", default="gpt-6-astra")
    args = parser.parse_args()
    try:
        if args.command == "google-client":
            import_google_client(args.file)
        elif args.command == "google":
            authorize_google(args.timeout, args.no_browser)
        elif args.command == "dropbox":
            authorize_dropbox(args.app_key, args.timeout, args.no_browser)
        elif args.command == "dropbox-token":
            if not sys_stdin_is_terminal():
                raise SetupError("Use an interactive terminal so the token can be entered without echo")
            value = getpass.getpass("Dropbox developer access token (hidden): ").strip()
            write_private("dropbox.json", {"access_token": required_text({"value": value}, "value")})
        else:
            if not sys_stdin_is_terminal():
                raise SetupError("Use an interactive terminal so the key can be entered without echo")
            value = getpass.getpass("OpenAI API key (hidden): ").strip()
            model = required_text({"model": args.model}, "model")
            write_private("openai.json", {"api_key": required_text({"value": value}, "value"), "model": model})
        print(json.dumps({"status": "configuration_saved", "live_verification": "not_performed"}))
        return 0
    except (SetupError, OSError, KeyboardInterrupt, EOFError) as exc:
        message = str(exc) if isinstance(exc, SetupError) else "Setup did not complete; credential values were not printed"
        print(json.dumps({"status": "blocked", "reason": message}))
        return 2


def sys_stdin_is_terminal():
    import sys
    return sys.stdin.isatty()


if __name__ == "__main__":
    raise SystemExit(main())
