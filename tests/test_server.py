"""Review-server boundary tests, invoking handlers without opening a socket."""

from email.message import Message
from io import BytesIO
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from hardstop.server import Handler
from hardstop.workflow import Workflow


class HandlerHarness:
    def __init__(self, server, path="/api/state", method="GET", body=None, headers=None):
        self.handler = object.__new__(Handler)
        self.handler.server = server
        self.handler.path = path
        self.handler.command = method
        self.handler.rfile = BytesIO(body or b"")
        self.handler.wfile = BytesIO()
        self.handler.headers = Message()
        for key, value in (headers or {}).items():
            self.handler.headers[key] = value
        self.status = None
        self.headers = {}
        self.handler.send_response = lambda status: setattr(self, "status", status)
        self.handler.send_header = lambda key, value: self.headers.update({key: value})
        self.handler.end_headers = lambda: None

    def invoke(self):
        getattr(self.handler, f"do_{self.handler.command}")()
        return self

    @property
    def body(self):
        return self.handler.wfile.getvalue()

    @property
    def json(self):
        return json.loads(self.body)


class PausedWorker:
    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon
        self.alive = False

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive


class ReviewServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()
        self.workflow = SimpleNamespace(
            state=self.state,
            snapshot=Mock(return_value={"source": None, "current_run": None, "configured": False}),
            set_brief=Mock(return_value={"subject": "Test fixture", "body": "Updated"}),
            reserve_run=Mock(return_value="run_1"),
            run=Mock(),
        )
        self.server = SimpleNamespace(workflow=self.workflow, server_port=8766,
                                      origin="http://127.0.0.1:8766", csrf="test-csrf-value",
                                      worker=None, mutex=threading.Lock())

    def get(self, path="/api/state", **headers):
        return HandlerHarness(self.server, path, headers={"Host": "127.0.0.1:8766", **headers}).invoke()

    def post(self, path="/api/run", value=None, *, raw=None, headers=None):
        raw = raw if raw is not None else json.dumps({} if value is None else value).encode()
        all_headers = {"Host": "127.0.0.1:8766", "Origin": self.server.origin,
                       "Content-Type": "application/json", "Content-Length": str(len(raw)),
                       "X-HardStop-CSRF": self.server.csrf}
        all_headers.update(headers or {})
        return HandlerHarness(self.server, path, "POST", raw, all_headers).invoke()

    def ready_media(self, data=b"0123456789", status="ready", identifier="run_1"):
        folder = self.state / "runs" / identifier
        folder.mkdir(parents=True)
        (folder / "report.json").write_text(json.dumps({"status": status}))
        (folder / "cut.mp4").write_bytes(data)
        return folder

    def test_host_origin_and_fetch_metadata_block_untrusted_reads(self):
        attacks = [{"Host": "evil.test"}, {"Host": "localhost:8766"}, {"Host": "127.0.0.1:80"},
                   {"Host": "127.0.0.1:8766.evil.test"}, {"Host": ""},
                   {"Origin": "https://evil.test"}, {"Origin": "null"},
                   {"Origin": "http://127.0.0.1:8766.evil.test"}, {"Sec-Fetch-Site": "cross-site"}]
        for headers in attacks:
            with self.subTest(headers=headers):
                self.assertEqual(self.get(**headers).status, 403)
        self.workflow.snapshot.assert_not_called()

    def test_read_permits_local_navigation_and_same_origin(self):
        self.assertEqual(self.get().status, 200)
        self.assertEqual(self.get(Origin=self.server.origin).status, 200)
        self.assertEqual(self.get(**{"Sec-Fetch-Site": "same-origin"}).status, 200)

    def test_post_requires_exact_origin_and_csrf_before_mutation(self):
        attacks = [{"Origin": ""}, {"Origin": "null"}, {"Origin": "https://evil.test"},
                   {"Host": "evil.test"}, {"X-HardStop-CSRF": ""},
                   {"X-HardStop-CSRF": "test-csrf-value-extra"}, {"Sec-Fetch-Site": "cross-site"}]
        for headers in attacks:
            with self.subTest(headers=headers):
                self.assertEqual(self.post(headers=headers).status, 403)
        self.workflow.reserve_run.assert_not_called()
        self.workflow.set_brief.assert_not_called()

    def test_non_ascii_csrf_is_rejected_without_handler_exception(self):
        self.assertEqual(self.post(headers={"X-HardStop-CSRF": "caf\u00e9"}).status, 403)
        self.workflow.reserve_run.assert_not_called()

    def test_json_size_type_and_shape_are_enforced(self):
        cases = [(b"{}", {"Content-Type": "text/plain"}, 415),
                 (b"{}", {"Content-Length": "-1"}, 400),
                 (b"{}", {"Content-Length": "0"}, 400),
                 (b"{}", {"Content-Length": "32769"}, 400),
                 (b"{}", {"Content-Length": "invalid"}, 400),
                 (b"{", {}, 400), (b"[]", {}, 400), (b"null", {}, 400),
                 (b'"string"', {}, 400), (b"\xff", {}, 400)]
        for raw, headers, status in cases:
            with self.subTest(raw=raw, headers=headers):
                self.assertEqual(self.post(raw=raw, headers=headers).status, status)
        self.workflow.reserve_run.assert_not_called()

    def test_brief_only_calls_fixture_operation(self):
        response = self.post("/api/brief", {"scenario": "impossible"})
        self.assertEqual(response.status, 200)
        self.workflow.set_brief.assert_called_once_with("impossible")
        self.workflow.reserve_run.assert_not_called()

    def test_invalid_scenario_is_a_safe_bad_request(self):
        self.workflow.set_brief.side_effect = ValueError("Unknown demo scenario")
        response = self.post("/api/brief", {"scenario": "invented"})
        self.assertEqual(response.status, 400)
        self.assertEqual(response.json, {"error": "Unknown demo scenario"})

    def test_run_reservation_precedes_one_worker_and_duplicate_is_rejected(self):
        with patch("hardstop.server.threading.Thread", PausedWorker):
            first = self.post()
            self.assertEqual(first.status, 202)
            self.assertEqual(first.json, {"run_id": "run_1"})
            self.assertTrue(self.server.worker.is_alive())
            self.workflow.run.assert_not_called()
            second = self.post()
            self.assertEqual(second.status, 409)
            self.workflow.reserve_run.assert_called_once_with()
            self.server.worker.target()
            self.workflow.run.assert_called_once_with("run_1", reserved=True)

    def test_completed_worker_can_be_replaced(self):
        self.server.worker = SimpleNamespace(is_alive=lambda: False)
        with patch("hardstop.server.threading.Thread", PausedWorker):
            self.assertEqual(self.post().status, 202)
        self.workflow.reserve_run.assert_called_once()

    def test_provider_failure_response_does_not_echo_arbitrary_exception_text(self):
        self.workflow.set_brief.side_effect = RuntimeError("private-token-sentinel")
        response = self.post("/api/brief", {"scenario": "original"})
        self.assertEqual(response.status, 502)
        self.assertNotIn(b"private-token-sentinel", response.body)

    def test_state_reads_only_public_snapshot_not_credentials_or_provider_objects(self):
        private = self.state / ".credentials"
        private.mkdir()
        (private / "openai.json").write_text('{"api_key":"private-token-sentinel"}')
        (self.state / "source.json").write_text('{"title":"Fictional demo","segments":[]}')
        actual = Workflow(self.state, providers=SimpleNamespace(api_key="private-provider-sentinel"))
        self.server.workflow = actual
        response = self.get()
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json["csrf"], self.server.csrf)
        self.assertEqual(response.json["source"]["title"], "Fictional demo")
        self.assertNotIn(b"private-token-sentinel", response.body)
        self.assertNotIn(b"private-provider-sentinel", response.body)
        self.assertNotIn("credentials", response.json)

    def test_no_generic_filesystem_or_traversal_routes(self):
        paths = ["/.credentials/openai.json", "/configure.py", "/.state/source.json",
                 "/media/../cut.mp4", "/media/%2e%2e/cut.mp4", "/media/run_1/../../configure.py",
                 "/media/run_1/report.json", "/media/run_1%2f../cut.mp4", "/web/../configure.py"]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status, 404)

    def test_media_available_only_for_ready_reports(self):
        for status in ["running", "failed", "infeasible", "needs_review", "stale", "unknown"]:
            self.ready_media(status=status, identifier=status)
            with self.subTest(status=status):
                self.assertEqual(self.get(f"/media/{status}/cut.mp4").status, 404)
        self.assertEqual(self.get("/media/missing/cut.mp4").status, 404)

    def test_ready_media_and_ranges_return_exact_bytes_and_headers(self):
        self.ready_media()
        cases = [(None, 200, b"0123456789", None), ("bytes=2-4", 206, b"234", "bytes 2-4/10"),
                 ("bytes=5-", 206, b"56789", "bytes 5-9/10"),
                 ("bytes=-3", 206, b"789", "bytes 7-9/10"),
                 ("bytes=-20", 206, b"0123456789", "bytes 0-9/10"),
                 ("bytes=0-999", 206, b"0123456789", "bytes 0-9/10")]
        for byte_range, status, expected, content_range in cases:
            with self.subTest(byte_range=byte_range):
                response = self.get("/media/run_1/cut.mp4", **({"Range":byte_range} if byte_range else {}))
                self.assertEqual(response.status, status)
                self.assertEqual(response.body, expected)
                self.assertEqual(response.headers["Content-Length"], str(len(expected)))
                self.assertEqual(response.headers["Accept-Ranges"], "bytes")
                self.assertEqual(response.headers.get("Content-Range"), content_range)

    def test_invalid_ranges_rejected(self):
        self.ready_media()
        for value in ["bytes=", "bytes=-", "bytes=10-", "bytes=8-2", "bytes=-0",
                      "bytes=1-2,4-5", "items=1-2", "bytes=-1-3", "bytes=1.5-2"]:
            with self.subTest(value=value):
                self.assertEqual(self.get("/media/run_1/cut.mp4", Range=value).status, 416)

    def test_unsatisfiable_range_identifies_current_file_size(self):
        self.ready_media()
        response = self.get("/media/run_1/cut.mp4", Range="bytes=100-")
        self.assertEqual(response.status, 416)
        self.assertEqual(response.headers.get("Content-Range"), "bytes */10")

    def test_unreasonably_long_range_is_rejected_without_integer_parse_exception(self):
        self.ready_media()
        response = self.get("/media/run_1/cut.mp4", Range="bytes=" + "9" * 5000 + "-")
        self.assertEqual(response.status, 416)

    def test_malformed_report_cannot_authorize_media(self):
        folder = self.ready_media()
        for content in ["null", "[]", "{", '"ready"']:
            (folder / "report.json").write_text(content)
            with self.subTest(content=content):
                self.assertEqual(self.get("/media/run_1/cut.mp4").status, 404)

    def test_symlinked_media_file_is_not_served(self):
        folder = self.ready_media()
        (folder / "cut.mp4").unlink()
        target = Path(self.tmp.name) / "private-media"
        target.write_bytes(b"private-file-sentinel")
        (folder / "cut.mp4").symlink_to(target)
        response = self.get("/media/run_1/cut.mp4")
        self.assertEqual(response.status, 404)
        self.assertNotIn(b"private-file-sentinel", response.body)

    def test_symlinked_run_directory_is_not_served(self):
        external = Path(self.tmp.name) / "outside"
        external.mkdir()
        (external / "report.json").write_text('{"status":"ready"}')
        (external / "cut.mp4").write_bytes(b"private-folder-sentinel")
        (self.state / "runs").mkdir()
        (self.state / "runs" / "run_1").symlink_to(external, target_is_directory=True)
        response = self.get("/media/run_1/cut.mp4")
        self.assertEqual(response.status, 404)
        self.assertNotIn(b"private-folder-sentinel", response.body)

    def test_symlinked_report_does_not_authorize_media(self):
        folder = self.ready_media()
        (folder / "report.json").unlink()
        external = Path(self.tmp.name) / "outside-report"
        external.write_text('{"status":"ready"}')
        (folder / "report.json").symlink_to(external)
        self.assertEqual(self.get("/media/run_1/cut.mp4").status, 404)

    def test_empty_file_is_not_a_verified_video(self):
        self.ready_media(data=b"")
        self.assertEqual(self.get("/media/run_1/cut.mp4").status, 404)

    def test_common_response_headers_disable_caching_and_embedding(self):
        response = self.get()
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        self.assertIn("connect-src 'self'", response.headers["Content-Security-Policy"])

    def test_unknown_mutation_routes_have_no_side_effects(self):
        self.assertEqual(self.post("/api/send").status, 404)
        self.workflow.reserve_run.assert_not_called()
        self.workflow.set_brief.assert_not_called()


if __name__ == "__main__":
    unittest.main()
