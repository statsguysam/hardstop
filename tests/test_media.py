"""Real FFmpeg tests for whole-clip media verification and safe publication."""
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from array import array

from hardstop.media import MediaError, make_demo_assets, probe, render_cut, sha256_file, verify_decode


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools required")
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        for name, color, frequency, seconds in [("first", "blue", 440, "0.5"),
                                                ("second", "yellow", 660, "0.7")]:
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30",
                            "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000",
                            "-t", seconds, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            "-ar", "48000", "-ac", "2", str(cls.root / f"{name}.mp4")],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_probe_measures_real_audio_and_video(self):
        data = probe(self.root / "first.mp4")
        self.assertTrue(data["has_video"])
        self.assertTrue(data["has_audio"])
        self.assertEqual((data["width"], data["height"]), (320, 180))
        self.assertGreaterEqual(data["duration_ms"], 500)
        self.assertLess(data["duration_ms"], 550)

    def test_real_cut_duration_hash_and_decode(self):
        sources = [self.root / "first.mp4", self.root / "second.mp4"]
        target = self.root / "complete-cut.mp4"
        result = render_cut(sources, target)
        self.assertTrue(result["decode_verified"])
        self.assertLessEqual(abs(result["duration_ms"] - sum(probe(p)["duration_ms"] for p in sources)), 60)
        self.assertEqual(result["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
        verify_decode(target)
        # Check source order by sampling visible colors from both portions.
        colors = []
        for moment in ["0.2", "0.9"]:
            rgb = subprocess.run(["ffmpeg", "-v", "error", "-ss", moment, "-i", str(target),
                                  "-vf", "scale=1:1", "-frames:v", "1", "-f", "rawvideo",
                                  "-pix_fmt", "rgb24", "pipe:1"], stdout=subprocess.PIPE, check=True).stdout
            colors.append(tuple(rgb[:3]))
        self.assertGreater(colors[0][2], colors[0][0] + 100)
        self.assertGreater(colors[1][0], colors[1][2] + 100)
        self.assertGreater(colors[1][1], colors[1][2] + 100)

    def test_refuses_to_overwrite_existing_result(self):
        target = self.root / "preserved.mp4"
        target.write_bytes(b"previous successful artifact")
        with self.assertRaises(MediaError):
            render_cut([self.root / "first.mp4"], target)
        self.assertEqual(target.read_bytes(), b"previous successful artifact")

    def test_original_audio_survives_in_source_order(self):
        target = self.root / "audio-order.mp4"
        render_cut([self.root / "first.mp4", self.root / "second.mp4"], target)
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(target), "-vn", "-ac", "1",
             "-ar", "48000", "-f", "s16le", "pipe:1"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout
        samples = array("h", raw)

        def energy_at(frequency, start):
            window = samples[round(start * 48000):round((start + 0.05) * 48000)]
            self.assertEqual(len(window), 2400)
            phase = 2 * math.pi * frequency / 48000
            real = sum(value * math.cos(phase * i) for i, value in enumerate(window))
            imaginary = sum(value * math.sin(phase * i) for i, value in enumerate(window))
            return real * real + imaginary * imaginary

        # Known input tones distinguish retained source audio from silence,
        # reordered clips, or a video-only result with a replacement soundtrack.
        for start, expected, other in [(0.15, 440, 660), (0.40, 440, 660),
                                        (0.75, 660, 440), (1.10, 660, 440)]:
            with self.subTest(start=start):
                self.assertGreater(energy_at(expected, start), energy_at(other, start) * 20)

    def test_missing_source_does_not_publish(self):
        target = self.root / "missing-output.mp4"
        with self.assertRaises(MediaError):
            render_cut([self.root / "missing.mp4"], target)
        self.assertFalse(target.exists())

    def test_truncated_source_does_not_publish(self):
        corrupt = self.root / "truncated.mp4"
        data = (self.root / "first.mp4").read_bytes()
        corrupt.write_bytes(data[:len(data) // 2])
        target = self.root / "corrupt-output.mp4"
        with self.assertRaises(MediaError):
            render_cut([corrupt], target)
        self.assertFalse(target.exists())

    def test_audio_only_rejected(self):
        audio = self.root / "audio.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(self.root / "first.mp4"),
                        "-vn", str(audio)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with self.assertRaises(MediaError):
            render_cut([audio], self.root / "audio-only.mp4")

    def test_empty_cut_rejected(self):
        with self.assertRaises(MediaError):
            render_cut([], self.root / "empty.mp4")

    def test_invalid_metadata_fails_closed(self):
        with mock.patch("hardstop.media._run", return_value=json.dumps({"format": {"duration": "NaN"}, "streams": []}).encode()):
            with self.assertRaises(MediaError):
                probe(self.root / "first.mp4")

    def test_cached_assets_are_verified_without_speech_generation(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temp:
            folder = Path(temp)
            source = folder / "source.mp4"
            shutil.copyfile(self.root / "first.mp4", source)
            catalog = folder / "catalog.json"
            catalog.write_text(json.dumps({"fictional": True, "segments": [{"id": "sample"}]}))
            manifest = {"catalog_sha256": sha256_file(catalog), "segments": [
                {"id": "sample", "media_path": str(source), "sha256": sha256_file(source),
                 "duration_ms": probe(source)["duration_ms"]}]}
            (folder / "manifest.json").write_text(json.dumps(manifest))
            self.assertEqual(make_demo_assets(catalog, folder), manifest)
            source.write_bytes(source.read_bytes() + b"tampered")
            with self.assertRaises(MediaError):
                make_demo_assets(catalog, folder)

    def test_changed_catalog_cannot_silently_replace_generated_assets(self):
        with tempfile.TemporaryDirectory(dir=self.root) as temp:
            folder = Path(temp)
            catalog = folder / "catalog.json"
            catalog.write_text(json.dumps({"fictional": True, "segments": [{"id": "sample"}]}))
            (folder / "manifest.json").write_text(json.dumps({"catalog_sha256": "different", "segments": []}))
            with self.assertRaises(MediaError):
                make_demo_assets(catalog, folder)


if __name__ == "__main__":
    unittest.main()
