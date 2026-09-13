#!/usr/bin/env python3
"""Export explicitly selected live-run receipts without private provider IDs.

This command does not call providers, infer success, or execute another run.
Only checked-in fictional fixture briefs may be reproduced verbatim.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
LABEL = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")
HASH = re.compile(r"[a-fA-F0-9]{64}\Z")
STATUSES = {"running", "ready", "infeasible", "needs_review", "stale", "failed", "unknown"}
PRIVATE_KEYS = {
    "presentation_id", "presentation_url", "deck_id", "draft_id", "message_id",
    "brief_draft_id", "slide_id", "request_id", "response_id", "dropbox_path",
    "dropbox_root", "dropbox_rev", "catalog_rev", "access_token", "refresh_token",
    "client_secret", "client_id", "api_key", "authorization", "temporary_link",
    "download_url", "video_url", "media_path", "card_path",
}
REDACTED = "[redacted: custom brief text]"


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.isoformat() if parsed.tzinfo is not None else None
    except ValueError:
        return None


def private_values(value, parent=""):
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if (key.lower() in PRIVATE_KEYS or key.lower().endswith("_token")
                    or parent == "model" and key == "id") and isinstance(item, str) and len(item) >= 4:
                found.add(item)
            found.update(private_values(item, key))
    elif isinstance(value, list):
        for item in value:
            found.update(private_values(item, parent))
    return found


def scrubber(report):
    private = sorted(private_values(report), key=len, reverse=True)

    def scrub(value):
        if not isinstance(value, str):
            return ""
        result = value[:10000]
        for secret in private:
            result = result.replace(secret, "[private identifier omitted]")
        result = re.sub(r"https?://[^\s<>\"']+", "[URL omitted]", result, flags=re.IGNORECASE)
        result = re.sub(r"(?<![\w:])/(?:[^\s/]+/)*[^\s,;]+", "[path omitted]", result)
        result = re.sub(r"\b(?:Bearer\s+\S+|sk-[A-Za-z0-9_-]+|resp_[A-Za-z0-9_-]+)\b", "[private value omitted]", result)
        return result

    return scrub


def usage_summary(usage):
    if not isinstance(usage, dict):
        return {}
    output = {key: usage[key] for key in ("input_tokens", "output_tokens", "total_tokens")
              if type(usage.get(key)) is int and usage[key] >= 0}
    for section in ("input_tokens_details", "output_tokens_details"):
        details = usage.get(section)
        if not isinstance(details, dict):
            continue
        clean = {key: details[key] for key in ("cached_tokens", "reasoning_tokens", "audio_tokens",
                                               "accepted_prediction_tokens", "rejected_prediction_tokens")
                 if type(details.get(key)) is int and details[key] >= 0}
        if clean:
            output[section] = clean
    return output


def export_report(report, label, fixtures, public_segment_ids):
    """Pure whitelist transformation, suitable for testing before publishing."""
    if not isinstance(report, dict) or report.get("status") not in STATUSES:
        raise ValueError("Run report has an invalid status or shape")
    if not isinstance(report.get("id"), str) or not RUN_ID.fullmatch(report["id"]):
        raise ValueError("Run report has an invalid local ID")
    scrub = scrubber(report)
    source = report.get("source") if isinstance(report.get("source"), dict) else {}
    brief = source.get("brief") if isinstance(source.get("brief"), dict) else {}
    subject = brief.get("subject") if isinstance(brief.get("subject"), str) else ""
    body = brief.get("body") if isinstance(brief.get("body"), str) else ""
    fixture_key = next((key for key, fixture in fixtures.items()
                        if isinstance(fixture, dict) and fixture.get("subject") == subject
                        and fixture.get("body") == body and body.startswith("FICTIONAL DEMO BRIEF")), None)
    public_text = fixture_key is not None
    text = scrub if public_text else lambda value: REDACTED

    def ids(value):
        if not isinstance(value, list):
            return []
        return [item if isinstance(item, str) and item in public_segment_ids else "[segment ID omitted]" for item in value]

    def checks(value):
        if not isinstance(value, list):
            return []
        result = []
        for check in value:
            if not isinstance(check, dict):
                continue
            name = check.get("name")
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,100}", name):
                name = "unnamed_check"
            result.append({"name": name, "passed": check.get("passed") is True,
                           "detail": text(check.get("detail", ""))})
        return result

    safe_brief = {"text_included": public_text}
    if body:
        safe_brief["body_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    fingerprint = brief.get("fingerprint")
    if isinstance(fingerprint, str) and HASH.fullmatch(fingerprint):
        safe_brief["source_fingerprint"] = fingerprint.lower()
    if public_text:
        safe_brief.update(fixture=fixture_key, subject=scrub(subject), body=scrub(body))
    else:
        safe_brief["note"] = "Brief content omitted because it does not exactly match a labeled, checked-in fictional fixture."

    result = {
        "schema_version": 1,
        "evidence_kind": "saved_run_receipt",
        "label": label,
        "local_run_id": report["id"],
        "status": report["status"],
        "started_at": timestamp(report.get("started_at")),
        "finished_at": timestamp(report.get("finished_at")),
        "brief": safe_brief,
        "events": [],
        "checks": checks(report.get("checks")),
        "limitations": [
            "This is a saved receipt, not a new live run or independently signed provider attestation.",
            "The exporter does not independently establish whether a report used live providers or test doubles; live provenance is documented separately.",
            "Private provider object IDs, URLs, paths, response IDs, and temporary download links are omitted.",
            "Fixture content is fictional and narration is synthesized. Gmail operations create or update unsent drafts only.",
            "Verification covers explicit requirements and declared prerequisites, not general semantic preservation.",
        ],
    }
    for event in report.get("events", []):
        if not isinstance(event, dict):
            continue
        stage = event.get("stage")
        if not isinstance(stage, str) or not re.fullmatch(r"[a-z][a-z0-9_ ]{0,80}", stage):
            stage = "event"
        result["events"].append({"at": timestamp(event.get("at")), "stage": stage,
                                 "message": text(event.get("message", ""))})

    plan = report.get("plan")
    if isinstance(plan, dict):
        result["plan"] = {key: plan[key] for key in ("duration_ms", "minimum_required_ms") if number(plan.get(key))}
        if plan.get("status") in {"feasible", "infeasible", "needs_review"}:
            result["plan"]["status"] = plan["status"]
        for key in ("selected_ids", "required_closure", "removed_ids"):
            result["plan"][key] = ids(plan.get(key))
        result["plan"]["reasons"] = [text(item) for item in plan.get("reasons", []) if isinstance(item, str)]
        result["plan"]["checks"] = checks(plan.get("checks"))

    constraints = report.get("constraints")
    if isinstance(constraints, dict):
        safe_constraints = {key: ids(constraints.get(key)) for key in ("required_ids", "excluded_ids")}
        if number(constraints.get("max_duration_ms")):
            safe_constraints["max_duration_ms"] = constraints["max_duration_ms"]
        priorities = constraints.get("priorities")
        safe_constraints["priorities"] = {key: value for key, value in priorities.items()
                                          if key in public_segment_ids and type(value) is int and value > 0} if isinstance(priorities, dict) else {}
        safe_constraints["ambiguities"] = [text(item) for item in constraints.get("ambiguities", []) if isinstance(item, str)]
        safe_constraints["evidence"] = []
        for item in constraints.get("evidence", []):
            if not isinstance(item, dict):
                continue
            kind = item.get("kind")
            if not isinstance(kind, str) or not re.fullmatch(r"[a-z][a-z_]{0,50}", kind):
                kind = "evidence"
            safe_constraints["evidence"].append({"kind": kind,
                "segment_id": item.get("segment_id") if item.get("segment_id") in public_segment_ids else None,
                "quote": text(item.get("quote", ""))})
        result["constraints"] = safe_constraints

    media = report.get("media")
    if isinstance(media, dict):
        safe_media = {key: media[key] for key in ("duration_ms", "expected_duration_ms", "width", "height") if number(media.get(key))}
        safe_media.update({key: media[key] for key in ("decode_verified", "has_audio", "has_video") if type(media.get(key)) is bool})
        if isinstance(media.get("sha256"), str) and HASH.fullmatch(media["sha256"]):
            safe_media["sha256"] = media["sha256"].lower()
        result["media"] = safe_media

    model = report.get("model")
    if isinstance(model, dict):
        safe_model = {"usage": usage_summary(model.get("usage"))}
        name = model.get("model")
        if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", name):
            safe_model["name"] = name
        if number(model.get("elapsed_ms")):
            safe_model["elapsed_ms"] = model["elapsed_ms"]
        result["model"] = safe_model

    outputs = report.get("outputs") if isinstance(report.get("outputs"), dict) else {}
    passed = {check.get("name") for check in report.get("checks", [])
              if isinstance(check, dict) and check.get("passed") is True}
    result["output_verification"] = {
        "delivery_promoted": report["status"] == "ready",
        "copied_deck_verified": bool(outputs.get("presentation_id")) and "matching_deck" in passed,
        "video_sha256_recorded": bool(result.get("media", {}).get("sha256")),
        "dropbox_readback_verified": "output_sha256" in passed,
        "handoff_draft_readback_verified": bool(outputs.get("draft_id")) and "handoff_readback" in passed,
        "inputs_rechecked_before_promotion": "fresh_inputs" in passed,
        "final_output_revisions_verified": "final_outputs" in passed,
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True, metavar="LABEL=RUN_ID",
                        help="Explicit saved run to export; repeat for several receipts")
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".state")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/evidence")
    args = parser.parse_args(argv)
    try:
        selections = []
        labels = set()
        for item in args.run:
            label, separator, run_id = item.partition("=")
            if not separator or not LABEL.fullmatch(label) or not RUN_ID.fullmatch(run_id) or label in labels:
                raise ValueError("Use unique labels and valid local run IDs: label=run_id")
            labels.add(label)
            selections.append((label, run_id))
        fixtures = json.loads((ROOT / "fixtures/briefs.json").read_text())
        catalog = json.loads((ROOT / "fixtures/catalog.json").read_text())
        public_ids = {segment["id"] for segment in catalog["segments"]}
        runs_root = (args.state_dir / "runs").resolve()
        prepared = []
        for label, run_id in selections:
            folder = runs_root / run_id
            path = folder / "report.json"
            if folder.is_symlink() or path.is_symlink() or folder.resolve().parent != runs_root:
                raise ValueError("Refusing a run path outside the selected state directory")
            report = json.loads(path.read_text())
            if report.get("id") != run_id:
                raise ValueError("Requested run ID does not match its report")
            prepared.append((label, export_report(report, label, fixtures, public_ids)))
        # Validate every requested report before creating any export.
        if args.output_dir.is_symlink():
            raise ValueError("Output directory must not be a symbolic link")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for label, exported in prepared:
            target = args.output_dir / f"{label}.json"
            if target.is_symlink():
                raise ValueError("Output files must not be symbolic links")
            target.write_text(json.dumps(exported, indent=2, ensure_ascii=False) + "\n")
            print(json.dumps({"label": label, "run_id": exported["local_run_id"], "status": exported["status"],
                              "brief_text_included": exported["brief"]["text_included"]}))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("Evidence export failed: check the explicit run IDs, report structure, and output directory.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
