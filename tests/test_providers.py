"""Provider contract tests use fake HTTP responses, never live accounts."""
import base64
import copy
from email import policy
from email.parser import BytesParser
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from hardstop.providers import (
    HASH_BLOCK, UPLOAD_CHUNK, ProviderError, Providers,
    _ContentHash, _NoRedirect,
)

CATALOG_IDS = (
    "opening", "problem", "workflow", "pilot_context", "result", "rollout",
    "disclaimer", "call_to_action",
)


class Response:
    status = 200

    def __init__(self, value=None, *, raw=None, headers=None):
        self.stream = io.BytesIO(raw if raw is not None else json.dumps(value).encode())
        self.headers = headers or {}

    def read(self, size=-1):
        return self.stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stream.close()


class QueueOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("Unexpected HTTP call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(request)
        return response


def draft(draft_id="draft1", message_id="message1", subject="Fictional fixture", body="Keep the result.", extra=""):
    raw = f"Subject: {subject}\r\n{extra}Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n".encode()
    return {"id": draft_id, "message": {"id": message_id,
            "raw": base64.urlsafe_b64encode(raw).decode().rstrip("=")}}


def deck(identifier="source1", ids=None, revision="rev1", title="Demo"):
    ids = ids if ids is not None else ["hs_opening", "hs_problem", "hs_result"]
    return {"presentationId": identifier, "revisionId": revision, "title": title,
            "pageSize": {"width": {"magnitude": 720, "unit": "PT"}, "height": {"magnitude": 405, "unit": "PT"}},
            "slides": [{"objectId": item, "pageElements": [{"objectId": item + "_text",
                       "shape": {"text": {"textElements": [{"textRun": {"content": item + "\n"}}]}}}]} for item in ids]}


def catalog():
    return {"title": "HardStop test fixture", "fictional": True, "description": "Fictional test catalog",
            "narration": "Synthesized test narration", "source_kind": "fictional_synthesized_recording",
            "segments": [{"id": item, "title": item.replace("_", " ").title(),
                          "slide_text": "A short fictional statement.", "value": 5,
                          "requires": ["pilot_context"] if item == "result" else []}
                         for item in CATALOG_IDS]}


def source_deck():
    source = catalog()
    result = deck("created1", ["hs_" + item for item in CATALOG_IDS], title=source["title"])
    for slide, segment in zip(result["slides"], source["segments"]):
        slide["pageElements"] = [
            {"objectId": slide["objectId"] + "_" + suffix,
             "shape": {"text": {"textElements": [{"textRun": {"content": text + "\n"}}]}}}
            for suffix, text in (("title", segment["title"]), ("body", segment["slide_text"]))
        ]
    return result


def content_hash(data):
    blocks = [hashlib.sha256(data[index:index + HASH_BLOCK]).digest()
              for index in range(0, len(data), HASH_BLOCK)]
    return hashlib.sha256(b"".join(blocks)).hexdigest()


def file_metadata(data, path="/test.mp4"):
    return {".tag": "file", "id": "id:test", "rev": "rev1", "path_lower": path.lower(),
            "path_display": path, "size": len(data), "content_hash": content_hash(data)}


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.google = patch("hardstop.providers.configure.google_access_token", return_value="google-test-secret")
        self.dropbox = patch("hardstop.providers.configure.dropbox_access_token", return_value="dropbox-test-secret")
        self.google.start()
        self.dropbox.start()
        self.addCleanup(self.google.stop)
        self.addCleanup(self.dropbox.stop)

    def test_create_draft_is_unaddressed_and_read_back(self):
        def created(request):
            payload = json.loads(request.data)
            encoded = payload["message"]["raw"]
            message = BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            self.assertEqual(str(message["Subject"]), "Fictional café brief")
            self.assertEqual(message.get_content().strip(), "Keep the result.")
            for name in ("To", "Cc", "Bcc", "From"):
                self.assertIsNone(message[name])
            return Response({"id": "draft1"})

        opener = QueueOpener(created, Response(draft(subject="Fictional café brief")))
        result = Providers(opener=opener).create_draft("Fictional café brief", "Keep the result.")
        self.assertFalse(result["has_recipients"])
        self.assertEqual(result["draft_id"], "draft1")
        self.assertEqual(len(opener.requests), 2)
        self.assertTrue(all("/drafts" in item.full_url and "/send" not in item.full_url for item in opener.requests))

    def test_draft_fingerprint_ignores_message_id_but_catches_recipient_edit(self):
        opener = QueueOpener(Response(draft()), Response(draft(message_id="message2", extra="Date: Yesterday\r\n")),
                             Response(draft(extra="To: recipient@example.invalid\r\n")))
        provider = Providers(opener=opener)
        first, second, third = (provider.read_draft("draft1") for _ in range(3))
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertNotEqual(first["fingerprint"], third["fingerprint"])
        self.assertTrue(third["has_recipients"])

    def test_draft_update_remains_unaddressed(self):
        opener = QueueOpener(Response({"id": "draft1"}), Response(draft(body="New brief")))
        result = Providers(opener=opener).update_draft("draft1", "Fictional fixture", "New brief")
        self.assertEqual(opener.requests[0].method, "PUT")
        self.assertEqual(result["body"], "New brief")
        payload = json.loads(opener.requests[0].data)
        encoded = payload["message"]["raw"]
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        self.assertNotIn(b"To:", raw)
        self.assertNotIn(b"Bcc:", raw)

    def test_header_injection_and_bad_ids_never_reach_http(self):
        opener = QueueOpener()
        provider = Providers(opener=opener)
        with self.assertRaises(ValueError):
            provider.create_draft("Title\r\nBcc: victim@example.invalid", "Body")
        with self.assertRaises(ValueError):
            provider.read_draft("../messages")
        self.assertEqual(opener.requests, [])

    def test_known_draft_id_survives_readback_failure(self):
        opener = QueueOpener(Response({"id": "draft1"}), URLError("upstream-secret"))
        with self.assertRaises(ProviderError) as caught:
            Providers(opener=opener).create_draft("Fixture", "Body")
        self.assertEqual(caught.exception.draft_id, "draft1")
        self.assertTrue(caught.exception.uncertain)
        self.assertNotIn("upstream-secret", str(caught.exception))

    def test_malformed_created_identity_is_unknown_and_never_retried(self):
        for value in (None, 7, ["draft1"], "../unexpected"):
            with self.subTest(value=value):
                opener = QueueOpener(Response({"id": value}))
                with self.assertRaises(ProviderError) as caught:
                    Providers(opener=opener).create_draft("Fixture", "Body")
                self.assertTrue(caught.exception.uncertain)
                self.assertEqual(len(opener.requests), 1)

    def test_http_failure_never_exposes_body_or_url_and_no_write_retry(self):
        error = HTTPError("https://example.invalid/token=secret", 503, "secret message", {}, io.BytesIO(b"private response"))
        opener = QueueOpener(error)
        with self.assertRaises(ProviderError) as caught:
            Providers(opener=opener).create_draft("Fixture", "Body")
        self.assertEqual(caught.exception.status, 503)
        self.assertTrue(caught.exception.uncertain)
        self.assertNotIn("secret", str(caught.exception))
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(len(opener.requests), 1)

    def test_network_failure_on_post_read_is_not_unknown_write(self):
        opener = QueueOpener(TimeoutError("dropbox-test-secret"))
        with self.assertRaises(ProviderError) as caught:
            Providers(opener=opener).metadata("/test.mp4")
        self.assertFalse(caught.exception.uncertain)
        self.assertNotIn("secret", str(caught.exception))

    def test_redirect_handler_never_builds_forwarded_request(self):
        from urllib.request import Request
        request = Request("https://gmail.googleapis.com/example", headers={"Authorization": "Bearer secret"})
        handler = _NoRedirect()
        for code in (301, 302, 303, 307, 308):
            self.assertIsNone(handler.redirect_request(request, None, code, "Redirect", {}, "https://evil.invalid/"))
        error = HTTPError(request.full_url, 302, "Found", {"Location": "https://evil.invalid/"}, io.BytesIO())
        opener = QueueOpener(error)
        with self.assertRaises(ProviderError) as caught:
            Providers(opener=opener).read_draft("draft1")
        self.assertEqual(caught.exception.status, 302)
        self.assertEqual(len(opener.requests), 1)

    def test_deck_fingerprint_retains_content_and_order_not_revision_or_url_signature(self):
        first = deck()
        first["slides"][0]["pageElements"].append({"objectId": "image1", "image": {
            "contentUrl": "https://lh3.googleusercontent.com/image-resource?signature=one"}})
        second = copy.deepcopy(first)
        second["revisionId"] = "revision2"
        second["slides"][0]["pageElements"][-1]["image"]["contentUrl"] = "https://lh3.googleusercontent.com/image-resource?signature=two"
        third = copy.deepcopy(second)
        third["slides"] = list(reversed(third["slides"]))
        fourth = copy.deepcopy(second)
        fourth["slides"][0]["pageElements"][0]["shape"]["text"]["textElements"][0]["textRun"]["content"] = "Different meaning\n"
        opener = QueueOpener(*(Response(value) for value in (first, second, third, fourth)))
        provider = Providers(opener=opener)
        results = [provider.read_deck("source1") for _ in range(4)]
        self.assertEqual(results[0]["fingerprint"], results[1]["fingerprint"])
        self.assertEqual(results[1]["revision_id"], "revision2")
        self.assertNotEqual(results[1]["fingerprint"], results[2]["fingerprint"])
        self.assertNotEqual(results[1]["fingerprint"], results[3]["fingerprint"])
        self.assertEqual(results[2]["slide_ids"], ["hs_result", "hs_problem", "hs_opening"])

    def test_copy_callback_is_before_trim_and_failure_carries_copy_id(self):
        recorded = []

        def failure(request):
            self.assertEqual(recorded, ["copy1"])
            raise URLError("private endpoint details")

        opener = QueueOpener(Response(deck()), Response({"id": "copy1"}), Response(deck("copy1")), failure)
        with self.assertRaises(ProviderError) as caught:
            Providers(opener=opener).copy_and_trim_deck("source1", ["hs_opening", "hs_result"], "Cut",
                                                       on_copied=recorded.append)
        self.assertEqual(caught.exception.copy_id, "copy1")
        self.assertTrue(caught.exception.uncertain)
        self.assertNotIn("private", str(caught.exception))

    def test_copy_resume_trims_only_known_copy_and_does_not_duplicate(self):
        selected = ["hs_opening", "hs_result"]
        opener = QueueOpener(Response(deck()), Response(deck("copy1")), Response({}), Response(deck("copy1", selected)))
        result = Providers(opener=opener).copy_and_trim_deck("source1", selected, "Cut", copy_id="copy1")
        self.assertEqual(result["slide_ids"], selected)
        self.assertEqual(result["copy_id"], "copy1")
        self.assertFalse(any("/copy?" in item.full_url for item in opener.requests))
        request = next(item for item in opener.requests if item.method == "POST")
        self.assertIn("/copy1:batchUpdate", request.full_url)
        self.assertEqual(json.loads(request.data), {"requests": [{"deleteObject": {"objectId": "hs_problem"}}]})

    def test_copy_resume_rejects_unexpected_human_added_slide(self):
        opener = QueueOpener(Response(deck()), Response(deck("copy1", ["hs_opening", "hs_problem", "hs_result", "human_added"])))
        with self.assertRaises(ProviderError):
            Providers(opener=opener).copy_and_trim_deck("source1", ["hs_opening"], "Cut", copy_id="copy1")
        self.assertTrue(all(item.method == "GET" for item in opener.requests))

    def test_copy_rejects_source_changed_since_workflow_snapshot_without_creating_copy(self):
        opener = QueueOpener(Response(deck()))
        with self.assertRaises(ProviderError) as caught:
            Providers(opener=opener).copy_and_trim_deck("source1", ["hs_opening"], "Cut",
                                                       expected_source_fingerprint="earlier-source-fingerprint")
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual([request.method for request in opener.requests], ["GET"])

    def test_copy_with_expected_ids_but_changed_text_cannot_be_trimmed_or_verified(self):
        altered = deck("copy1")
        altered["slides"][0]["pageElements"][0]["shape"]["text"]["textElements"][0]["textRun"]["content"] = "Changed claim\n"
        opener = QueueOpener(Response(deck()), Response({"id": "copy1"}), Response(altered))
        with self.assertRaises(ProviderError) as caught:
            Providers(opener=opener).copy_and_trim_deck("source1", ["hs_opening"], "Cut")
        self.assertEqual(caught.exception.copy_id, "copy1")
        self.assertTrue(caught.exception.uncertain)
        self.assertFalse(any(":batchUpdate" in request.full_url for request in opener.requests))

    def test_copy_comparison_includes_shared_layouts_and_geometry(self):
        for field in ("layouts", "pageSize"):
            with self.subTest(field=field):
                altered = deck("copy1")
                altered[field] = [{"objectId": "changed-layout"}] if field == "layouts" else {"width": {"magnitude": 400, "unit": "PT"}}
                opener = QueueOpener(Response(deck()), Response(altered))
                with self.assertRaises(ProviderError):
                    Providers(opener=opener).copy_and_trim_deck("source1", ["hs_opening"], "Cut", copy_id="copy1")
                self.assertTrue(all(request.method == "GET" for request in opener.requests))

    def test_content_edit_during_trim_cannot_become_the_verified_baseline(self):
        altered = deck("copy1", ["hs_opening", "hs_result"])
        altered["slides"][0]["pageElements"][0]["transform"] = {"scaleX": 0, "scaleY": 0}
        opener = QueueOpener(Response(deck()), Response(deck("copy1")), Response({}), Response(altered))
        with self.assertRaises(ProviderError) as caught:
            Providers(opener=opener).copy_and_trim_deck("source1", ["hs_opening", "hs_result"], "Cut", copy_id="copy1")
        self.assertEqual(caught.exception.copy_id, "copy1")
        self.assertTrue(caught.exception.uncertain)

    def test_copy_title_and_server_revision_may_differ_from_source(self):
        selected = ["hs_opening", "hs_result"]
        copied = deck("copy1", title="Delivery title", revision="copy-revision")
        trimmed = deck("copy1", selected, title="Delivery title", revision="trim-revision")
        opener = QueueOpener(Response(deck()), Response(copied), Response({}), Response(trimmed))
        result = Providers(opener=opener).copy_and_trim_deck("source1", selected, "Delivery title", copy_id="copy1")
        self.assertEqual(result["slide_ids"], selected)

    def test_source_creation_records_id_before_native_slide_write(self):
        recorded = []

        def populate(request):
            self.assertEqual(recorded, ["created1"])
            requests = json.loads(request.data)["requests"]
            ids = [item["createSlide"]["objectId"] for item in requests if "createSlide" in item]
            self.assertEqual(ids, ["hs_" + item for item in CATALOG_IDS])
            text = [item["insertText"]["text"] for item in requests if "insertText" in item]
            self.assertIn("A short fictional statement.", text)
            self.assertIn("Fictional sample. Synthesized narration.", text)
            self.assertFalse(any("createImage" in item for item in requests))
            return Response({})

        opener = QueueOpener(Response(deck("created1", [], title=catalog()["title"])), populate, Response(source_deck()))
        result = Providers(opener=opener).create_source_deck(catalog(), on_created=recorded.append)
        self.assertEqual(result["slide_ids"]["result"], "hs_result")
        self.assertEqual(result["presentation_id"], "created1")

    def test_source_resume_does_not_recreate_or_overwrite_populated_deck(self):
        opener = QueueOpener(Response(source_deck()))
        result = Providers(opener=opener).create_source_deck(catalog(), presentation_id="created1")
        self.assertEqual(result["presentation_id"], "created1")
        self.assertEqual([item.method for item in opener.requests], ["GET"])
        changed = source_deck()
        changed["slides"][0]["pageElements"][0]["shape"]["text"]["textElements"][0]["textRun"]["content"] = "Human changed title\n"
        with self.assertRaises(ProviderError):
            Providers(opener=QueueOpener(Response(changed))).create_source_deck(catalog(), presentation_id="created1")

    def test_user_source_builds_new_segment_ids_and_preserves_declared_narration(self):
        source = {"title": "Workshop", "description": "User-provided recording", "fictional": False,
                  "narration": "Recorded human speaker", "source_kind": "user_recordings",
                  "segments": [{"id": "lesson", "title": "One lesson", "slide_text": "Practice the exercise",
                                "requires": [], "value": 8}]}
        def populate(request):
            requests = json.loads(request.data)["requests"]
            self.assertEqual([item["createSlide"]["objectId"] for item in requests if "createSlide" in item], ["hs_lesson"])
            text = [item["insertText"]["text"] for item in requests if "insertText" in item]
            self.assertIn("Source recordings. Recorded human speaker", text)
            self.assertFalse(any("FICTIONAL" in item.upper() or "SYNTHESIZED" in item.upper() for item in text))
            return Response({})
        opener = QueueOpener(Response(deck("created1", [], title="Workshop")), populate,
                             Response(deck("created1", ["hs_lesson"], title="Workshop")))
        result = Providers(opener=opener).create_source_deck(source)
        self.assertEqual(result["slide_ids"], {"lesson": "hs_lesson"})

    def test_reusing_demo_ids_does_not_apply_fictional_or_synthesized_labels(self):
        source = catalog()
        source.update(fictional=False, narration="Recorded workshop speaker", source_kind="user_recordings")
        def populate(request):
            text = [item["insertText"]["text"] for item in json.loads(request.data)["requests"] if "insertText" in item]
            self.assertIn("Source recordings. Recorded workshop speaker", text)
            self.assertNotIn("Fictional sample. Synthesized narration.", text)
            return Response({})
        opener = QueueOpener(Response(deck("created1", [], title=source["title"])), populate, Response(source_deck()))
        Providers(opener=opener).create_source_deck(source)

    def test_source_deck_rejects_unknown_or_late_prerequisite_before_api(self):
        source = catalog()
        source["segments"][0]["requires"] = ["result"]
        opener = QueueOpener()
        with self.assertRaises(ValueError):
            Providers(opener=opener).create_source_deck(source)
        self.assertEqual(opener.requests, [])

    def test_source_deck_id_boundaries_produce_legal_google_object_ids(self):
        source = catalog()
        for length in (1, 41):
            with self.subTest(rejected_length=length):
                source["segments"] = [dict(catalog()["segments"][0], id="a" * length)]
                opener = QueueOpener()
                with self.assertRaises(ValueError):
                    Providers(opener=opener).create_source_deck(source)
                self.assertEqual(opener.requests, [])
        for length in (2, 40):
            with self.subTest(accepted_length=length):
                sid = "a" * length
                source["segments"] = [dict(catalog()["segments"][0], id=sid)]
                def populate(request):
                    requests = json.loads(request.data)["requests"]
                    ids = [item[key]["objectId"] for item in requests for key in ("createSlide", "createShape") if key in item]
                    self.assertTrue(all(5 <= len(value) <= 50 for value in ids))
                    self.assertEqual(len(ids), len(set(ids)))
                    return Response({})
                opener = QueueOpener(Response(deck("created1", [], title=source["title"])), populate,
                                     Response(deck("created1", ["hs_" + sid], title=source["title"])))
                Providers(opener=opener).create_source_deck(source)

    def test_source_shape_name_collision_is_rejected_before_api(self):
        source = catalog()
        first = source["segments"][0]
        source["segments"] = [dict(first, id="lesson"), dict(first, id="lesson_footer")]
        opener = QueueOpener()
        with self.assertRaises(ValueError):
            Providers(opener=opener).create_source_deck(source)
        self.assertEqual(opener.requests, [])

    def test_dropbox_hash_matches_reference_at_empty_and_block_boundaries(self):
        for length in (0, 1, HASH_BLOCK - 1, HASH_BLOCK, HASH_BLOCK + 1, HASH_BLOCK * 2 + 7):
            data = b"x" * length
            actual = _ContentHash()
            for offset in range(0, length, 900_001):
                actual.update(data[offset:offset + 900_001])
            self.assertEqual(actual.hexdigest(), content_hash(data))

    def test_small_upload_is_streamed_create_only_and_read_back(self):
        data = b"A fictional media file"
        metadata = file_metadata(data)

        def uploaded(request):
            arguments = json.loads(request.get_header("Dropbox-api-arg"))
            self.assertEqual(arguments["mode"], "add")
            self.assertFalse(arguments["autorename"])
            self.assertTrue(arguments["strict_conflict"])
            self.assertTrue(hasattr(request.data, "read"))
            self.assertEqual(request.data.read(), data)
            return Response(metadata)

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(data)
            opener = QueueOpener(uploaded, Response(metadata))
            result = Providers(opener=opener).upload("/test.mp4", source)
        self.assertTrue(result["verified"])
        self.assertEqual(result["sha256"], hashlib.sha256(data).hexdigest())
        self.assertTrue(opener.requests[-1].full_url.endswith("/get_metadata"))

    def test_upload_detects_changed_revision_during_readback(self):
        data = b"source"
        original = file_metadata(data)
        changed = dict(original, rev="rev2")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(data)
            with self.assertRaises(ProviderError) as caught:
                Providers(opener=QueueOpener(Response(original), Response(changed))).upload("/test.mp4", source)
        self.assertTrue(caught.exception.uncertain)

    def test_successful_upload_without_revision_is_unknown_not_verified(self):
        data = b"source"
        metadata = file_metadata(data)
        metadata.pop("rev")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            source.write_bytes(data)
            opener = QueueOpener(Response(metadata))
            with self.assertRaises(ProviderError) as caught:
                Providers(opener=opener).upload("/test.mp4", source)
        self.assertTrue(caught.exception.uncertain)
        self.assertEqual(len(opener.requests), 1)

    def test_download_wrong_file_identity_preserves_existing_local_output(self):
        data = b"matching bytes are insufficient identity evidence"
        metadata = file_metadata(data, "/different.mp4")
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "cut.mp4"
            destination.write_bytes(b"previous output")
            opener = QueueOpener(Response(raw=data, headers={"Dropbox-API-Result": json.dumps(metadata)}))
            with self.assertRaises(ProviderError):
                Providers(opener=opener).download("/test.mp4", destination)
            self.assertEqual(destination.read_bytes(), b"previous output")

    def test_upload_over_100_mib_uses_bounded_chunks_and_correct_cursor(self):
        total_size = 100 * 1024 * 1024 + 123
        state = {"offset": 0, "hash": _ContentHash(), "largest": 0, "committed": None}

        class SessionOpener:
            def open(inner, request, timeout):
                arguments = json.loads(request.get_header("Dropbox-api-arg")) if request.get_header("Dropbox-api-arg") else None
                if request.full_url.endswith("/upload_session/start"):
                    return Response({"session_id": "session-test"})
                if request.full_url.endswith("/get_metadata"):
                    return Response(state["committed"])
                self.assertEqual(arguments["cursor"], {"session_id": "session-test", "offset": state["offset"]})
                chunk = request.data
                self.assertIsInstance(chunk, bytes)
                self.assertLessEqual(len(chunk), UPLOAD_CHUNK)
                state["largest"] = max(state["largest"], len(chunk))
                state["offset"] += len(chunk)
                state["hash"].update(chunk)
                if request.full_url.endswith("/append_v2"):
                    return Response(None)
                self.assertTrue(request.full_url.endswith("/upload_session/finish"))
                self.assertTrue(arguments["commit"]["strict_conflict"])
                state["committed"] = {".tag": "file", "id": "id:large", "rev": "rev1", "path_lower": "/large.mp4",
                                      "size": state["offset"], "content_hash": state["hash"].hexdigest()}
                return Response(state["committed"])

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "large.mp4"
            with source.open("wb") as stream:
                stream.truncate(total_size)
            result = Providers(opener=SessionOpener()).upload("/large.mp4", source)
        self.assertEqual(result["size"], total_size)
        self.assertEqual(state["offset"], total_size)
        self.assertEqual(state["largest"], UPLOAD_CHUNK)

    def test_download_over_100_mib_is_streamed_and_hash_verified(self):
        total_size = 100 * 1024 * 1024 + 123
        hasher = _ContentHash()
        sha = hashlib.sha256()
        remaining = total_size
        while remaining:
            chunk = b"x" * min(1024 * 1024, remaining)
            hasher.update(chunk)
            sha.update(chunk)
            remaining -= len(chunk)
        metadata = {".tag": "file", "id": "id:large", "rev": "rev3", "size": total_size, "content_hash": hasher.hexdigest()}

        class StreamingResponse:
            status = 200
            headers = {"Dropbox-API-Result": json.dumps(metadata)}
            remaining = total_size

            def read(inner, amount=-1):
                self.assertGreater(amount, 0)
                self.assertLessEqual(amount, 1024 * 1024)
                chunk = b"x" * min(amount, inner.remaining)
                inner.remaining -= len(chunk)
                return chunk

            def __enter__(inner):
                return inner

            def __exit__(inner, *_):
                pass

        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "large.mp4"
            result = Providers(opener=QueueOpener(StreamingResponse())).download("/large.mp4", destination)
            self.assertEqual(destination.stat().st_size, total_size)
            self.assertEqual(list(Path(directory).glob(".hardstop-download-*")), [])
        self.assertEqual(result["sha256"], sha.hexdigest())
        self.assertEqual(result["rev"], "rev3")

    def test_bad_download_keeps_previous_file_and_removes_partial(self):
        metadata = file_metadata(b"expected")
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "cut.mp4"
            destination.write_bytes(b"previous successful output")
            opener = QueueOpener(Response(raw=b"corrupt!", headers={"Dropbox-API-Result": json.dumps(metadata)}))
            with self.assertRaises(ProviderError):
                Providers(opener=opener).download("/test.mp4", destination)
            self.assertEqual(destination.read_bytes(), b"previous successful output")
            self.assertEqual(list(Path(directory).glob(".hardstop-download-*")), [])

    def test_dropbox_path_rejects_urls_and_traversal_before_network(self):
        opener = QueueOpener()
        provider = Providers(opener=opener)
        for path in ("https://evil.invalid/a", "/../a", "/a//b", "/a\\b", "/a\nheader"):
            with self.assertRaises(ValueError):
                provider.metadata(path)
        self.assertEqual(opener.requests, [])

    def test_temporary_link_does_not_create_shared_link(self):
        link = "https://dl.dropboxusercontent.com/apitl/1/fixture"
        opener = QueueOpener(Response({"link": link}))
        self.assertEqual(Providers(opener=opener).temporary_link("/cut.mp4"), link)
        self.assertTrue(opener.requests[0].full_url.endswith("/files/get_temporary_link"))
        with self.assertRaises(ProviderError):
            Providers(opener=QueueOpener(Response({"link": "https://dropboxusercontent.com.evil.invalid/file"}))).temporary_link("/cut.mp4")


if __name__ == "__main__":
    unittest.main()
