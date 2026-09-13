"""Small, fail-closed adapters for the three HardStop applications.

No sending, searches, overwrite uploads, automatic write retries, or runtime mocks.
Credentials are obtained from the private configuration module on every request.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import configure
from .source import validate_catalog_metadata


JSON_LIMIT = 16 * 1024 * 1024
UPLOAD_CHUNK = 8 * 1024 * 1024
HASH_BLOCK = 4 * 1024 * 1024
ALLOWED_HOSTS = frozenset({
    "gmail.googleapis.com", "slides.googleapis.com", "www.googleapis.com",
    "api.dropboxapi.com", "content.dropboxapi.com",
})


class ProviderError(configure.SetupError):
    """Safe error information; never carries response bodies or credentials."""

    def __init__(self, operation, status=None, uncertain=False, *, copy_id=None,
                 presentation_id=None, draft_id=None):
        self.operation = operation
        self.status = status
        self.uncertain = bool(uncertain)
        self.copy_id = copy_id
        self.presentation_id = presentation_id
        self.draft_id = draft_id
        suffix = f" (HTTP {status})" if status is not None else ""
        state = "; write outcome requires reconciliation" if uncertain else ""
        super().__init__(f"{operation} failed{suffix}{state}")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward bearer headers (or request bodies) to a redirect target.
        return None


class _ContentHash:
    """Dropbox's SHA-256-of-4-MiB-block-digests, with bounded memory."""

    def __init__(self):
        self.outer = hashlib.sha256()
        self.block = hashlib.sha256()
        self.used = 0

    def update(self, data):
        view = memoryview(data)
        while view:
            length = min(HASH_BLOCK - self.used, len(view))
            self.block.update(view[:length])
            self.used += length
            view = view[length:]
            if self.used == HASH_BLOCK:
                self.outer.update(self.block.digest())
                self.block = hashlib.sha256()
                self.used = 0

    def hexdigest(self):
        result = self.outer.copy()
        if self.used:
            result.update(self.block.digest())
        return result.hexdigest()


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise ValueError("Invalid application resource ID")
    return value


def _created_identifier(result, key, operation):
    try:
        return _identifier(result.get(key))
    except ValueError:
        raise ProviderError(operation, uncertain=True) from None


def _valid_file_metadata(value):
    return (isinstance(value, dict) and value.get(".tag", "file") == "file" and
            type(value.get("size")) is int and value["size"] >= 0 and
            all(isinstance(value.get(key), str) and value[key] for key in ("id", "rev", "content_hash")) and
            re.fullmatch(r"[0-9a-f]{64}", value["content_hash"]) is not None)


def _dropbox_path(value):
    if (not isinstance(value, str) or not value.startswith("/") or
            value.endswith("/") or "\\" in value or
            any(ord(char) < 32 or ord(char) == 127 for char in value) or
            any(part in ("", ".", "..") for part in value[1:].split("/"))):
        raise ValueError("Expected an absolute Dropbox file path")
    return value


