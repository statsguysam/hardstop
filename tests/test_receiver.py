import json
from pathlib import Path
import queue
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import configure
import receive_credentials as receiver


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hardstop-test-receiver-")
        self.patch = patch.object(configure, "CREDENTIALS", Path(self.temporary.name) / ".credentials")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temporary.cleanup()

    def test_csrf_rejection_never_saves(self):
        for csrf in ([], ["wrong"], ["α"], ["expected", "expected"]):
            with self.subTest(csrf=csrf), patch.object(configure, "write_private") as writer:
                with self.assertRaises(configure.SetupError):
                    receiver.validate_submission({"csrf": csrf, "credential": ["secret-example"]}, "expected", "dropbox")
                writer.assert_not_called()

    def test_google_client_validated_and_secret_stays_private(self):
        fields = {"csrf": ["expected"], "credential": [json.dumps({"installed": {"client_id": "example-client", "client_secret": "secret-example"}, "ignored": "field"})]}
        receiver.validate_submission(fields, "expected", "google-client")
        self.assertEqual(configure.read_private("google-client.json"), {"client_id": "example-client", "client_secret": "secret-example"})
        fields["credential"] = [json.dumps({"web": {"client_secret": "secret-example"}})]
        with self.assertRaises(configure.SetupError) as caught:
            receiver.validate_submission(fields, "expected", "google-client")
        self.assertNotIn("secret-example", str(caught.exception))

    def test_loopback_form_checks_host_origin_csrf_and_closes(self):
        messages = queue.Queue()
        results = queue.Queue()

        def worker():
            try:
                results.put(receiver.serve("dropbox", timeout=10))
            except Exception as exc:
                results.put(exc)

        with patch("builtins.print", side_effect=lambda value, **_: messages.put(value)):
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            try:
                announcement = json.loads(messages.get(timeout=3))
            except queue.Empty:
                if not results.empty():
                    failure = results.get_nowait()
                    if isinstance(failure, Exception):
                        raise failure
                raise
            url = announcement["url"]
            origin = url.rstrip("/")
            self.assertTrue(url.startswith("http://127.0.0.1:"))
            with urlopen(url, timeout=3) as response:
                page = response.read().decode()
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
            csrf = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
            body = urlencode({"csrf": csrf, "credential": "secret-example"}).encode()
            requests = [
                (Request(url, data=body, headers={"Host": "attacker.invalid", "Origin": origin}), 403),
                (Request(url, data=body, headers={"Origin": "https://attacker.invalid"}), 403),
                (Request(url, data=body), 403),
                (Request(url, data=urlencode({"csrf": "wrong", "credential": "secret-example"}).encode(), headers={"Origin": origin}), 400),
            ]
            for request, expected in requests:
                with self.assertRaises(HTTPError) as caught:
                    urlopen(request, timeout=3)
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn("secret-example", caught.exception.read().decode())
                caught.exception.close()
            with urlopen(Request(url, data=body, headers={"Origin": origin}), timeout=3) as response:
                self.assertNotIn("secret-example", response.read().decode())
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            result = results.get_nowait()
            self.assertIsInstance(result, dict)
            self.assertEqual(result["status"], "configuration_saved")
            self.assertNotIn("secret-example", json.dumps(result))
            self.assertEqual(configure.read_private("dropbox.json")["access_token"], "secret-example")


if __name__ == "__main__":
    unittest.main()
