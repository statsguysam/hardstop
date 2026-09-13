import copy
import json
import unittest

from scripts.evaluate_harbor_holdout import ROOT, DURATIONS, declaration, evaluate, fixed_cases
from scripts.evaluate_briefs import digest


class HarborHoldoutTests(unittest.TestCase):
    def setUp(self):
        keys = ("id", "title", "transcript", "requires", "value")
        source = json.loads((ROOT / "fixtures/examples/harbor-catalog.json").read_text())
        self.segments = [dict({key: segment[key] for key in keys}, duration_ms=duration)
                         for segment, duration in zip(source["segments"], DURATIONS)]

    def response(self, case):
        expected = case["expected"]
        priorities = {segment["id"]: 1 for segment in self.segments}
        wanted = expected["selected_allowlist"][0]
        if "introduction" in wanted:
            priorities["introduction"] = 10
        if "walkthrough" in wanted:
            priorities["walkthrough"] = 10
        constraints = {"max_duration_ms": expected["max_duration_ms"] or 1000,
                       "required_ids": expected["required_ids"], "excluded_ids": expected["excluded_ids"],
                       "priorities": priorities, "evidence": [],
                       "ambiguities": ["Review this test brief"] if expected["status"] == "needs_review" else []}
        return {"result": {"constraints": constraints, "interpretation": {"summary": "Unit test fixture"}},
                "model_calls": [{"usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}}]}

    def test_declaration_is_saved_before_first_call_and_all_expected_boundaries_hold(self):
        checkpoints, seen = [], []
        declared = declaration(self.segments)
        def invoke(brief, segments):
            self.assertEqual(checkpoints[0]["cases"], fixed_cases())
            self.assertEqual(checkpoints[0]["results"], [])
            case = fixed_cases()[len(seen)]
            self.assertEqual(brief, case["brief"])
            seen.append(brief)
            return self.response(case)
        report = evaluate(declared, invoke, checkpoint=lambda value: checkpoints.append(copy.deepcopy(value)))
        self.assertEqual(report["suite_sha256"], digest(fixed_cases()))
        self.assertEqual(report["summary"]["passed_cases"], 6)
        self.assertEqual(report["summary"]["fixed_priority_baseline_passed"], 5)
        self.assertEqual(report["results"][0]["plan"]["duration_ms"], 61535)
        self.assertEqual(report["results"][1]["plan"]["duration_ms"], 64535)
        self.assertEqual(report["results"][3]["plan"]["minimum_required_ms"], 43601)
        self.assertNotIn("dropbox", json.dumps(report["catalog"]))

    def test_failed_model_call_does_not_retry_or_skip_later_cases(self):
        seen = []
        def invoke(brief, segments):
            case = fixed_cases()[len(seen)]
            seen.append(brief)
            if case["id"] == "experienced_operator":
                return {"error": "RemoteError", "model_calls": [{"usage": None}]}
            return self.response(case)
        report = evaluate(declaration(self.segments), invoke)
        self.assertEqual(len(seen), 6)
        self.assertEqual(report["summary"]["passed_cases"], 5)
        self.assertFalse(report["summary"]["usage_complete"])
        self.assertEqual(report["summary"]["reported_usage"]["total_tokens"], 75)
        self.assertEqual(report["results"][1]["error"], "RemoteError")


if __name__ == "__main__":
    unittest.main()
