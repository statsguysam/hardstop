"""Local source imports: actual file operations with controlled decoder responses."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hardstop import media
from hardstop.source import SourceError, _measure_recording, import_source


def catalog():
    return {"title": "Workshop recording", "description": "Producer supplied workshop segments",
            "fictional": False, "narration": "Recorded human speaker; declared by the producer",
            "segments": [
                {"id": "orientation", "title": "Start here", "transcript": "First orient the audience.",
                 "slide_text": "Three steps", "requires": [], "value": 4, "media_path": "clips/first.mp4"},
                {"id": "practice", "title": "Try the exercise", "transcript": "Now try the exercise.",
                 "slide_text": "Work through an example", "requires": ["orientation"], "value": 9, "media_path": "clips/second.mp4"},
            ]}


class SourceImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.input = self.root / "input"
        (self.input / "clips").mkdir(parents=True)
        (self.input / "clips/first.mp4").write_bytes(b"first recording bytes")
        (self.input / "clips/second.mp4").write_bytes(b"second recording bytes")
        self.path = self.input / "catalog.json"
        self.output = self.root / "registered-source"
        self.data = catalog()
        self.measure = patch("hardstop.source._measure_recording", return_value={
            "duration_ms": 1234, "has_video": True, "has_audio": True, "width": 1280,
            "height": 720, "decode_verified": True})
        self.measure_mock = self.measure.start()
        self.addCleanup(self.measure.stop)

    def run_import(self):
        self.path.write_text(json.dumps(self.data))
        return import_source(self.path, self.output)

    def test_import_accepts_new_ids_and_real_source_labels_without_changing_recordings(self):
        result = self.run_import()
        self.assertEqual(result["source_kind"], "user_recordings")
        self.assertEqual(result["metadata_provenance"], "user_declared")
        self.assertFalse(result["fictional"])
        self.assertEqual(result["narration"], self.data["narration"])
        self.assertEqual(result["source_duration_ms"], 2468)
        self.assertEqual(result["catalog_sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(result, json.loads((self.output / "manifest.json").read_text()))
        self.assertEqual([s["slide_id"] for s in result["segments"]], ["hs_orientation", "hs_practice"])
        for old, new in zip(self.data["segments"], result["segments"]):
            self.assertEqual(Path(new["media_path"]).read_bytes(), (self.input / old["media_path"]).read_bytes())
            self.assertEqual(new["sha256"], hashlib.sha256(Path(new["media_path"]).read_bytes()).hexdigest())
            self.assertEqual(new["requires"], old["requires"])
            self.assertTrue(new["decode_verified"])
        self.assertEqual(list(self.root.glob(".hardstop-source-*")), [])

    def test_existing_directory_is_preserved_and_import_is_not_repeated(self):
        self.output.mkdir()
        marker = self.output / "existing.txt"
        marker.write_text("previous source")
        with self.assertRaises(SourceError):
            self.run_import()
        self.assertEqual(marker.read_text(), "previous source")
        self.measure_mock.assert_not_called()

    def test_catalog_cannot_supply_claimed_duration_hash_or_provenance(self):
        for target, key, value in (("segment", "duration_ms", 1), ("segment", "sha256", "a" * 64),
                                   ("catalog", "source_kind", "fictional_synthesized_recording")):
            with self.subTest(key=key):
                self.data = catalog()
                (self.data["segments"][0] if target == "segment" else self.data)[key] = value
                with self.assertRaises(SourceError):
                    self.run_import()
        self.assertFalse(self.output.exists())

    def test_fiction_and_narration_must_be_explicit(self):
        for field, value in (("fictional", "false"), ("fictional", None), ("narration", "")):
            with self.subTest(field=field, value=value):
                self.data = catalog()
                self.data[field] = value
                with self.assertRaises(SourceError):
                    self.run_import()
        self.measure_mock.assert_not_called()

    def test_escape_absolute_url_and_non_mp4_paths_are_rejected_before_decode(self):
        for value in ("../outside.mp4", "/outside.mp4", "https://example.invalid/file.mp4", "clips/../first.mp4",
                      "clips//first.mp4", "clips\\first.mp4", "clips/first.m3u8"):
            with self.subTest(path=value):
                self.data = catalog()
                self.data["segments"][0]["media_path"] = value
                with self.assertRaises(SourceError):
                    self.run_import()
        self.measure_mock.assert_not_called()

    def test_symlink_file_and_symlink_directory_cannot_escape_catalog(self):
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"outside")
        (self.input / "linked.mp4").symlink_to(outside)
        (self.input / "linked-folder").symlink_to(self.root, target_is_directory=True)
        for value in ("linked.mp4", "linked-folder/outside.mp4"):
            with self.subTest(path=value):
                self.data["segments"][0]["media_path"] = value
                with self.assertRaises(SourceError):
                    self.run_import()
        self.measure_mock.assert_not_called()
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_symlink_catalog_or_output_parent_is_rejected(self):
        self.path.write_text(json.dumps(self.data))
        linked = self.input / "linked.json"
        linked.symlink_to(self.path)
        with self.assertRaises(SourceError):
            import_source(linked, self.output)
        parent = self.root / "linked-output-parent"
        parent.symlink_to(self.input, target_is_directory=True)
        with self.assertRaises(SourceError):
            import_source(self.path, parent / "output")
        self.assertFalse((self.input / "output").exists())

    def test_nonregular_input_does_not_block_on_fifo(self):
        fifo = self.input / "clips/fifo.mp4"
        os.mkfifo(fifo)
        self.data["segments"][0]["media_path"] = "clips/fifo.mp4"
        with self.assertRaises(SourceError):
            self.run_import()
        self.measure_mock.assert_not_called()

    def test_invalid_graph_ids_values_and_count_are_rejected(self):
        cases = []
        value = catalog(); value["segments"][1]["id"] = "orientation"; cases.append(value)
        value = catalog(); value["segments"][0]["id"] = "../escape"; cases.append(value)
        value = catalog(); value["segments"][0]["requires"] = ["practice"]; cases.append(value)
        value = catalog(); value["segments"][1]["requires"] = ["missing"]; cases.append(value)
        value = catalog(); value["segments"][1]["requires"] = ["orientation", "orientation"]; cases.append(value)
        value = catalog(); value["segments"][0]["value"] = True; cases.append(value)
        value = catalog(); value["segments"] = []; cases.append(value)
        value = catalog(); value["segments"] = value["segments"] * 10; cases.append(value)
        for index, data in enumerate(cases):
            with self.subTest(case=index):
                self.data = data
                with self.assertRaises(SourceError):
                    self.run_import()
        self.measure_mock.assert_not_called()

    def test_one_and_eighteen_segments_are_valid_bounds(self):
        for count in (1, 18):
            with self.subTest(count=count):
                self.output = self.root / ("source" + str(count))
                first = catalog()["segments"][0]
                self.data["segments"] = [dict(first, id="clip_" + str(index)) for index in range(count)]
                self.assertEqual(len(self.run_import()["segments"]), count)

    def test_segment_id_length_reserves_space_for_slides_and_shapes(self):
        for length in (1, 41):
            with self.subTest(rejected_length=length):
                self.data = catalog()
                self.data["segments"] = [dict(self.data["segments"][0], id="a" * length)]
                with self.assertRaises(SourceError):
                    self.run_import()
        self.measure_mock.assert_not_called()
        for length in (2, 40):
            with self.subTest(accepted_length=length):
                self.output = self.root / ("source-id-" + str(length))
                self.data["segments"] = [dict(catalog()["segments"][0], id="a" * length)]
                self.assertEqual(self.run_import()["segments"][0]["slide_id"], "hs_" + "a" * length)

    def test_segment_names_cannot_collide_with_generated_shape_ids(self):
        self.data["segments"][0]["id"] = "lesson"
        self.data["segments"][1].update(id="lesson_footer", requires=[])
        with self.assertRaises(SourceError):
            self.run_import()
        self.measure_mock.assert_not_called()

    def test_decode_failure_and_mismatched_dimensions_leave_no_installed_source(self):
        self.measure_mock.side_effect = media.MediaError("decode failure")
        with self.assertRaises(SourceError):
            self.run_import()
        self.assertFalse(self.output.exists())
        info = dict(self.measure_mock.return_value)
        self.measure_mock.side_effect = [info, dict(info, width=1920)]
        with self.assertRaises(SourceError):
            self.run_import()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.root.glob(".hardstop-source-*")), [])

    def test_file_changed_while_decoding_cannot_be_registered(self):
        info = dict(self.measure_mock.return_value)
        def changed(path):
            Path(path).write_bytes(b"changed after hashing")
            return info
        self.measure_mock.side_effect = changed
        with self.assertRaises(SourceError):
            self.run_import()
        self.assertFalse(self.output.exists())

    def test_destination_race_does_not_overwrite_competing_directory(self):
        info = dict(self.measure_mock.return_value)
        def race(_):
            self.output.mkdir(exist_ok=True)
            (self.output / "other.txt").write_text("another operation")
            return info
        self.measure_mock.side_effect = race
        with self.assertRaises(SourceError):
            self.run_import()
        self.assertEqual((self.output / "other.txt").read_text(), "another operation")
        self.assertFalse((self.output / "manifest.json").exists())

    def test_duplicate_json_keys_are_rejected(self):
        self.path.write_text('{"title":"one","title":"two"}')
        with self.assertRaises(SourceError):
            import_source(self.path, self.output)
        self.assertFalse(self.output.exists())


class SourceDecoderTests(unittest.TestCase):
    def metadata(self):
        return {"format": {"duration": "1.2341"}, "streams": [
            {"codec_type": "video", "width": 1280, "height": 720}, {"codec_type": "audio"}]}

    def test_probe_rounds_up_and_full_decode_forces_local_mp4_demuxing(self):
        with patch("hardstop.source.media._tool", side_effect=lambda name: name), patch(
                "hardstop.source.media._run", side_effect=[json.dumps(self.metadata()).encode(), b""]) as run:
            result = _measure_recording(Path("/private/tmp/source.mp4"))
        self.assertEqual(result["duration_ms"], 1235)
        self.assertTrue(result["decode_verified"])
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            args = call.args[0]
            self.assertEqual(args[args.index("-protocol_whitelist") + 1], "file,pipe")
            self.assertEqual(args[args.index("-enable_drefs") + 1], "0")
            self.assertEqual(args[args.index("-f") + 1], "mov")
        self.assertIn("-xerror", run.call_args_list[1].args[0])

    def test_missing_audio_cover_art_multiple_audio_and_odd_dimensions_fail_before_decode(self):
        cases = []
        value = self.metadata(); value["streams"].pop(); cases.append(value)
        value = self.metadata(); value["streams"][0]["disposition"] = {"attached_pic": 1}; cases.append(value)
        value = self.metadata(); value["streams"].append({"codec_type": "audio"}); cases.append(value)
        value = self.metadata(); value["streams"][0]["width"] = 1279; cases.append(value)
        value = self.metadata(); value["format"]["duration"] = "601"; cases.append(value)
        for index, data in enumerate(cases):
            with self.subTest(case=index), patch("hardstop.source.media._tool", side_effect=lambda name: name), patch(
                    "hardstop.source.media._run", return_value=json.dumps(data).encode()) as run:
                with self.assertRaises(SourceError):
                    _measure_recording(Path("/private/tmp/source.mp4"))
                self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
