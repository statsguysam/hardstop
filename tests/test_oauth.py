"""Offline OAuth contracts; isolated synthetic credentials never touch live setup."""
import contextlib
import hashlib
import base64
import io
import json
import os
import stat
from http.client import HTTPConnection
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import configure

DROPBOX_SCOPES = ("files.content.read", "files.content.write", "files.metadata.read")
GOOGLE_SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",
                 "https://www.googleapis.com/auth/gmail.compose",
                 "https://www.googleapis.com/auth/drive.file")


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hardstop-test-oauth-")
        self.addCleanup(self.temporary.cleanup)
        self.credentials = Path(self.temporary.name) / ".credentials"
        patcher = patch.object(configure, "CREDENTIALS", self.credentials)
        patcher.start()
        self.addCleanup(patcher.stop)

    @unittest.skipUnless(os.name == "posix", "POSIX private-file permissions")
    def test_private_credentials_have_owner_only_permissions(self):
        configure.write_private("synthetic.json", {"token": "synthetic-private-token"})
        self.assertEqual(stat.S_IMODE(self.credentials.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.credentials / "synthetic.json").stat().st_mode), 0o600)
        self.assertEqual(configure.read_private("synthetic.json"), {"token": "synthetic-private-token"})

    def test_private_storage_rejects_path_traversal_and_symlinks(self):
        with self.assertRaises(configure.SetupError):
            configure.write_private("../escape.json", {"token": "synthetic-private-token"})
        target = Path(self.temporary.name) / "target.json"
        target.write_text('{"token":"untouched"}')
        self.credentials.mkdir()
        (self.credentials / "link.json").symlink_to(target)
        with self.assertRaises(configure.SetupError):
            configure.write_private("link.json", {"token": "synthetic-private-token"})
        with self.assertRaises(configure.SetupError):
            configure.read_private("link.json")
        self.assertEqual(target.read_text(), '{"token":"untouched"}')

    def test_malformed_private_json_error_does_not_echo_content(self):
        self.credentials.mkdir()
        (self.credentials / "broken.json").write_text('synthetic-private-token invalid JSON')
        with self.assertRaises(configure.SetupError) as caught:
            configure.read_private("broken.json")
        self.assertNotIn("synthetic-private-token", str(caught.exception))

    def test_http_redirect_handler_declines_redirecting_credentials(self):
        self.assertIsNone(configure.NoRedirect().redirect_request(
            None, None, 302, "Found", {}, "https://untrusted.example/"))
        failure = HTTPError("https://provider.example/synthetic-private-token", 302,
                            "synthetic-private-token", {"Location":"https://untrusted.example/"},
                            io.BytesIO(b"synthetic-private-token"))
        with patch.object(configure.HTTP, "open", side_effect=failure):
            with self.assertRaises(configure.RemoteError) as caught:
                configure.request_bytes("https://provider.example/", headers={"Authorization":"Bearer synthetic-private-token"})
        self.assertEqual(caught.exception.status, 302)
        self.assertNotIn("synthetic-private-token", str(caught.exception))

    def dropbox_response(self, **overrides):
        result = {"access_token": "synthetic-dropbox-access", "refresh_token": "synthetic-dropbox-refresh",
                  "expires_in": 14400, "scope": " ".join(DROPBOX_SCOPES)}
        result.update(overrides)
        return result

    def test_dropbox_initial_grant_requires_refresh_token_and_all_scopes(self):
        for removed in ("refresh_token", "scope"):
            response = self.dropbox_response()
            response.pop(removed)
            with self.subTest(removed=removed), self.assertRaises(configure.SetupError):
                configure.dropbox_token_record(response, "synthetic-app-key")
        for missing_scope in DROPBOX_SCOPES:
            response = self.dropbox_response(scope=" ".join(scope for scope in DROPBOX_SCOPES if scope != missing_scope))
            with self.subTest(scope=missing_scope), self.assertRaises(configure.SetupError):
                configure.dropbox_token_record(response, "synthetic-app-key")

    def test_dropbox_refresh_preserves_existing_refresh_token(self):
        previous = configure.dropbox_token_record(self.dropbox_response(), "synthetic-app-key")
        refreshed = configure.dropbox_token_record({"access_token": "synthetic-new-access", "expires_in": 14400},
                                                   "synthetic-app-key", previous=previous)
        self.assertEqual(refreshed["refresh_token"], previous["refresh_token"])
        self.assertEqual(refreshed["scope"], previous["scope"])
        self.assertEqual(refreshed["app_key"], "synthetic-app-key")

    def test_dropbox_near_expiry_refresh_is_persisted_before_use(self):
        token = configure.dropbox_token_record(self.dropbox_response(), "synthetic-app-key")
        token["expires_at"] = time.time() + 15
        configure.write_private("dropbox.json", token)
        with patch.object(configure, "request_json", return_value={"access_token": "synthetic-refreshed-access", "expires_in": 14400}) as request:
            result = configure.dropbox_access_token()
        self.assertEqual(result, "synthetic-refreshed-access")
        stored = configure.read_private("dropbox.json")
        self.assertEqual(stored["access_token"], result)
        self.assertEqual(stored["refresh_token"], "synthetic-dropbox-refresh")
        self.assertGreater(stored["expires_at"], time.time() + 60)
        self.assertEqual(request.call_args.kwargs["form"]["grant_type"], "refresh_token")
        self.assertEqual(request.call_args.kwargs["form"]["client_id"], "synthetic-app-key")
        self.assertNotIn("client_secret", request.call_args.kwargs["form"])

    def test_legacy_generated_dropbox_token_requires_no_refresh(self):
        configure.write_private("dropbox.json", {"access_token": "synthetic-legacy-token"})
        with patch.object(configure, "request_json", side_effect=AssertionError("Legacy token should not trigger refresh")):
            self.assertEqual(configure.dropbox_access_token(), "synthetic-legacy-token")

    def test_google_authorization_requests_only_required_scopes_and_offline_access(self):
        configure.write_private("google-client.json", {"client_id": "synthetic-client", "client_secret": "synthetic-client-secret"})
        received = ("synthetic-code", "synthetic-verifier", "http://127.0.0.1:34567/oauth/callback")
        response = {"access_token": "synthetic-access", "refresh_token": "synthetic-refresh", "expires_in": 3600,
                    "scope": " ".join(configure.SCOPES)}
        with patch.object(configure, "receive_oauth_code", return_value=received) as receive, patch.object(configure, "request_json", return_value=response) as request:
            configure.authorize_google(timeout=30, no_browser=True)
        parameters = receive.call_args.args[2]
        self.assertEqual(set(parameters["scope"].split()), set(GOOGLE_SCOPES))
        self.assertEqual(parameters["access_type"], "offline")
        self.assertEqual(receive.call_args.args[-1], True)
        self.assertEqual(request.call_args.args[0], configure.GOOGLE_TOKEN)
        self.assertEqual(request.call_args.kwargs["form"]["code_verifier"], received[1])
        self.assertEqual(configure.read_private("google-token.json")["refresh_token"], "synthetic-refresh")

    def test_dropbox_authorization_uses_pkce_offline_access_without_client_secret(self):
        received = ("synthetic-code", "synthetic-verifier", "http://127.0.0.1:8765/dropbox/callback")
        with patch.object(configure, "receive_oauth_code", return_value=received) as receive, patch.object(configure, "request_json", return_value=self.dropbox_response()) as request:
            configure.authorize_dropbox("synthetic-app-key", timeout=30, no_browser=True)
        parameters = receive.call_args.args[2]
        self.assertEqual(set(parameters["scope"].split()), set(DROPBOX_SCOPES))
        self.assertEqual(parameters["token_access_type"], "offline")
        self.assertEqual(receive.call_args.args[-1], True)
        self.assertEqual(request.call_args.args[0], configure.DROPBOX_TOKEN)
        self.assertEqual(request.call_args.kwargs["form"]["code_verifier"], received[1])
        self.assertNotIn("client_secret", request.call_args.kwargs["form"])
        self.assertEqual(configure.read_private("dropbox.json")["app_key"], "synthetic-app-key")

    def exercise_local_start(self, provider, endpoint, parameters, callback_path):
        ready = threading.Event()

        class CapturedOutput(io.StringIO):
            def write(self, value):
                result = super().write(value)
                if "\n" in value:
                    ready.set()
                return result

        output, result, errors = CapturedOutput(), [], []

        def receive():
            try:
                result.append(configure.receive_oauth_code(provider, endpoint, parameters, callback_path, 0, timeout=5, no_browser=True))
            except Exception as exc:
                errors.append(exc)
                ready.set()

        with contextlib.redirect_stdout(output), patch.object(configure.webbrowser, "open", side_effect=AssertionError("No-browser must not launch provider page")):
            worker = threading.Thread(target=receive, daemon=True)
            worker.start()
            try:
                self.assertTrue(ready.wait(3), "Local OAuth listener did not start")
                if errors:
                    raise errors[0]
                notice = json.loads(output.getvalue())
                start = urlparse(notice["url"])
                self.assertEqual((start.scheme, start.hostname, start.path, start.query), ("http", "127.0.0.1", "/start", ""))
                self.assertNotEqual(start.port, 8765)

                def local_request(path):
                    connection = HTTPConnection("127.0.0.1", start.port, timeout=2)
                    try:
                        connection.request("GET", path)
                        response = connection.getresponse()
                        response.read()
                        return response.status, response.getheader("Location")
                    finally:
                        connection.close()

                status, location = local_request("/start")
                self.assertEqual(status, 302)
                destination = urlparse(location)
                self.assertEqual(destination.scheme + "://" + destination.netloc + destination.path, endpoint)
                query = parse_qs(destination.query)
                for key, value in parameters.items():
                    self.assertEqual(query[key], [value])
                self.assertEqual(query["code_challenge_method"], ["S256"])
                self.assertEqual(query["response_type"], ["code"])
                wrong_path = callback_path + "?" + urlencode({"state": "wrong-state", "code": "synthetic-code"})
                self.assertEqual(local_request(wrong_path)[0], 400)
                good_path = callback_path + "?" + urlencode({"state": query["state"][0], "code": "synthetic-code"})
                self.assertEqual(local_request(good_path)[0], 200)
            finally:
                worker.join(6)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        code, verifier, redirect = result[0]
        self.assertEqual(code, "synthetic-code")
        expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        self.assertEqual(query["code_challenge"], [expected_challenge])
        self.assertEqual(query["redirect_uri"], [redirect])
        for sensitive in (code, verifier, query["state"][0], expected_challenge, endpoint):
            self.assertNotIn(sensitive, output.getvalue())

    def test_google_no_browser_start_redirect_keeps_oauth_material_out_of_output(self):
        self.exercise_local_start("google", configure.GOOGLE_AUTH,
            {"client_id": "synthetic-client", "scope": " ".join(configure.SCOPES), "access_type": "offline", "prompt": "consent"}, "/oauth/callback")

    def test_dropbox_no_browser_start_redirect_keeps_oauth_material_out_of_output(self):
        self.exercise_local_start("dropbox", configure.DROPBOX_AUTH,
            {"client_id": "synthetic-app-key", "scope": " ".join(DROPBOX_SCOPES), "token_access_type": "offline"}, "/dropbox/callback")


if __name__ == "__main__":
    unittest.main()
