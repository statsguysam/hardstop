#!/usr/bin/env python3
"""Predeclared, once-per-case live interpretation evaluation; no app deliveries.

Run without --live to inspect every case and its ground truth before spending API
credit. The live report includes failures, a fixed-priority ablation, and actual
Responses usage, including responses that fail the interpreter's validation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import configure
from hardstop.interpret import interpret_brief
from hardstop.planner import plan, verify_selection

BUYER = ("The audience is a prospective buyer assessing whether coordination failures are worth solving. "
         "The extra time should make the pain of scattered updates and missing ownership concrete; "
         "product mechanics are secondary.")
OPERATOR = ("The audience is the team that would use Relay day to day. "
            "The extra time should explain how a change leads to an owner and a confirmed next move; "
            "general framing of the pain is secondary.")
COMMON = "Fit within 90 seconds. Keep result, disclaimer and call to action. "
REQUIRED = ["result", "disclaimer", "call_to_action"]
CLOSURE = ["pilot_context", "result", "disclaimer", "call_to_action"]


def fixed_cases():
    """This order, all prompts, and strict expected selections precede API calls."""
    cases = []
    for identifier, brief, optional in (
        ("buyer", COMMON + BUYER, "problem"),
        ("operator", COMMON + OPERATOR, "workflow"),
        ("buyer_paraphrase", "At most 1.5 minutes. The result, disclaimer and call to action must be retained. " + BUYER, "problem"),
        ("operator_paraphrase", "The time limit is 90 seconds. Do not remove result, disclaimer and call to action. " + OPERATOR, "workflow"),
    ):
        cases.append({"id": identifier, "brief": brief, "expected": {
            "status": "feasible", "max_duration_ms": 90000,
            "required_ids": list(REQUIRED), "excluded_ids": [],
            "selected_allowlist": [[optional] + CLOSURE], "audience_optional": optional}})
    cases.extend([
        {"id": "unsupported_rewrite", "brief": COMMON + "Rewrite the result narration to make the claim more persuasive.",
         "expected": {"status": "needs_review", "max_duration_ms": 90000,
                      "required_ids": list(REQUIRED), "excluded_ids": [], "selected_allowlist": [[]]}},
        {"id": "ambiguous_timing", "brief": "Fit within 60 seconds or 90 seconds; the slot is unconfirmed. Keep result, disclaimer and call to action.",
         "expected": {"status": "needs_review", "max_duration_ms": None,
                      "required_ids": list(REQUIRED), "excluded_ids": [], "selected_allowlist": [[]]}},
    ])
    return cases


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def public_usage(value):
    """Never copy arbitrary provider fields, response IDs, or error bodies."""
    if not isinstance(value, dict):
        return None
    result = {key: value[key] for key in ("input_tokens", "output_tokens", "total_tokens")
              if type(value.get(key)) is int and value[key] >= 0}
    for group, key in (("input_tokens_details", "cached_tokens"),
                       ("output_tokens_details", "reasoning_tokens")):
        child = value.get(group)
        if isinstance(child, dict) and type(child.get(key)) is int and child[key] >= 0:
            result[group] = {key: child[key]}
    return result or None


@contextmanager
def observe_responses(records):
    """Observe the existing interpreter request without changing its behavior.

    This script is a separate process. Metadata is captured before downstream
    validation so a failed interpretation cannot disappear from token totals.
    There are no retry or repair calls.
    """
    original = configure.request_json

    def request(url, **kwargs):
        if url != "https://api.openai.com/v1/responses":
            raise RuntimeError("The evaluation permits only Responses API requests")
        if records:
            raise RuntimeError("Each evaluation case permits exactly one API request")
        record = {"request_attempted": True, "response_received": False, "usage": None}
        records.append(record)
        started = time.monotonic()
        try:
            response = original(url, **kwargs)
            record.update(response_received=True, model=response.get("model"),
                          usage=public_usage(response.get("usage")), status=response.get("status"))
            return response
        finally:
            record["elapsed_ms"] = round((time.monotonic() - started) * 1000)

    configure.request_json = request
    try:
        yield
    finally:
        configure.request_json = original


def live_interpret(brief, segments):
    records = []
    try:
        with observe_responses(records):
            result = interpret_brief(brief, segments)
        return {"result": result, "model_calls": records}
    except Exception as exc:
        # Generic errors may contain private paths or upstream text.
        return {"error": type(exc).__name__, "model_calls": records}


def assess(expected, constraints, selection, segments):
    checks = []

    def check(name, actual, wanted):
        checks.append({"name": name, "passed": actual == wanted, "actual": actual, "expected": wanted})

    check("plan_status", selection["status"], expected["status"])
    check("required_ids", sorted(constraints["required_ids"]), sorted(expected["required_ids"]))
    check("excluded_ids", sorted(constraints["excluded_ids"]), sorted(expected["excluded_ids"]))
    if expected["max_duration_ms"] is not None:
        check("duration_constraint", constraints["max_duration_ms"], expected["max_duration_ms"])
    checks.append({"name": "selected_allowlist", "passed": selection["selected_ids"] in expected["selected_allowlist"],
                   "actual": selection["selected_ids"], "expected": expected["selected_allowlist"]})
    if selection["status"] == "feasible":
        check("independent_selection_valid", verify_selection(segments, constraints, selection["selected_ids"])["valid"], True)
    elif expected["status"] == "needs_review":
        check("review_has_reasons", bool(selection["reasons"]), True)
    return {"passed": all(item["passed"] for item in checks), "checks": checks}


def summarize(report):
    results = report["results"]
    calls = [call for result in results for call in result.get("model_calls", [])]
    usage = {key: sum(call.get("usage", {}).get(key, 0) for call in calls if call.get("usage"))
             for key in ("input_tokens", "output_tokens", "total_tokens")}
    by_id = {result["id"]: result for result in results}
    pairs = []
    for buyer, operator in (("buyer", "operator"), ("buyer_paraphrase", "operator_paraphrase")):
        left, right = by_id.get(buyer, {}), by_id.get(operator, {})
        fields = ("max_duration_ms", "required_ids", "excluded_ids", "ambiguities")
        def hard_value(result, key):
            value = result.get("constraints", {}).get(key)
            return sorted(value) if isinstance(value, list) else value
        equal = all(hard_value(left, key) == hard_value(right, key) for key in fields)
        different = left.get("plan", {}).get("selected_ids") != right.get("plan", {}).get("selected_ids")
        pairs.append({"cases": [buyer, operator], "same_hard_constraints": equal,
                      "different_selections": different,
                      "passed": bool(left.get("passed") and right.get("passed") and equal and different)})
    return {"completed_cases": len(results), "total_cases": len(report["cases"]),
            "passed_cases": sum(result["passed"] for result in results),
            "fixed_priority_baseline_passed": sum(result.get("baseline", {}).get("passed", False) for result in results),
            "request_attempts": len(calls), "reported_usage": usage,
            "usage_complete": len(calls) == len(report["cases"]) and all(call.get("usage") is not None for call in calls),
            "audience_pairs": pairs}


def evaluate(segments, invoke, *, checkpoint=None, execution="test"):
    cases = fixed_cases()
    report = {"format": "hardstop-brief-evaluation-v1", "execution": execution, "status": "running",
              "started_at": now(), "suite_sha256": digest(cases), "catalog_sha256": digest(segments),
              "cases": cases, "catalog": deepcopy(segments), "results": [],
              "limitations": ["Six authored cases on one fictional catalog are a small functional evaluation, not a general language benchmark.",
                              "Audience selections are strict, predeclared editorial ground truth; other editorial choices may be defensible but count as failures here.",
                              "The baseline reuses model-extracted hard constraints and removes only model priorities; it isolates ranking, not all model contribution.",
                              "No video rendering or Gmail, Slides or Dropbox delivery occurs in this evaluation.",
                              "One request per case, with no retries, prompt repair, or selective resampling. Missing usage remains unknown, not zero cost."]}
    if checkpoint:
        checkpoint(report)
    for case in cases:
        item = {"id": case["id"], "started_at": now(), "passed": False}
        try:
            called = invoke(case["brief"], deepcopy(segments))
            item["model_calls"] = called.get("model_calls", [])
            if called.get("error"):
                item["error"] = called["error"]
            else:
                interpreted = called["result"]
                constraints = interpreted["constraints"]
                selection = plan(segments, constraints)
                item.update(constraints=constraints, interpretation=interpreted["interpretation"], plan=selection)
                item.update(assess(case["expected"], constraints, selection, segments))
                baseline = plan(segments, dict(constraints, priorities={}))
                item["baseline"] = dict(assess(case["expected"], constraints, baseline, segments),
                                        selected_ids=baseline["selected_ids"], status=baseline["status"])
        except Exception as exc:
            item["error"] = type(exc).__name__
        item["finished_at"] = now()
        report["results"].append(item)
        report["summary"] = summarize(report)
        if checkpoint:
            checkpoint(report)
    report.update(status="completed", finished_at=now())
    if checkpoint:
        checkpoint(report)
    return report


def load_segments(path):
    source = json.loads(path.read_text())
    catalog = json.loads((ROOT / "fixtures/catalog.json").read_text())
    keys = ("id", "title", "transcript", "requires", "duration_ms", "value")
    segments = [{key: segment[key] for key in keys} for segment in source["segments"]]
    if [{key: item[key] for key in keys if key != "duration_ms"} for item in segments] != [
            {key: item[key] for key in keys if key != "duration_ms"} for item in catalog["segments"]]:
        raise ValueError("Evaluation requires the checked-in fictional catalog and measured clip durations")
    plan(segments, {"max_duration_ms": 90000, "required_ids": REQUIRED, "excluded_ids": [],
                    "priorities": {}, "evidence": [], "ambiguities": []})
    return segments


def save(path, report):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(report, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make exactly one real Responses request per case")
    parser.add_argument("--source", type=Path, default=ROOT / ".state/source.json")
    parser.add_argument("--output", type=Path, help="New local report; an existing file is never overwritten")
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({"suite_sha256": digest(fixed_cases()), "cases": fixed_cases()}, indent=2))
        return 0
    segments = load_segments(args.source)
    output = args.output or ROOT / ".state/evaluations" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x"):
        pass
    report = evaluate(segments, live_interpret, checkpoint=lambda value: save(output, value), execution="live Responses API")
    print(json.dumps(report["summary"], indent=2))
    return 0 if all(result["passed"] for result in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
