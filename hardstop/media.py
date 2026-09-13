"""Measured, whole-clip media operations. No model estimates or mock outputs."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from decimal import Decimal, InvalidOperation, ROUND_CEILING


class MediaError(RuntimeError):
    """A safe failure that prevents an unverifiable cut from being delivered."""


def _run(arguments: list[str], timeout: int = 300) -> bytes:
    try:
        result = subprocess.run(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaError(f"Media command unavailable or timed out: {Path(arguments[0]).name}") from exc
    if result.returncode:
        # FFmpeg can echo arbitrary file metadata; don't pass its stderr into the UI.
        raise MediaError(f"Media verification failed: {Path(arguments[0]).name} exited {result.returncode}")
    return result.stdout


def _tool(name: str) -> str:
    value = shutil.which(name)
    if not value:
        raise MediaError(f"Required media tool is not installed: {name}")
    return value


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe(path: str | Path) -> dict:
    """Return measured container duration rounded UP to whole milliseconds."""
    source = Path(path).resolve()
    if not source.is_file():
        raise MediaError("Media file is missing")
    raw = _run([_tool("ffprobe"), "-v", "error", "-show_format", "-show_streams",
                "-of", "json", str(source)], timeout=60)
    try:
        data = json.loads(raw)
        duration = Decimal(str(data["format"]["duration"]))
        if not duration.is_finite() or duration <= 0:
            raise ValueError("Invalid duration")
        streams = data["streams"]
        videos = [s for s in streams if s.get("codec_type") == "video" and
                  not s.get("disposition", {}).get("attached_pic")]
        audios = [s for s in streams if s.get("codec_type") == "audio"]
        video = videos[0] if videos else {}
        return {"duration_ms": int((duration * 1000).to_integral_value(rounding=ROUND_CEILING)),
                "has_video": bool(videos), "has_audio": bool(audios),
                "width": int(video.get("width", 0)), "height": int(video.get("height", 0))}
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise MediaError("Media metadata is missing or invalid") from exc


def verify_decode(path: str | Path) -> None:
    """Decode every audio sample and video frame; a valid header is insufficient."""
    _run([_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-xerror",
          "-err_detect", "explode", "-i", str(Path(path).resolve()),
          "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], timeout=600)


def render_cut(paths: list[str | Path], output_path: str | Path) -> dict:
    """Concatenate complete source clips, then fully decode and hash the result.

    Inputs must share dimensions and contain both video and audio. Audio is padded
    only with silence to its measured clip boundary. The last video/audio boundary
    is limited to the sum of measured source durations, never to a user's budget.
    This preserves complete selected clips rather than cutting speech to fit.
    Output creation is atomic and refuses to replace an existing artifact.
    """
    if not paths:
        raise MediaError("At least one source clip is required")
    sources = [Path(p).resolve() for p in paths]
    destination = Path(output_path).resolve()
    if destination.exists() or destination in sources:
        raise MediaError("Output already exists; choose a new run path")
    metadata = [probe(path) for path in sources]
    dimensions = {(m["width"], m["height"]) for m in metadata}
    if len(dimensions) != 1 or any(not m["has_video"] or not m["has_audio"] for m in metadata):
        raise MediaError("Source clips need matching dimensions, video, and audio")
    for source in sources:
        verify_decode(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".hardstop-render-", dir=destination.parent) as temp:
        target = Path(temp) / "cut.mp4"
        arguments = [_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        filters = []
        for index, (source, info) in enumerate(zip(sources, metadata)):
            arguments += ["-i", str(source)]
            seconds = info["duration_ms"] / 1000
            filters += [f"[{index}:v:0]setpts=PTS-STARTPTS,fps=30,format=yuv420p[v{index}]",
                        f"[{index}:a:0]aresample=48000,aformat=channel_layouts=stereo,apad,"
                        f"atrim=duration={seconds:.3f},asetpts=PTS-STARTPTS[a{index}]"]
        labels = "".join(f"[v{i}][a{i}]" for i in range(len(sources)))
        filters.append(f"{labels}concat=n={len(sources)}:v=1:a=1[v][a]")
        expected_ms = sum(m["duration_ms"] for m in metadata)
        arguments += ["-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
                      "-t", f"{expected_ms / 1000:.3f}", "-c:v", "libx264", "-preset", "veryfast",
                      "-crf", "20", "-threads", "2", "-pix_fmt", "yuv420p", "-c:a", "aac",
                      "-b:a", "128k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
                      "-map_metadata", "-1", str(target)]
        _run(arguments, timeout=max(600, math.ceil(expected_ms / 1000) * 5))
        actual = probe(target)
        if not actual["has_video"] or not actual["has_audio"]:
            raise MediaError("Rendered output is missing video or audio")
        # One video frame plus AAC packet rounding is the only permitted drift.
        if abs(actual["duration_ms"] - expected_ms) > 60:
            raise MediaError("Rendered duration does not match complete selected clips")
        verify_decode(target)
        result = {**actual, "sha256": sha256_file(target), "decode_verified": True,
                  "expected_duration_ms": expected_ms}
        # Hard-link installation is atomic and exclusive on the same filesystem.
        try:
            os.link(target, destination)
        except FileExistsError as exc:
            raise MediaError("Output already exists; choose a new run path") from exc
    return result


def make_demo_assets(catalog_path: str | Path, output_dir: str | Path) -> dict:
    """Generate labeled fictional sample clips using the optional Pillow script."""
    catalog_path = Path(catalog_path).resolve()
    output_dir = Path(output_dir).resolve()
    manifest_path = output_dir / "manifest.json"
    # Reuse only immutable generated recordings with the same committed script
    # inputs and independently verified bytes. This also lets normal runtime use
    # the already generated media without Pillow or a local speech service.
    if manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text())
            source = json.loads(catalog_path.read_text())
            if (existing.get("catalog_sha256") == sha256_file(catalog_path) and
                    [s["id"] for s in existing["segments"]] == [s["id"] for s in source["segments"]]):
                for segment in existing["segments"]:
                    media = Path(segment["media_path"]).resolve()
                    if not media.is_relative_to(output_dir) or sha256_file(media) != segment["sha256"]:
                        raise MediaError("Existing sample media failed its integrity check")
                    info = probe(media)
                    if info["duration_ms"] != segment["duration_ms"] or not info["has_video"] or not info["has_audio"]:
                        raise MediaError("Existing sample metadata did not match the recording")
                    verify_decode(media)
                return existing
            raise MediaError("Sample catalog changed; generate into a new source directory")
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise MediaError("Existing sample manifest is invalid") from exc
    script = Path(__file__).resolve().parents[1] / "scripts" / "generate_demo_assets.py"
    import sys
    _run([sys.executable, str(script), "--catalog", str(catalog_path),
          "--output", str(output_dir)], timeout=1200)
    try:
        return json.loads(manifest_path.read_text())
    except (OSError, ValueError) as exc:
        raise MediaError("Generated sample manifest is missing or invalid") from exc
