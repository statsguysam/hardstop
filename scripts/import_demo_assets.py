#!/usr/bin/env python3
"""Import a verified portable source bundle without Pillow or speech synthesis."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardstop.media import MediaError, make_demo_assets, probe, sha256_file

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 100 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
FORMAT = "hardstop-source-v1"
MEDIA_FIELDS = {"duration_ms", "has_video", "has_audio", "width", "height", "media_path",
                "card_path", "sha256", "slide_id", "decode_verified", "narration"}


class BundleError(ValueError):
    pass


def install_directory(staged: Path, destination: Path) -> None:
    """Atomic exclusive rename on the two supported platforms, including races."""
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(library, "renamex_np"):
        rename = library.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = rename(os.fsencode(staged), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename = library.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = rename(-100, os.fsencode(staged), -100, os.fsencode(destination), 1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise BundleError("This platform does not provide an atomic exclusive directory rename")
    if result != 0:
        raise OSError(ctypes.get_errno(), "Exclusive source installation failed")


def expected_catalog(catalog_path: Path) -> dict:
    catalog = json.loads(catalog_path.read_text())
    segments = catalog.get("segments")
    if catalog.get("fictional") is not True or not isinstance(segments, list) or len(segments) != 8:
        raise BundleError("The source bundle requires the eight-segment fictional catalog")
    ids = [s.get("id") for s in segments]
    if len(set(ids)) != 8 or any(not isinstance(s, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", s) for s in ids):
        raise BundleError("The catalog has invalid segment IDs")
    return catalog


def validate_manifest(manifest: dict, catalog: dict, catalog_path: Path) -> set[str]:
    if not isinstance(manifest, dict) or manifest.get("bundle_format") != FORMAT:
        raise BundleError("Unsupported source bundle format")
    top_fields = set(catalog) | {"source_duration_ms", "source_kind", "catalog_sha256", "bundle_format"}
    if set(manifest) != top_fields or manifest.get("catalog_sha256") != sha256_file(catalog_path):
        raise BundleError("Source bundle does not match this checkout's catalog")
    if manifest.get("source_kind") != "fictional_synthesized_recording":
        raise BundleError("Source recordings must remain labeled fictional and synthesized")
    for key, value in catalog.items():
        if key != "segments" and manifest.get(key) != value:
            raise BundleError("Source bundle changed the fictional catalog metadata")
    segments = manifest.get("segments")
    if not isinstance(segments, list) or len(segments) != 8:
        raise BundleError("Source bundle must contain exactly eight clips")
    names = {"manifest.json"}
    total_ms = 0
    for original, segment in zip(catalog["segments"], segments):
        if not isinstance(segment, dict) or set(segment) - (set(original) | MEDIA_FIELDS):
            raise BundleError("Unexpected segment metadata")
        if any(segment.get(k) != v for k, v in original.items()):
            raise BundleError("Source bundle changed a transcript, dependency, or catalog value")
        ident = original["id"]
        if segment.get("media_path") != f"{ident}.mp4":
            raise BundleError("Source media paths must be portable clip basenames")
        if "card_path" in segment and segment["card_path"] != f"{ident}.png":
            raise BundleError("Source card paths must be portable image basenames")
        if not isinstance(segment.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", segment["sha256"]):
            raise BundleError("Source clip SHA-256 is invalid")
        if type(segment.get("duration_ms")) is not int or segment["duration_ms"] <= 0:
            raise BundleError("Source clip duration is invalid")
        if segment.get("has_video") is not True or segment.get("has_audio") is not True:
            raise BundleError("Each recording must declare audio and video")
        if any(type(segment.get(key)) is not int or segment[key] <= 0 for key in ("width", "height")):
            raise BundleError("Source video dimensions are invalid")
        if segment.get("slide_id") != "hs_" + ident:
            raise BundleError("Source slide identity changed")
        names.add(segment["media_path"])
        if "card_path" in segment:
            names.add(segment["card_path"])
        total_ms += segment["duration_ms"]
    if manifest.get("source_duration_ms") != total_ms:
        raise BundleError("Source duration does not equal its measured clip sum")
    return names


def import_bundle(archive_path: str | Path, output_dir: str | Path,
                  catalog_path: str | Path = ROOT / "fixtures/catalog.json") -> dict:
    archive_path, output_dir, catalog_path = Path(archive_path), Path(output_dir), Path(catalog_path)
    output_dir = output_dir.absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise BundleError("Destination already exists; choose a new source directory")
    if not archive_path.is_file() or archive_path.stat().st_size > MAX_BYTES:
        raise BundleError("Bundle is missing or exceeds the 100 MiB limit")
    catalog = expected_catalog(catalog_path)
    allowed = {"manifest.json"} | {s["id"] + suffix for s in catalog["segments"] for suffix in (".mp4", ".png")}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > 17 or len(names) != len(set(names)) or not set(names) <= allowed:
                raise BundleError("Bundle contains duplicate, unknown, or nonportable filenames")
            if "manifest.json" not in names or sum(e.file_size for e in entries) > MAX_BYTES:
                raise BundleError("Bundle is missing its manifest or exceeds the extraction limit")
            for entry in entries:
                file_type = stat.S_IFMT(entry.external_attr >> 16)
                if (entry.is_dir() or file_type not in (0, stat.S_IFREG) or entry.flag_bits & 1 or
                        entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise BundleError("Bundle contains a directory, link, encrypted or unsupported entry")
                if entry.file_size > 1024 * 1024 and entry.file_size > max(1, entry.compress_size) * 200:
                    raise BundleError("Bundle compression ratio exceeds the extraction limit")
            if archive.getinfo("manifest.json").file_size > MAX_MANIFEST_BYTES:
                raise BundleError("Source manifest is too large")
            manifest = json.loads(archive.read("manifest.json"))
            expected = validate_manifest(manifest, catalog, catalog_path)
            if set(names) != expected:
                raise BundleError("Bundle contents do not exactly match the manifest")
            output_dir.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".hardstop-import-", dir=output_dir.parent) as temporary:
                staged = Path(temporary) / "assets"
                staged.mkdir()
                written = 0
                for entry in entries:
                    if entry.filename == "manifest.json":
                        continue
                    with archive.open(entry) as source, (staged / entry.filename).open("xb") as destination:
                        while block := source.read(65536):
                            written += len(block)
                            if written > MAX_BYTES:
                                raise BundleError("Bundle exceeds the extraction limit")
                            destination.write(block)
                for segment in manifest["segments"]:
                    segment["media_path"] = str(staged / segment["media_path"])
                    if "card_path" in segment:
                        segment["card_path"] = str(staged / segment["card_path"])
                (staged / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
                # Hash, duration and full decode verification happen before install.
                make_demo_assets(catalog_path, staged)
                for segment in manifest["segments"]:
                    actual = probe(segment["media_path"])
                    if any(segment.get(key) != value for key, value in actual.items()):
                        raise BundleError("Source media measurements differ from the portable manifest")
                for segment in manifest["segments"]:
                    segment["media_path"] = str(output_dir / Path(segment["media_path"]).name)
                    if "card_path" in segment:
                        segment["card_path"] = str(output_dir / Path(segment["card_path"]).name)
                (staged / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
                if output_dir.exists() or output_dir.is_symlink():
                    raise BundleError("Destination appeared during import; refusing replacement")
                install_directory(staged, output_dir)
                return manifest
    except (zipfile.BadZipFile, zlib.error, OSError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, MediaError) as exc:
        raise BundleError("Source bundle failed validation; no verified source was installed") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / ".state/demo-assets")
    args = parser.parse_args()
    try:
        manifest = import_bundle(args.archive, args.output)
        print(json.dumps({"status": "verified_source_imported", "segments": len(manifest["segments"]),
                          "source_duration_ms": manifest["source_duration_ms"], "output": str(args.output.absolute())}))
    except BundleError as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
