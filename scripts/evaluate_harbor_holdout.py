#!/usr/bin/env python3
"""Separate, predeclared Harbor holdout. Six Responses calls; no app delivery.

The original Relay evaluation is unchanged. Run without --live to inspect and
save the declaration before authorizing this small additional model evaluation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_briefs import assess, digest, live_interpret, now, save
from hardstop.planner import plan

REQUIRED = ["finding", "limitations", "next_step"]
CLOSURE = ["setting", "finding", "limitations", "next_step"]
DURATIONS = [17934, 12334, 11300, 20934, 9967, 10000]
COMMON = "Fit within 65 seconds. Keep finding, limitations and next step. "


def fixed_cases():
    cases = [
        ("newcomer", COMMON + "The viewers have never seen the handoff concept. Use the spare time to establish what the incoming team needs to know and why open questions need owners; form-filling mechanics are secondary.",
         "feasible", 65000, [], [["introduction"] + CLOSURE]),
        ("experienced_operator", COMMON + "The viewers already understand the purpose of the handoff. The spare time should show which fields staff complete, how an unresolved question gets an owner, and what the next shift checks before accepting it; general orientation is secondary.",
         "feasible", 65000, [], [["setting", "finding", "walkthrough", "limitations", "next_step"]]),
        ("exclude_walkthrough", "No more than 65 seconds. Keep finding, limitations and next step. Exclude walkthrough. This is for incoming staff seeing the handoff idea for the first time.",
         "feasible", 65000, ["walkthrough"], [["introduction"] + CLOSURE]),
        ("impossible_30", "Fit within 30 seconds. Keep finding, limitations and next step.",
         "infeasible", 30000, [], [[]]),
        ("unconfirmed_slot", "The slot is either 45 seconds or 65 seconds; scheduling has not confirmed which. Keep finding, limitations and next step.",
         "needs_review", None, [], [[]]),
        ("rewrite_narration", COMMON + "Rewrite the finding narration in plainer language.",
         "needs_review", 65000, [], [[]]),
    ]
    return [{"id": sid, "brief": brief, "expected": {
        "status": status, "max_duration_ms": duration,
        "required_ids": list(REQUIRED), "excluded_ids": excluded,
        "selected_allowlist": selections,
    }} for sid, brief, status, duration, excluded, selections in cases]


def load_segments(path):
    source = json.loads(path.read_text())
    fixture = json.loads((ROOT / "fixtures/examples/harbor-catalog.json").read_text())
    keys = ("id", "title", "transcript", "requires", "duration_ms", "value")
    segments = [{key: segment[key] for key in keys} for segment in source["segments"]]
    declared = [{key: segment[key] for key in keys if key != "duration_ms"}
                for segment in fixture["segments"]]
    if [{key: segment[key] for key in keys if key != "duration_ms"}
            for segment in segments] != declared:
        raise ValueError("The holdout requires the original Harbor catalog")
    if [segment["duration_ms"] for segment in segments] != DURATIONS:
        raise ValueError("The holdout requires the original measured Harbor durations")
    return segments


def declaration(segments):
    cases = fixed_cases()
    files = ("hardstop/interpret.py", "hardstop/planner.py", "scripts/evaluate_harbor_holdout.py")
    return {"format": "hardstop-harbor-holdout-v1", "declared_at": now(),
            "suite_sha256": digest(cases), "catalog_sha256": digest(segments),
            "implementation_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                       for name in files},
            "cases": cases, "catalog": deepcopy(segments),
            "limitations": [
                "Six authored holdout cases on a second fictional catalog extend coverage; they are not a general accuracy estimate or customer validation.",
                "This set was authored after reviewing the Relay evaluation and existing Harbor runs, but before these six model calls. It is not an independently sampled or blinded benchmark.",
                "Editorial selections are predeclared strict ground truth; a different defensible choice still fails the selection check.",
                "No delivery, rendering, Gmail, Google Slides, or Dropbox calls occur. Only one Responses request is attempted per case.",
                "The fixed-priority baseline reuses extracted hard constraints and removes model priorities. It does not remove all model contribution.",
                "All attempts, including errors and missing usage, remain in the report. No prompt repair, retries or selective resampling."]}


def summarize(report):
    results = report["results"]
    calls = [call for result in results for call in result.get("model_calls", [])]
    usage = {key: sum(call.get("usage", {}).get(key, 0) for call in calls if call.get("usage"))
             for key in ("input_tokens", "output_tokens", "total_tokens")}
    return {"completed_cases": len(results), "total_cases": len(report["cases"]),
            "passed_cases": sum(result["passed"] for result in results),
            "fixed_priority_baseline_passed": sum(result.get("baseline", {}).get("passed", False) for result in results),
            "request_attempts": len(calls), "reported_usage": usage,
            "usage_complete": len(calls) == len(report["cases"]) and all(call.get("usage") is not None for call in calls)}


def evaluate(declared, invoke, *, checkpoint=None, execution="test"):
    report = dict(deepcopy(declared), execution=execution, status="running", started_at=now(), results=[])
    if checkpoint:
        checkpoint(report)
    for case in report["cases"]:
        item = {"id": case["id"], "started_at": now(), "passed": False}
        try:
            called = invoke(case["brief"], deepcopy(report["catalog"]))
            item["model_calls"] = called.get("model_calls", [])
            if called.get("error"):
                item["error"] = called["error"]
            else:
                interpreted = called["result"]
                constraints = interpreted["constraints"]
                selection = plan(report["catalog"], constraints)
                item.update(constraints=constraints, interpretation=interpreted["interpretation"], plan=selection)
                item.update(assess(case["expected"], constraints, selection, report["catalog"]))
                baseline = plan(report["catalog"], dict(constraints, priorities={}))
                item["baseline"] = dict(assess(case["expected"], constraints, baseline, report["catalog"]),
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--source", type=Path, default=ROOT / ".state/harbor-workspace/source.json")
    parser.add_argument("--declaration", type=Path, required=True, help="New declaration file, or the exact saved declaration for --live")
    parser.add_argument("--output", type=Path, help="New private live report file")
    args = parser.parse_args()
    segments = load_segments(args.source)
    current = declaration(segments)
    if not args.live:
        args.declaration.parent.mkdir(parents=True, exist_ok=True)
        with args.declaration.open("x") as stream:
            json.dump(current, stream, indent=2)
            stream.write("\n")
        print(json.dumps({"declared_at": current["declared_at"], "suite_sha256": current["suite_sha256"], "cases": current["cases"]}, indent=2))
        return 0
    if not args.output:
        parser.error("--live requires --output")
    declared = json.loads(args.declaration.read_text())
    if any(declared[key] != current[key] for key in ("suite_sha256", "catalog_sha256", "implementation_sha256", "cases", "catalog")):
        raise ValueError("Declaration, implementation or source changed; refusing live execution")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x"):
        pass
    args.output.chmod(0o600)
    report = evaluate(declared, live_interpret, checkpoint=lambda value: save(args.output, value), execution="live Responses API")
    print(json.dumps(report["summary"], indent=2))
    return 0 if all(result["passed"] for result in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
