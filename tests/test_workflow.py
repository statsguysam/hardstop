"""Workflow state-machine tests; all providers, model calls, and media are local fakes."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from hardstop.providers import ProviderError
from hardstop.workflow import Workflow, atomic_json, read_json


def digest(value):
    return hashlib.sha256(value).hexdigest()


def constraints(budget=5500, *, ambiguous=False):
    return {
        "max_duration_ms": budget,
        "required_ids": ["result", "disclaimer", "call_to_action"],
        "excluded_ids": [], "priorities": {},
        "evidence": [{"kind": "required", "segment_id": "result", "quote": "Keep the result"}],
        "ambiguities": ["Unconfirmed timing"] if ambiguous else [],
    }


class FakeProviders:
    """Stores bytes/revisions separately, allowing realistic external race edits."""

    def __init__(self):
        self.calls = []
        self.writes = []
        self.hook = None
        self.fault = {}
        self.files = {}
        self.revisions = {}
        self.decks = {}
        self.drafts = {}
        self.next_copy = 1
        self.next_draft = 1

    def record(self, name, *args, write=False):
        self.calls.append((name, args))
        if write:
            self.writes.append((name, args))
        if self.hook:
            self.hook(name, args)
        if name in self.fault:
            raise self.fault[name]

    def put_file(self, path, data):
        self.files[path] = data
        self.revisions[path] = self.revisions.get(path, 0) + 1

    def file_meta(self, path):
        data = self.files[path]
        return {"rev": "rev" + str(self.revisions[path]), "sha256": digest(data),
                "content_hash": "content-" + digest(data), "size": len(data), "id": "file-" + path,
                "path_lower": path, "verified": True}

    def read_draft(self, draft_id):
        self.record("read_draft", draft_id)
        return copy.deepcopy(self.drafts[draft_id])

    def update_draft(self, draft_id, subject, body):
        self.record("update_draft", draft_id, subject, body, write=True)
        result = {"draft_id": draft_id, "message_id": "message-" + draft_id,
                  "subject": subject, "body": body.rstrip("\n"), "has_recipients": False,
                  "fingerprint": digest((subject + body).encode())}
        self.drafts[draft_id] = result
        return copy.deepcopy(result)

    def create_draft(self, subject, body):
        self.record("create_draft", subject, body, write=True)
        draft_id = "handoff" + str(self.next_draft)
        self.next_draft += 1
        result = {"draft_id": draft_id, "message_id": "message-" + draft_id,
                  "subject": subject, "body": body.rstrip("\n"), "has_recipients": False,
                  "fingerprint": digest((subject + body).encode())}
        self.drafts[draft_id] = result
        return copy.deepcopy(result)

    def read_deck(self, presentation_id):
        self.record("read_deck", presentation_id)
        return copy.deepcopy(self.decks[presentation_id])

    def copy_and_trim_deck(self, source_id, selected_slide_ids, title, *, on_copied=None, copy_id=None,
                           expected_source_fingerprint=None):
        self.record("copy_and_trim_deck", source_id, selected_slide_ids, title, write=True)
        if expected_source_fingerprint is not None and self.decks[source_id]["fingerprint"] != expected_source_fingerprint:
            raise ProviderError("Verify source deck before copy")
        copy_id = copy_id or "copy" + str(self.next_copy)
        self.next_copy += 1
        if on_copied:
            on_copied(copy_id)
        result = {"presentation_id": copy_id, "copy_id": copy_id,
                  "slide_ids": list(selected_slide_ids), "revision_id": "deckrev1",
                  "fingerprint": digest((title + repr(selected_slide_ids)).encode())}
        self.decks[copy_id] = result
        return copy.deepcopy(result)

    def upload(self, path, local_file):
        self.record("upload", path, local_file, write=True)
        if path in self.files:
            raise ProviderError("Upload fake Dropbox file", status=409)
        self.put_file(path, Path(local_file).read_bytes())
        return self.file_meta(path)

    def download(self, path, destination):
        self.record("download", path, destination)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.files[path])
        return dict(self.file_meta(path), local_file=str(destination))

    def metadata(self, path):
        self.record("metadata", path)
        return self.file_meta(path)

    def temporary_link(self, path):
        self.record("temporary_link", path)
        return "https://dl.dropboxusercontent.com/fake-expiring-link"


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name)
        self.providers = FakeProviders()
        self.ids = ["opening", "problem", "workflow", "pilot_context", "result", "rollout", "disclaimer", "call_to_action"]
        values = [5, 4, 10, 8, 9, 3, 1, 7]
        self.segments = []
        for identifier, value in zip(self.ids, values):
            data = ("fictional-clip:" + identifier).encode()
            path = "/source-" + identifier + ".mp4"
            self.providers.put_file(path, data)
            self.segments.append({"id": identifier, "title": identifier, "transcript": "Fictional " + identifier,
                "slide_text": identifier, "value": value, "requires": ["pilot_context"] if identifier == "result" else [],
                "duration_ms": 1000, "sha256": digest(data), "dropbox_path": path, "dropbox_rev": "rev1",
                "slide_id": "hs_" + identifier})
        self.providers.decks["source-deck"] = {"presentation_id": "source-deck", "fingerprint": "source-fingerprint",
            "slide_ids": [item["slide_id"] for item in self.segments], "revision_id": "source-revision"}
        self.catalog = {"title": "Fictional source", "fictional": True, "segments": self.segments,
                        "presentation_id": "source-deck", "deck_fingerprint": "source-fingerprint"}
        catalog_bytes = json.dumps(self.catalog).encode()
        self.providers.put_file("/catalog.json", catalog_bytes)
        self.providers.drafts["brief1"] = {"draft_id": "brief1", "message_id": "message1", "subject": "Fictional producer brief",
            "body": "Keep the result, disclaimer, and call to action; under 5.5 seconds.",
            "fingerprint": "brief-fingerprint", "has_recipients": False}
        self.registered = dict(self.catalog, brief_draft_id="brief1",
                               catalog={"path": "/catalog.json", "sha256": digest(catalog_bytes), "rev": "rev1"})
        atomic_json(self.state / "source.json", self.registered)
        self.rules = constraints()
        self.interpreter = Mock(side_effect=lambda *_: {"constraints": copy.deepcopy(self.rules),
            "interpretation": {"summary": "Fictional test interpretation"}, "receipt": {"provider": "test-double"}})
        self.render_duration = None
        self.renderer = Mock(side_effect=self.render)
        self.workflow = Workflow(self.state, providers=self.providers, interpreter=self.interpreter, renderer=self.renderer)
        self.probe_patch = patch("hardstop.workflow.probe", return_value={"duration_ms": 1000, "has_audio": True, "has_video": True})
        self.probe_patch.start()
        self.addCleanup(self.probe_patch.stop)

    def render(self, paths, output_path):
        data = b"CUT:" + b"|".join(Path(path).read_bytes() for path in paths)
        Path(output_path).write_bytes(data)
        return {"duration_ms": self.render_duration if self.render_duration is not None else len(paths) * 1000,
                "has_video": True, "has_audio": True, "decode_verified": True, "sha256": digest(data)}

    def previous_ready(self):
        previous = {"id": "previous", "status": "ready", "started_at": "2000-01-01T00:00:00Z", "outputs": {"draft_id": "old-draft"}}
        atomic_json(self.state / "runs" / "previous" / "report.json", previous)
        pointer = {"id": "previous", "verified_at": "2000-01-01T00:00:00Z"}
        atomic_json(self.state / "latest_ready.json", pointer)
        return pointer

    def assert_previous_preserved(self, pointer):
        self.assertEqual(read_json(self.state / "latest_ready.json"), pointer)
        self.assertEqual(self.workflow.snapshot()["last_ready"]["id"], "previous")

    def test_happy_path_real_contracts_produce_verified_three_app_receipts(self):
        report = self.workflow.run("happy")
        self.assertEqual(report["status"], "ready", report.get("error"))
        expected_ids = ["workflow", "pilot_context", "result", "disclaimer", "call_to_action"]
        self.assertEqual(report["plan"]["selected_ids"], expected_ids)
        self.assertEqual(report["media"]["duration_ms"], 5000)
        self.assertTrue(all(check["passed"] for check in report["checks"]))
        self.assertEqual([name for name, _ in self.providers.writes], ["copy_and_trim_deck", "upload", "create_draft"])
        self.assertEqual(report["outputs"]["presentation_id"], "copy1")
        self.assertEqual(report["outputs"]["dropbox_path"], "/hardstop-cut-happy.mp4")
        self.assertEqual(report["outputs"]["draft_id"], "handoff1")
        self.assertEqual(read_json(self.state / "latest_ready.json")["id"], "happy")
        self.assertEqual(read_json(self.state / "runs" / "happy" / "report.json"), report)
        body = self.providers.drafts["handoff1"]["body"]
        self.assertIn("Finished length: 5.000 seconds.", body)
        self.assertIn("No email has been sent", body)
        self.assertFalse((self.state / "runs" / "happy" / "readback.mp4").exists())
        self.assertEqual(self.interpreter.call_count, 1)

    def test_infeasible_plan_never_downloads_segments_renders_or_writes_outputs(self):
        pointer = self.previous_ready()
        self.rules = constraints(3000)
        report = self.workflow.run("infeasible")
        self.assertEqual(report["status"], "infeasible")
        self.assertEqual(report["plan"]["minimum_required_ms"], 4000)
        self.assertEqual(self.providers.writes, [])
        self.assertEqual([args[0] for name, args in self.providers.calls if name == "download"], ["/catalog.json"])
        self.renderer.assert_not_called()
        self.assert_previous_preserved(pointer)

    def test_source_change_between_freshness_check_and_copy_is_not_promoted(self):
        pointer = self.previous_ready()

        def change_at_copy(name, _):
            if name == "copy_and_trim_deck":
                self.providers.decks["source-deck"]["fingerprint"] = "source-changed-just-now"

        self.providers.hook = change_at_copy
        report = self.workflow.run("source-copy-race")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["outputs"], {})
        self.assertFalse(any(name in ("upload", "create_draft") for name, _ in self.providers.writes))
        self.assert_previous_preserved(pointer)

    def test_ambiguous_plan_never_produces_an_output(self):
        self.rules = constraints(ambiguous=True)
        report = self.workflow.run("ambiguous")
        self.assertEqual(report["status"], "needs_review")
        self.assertEqual(self.providers.writes, [])
        self.renderer.assert_not_called()

    def test_stale_brief_after_render_but_before_publication_preserves_last_ready(self):
        pointer = self.previous_ready()

        def edit(name, _):
            if name == "read_draft" and sum(call[0] == "read_draft" for call in self.providers.calls) == 3:
                self.providers.drafts["brief1"]["fingerprint"] = "changed-brief"

        self.providers.hook = edit
        report = self.workflow.run("stale-before-publish")
        self.assertEqual(report["status"], "stale")
        self.renderer.assert_called_once()
        self.assertEqual(self.providers.writes, [])
        self.assert_previous_preserved(pointer)

    def test_stale_brief_after_handoff_draft_keeps_unpromoted_output_receipts(self):
        pointer = self.previous_ready()

        def edit(name, _):
            if name == "create_draft":
                self.providers.drafts["brief1"]["fingerprint"] = "changed-after-publication"

        self.providers.hook = edit
        report = self.workflow.run("stale-after-publish")
        self.assertEqual(report["status"], "stale")
        self.assertEqual(report["outputs"]["presentation_id"], "copy1")
        self.assertEqual(report["outputs"]["draft_id"], "handoff1")
        self.assertIn(report["outputs"]["dropbox_path"], self.providers.files)
        self.assert_previous_preserved(pointer)

    def test_unknown_provider_write_records_all_available_resource_ids(self):
        pointer = self.previous_ready()
        self.providers.fault["copy_and_trim_deck"] = ProviderError("Populate copied deck", status=503, uncertain=True,
            copy_id="uncertain-copy", presentation_id="uncertain-copy", draft_id="known-draft")
        report = self.workflow.run("uncertain")
        self.assertEqual(report["status"], "unknown")
        self.assertEqual(report["outputs"]["copy_id"], "uncertain-copy")
        self.assertEqual(report["outputs"]["presentation_id"], "uncertain-copy")
        self.assertEqual(report["outputs"]["draft_id"], "known-draft")
        self.assertEqual([name for name, _ in self.providers.writes], ["copy_and_trim_deck"])
        self.assert_previous_preserved(pointer)

    def test_copy_id_is_journaled_by_callback_before_later_failure(self):
        pointer = self.previous_ready()
        original = self.providers.copy_and_trim_deck

        def fail_after_copy(*args, **kwargs):
            result = original(*args, **kwargs)
            persisted = read_json(self.state / "runs" / "partial-copy" / "report.json")
            self.assertEqual(persisted["outputs"]["presentation_id"], result["presentation_id"])
            raise ProviderError("Trim copied deck", uncertain=True, copy_id=result["presentation_id"])

        self.providers.copy_and_trim_deck = fail_after_copy
        report = self.workflow.run("partial-copy")
        self.assertEqual(report["status"], "unknown")
        self.assertEqual(report["outputs"]["presentation_id"], "copy1")
        self.assert_previous_preserved(pointer)

    def test_corrupt_output_download_is_not_promoted_or_handed_off(self):
        pointer = self.previous_ready()

        def tamper(name, args):
            if name == "download" and args[0].startswith("/hardstop-cut-"):
                self.providers.put_file(args[0], b"unexpected remote bytes")

        self.providers.hook = tamper
        report = self.workflow.run("wrong-output-hash")
        self.assertEqual(report["status"], "failed")
        self.assertFalse(next(check for check in report["checks"] if check["name"] == "output_sha256")["passed"])
        self.assertNotIn("create_draft", [name for name, _ in self.providers.writes])
        self.assert_previous_preserved(pointer)

    def test_mismatched_output_slide_order_is_not_promoted(self):
        pointer = self.previous_ready()

        def reorder(name, args):
            if name == "read_deck" and args[0].startswith("copy"):
                self.providers.decks[args[0]]["slide_ids"].reverse()

        self.providers.hook = reorder
        report = self.workflow.run("wrong-output-order")
        self.assertEqual(report["status"], "failed")
        self.assertFalse(next(check for check in report["checks"] if check["name"] == "matching_deck")["passed"])
        self.assertNotIn("create_draft", [name for name, _ in self.providers.writes])
        self.assert_previous_preserved(pointer)

    def test_same_ready_run_id_returns_saved_receipt_without_any_calls(self):
        first = self.workflow.run("repeat")
        self.assertEqual(first["status"], "ready")
        calls = copy.deepcopy(self.providers.calls)
        second = self.workflow.run("repeat")
        self.assertEqual(first, second)
        self.assertEqual(self.providers.calls, calls)
        self.assertEqual(self.interpreter.call_count, 1)

    def test_interrupted_run_is_marked_unknown_without_repeating_writes(self):
        self.workflow.reserve_run("interrupted")
        report = self.workflow.run("interrupted")
        self.assertEqual(report["status"], "unknown")
        self.assertEqual(self.providers.calls, [])
        self.interpreter.assert_not_called()

    def test_reserved_run_executes_once_and_rejects_second_execution(self):
        identifier = self.workflow.reserve_run("reserved")
        report = self.workflow.run(identifier, reserved=True)
        self.assertEqual(report["status"], "ready")
        calls = copy.deepcopy(self.providers.calls)
        with self.assertRaises(ValueError):
            self.workflow.run(identifier, reserved=True)
        self.assertEqual(self.providers.calls, calls)

    def test_path_traversal_run_ids_rejected_before_any_provider_call(self):
        for value in ("../escape", "a/b", "a\\b", ".", "..", "%2fetc", "x" * 81):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.workflow.run(value)
            with self.subTest(reserve=value), self.assertRaises(ValueError):
                self.workflow.reserve_run(value)
        self.assertEqual(self.providers.calls, [])
        self.interpreter.assert_not_called()

    def test_changed_source_catalog_fails_before_model_or_output_write(self):
        self.providers.put_file("/catalog.json", json.dumps(dict(self.catalog, title="Changed source")).encode())
        report = self.workflow.run("changed-catalog")
        self.assertEqual(report["status"], "failed")
        self.interpreter.assert_not_called()
        self.renderer.assert_not_called()
        self.assertEqual(self.providers.writes, [])

    def test_changed_source_deck_content_fails_before_model_or_output_write(self):
        self.providers.decks["source-deck"]["fingerprint"] = "different-source"
        report = self.workflow.run("changed-deck")
        self.assertEqual(report["status"], "failed")
        self.interpreter.assert_not_called()
        self.assertEqual(self.providers.writes, [])

    def test_changed_source_deck_order_fails_even_if_fingerprint_is_unchanged(self):
        self.providers.decks["source-deck"]["slide_ids"].reverse()
        report = self.workflow.run("changed-deck-order")
        self.assertEqual(report["status"], "failed")
        self.interpreter.assert_not_called()
        self.assertEqual(self.providers.writes, [])

    def test_actual_render_over_budget_prevents_all_publication(self):
        pointer = self.previous_ready()
        self.render_duration = 5501
        report = self.workflow.run("render-overrun")
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["plan"]["duration_ms"], 5000)
        self.assertEqual(report["media"]["duration_ms"], 5501)
        self.assertEqual(self.providers.writes, [])
        self.assertFalse(next(check for check in report["checks"] if check["name"] == "measured_deadline")["passed"])
        self.assert_previous_preserved(pointer)

    def test_selected_media_edit_during_run_blocks_before_render(self):
        def edit(name, args):
            if name == "metadata" and args[0] == "/source-result.mp4":
                self.providers.put_file(args[0], self.providers.files[args[0]])

        self.providers.hook = edit
        report = self.workflow.run("source-media-edited")
        self.assertEqual(report["status"], "stale")
        self.renderer.assert_not_called()
        self.assertEqual(self.providers.writes, [])

    def test_source_download_duration_mismatch_blocks_before_render(self):
        self.probe_patch.stop()
        with patch("hardstop.workflow.probe", return_value={"duration_ms": 1001}):
            report = self.workflow.run("source-duration-mismatch")
        self.assertEqual(report["status"], "failed")
        self.renderer.assert_not_called()
        self.assertEqual(self.providers.writes, [])

    def test_source_brief_with_recipients_blocks_before_model(self):
        self.providers.drafts["brief1"]["has_recipients"] = True
        report = self.workflow.run("addressed-brief")
        self.assertEqual(report["status"], "failed")
        self.interpreter.assert_not_called()
        self.assertEqual(self.providers.writes, [])

    def test_output_revision_changes_at_final_check_prevents_promotion(self):
        pointer = self.previous_ready()

        def edit(name, args):
            if name == "metadata" and args[0].startswith("/hardstop-cut-"):
                self.providers.put_file(args[0], self.providers.files[args[0]])

        self.providers.hook = edit
        report = self.workflow.run("late-output-edit")
        self.assertEqual(report["status"], "failed")
        self.assertIn("draft_id", report["outputs"])
        self.assertFalse(next(check for check in report["checks"] if check["name"] == "final_outputs")["passed"])
        self.assert_previous_preserved(pointer)


if __name__ == "__main__":
    unittest.main()
