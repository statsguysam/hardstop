import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import configure
from scripts.evaluate_briefs import (ROOT, assess, digest, evaluate, fixed_cases,
                                     live_interpret, public_usage, summarize)
from hardstop.planner import plan


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.segments = json.loads((ROOT / "fixtures/catalog.json").read_text())["segments"]
        durations = [30567, 31634, 32234, 14934, 15567, 30667, 12734, 10734]
        for segment, duration in zip(self.segments, durations):
            segment["duration_ms"] = duration

    def result(self, case):
        expected = case["expected"]
        priorities = {segment["id"]: 1 for segment in self.segments}
        if expected.get("audience_optional"):
            priorities[expected["audience_optional"]] = 10
        constraints = {"max_duration_ms": expected["max_duration_ms"] or 1000,
                       "required_ids": expected["required_ids"], "excluded_ids": [],
                       "priorities": priorities, "evidence": [],
                       "ambiguities": ["Review the brief"] if expected["status"] == "needs_review" else []}
        return {"result": {"constraints": constraints, "interpretation": {"summary": "Synthetic unit test"}},
                "model_calls": [{"usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}}]}

    def test_ground_truth_and_full_declaration_precede_every_call(self):
        observed, checkpoints = [], []
        cases = fixed_cases()
        def invoke(brief, segments):
            self.assertEqual(checkpoints[0]["cases"], cases)
            self.assertEqual(checkpoints[0]["results"], [])
            case = cases[len(observed)]
            self.assertEqual(brief, case["brief"])
            observed.append(brief)
            return self.result(case)
        report = evaluate(self.segments, invoke, checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)))
        self.assertEqual(len(observed), 6)
        self.assertEqual(report["suite_sha256"], digest(cases))
        self.assertEqual(report["summary"]["passed_cases"], 6)
        self.assertEqual(report["summary"]["fixed_priority_baseline_passed"], 4)
        self.assertEqual(report["summary"]["reported_usage"]["total_tokens"], 90)
        self.assertTrue(all(pair["passed"] for pair in report["summary"]["audience_pairs"]))

    def test_api_failure_is_retained_without_retry_or_abandoning_later_cases(self):
        cases, seen = fixed_cases(), []
        def invoke(brief, segments):
            index = len(seen)
            seen.append(brief)
            if index == 1:
                return {"error": "RemoteError", "model_calls": [{"usage": None}]}
            return self.result(cases[index])
        report = evaluate(self.segments, invoke)
        self.assertEqual(seen, [case["brief"] for case in cases])
        self.assertEqual(report["results"][1]["error"], "RemoteError")
        self.assertEqual(report["summary"]["passed_cases"], 5)
        self.assertFalse(report["summary"]["usage_complete"])
        self.assertEqual(report["summary"]["reported_usage"]["total_tokens"], 75)

    def test_wrong_audience_selection_does_not_pass_from_safe_constraints_alone(self):
        case = fixed_cases()[0]
        constraints = self.result(case)["result"]["constraints"]
        constraints["priorities"] = {}
        selection = plan(self.segments, constraints)
        scored = assess(case["expected"], constraints, selection, self.segments)
        self.assertFalse(scored["passed"])
        self.assertEqual([check["name"] for check in scored["checks"] if not check["passed"]], ["selected_allowlist"])

    def test_review_expected_does_not_accept_error_or_feasible_output(self):
        case = fixed_cases()[-2]
        constraints = self.result(case)["result"]["constraints"]
        constraints["ambiguities"] = []
        self.assertFalse(assess(case["expected"], constraints, plan(self.segments, constraints), self.segments)["passed"])

    def test_priority_only_ablation_does_not_modify_result_constraints(self):
        results = [self.result(case) for case in fixed_cases()]
        before = copy.deepcopy(results)
        report = evaluate(self.segments, lambda brief, segments: results.pop(0))
        self.assertEqual(report["results"][0]["constraints"], before[0]["result"]["constraints"])
        self.assertEqual(report["results"][0]["baseline"]["selected_ids"][0], "workflow")

    def test_actual_response_usage_survives_interpreter_validation_failure(self):
        response = {"status": "incomplete", "id": "PRIVATE_RESPONSE_SENTINEL", "model": "test-model",
                    "usage": {"input_tokens": 101, "output_tokens": 20, "total_tokens": 121,
                              "private_field": "PRIVATE_USAGE_SENTINEL"}}
        with patch.object(configure, "read_private", return_value={"api_key": "PRIVATE_KEY_SENTINEL", "model": "test-model"}), \
                patch.object(configure, "request_json", return_value=response) as request:
            result = live_interpret("Test brief", self.segments)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(result["error"], "InterpretationError")
        self.assertEqual(result["model_calls"][0]["usage"]["total_tokens"], 121)
        self.assertNotIn("PRIVATE_", json.dumps(result))

    def test_hard_constraint_comparison_ignores_list_order(self):
        cases = fixed_cases()
        report = evaluate(self.segments, lambda brief, segments: self.result(next(case for case in cases if case["brief"] == brief)))
        report["results"][1]["constraints"]["required_ids"] = list(reversed(report["results"][1]["constraints"]["required_ids"]))
        self.assertTrue(summarize(report)["audience_pairs"][0]["same_hard_constraints"])

    def test_usage_missing_or_non_numeric_is_not_reported_as_measured_zero(self):
        self.assertIsNone(public_usage(None))
        self.assertIsNone(public_usage({"total_tokens": True, "input_tokens": "10"}))
        self.assertEqual(public_usage({"total_tokens": 0}), {"total_tokens": 0})


if __name__ == "__main__":
    unittest.main()
