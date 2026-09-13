"""Portable bundle tests with real recordings and malicious archive inputs."""
import json
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

from hardstop.media import probe, sha256_file
from scripts.import_demo_assets import BundleError, import_bundle, install_directory
from scripts.package_demo_assets import package_bundle


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools required")
class AssetBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.catalog = Path(__file__).resolve().parents[1] / "fixtures/catalog.json"
        data = json.loads(cls.catalog.read_text())
        source = cls.root / "source"
        source.mkdir()
        clip = cls.root / "clip.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=30",
                        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "0.3",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        info = probe(clip)
        segments = []
        for segment in data["segments"]:
            media = source / (segment["id"] + ".mp4")
            shutil.copyfile(clip, media)
            segments.append({**segment, **info, "media_path": str(media), "sha256": sha256_file(media),
                             "slide_id": "hs_" + segment["id"], "decode_verified": True,
                             "narration": "Synthetic test tone"})
        manifest = {**data, "segments": segments, "source_duration_ms": info["duration_ms"] * 8,
                    "catalog_sha256": sha256_file(cls.catalog), "source_kind": "fictional_synthesized_recording"}
        (source / "manifest.json").write_text(json.dumps(manifest))
        cls.bundle = cls.root / "portable.zip"
        package_bundle(source, cls.bundle, cls.catalog)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def altered(self, name, mutate):
        path = self.root / name
        with zipfile.ZipFile(self.bundle) as archive:
            values = {i.filename: archive.read(i.filename) for i in archive.infolist()}
        mutate(values)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for key, value in values.items():
                archive.writestr(key, value)
        return path

    def test_round_trip_rebases_paths_and_verifies_real_media(self):
        with zipfile.ZipFile(self.bundle) as archive:
            raw = archive.read("manifest.json")
            self.assertNotIn(str(self.root).encode(), raw)
            self.assertNotIn(b"/Users/", raw)
            self.assertEqual(len(archive.namelist()), 9)
        output = self.root / "relocated-assets"
        result = import_bundle(self.bundle, output, self.catalog)
        self.assertEqual(len(result["segments"]), 8)
        for segment in result["segments"]:
            self.assertEqual(Path(segment["media_path"]).parent, output)
            self.assertEqual(sha256_file(segment["media_path"]), segment["sha256"])

    def test_refuses_existing_destination_without_touching_it(self):
        destination = self.root / "existing"
        destination.mkdir()
        (destination / "keep").write_text("previous source")
        with self.assertRaises(BundleError):
            import_bundle(self.bundle, destination, self.catalog)
        self.assertEqual((destination / "keep").read_text(), "previous source")

    def test_traversal_unknown_files_and_duplicate_members_rejected(self):
        for index, filename in enumerate(["../escape", "/absolute", "nested/clip.mp4", "credentials.json"]):
            archive = self.altered(f"bad-name-{index}.zip", lambda values: values.update({filename: b"x"}))
            with self.assertRaises(BundleError):
                import_bundle(archive, self.root / f"bad-name-{index}", self.catalog)

    def test_changed_clip_hash_never_installs_destination(self):
        archive = self.altered("bad-hash.zip", lambda values: values.update({"opening.mp4": values["opening.mp4"] + b"changed"}))
        destination = self.root / "bad-hash"
        with self.assertRaises(BundleError):
            import_bundle(archive, destination, self.catalog)
        self.assertFalse(destination.exists())

    def test_catalog_dependency_tampering_rejected(self):
        def mutate(values):
            manifest = json.loads(values["manifest.json"])
            manifest["segments"][4]["requires"] = []
            values["manifest.json"] = json.dumps(manifest).encode()
        archive = self.altered("bad-dependency.zip", mutate)
        with self.assertRaises(BundleError):
            import_bundle(archive, self.root / "bad-dependency", self.catalog)

    def test_symlink_and_oversized_extraction_rejected(self):
        symlink = self.root / "symlink.zip"
        with zipfile.ZipFile(symlink, "w") as archive:
            info = zipfile.ZipInfo("opening.mp4")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../../outside")
            archive.writestr("manifest.json", "{}")
        with self.assertRaises(BundleError):
            import_bundle(symlink, self.root / "bad-symlink", self.catalog)
        with mock.patch("scripts.import_demo_assets.MAX_BYTES", 100):
            with self.assertRaises(BundleError):
                import_bundle(self.bundle, self.root / "oversized", self.catalog)

    def test_portable_manifest_cannot_reference_absolute_path(self):
        def mutate(values):
            manifest = json.loads(values["manifest.json"])
            manifest["segments"][0]["media_path"] = "/tmp/secret.mp4"
            values["manifest.json"] = json.dumps(manifest).encode()
        archive = self.altered("absolute-manifest.zip", mutate)
        with self.assertRaises(BundleError):
            import_bundle(archive, self.root / "absolute-manifest", self.catalog)

    def test_duplicate_member_rejected(self):
        archive = self.root / "duplicate.zip"
        shutil.copyfile(self.bundle, archive)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(archive, "a") as output:
                output.writestr("opening.mp4", b"duplicate")
        with self.assertRaises(BundleError):
            import_bundle(archive, self.root / "duplicate", self.catalog)

    def test_extreme_compression_ratio_rejected_before_extraction(self):
        archive = self.altered("compressed-bomb.zip", lambda values: values.update({"opening.mp4": b"0" * (2 * 1024 * 1024)}))
        destination = self.root / "compressed-bomb"
        with self.assertRaises(BundleError):
            import_bundle(archive, destination, self.catalog)
        self.assertFalse(destination.exists())

    def test_atomic_install_cannot_replace_even_an_empty_existing_directory(self):
        source = self.root / "race-source"
        destination = self.root / "race-destination"
        source.mkdir()
        destination.mkdir()
        inode = destination.stat().st_ino
        with self.assertRaises(OSError):
            install_directory(source, destination)
        self.assertTrue(source.exists())
        self.assertEqual(destination.stat().st_ino, inode)


if __name__ == "__main__":
    unittest.main()
