#!/usr/bin/env python3
"""Package only verified fictional recordings and cards into a portable archive."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardstop.media import make_demo_assets, sha256_file
from scripts.import_demo_assets import BundleError, FORMAT, MAX_BYTES, ROOT, expected_catalog, validate_manifest


def package_bundle(source_dir: str | Path, output_path: str | Path,
                   catalog_path: str | Path = ROOT / "fixtures/catalog.json") -> dict:
    source_dir, output_path, catalog_path = Path(source_dir).resolve(), Path(output_path).absolute(), Path(catalog_path)
    if output_path.exists() or output_path.is_symlink():
        raise BundleError("Bundle output already exists; choose a new path")
    catalog = expected_catalog(catalog_path)
    manifest = make_demo_assets(catalog_path, source_dir)
    portable = {**catalog, "segments": [], "bundle_format": FORMAT,
                "catalog_sha256": sha256_file(catalog_path), "source_kind": "fictional_synthesized_recording",
                "source_duration_ms": manifest["source_duration_ms"]}
    files = {}
    for original, segment in zip(catalog["segments"], manifest["segments"]):
        source = Path(segment["media_path"])
        if source.is_symlink() or source.resolve().parent != source_dir:
            raise BundleError("Source media must be ordinary files in the source directory")
        item = {**original, **{k: segment[k] for k in ("duration_ms", "has_video", "has_audio", "width", "height", "sha256", "slide_id", "decode_verified", "narration")},
                "media_path": source.name}
        files[source.name] = source
        if segment.get("card_path"):
            card = Path(segment["card_path"])
            if card.is_symlink() or card.resolve().parent != source_dir or not card.is_file():
                raise BundleError("Source card must be an ordinary file in the source directory")
            item["card_path"] = card.name
            files[card.name] = card
        portable["segments"].append(item)
    validate_manifest(portable, catalog, catalog_path)
    if sum(path.stat().st_size for path in files.values()) > MAX_BYTES - 1024 * 1024:
        raise BundleError("Source bundle exceeds the size limit")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".hardstop-package-", dir=output_path.parent) as temporary:
        target = Path(temporary) / "source.zip"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("manifest.json", json.dumps(portable, indent=2) + "\n")
            for name, path in sorted(files.items()):
                archive.write(path, name)
        os.link(target, output_path)
    return {"path": str(output_path), "sha256": sha256_file(output_path),
            "bytes": output_path.stat().st_size, "segments": len(portable["segments"]),
            "source_duration_ms": portable["source_duration_ms"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / ".state/demo-assets")
    parser.add_argument("--output", type=Path, default=ROOT / "output/hardstop-source.zip")
    args = parser.parse_args()
    try:
        print(json.dumps(package_bundle(args.source, args.output), indent=2))
    except (BundleError, OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