def _safe_title(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500 or any(
            char in value for char in ("\r", "\n", "\x00")):
        raise ValueError("Expected a nonempty single-line title")
    return value


def _stable_presentation(raw):
    """Retain text, style, geometry, notes, and ordering; omit server volatility."""
    volatile = {"revisionId", "presentationId", "createdTime", "modifiedTime",
                "lastModifiedTime", "thumbnailUrl"}

    def clean(value):
        if isinstance(value, list):
            return [clean(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {}
        for key, item in value.items():
            if key in volatile:
                continue
            if key == "contentUrl" and isinstance(item, str):
                # Signed URL queries expire without the image changing. Preserve
                # the image resource path, so replacing an image still matters.
                parsed = urlsplit(item)
                result[key] = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
            else:
                result[key] = clean(item)
        return result

    return clean(raw)


def _file_hashes(path):
    sha = hashlib.sha256()
    content = _ContentHash()
    size = 0
    with open(path, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            sha.update(chunk)
            content.update(chunk)
    return size, sha.hexdigest(), content.hexdigest()


def _selected_presentation(raw, slide_ids):
    content = _stable_presentation(raw)
    content.pop("title", None)  # A copied delivery has its own document title.
    selected = set(slide_ids)
    content["slides"] = [slide for slide in content.get("slides", []) if slide["objectId"] in selected]
    return content


class Providers:
    def __init__(self, *, timeout=30, media_timeout=120, opener=None):
        if timeout <= 0 or media_timeout <= 0:
            raise ValueError("Provider timeouts must be positive")
        self.timeout = timeout
        self.media_timeout = media_timeout
        self._opener = opener if opener is not None else build_opener(_NoRedirect())

    @contextmanager
    def _response(self, url, *, method="GET", headers=None, body=None,
                  operation="Application request", write=False, media=False):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or
                parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise ValueError("Unapproved provider endpoint")
        request = Request(url, method=method, headers=headers or {}, data=body)
        try:
            with self._opener.open(request, timeout=self.media_timeout if media else self.timeout) as response:
                status = getattr(response, "status", 200)
                if not 200 <= status < 300:
                    raise ProviderError(operation, status, write and status >= 500)
                yield response
        except ProviderError:
            raise
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise ProviderError(operation, status, write and (status >= 500 or status == 408)) from None
        except (URLError, TimeoutError, OSError, EOFError, HTTPException):
            raise ProviderError(operation, uncertain=write) from None

    def _json(self, url, *, method="POST", headers=None, payload=None,
              body=None, operation="Application request", write=False, media=False):
        request_headers = dict(headers or {})
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=True).encode()
            request_headers["Content-Type"] = "application/json"
        with self._response(url, method=method, headers=request_headers, body=body,
                            operation=operation, write=write, media=media) as response:
            raw = response.read(JSON_LIMIT + 1)
            if len(raw) > JSON_LIMIT:
                raise ProviderError(operation, uncertain=write)
            try:
                result = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ProviderError(operation, uncertain=write) from None
            if not isinstance(result, dict):
                raise ProviderError(operation, uncertain=write)
            return result

    def _google(self, url, *, method="GET", payload=None, operation="Google request", write=False):
        return self._json(url, method=method, payload=payload, operation=operation, write=write,
                          headers={"Authorization": "Bearer " + configure.google_access_token()})

    @staticmethod
    def _draft_raw(subject, body):
        subject = _safe_title(subject)
        if not isinstance(body, str) or len(body.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Draft body must be text smaller than 1 MiB")
        message = EmailMessage(policy=policy.SMTP)
        message["Subject"] = subject
        # Intentionally no To, Cc, Bcc, From, or sending operation.
        message.set_content(body)
        return base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")

    def create_draft(self, subject, body):
        result = self._google("https://gmail.googleapis.com/gmail/v1/users/me/drafts", method="POST",
                              payload={"message": {"raw": self._draft_raw(subject, body)}},
                              operation="Create Gmail draft", write=True)
        draft_id = _created_identifier(result, "id", "Create Gmail draft")
        try:
            return self.read_draft(draft_id)
        except ProviderError as exc:
            exc.draft_id = draft_id
            exc.uncertain = True
            raise

    def read_draft(self, draft_id):
        draft_id = _identifier(draft_id)
        result = self._google(f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_id}?format=raw",
                              operation="Read Gmail draft")
        try:
            raw_message = result["message"]
            raw = raw_message["raw"]
            decoded = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True)
            message = BytesParser(policy=policy.default).parsebytes(decoded)
            subject = str(message.get("Subject", ""))
            parts = [part.get_content() for part in message.walk()
                     if part.get_content_type() == "text/plain" and
                     part.get_content_disposition() != "attachment"]
            if not parts or not all(isinstance(part, str) for part in parts):
                raise ValueError("No plaintext draft")
            body = "\n".join(parts).replace("\r\n", "\n").rstrip("\n")
            addresses = {key: [str(item) for item in message.get_all(key, [])]
                         for key in ("To", "Cc", "Bcc", "From")}
            message_id = _identifier(raw_message["id"])
            if result.get("id") != draft_id:
                raise ValueError("Draft identity mismatch")
        except (KeyError, TypeError, ValueError, UnicodeError, LookupError):
            raise ProviderError("Read Gmail draft") from None
        return {"draft_id": draft_id, "message_id": message_id, "subject": subject,
                "body": body, "has_recipients": any(addresses[key] for key in ("To", "Cc", "Bcc")),
                "fingerprint": _fingerprint({"subject": subject, "body": body, "addresses": addresses})}

    def update_draft(self, draft_id, subject, body):
        draft_id = _identifier(draft_id)
        result = self._google(f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{draft_id}",
                              method="PUT", payload={"id": draft_id, "message": {"raw": self._draft_raw(subject, body)}},
                              operation="Update Gmail draft", write=True)
        if result.get("id") != draft_id:
            raise ProviderError("Update Gmail draft", uncertain=True, draft_id=draft_id)
        try:
            return self.read_draft(draft_id)
        except ProviderError as exc:
            exc.draft_id = draft_id
            exc.uncertain = True
            raise

    def create_source_deck(self, catalog, *, presentation_id=None, on_created=None):
        validate_catalog_metadata(catalog, require_media_paths=False)
        segments = catalog["segments"]
        identifiers = [segment["id"] for segment in segments]
        title = _safe_title(catalog["title"])
        legacy_demo = catalog.get("source_kind") == "fictional_synthesized_recording"
        if presentation_id is None:
            created = self._google("https://slides.googleapis.com/v1/presentations", method="POST",
                                   payload={"title": title}, operation="Create source deck", write=True)
            presentation_id = _created_identifier(created, "presentationId", "Create source deck")
            if on_created is not None:
                try:
                    on_created(presentation_id)
                except Exception:
                    raise ProviderError("Record created source deck", uncertain=True, presentation_id=presentation_id) from None
        else:
            existing = self.read_deck(presentation_id)
            created = existing["raw"]
            if existing["slide_ids"]:
                expected = ["hs_" + item for item in identifiers]
                content_matches = existing["slide_ids"] == expected and created.get("title") == title
                for slide, segment in zip(created.get("slides", []), segments):
                    elements = {element.get("objectId"): element for element in slide.get("pageElements", [])}
                    for field, text in (("title", segment["title"]), ("body", segment["slide_text"])):
                        element = elements.get("hs_" + segment["id"] + "_" + field, {})
                        actual = "".join(item.get("textRun", {}).get("content", "") for item in
                                         element.get("shape", {}).get("text", {}).get("textElements", []))
                        content_matches = content_matches and actual.rstrip("\n") == text.rstrip("\n")
                if not content_matches:
                    raise ProviderError("Verify source deck before resume", presentation_id=presentation_id)
                return {"presentation_id": presentation_id, "slide_ids": dict(zip(identifiers, expected)),
                        "fingerprint": existing["fingerprint"], "revision_id": existing["revision_id"]}
        try:
            presentation_id = _identifier(presentation_id)
            page_size = created.get("pageSize", {})
            width = self._points(page_size.get("width"), 720)
            height = self._points(page_size.get("height"), 405)
            requests = [{"deleteObject": {"objectId": slide["objectId"]}}
                        for slide in created.get("slides", [])]
            for index, segment in enumerate(segments):
                requests.extend(self._slide_requests(segment, index, width, height, len(segments),
                    legacy_demo=legacy_demo, fictional=catalog["fictional"], narration=catalog["narration"]))
            self._google(f"https://slides.googleapis.com/v1/presentations/{presentation_id}:batchUpdate",
                         method="POST", payload={"requests": requests}, operation="Populate source deck", write=True)
            deck = self.read_deck(presentation_id)
            expected = ["hs_" + item for item in identifiers]
            if deck["slide_ids"] != expected:
                raise ProviderError("Verify source deck", uncertain=True)
            return {"presentation_id": presentation_id, "slide_ids": dict(zip(identifiers, expected)),
                    "fingerprint": deck["fingerprint"], "revision_id": deck["revision_id"]}
        except ProviderError as exc:
            exc.presentation_id = presentation_id
            raise

    @staticmethod
    def _points(dimension, default):
        if not dimension:
            return default
        value = float(dimension["magnitude"])
        unit = dimension.get("unit", "PT")
        if unit == "EMU":
            value /= 12700
        elif unit != "PT":
            raise ValueError("Unsupported slide dimension unit")
        if not 100 <= value <= 3000:
            raise ValueError("Unsupported slide dimensions")
        return value

    @staticmethod
    def _slide_requests(segment, index, width, height, total, *, legacy_demo=False, fictional=False, narration=""):
        slide_id = "hs_" + segment["id"]
        navy = {"red": 11 / 255, "green": 17 / 255, "blue": 32 / 255}
        cobalt = {"red": 59 / 255, "green": 91 / 255, "blue": 1.0}
        citrus = {"red": 215 / 255, "green": 1.0, "blue": 88 / 255}
        white = {"red": 0.96, "green": 0.97, "blue": 1.0}
        muted = {"red": 0.64, "green": 0.70, "blue": 0.80}
        sx, sy = width / 720, height / 405
        requests = [
            {"createSlide": {"objectId": slide_id, "insertionIndex": index,
                             "slideLayoutReference": {"predefinedLayout": "BLANK"}}},
            {"updatePageProperties": {"objectId": slide_id,
                "pageProperties": {"pageBackgroundFill": {"solidFill": {"color": {"rgbColor": navy}, "alpha": 1}}},
                "fields": "pageBackgroundFill"}},
        ]

        def shape(name, x, y, w, h, text=None, size=20, color=white, bold=False, fill=None):
            object_id = slide_id + "_" + name
            requests.append({"createShape": {"objectId": object_id, "shapeType": "RECTANGLE" if fill else "TEXT_BOX",
                "elementProperties": {"pageObjectId": slide_id,
                    "size": {"width": {"magnitude": w * sx, "unit": "PT"}, "height": {"magnitude": h * sy, "unit": "PT"}},
                    "transform": {"scaleX": 1, "scaleY": 1, "translateX": x * sx, "translateY": y * sy, "unit": "PT"}}}})
            if fill:
                requests.append({"updateShapeProperties": {"objectId": object_id,
                    "shapeProperties": {"shapeBackgroundFill": {"solidFill": {"color": {"rgbColor": fill}, "alpha": 1}},
                                        "outline": {"propertyState": "NOT_RENDERED"}},
                    "fields": "shapeBackgroundFill,outline"}})
            if text is not None:
                requests.extend([
                    {"insertText": {"objectId": object_id, "text": text}},
                    {"updateTextStyle": {"objectId": object_id, "textRange": {"type": "ALL"},
                        "style": {"fontFamily": "Arial", "fontSize": {"magnitude": size * sy, "unit": "PT"},
                                  "foregroundColor": {"opaqueColor": {"rgbColor": color}}, "bold": bold},
                        "fields": "fontFamily,fontSize,foregroundColor,bold"}},
                ])

        shape("edge", 0, 0, 8, 405, fill=cobalt)
        brand = "HARDSTOP  /  DEMO DELIVERY" if legacy_demo else "HARDSTOP  /  SOURCE RECORDINGS"
        footer = "FICTIONAL FIXTURE · SYNTHESIZED NARRATION" if legacy_demo else (
            ("FICTIONAL SOURCE · " if fictional else "SOURCE RECORDINGS · ") + narration)
        title_size = 35 if legacy_demo or len(segment["title"]) <= 65 else 28 if len(segment["title"]) <= 100 else 24
        body_size = 23 if legacy_demo or len(segment["slide_text"]) <= 140 else 18 if len(segment["slide_text"]) <= 240 else 15
        shape("brand", 34, 27, 550, 27, brand, size=11, color=citrus, bold=True)
        shape("number", 633, 27, 60, 27, f"{index + 1:02d} / {total:02d}", size=11, color=muted)
        shape("title", 34, 91, 650, 100, segment["title"], size=title_size, bold=True)
        shape("rule", 39, 200, 86, 4, fill=cobalt)
        shape("body", 34, 222, 645, 113, segment["slide_text"], size=body_size)
        shape("footer", 34, 365, 650, 23, footer, size=9, color=muted)
        return requests

    def read_deck(self, presentation_id):
        presentation_id = _identifier(presentation_id)
        raw = self._google(f"https://slides.googleapis.com/v1/presentations/{presentation_id}", operation="Read Google Slides deck")
        try:
            if raw.get("presentationId") != presentation_id:
                raise ValueError("Presentation identity mismatch")
            slide_ids = [_identifier(slide["objectId"]) for slide in raw.get("slides", [])]
            if len(slide_ids) != len(set(slide_ids)):
                raise ValueError("Duplicate slide IDs")
        except (KeyError, TypeError, ValueError):
            raise ProviderError("Read Google Slides deck") from None
        return {"presentation_id": presentation_id, "raw": raw, "presentation": raw,
                "slide_ids": slide_ids, "revision_id": raw.get("revisionId"),
                "fingerprint": _fingerprint(_stable_presentation(raw))}

    def copy_and_trim_deck(self, source_id, selected_slide_ids, title, *, copy_id=None, on_copied=None,
                           expected_source_fingerprint=None):
        source_id = _identifier(source_id)
        title = _safe_title(title)
        selected = [_identifier(item) for item in selected_slide_ids]
        if not selected or len(selected) != len(set(selected)):
            raise ValueError("Select at least one slide without duplicates")
        source = self.read_deck(source_id)
        if expected_source_fingerprint is not None and source["fingerprint"] != expected_source_fingerprint:
            raise ProviderError("Verify source deck before copy")
        if [item for item in source["slide_ids"] if item in set(selected)] != selected:
            raise ValueError("Selected slides must exist and retain source order")
        if copy_id is None:
            copied = self._google(f"https://www.googleapis.com/drive/v3/files/{source_id}/copy?fields=id",
                                  method="POST", payload={"name": title}, operation="Copy Google Slides deck", write=True)
            copy_id = _created_identifier(copied, "id", "Copy Google Slides deck")
            if on_copied is not None:
                try:
                    on_copied(copy_id)
                except Exception:
                    raise ProviderError("Record copied deck", uncertain=True, copy_id=copy_id) from None
        copy_id = _identifier(copy_id)
        if copy_id == source_id:
            raise ValueError("The source deck cannot be trimmed")
        try:
            current = self.read_deck(copy_id)
            if (not set(selected).issubset(current["slide_ids"]) or
                    not set(current["slide_ids"]).issubset(source["slide_ids"]) or
                    [item for item in current["slide_ids"] if item in set(selected)] != selected):
                raise ProviderError("Verify copied deck before trim", uncertain=True, copy_id=copy_id)
            if _selected_presentation(current["raw"], current["slide_ids"]) != _selected_presentation(source["raw"], current["slide_ids"]):
                raise ProviderError("Verify copied source content before trim", uncertain=True, copy_id=copy_id)
            requests = [{"deleteObject": {"objectId": item}}
                        for item in current["slide_ids"] if item not in set(selected)]
            if requests:
                self._google(f"https://slides.googleapis.com/v1/presentations/{copy_id}:batchUpdate",
                             method="POST", payload={"requests": requests}, operation="Trim copied deck", write=True)
            result = self.read_deck(copy_id)
            if (result["slide_ids"] != selected or
                    _selected_presentation(result["raw"], selected) != _selected_presentation(source["raw"], selected)):
                raise ProviderError("Verify trimmed deck", uncertain=True, copy_id=copy_id)
            return dict(result, copy_id=copy_id, source_id=source_id)
        except ProviderError as exc:
            exc.copy_id = copy_id
            exc.presentation_id = copy_id
            raise

    def metadata(self, path):
        path = _dropbox_path(path)
        result = self._json("https://api.dropboxapi.com/2/files/get_metadata", payload={"path": path},
                            headers={"Authorization": "Bearer " + configure.dropbox_access_token()},
                            operation="Read Dropbox metadata")
        if not _valid_file_metadata(result) or (result.get("path_lower") is not None and result["path_lower"] != path.lower()):
            raise ProviderError("Read Dropbox metadata")
        return result

    def temporary_link(self, path):
        """Return Dropbox's expiring download URL; never create a shared link."""
        path = _dropbox_path(path)
        result = self._json("https://api.dropboxapi.com/2/files/get_temporary_link", payload={"path": path},
                            headers={"Authorization": "Bearer " + configure.dropbox_access_token()},
                            operation="Get temporary Dropbox download link")
        link = result.get("link")
        try:
            parsed = urlsplit(link)
            if (not isinstance(link, str) or parsed.scheme != "https" or not parsed.hostname or
                    parsed.username or parsed.password or parsed.port not in (None, 443) or
                    not (parsed.hostname == "dropboxusercontent.com" or parsed.hostname.endswith(".dropboxusercontent.com"))):
                raise ValueError("Unexpected download link")
        except (ValueError, TypeError):
            raise ProviderError("Validate temporary Dropbox download link") from None
        return link

    def _dropbox_content(self, endpoint, arguments, body, size, operation):
        return self._json("https://content.dropboxapi.com/2/files/" + endpoint,
                          headers={"Authorization": "Bearer " + configure.dropbox_access_token(),
                                   "Content-Type": "application/octet-stream", "Content-Length": str(size),
                                   "Dropbox-API-Arg": json.dumps(arguments, ensure_ascii=True, separators=(",", ":"))},
                          body=body, operation=operation, write=True, media=True)

    def upload(self, path, local_file):
        path = _dropbox_path(path)
        size, sha256, content_hash = _file_hashes(local_file)
        commit = {"path": path, "mode": "add", "autorename": False, "mute": True, "strict_conflict": True}
        with open(local_file, "rb") as stream:
            if size <= UPLOAD_CHUNK:
                result = self._dropbox_content("upload", commit, stream, size, "Upload Dropbox file")
            else:
                started = self._dropbox_content("upload_session/start", {"close": False}, b"", 0, "Start Dropbox upload")
                session = started.get("session_id")
                if not isinstance(session, str) or not session:
                    raise ProviderError("Start Dropbox upload", uncertain=True)
                offset = 0
                while size - offset > UPLOAD_CHUNK:
                    chunk = stream.read(UPLOAD_CHUNK)
                    if len(chunk) != UPLOAD_CHUNK:
                        raise ProviderError("Read source during Dropbox upload", uncertain=True)
                    # append_v2 returns a JSON null on success, handled separately.
                    self._append_upload(session, offset, chunk)
                    offset += len(chunk)
                final = stream.read(UPLOAD_CHUNK + 1)
                if len(final) != size - offset:
                    raise ProviderError("Read source during Dropbox upload", uncertain=True)
                result = self._dropbox_content("upload_session/finish",
                    {"cursor": {"session_id": session, "offset": offset}, "commit": commit}, final, len(final), "Finish Dropbox upload")
        if (not _valid_file_metadata(result) or result.get("size") != size or result.get("content_hash") != content_hash or
                result.get("path_lower") != path.lower()):
            raise ProviderError("Verify Dropbox upload response", uncertain=True)
        try:
            actual = self.metadata(path)
        except ProviderError as exc:
            exc.uncertain = True
            raise
        if (actual.get("size") != size or actual.get("content_hash") != content_hash or
                actual.get("rev") != result.get("rev") or actual.get("id") != result.get("id")):
            raise ProviderError("Verify Dropbox upload readback", uncertain=True)
        return dict(actual, sha256=sha256, verified=True)

    def _append_upload(self, session, offset, chunk):
        arguments = {"cursor": {"session_id": session, "offset": offset}, "close": False}
        headers = {"Authorization": "Bearer " + configure.dropbox_access_token(),
                   "Content-Type": "application/octet-stream", "Content-Length": str(len(chunk)),
                   "Dropbox-API-Arg": json.dumps(arguments, ensure_ascii=True, separators=(",", ":"))}
        with self._response("https://content.dropboxapi.com/2/files/upload_session/append_v2",
                            method="POST", headers=headers, body=chunk,
                            operation="Append Dropbox upload", write=True, media=True) as response:
            raw = response.read(1025)
            if raw.strip() not in (b"", b"null"):
                raise ProviderError("Append Dropbox upload", uncertain=True)

    def download(self, path, destination):
        path = _dropbox_path(path)
        destination = Path(destination)
        if destination.is_symlink():
            raise ValueError("Download destination cannot be a symbolic link")
        destination.parent.mkdir(parents=True, exist_ok=True)
        headers = {"Authorization": "Bearer " + configure.dropbox_access_token(),
                   "Dropbox-API-Arg": json.dumps({"path": path}, ensure_ascii=True)}
        temporary = None
        try:
            with self._response("https://content.dropboxapi.com/2/files/download", method="POST",
                                headers=headers, operation="Download Dropbox file", media=True) as response:
                try:
                    metadata = json.loads(response.headers.get("Dropbox-API-Result", ""))
                    if (not _valid_file_metadata(metadata) or
                            (metadata.get("path_lower") is not None and metadata["path_lower"] != path.lower())):
                        raise ValueError("Invalid file metadata")
                except (ValueError, TypeError):
                    raise ProviderError("Read Dropbox download metadata") from None
                sha = hashlib.sha256()
                content = _ContentHash()
                total = 0
                fd, temporary = tempfile.mkstemp(prefix=".hardstop-download-", dir=destination.parent)
                with os.fdopen(fd, "wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > metadata["size"]:
                            raise ProviderError("Verify Dropbox download length")
                        sha.update(chunk)
                        content.update(chunk)
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                if total != metadata["size"] or content.hexdigest() != metadata["content_hash"]:
                    raise ProviderError("Verify Dropbox downloaded content")
                os.replace(temporary, destination)
                temporary = None
                return dict(metadata, local_file=str(destination), sha256=sha.hexdigest(), verified=True)
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
