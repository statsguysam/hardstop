"""Import a bounded catalog of local, complete recordings without synthesis."""
from __future__ import annotations

import ctypes
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile

from . import media

MAX_CATALOG_BYTES = 256 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_CLIP_MS = 600_000
MAX_TOTAL_MS = 3_600_000
CATALOG_FIELDS = {"title", "description", "fictional", "narration", "segments"}
SEGMENT_FIELDS = {"id", "title", "transcript", "slide_text", "requires", "value", "media_path"}
# Slides IDs are 5 to 50 characters; reserve space for hs_ and _footer.
ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{1,39}\Z")
SHAPE_SUFFIXES = ("edge", "brand", "number", "title", "rule", "body", "footer")


class SourceError(ValueError):
    pass


def _text(value, label, limit, *, single_line=False):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit or
            any(ord(char) < 32 and char not in ("\n", "\t") for char in value) or
            (single_line and any(char in value for char in ("\n", "\t")))):
        raise SourceError(f"{label} must contain 1 to {limit} characters of valid text")
    return value


def validate_catalog_metadata(catalog, *, require_media_paths=True):
    """Validate declared content; this does not authenticate its truthfulness."""
    if not isinstance(catalog, dict):
        raise SourceError("The source catalog must be a JSON object")
    if require_media_paths and set(catalog) != CATALOG_FIELDS:
        raise SourceError("Catalog fields must be title, description, fictional, narration and segments")
    _text(catalog.get("title"), "Catalog title", 120, single_line=True)
    _text(catalog.get("description"), "Catalog description", 2000)
    _text(catalog.get("narration"), "Narration description", 120, single_line=True)
    if type(catalog.get("fictional")) is not bool:
        raise SourceError("Declare fictional explicitly as true or false")
    segments = catalog.get("segments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= 18:
        raise SourceError("A source catalog must contain 1 to 18 recordings")
    known, object_ids = set(), set()
    for segment in segments:
        if not isinstance(segment, dict) or (require_media_paths and set(segment) != SEGMENT_FIELDS):
            raise SourceError("Each segment must declare id, title, transcript, slide_text, requires, value and media_path")
        sid = segment.get("id")
        if not isinstance(sid, str) or not ID_PATTERN.fullmatch(sid) or sid in known:
            raise SourceError("Segment IDs must be unique snake_case names of 2 to 40 characters")
        generated_ids = {"hs_" + sid} | {"hs_" + sid + "_" + suffix for suffix in SHAPE_SUFFIXES}
        if generated_ids & object_ids:
            raise SourceError("Segment names collide with generated slide or shape IDs")
        object_ids.update(generated_ids)
        _text(segment.get("title"), "Segment title", 120, single_line=True)
        _text(segment.get("slide_text"), "Segment slide text", 320)
        if require_media_paths:
            _text(segment.get("transcript"), "Segment transcript", 12000)
            _relative_parts(segment.get("media_path"))
        requires = segment.get("requires")
        if (not isinstance(requires, list) or any(not isinstance(item, str) for item in requires) or
                len(requires) != len(set(requires)) or not set(requires) <= known):
            raise SourceError("Prerequisites must be unique IDs of earlier source recordings")
        if type(segment.get("value")) is not int or not 1 <= segment["value"] <= 10:
            raise SourceError("Segment value must be an integer from 1 to 10")
        known.add(sid)


def _relative_parts(value):
    if (not isinstance(value, str) or not value or "\\" in value or
            any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise SourceError("media_path must be a relative MP4 path inside the catalog directory")
    parts = value.split("/")
    if (value.startswith("/") or any(part in ("", ".", "..") for part in parts) or
            PurePosixPath(value).suffix.lower() != ".mp4"):
        raise SourceError("media_path must be a relative MP4 path inside the catalog directory")
    return parts


def _open_directory(path, *, create=False):
    path = Path(path).absolute()
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if part in (".", ".."):
                raise SourceError("Directory paths cannot contain traversal components")
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_relative(directory_fd, parts):
    descriptor = os.dup(directory_fd)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        result = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        if not stat.S_ISREG(os.fstat(result).st_mode):
            os.close(result)
            raise SourceError("Catalog and recordings must be regular files")
        return result
    finally:
        os.close(descriptor)


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_catalog(descriptor):
    before = os.fstat(descriptor)
    if before.st_size > MAX_CATALOG_BYTES:
        os.close(descriptor)
        raise SourceError("Source catalog exceeds 256 KiB")
    with os.fdopen(descriptor, "rb") as stream:
        raw = stream.read(MAX_CATALOG_BYTES + 1)
        if len(raw) > MAX_CATALOG_BYTES or _signature(os.fstat(stream.fileno())) != _signature(before):
            raise SourceError("Source catalog changed while being read")
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SourceError("Source JSON contains duplicate keys")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique_keys), hashlib.sha256(raw).hexdigest()


def _copy_recording(descriptor, destination):
    before = os.fstat(descriptor)
    if before.st_size <= 0 or before.st_size > MAX_FILE_BYTES:
        os.close(descriptor)
        raise SourceError("Each recording must contain between 1 byte and 512 MiB")
    digest, total = hashlib.sha256(), 0
    with os.fdopen(descriptor, "rb") as source, open(destination, "xb") as target:
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise SourceError("A source recording grew beyond the import limit")
            digest.update(chunk)
            target.write(chunk)
        if total != before.st_size or _signature(os.fstat(source.fileno())) != _signature(before):
            raise SourceError("A source recording changed while being copied")
        target.flush()
        os.fsync(target.fileno())
    return total, digest.hexdigest()


def _measure_recording(path):
    # Force a self-contained MP4/MOV demuxer; a renamed playlist cannot open a URL.
    input_options = ["-protocol_whitelist", "file,pipe", "-enable_drefs", "0", "-use_absolute_path", "0", "-f", "mov"]
    raw = media._run([media._tool("ffprobe"), "-v", "error", *input_options,
                      "-show_format", "-show_streams", "-of", "json", str(path)], timeout=60)
    try:
        data = json.loads(raw)
        duration = Decimal(str(data["format"]["duration"]))
        videos = [item for item in data["streams"] if item.get("codec_type") == "video"]
        audios = [item for item in data["streams"] if item.get("codec_type") == "audio"]
        if (len(videos) != 1 or len(audios) != 1 or videos[0].get("disposition", {}).get("attached_pic") or
                not duration.is_finite() or duration <= 0):
            raise ValueError()
        info = {"duration_ms": int((duration * 1000).to_integral_value(rounding=ROUND_CEILING)),
                "has_video": True, "has_audio": True, "width": int(videos[0]["width"]), "height": int(videos[0]["height"])}
        if (not 1 <= info["duration_ms"] <= MAX_CLIP_MS or
                not 16 <= info["width"] <= 3840 or not 16 <= info["height"] <= 2160 or
                info["width"] % 2 or info["height"] % 2):
            raise ValueError()
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise SourceError("Each MP4 needs one video stream, one audio stream, even dimensions up to 3840x2160, and at most 10 minutes") from None
    media._run([media._tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-xerror",
                "-err_detect", "explode", *input_options, "-i", str(path),
                "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], timeout=600)
    return dict(info, decode_verified=True)


def _install_directory(parent_fd, staged_name, destination_name):
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(library, "renameatx_np"):
        rename, flag = library.renameatx_np, 4  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        rename, flag = library.renameat2, 1  # RENAME_NOREPLACE
    else:
        raise SourceError("Atomic source installation requires macOS or Linux")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    if rename(parent_fd, os.fsencode(staged_name), parent_fd, os.fsencode(destination_name), flag) != 0:
        raise SourceError("Source destination already exists or could not be installed")


def import_source(catalog_path, output_dir):
    """Copy, measure and fully decode 1 to 18 clips into a new source directory.

    Paths in the input JSON are relative to its directory. Fiction/narration,
    transcripts and slide text are declarations by the user, not independently
    verified descriptions of the recording. No media is synthesized or rewritten.
    """
    catalog_path, output_dir = Path(catalog_path).absolute(), Path(output_dir).absolute()
    root_fd = parent_fd = None
    try:
        root_fd = _open_directory(catalog_path.parent)
        catalog, catalog_hash = _read_catalog(_open_relative(root_fd, [catalog_path.name]))
        validate_catalog_metadata(catalog)
        parent_fd = _open_directory(output_dir.parent, create=True)
        try:
            os.stat(output_dir.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise SourceError("Source destination already exists; choose a new directory")
        with tempfile.TemporaryDirectory(prefix=".hardstop-source-", dir=output_dir.parent) as temporary:
            staged = Path(temporary)
            manifest = {key: value for key, value in catalog.items() if key != "segments"}
            manifest.update(source_kind="user_recordings", metadata_provenance="user_declared",
                            catalog_sha256=catalog_hash, segments=[])
            dimensions, total_bytes, total_ms = set(), 0, 0
            for original in catalog["segments"]:
                descriptor = _open_relative(root_fd, _relative_parts(original["media_path"]))
                target = staged / (original["id"] + ".mp4")
                size, digest = _copy_recording(descriptor, target)
                total_bytes += size
                if total_bytes > MAX_TOTAL_BYTES:
                    raise SourceError("Combined recordings exceed the 2 GiB import limit")
                info = _measure_recording(target)
                if media.sha256_file(target) != digest:
                    raise SourceError("Copied recording changed during verification")
                dimensions.add((info["width"], info["height"]))
                total_ms += info["duration_ms"]
                if len(dimensions) > 1 or total_ms > MAX_TOTAL_MS:
                    raise SourceError("Recordings must share dimensions and total at most 60 minutes")
                manifest["segments"].append(dict(original, **info, sha256=digest,
                    media_path=str(output_dir / target.name), slide_id="hs_" + original["id"]))
            manifest["source_duration_ms"] = total_ms
            manifest["source_size_bytes"] = total_bytes
            with (staged / "manifest.json").open("x") as stream:
                json.dump(manifest, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            _install_directory(parent_fd, staged.name, output_dir.name)
            return manifest
    except SourceError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, media.MediaError):
        raise SourceError("Source import failed validation; no verified source was installed") from None
    finally:
        if root_fd is not None:
            os.close(root_fd)
        if parent_fd is not None:
            os.close(parent_fd)
