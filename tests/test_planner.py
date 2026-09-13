"""Behavioral tests for the constraint boundary and independent verifier."""

import copy
import itertools
import random
import unittest

from hardstop.planner import plan, verify_selection


def segment(identifier, duration, value=5, requires=()):
    return {"id": identifier, "duration_ms": duration, "value": value, "requires": list(requires)}


def constraints(budget=90000, required=(), excluded=(), priorities=None, ambiguities=()):
    return {
        "max_duration_ms": budget, "required_ids": list(required), "excluded_ids": list(excluded),
        "priorities": {} if priorities is None else priorities, "evidence": [],
        "ambiguities": list(ambiguities),
    }


class PlannerTests(unittest.TestCase):
    def test_exact_boundary_uses_measured_milliseconds(self):
        clips = [segment("disclaimer", 12001), segment("result", 17999)]
        result = plan(clips, constraints(30000, required=["disclaimer", "result"]))
        self.assertEqual(result["status"], "feasible")
        self.assertEqual(result["duration_ms"], 30000)
        too_short = plan(clips, constraints(29999, required=["disclaimer", "result"]))
        self.assertEqual(too_short["status"], "infeasible")
        self.assertEqual(too_short["minimum_required_ms"], 30000)
        self.assertEqual(too_short["selected_ids"], [])
        self.assertIn("0.001 seconds", " ".join(too_short["reasons"]))

    def test_transitive_required_closure_remains_in_source_order(self):
        clips = [segment("terms", 10), segment("method", 20, requires=["terms"]),
                 segment("result", 30, requires=["method"]), segment("flourish", 100)]
        result = plan(clips, constraints(60, required=["result"]))
        self.assertEqual(result["selected_ids"], ["terms", "method", "result"])
        self.assertEqual(result["required_closure"], ["terms", "method", "result"])
        self.assertEqual(result["minimum_required_ms"], 60)
        self.assertEqual(result["removed_ids"], ["flourish"])
        self.assertTrue(all(check["passed"] for check in result["checks"]))

    def test_excluded_transitive_prerequisite_blocks_required_content(self):
        clips = [segment("terms", 10), segment("method", 20, requires=["terms"]),
                 segment("result", 30, requires=["method"])]
        result = plan(clips, constraints(90, required=["result"], excluded=["terms"]))
        self.assertEqual(result["status"], "infeasible")
        self.assertEqual(result["minimum_required_ms"], 60)
        self.assertIn("terms", " ".join(result["reasons"]))

    def test_direct_required_excluded_conflict_is_infeasible(self):
        result = plan([segment("a", 10)], constraints(100, required=["a"], excluded=["a"]))
        self.assertEqual(result["status"], "infeasible")

    def test_optional_dependent_cannot_survive_excluded_prerequisite(self):
        clips = [segment("method", 10, 1), segment("result", 10, 10, ["method"]),
                 segment("intro", 10, 1)]
        result = plan(clips, constraints(20, excluded=["method"], priorities={"result": 10000}))
        self.assertEqual(result["selected_ids"], ["intro"])

    def test_not_greedy_and_priorities_do_not_change_duration(self):
        clips = [segment("a", 7, 10), segment("b", 5, 8), segment("c", 5, 8)]
        result = plan(clips, constraints(10))
        self.assertEqual(result["selected_ids"], ["b", "c"])
        prioritized = plan(clips, constraints(10, priorities={"a": 1000}))
        self.assertEqual(prioritized["selected_ids"], ["a"])
        self.assertEqual(prioritized["duration_ms"], 7)
        mandatory = plan(clips, constraints(10, required=["b", "c"], priorities={"a": 1000}))
        self.assertEqual(mandatory["selected_ids"], ["b", "c"])

    def test_optional_dependency_cost_is_counted(self):
        clips = [segment("premise", 6, 1), segment("payoff", 5, 10, ["premise"]),
                 segment("standalone", 10, 8)]
        result = plan(clips, constraints(10, priorities={"payoff": 100000}))
        self.assertEqual(result["selected_ids"], ["standalone"])

    def test_shorter_then_source_order_tie_break(self):
        self.assertEqual(plan([segment("a", 8), segment("b", 7)], constraints(8))["selected_ids"], ["b"])
        self.assertEqual(plan([segment("z", 8), segment("a", 8)], constraints(8))["selected_ids"], ["z"])

    def test_ambiguity_blocks_even_when_budget_is_feasible(self):
        result = plan([segment("a", 10)], constraints(10, ambiguities=["Does 'the result' mean clip a?"]))
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["selected_ids"], [])
        self.assertIn("Does 'the result'", result["reasons"][0])

    def test_no_nonempty_cut_is_infeasible(self):
        for rules in [constraints(1), constraints(100, excluded=["a"])]:
            with self.subTest(rules=rules):
                self.assertEqual(plan([segment("a", 10)], rules)["status"], "infeasible")

    def test_does_not_mutate_nested_input(self):
        clips = [segment("a", 10), segment("b", 10, requires=["a"])]
        rules = constraints(100, required=["b"], priorities={"a": 2})
        rules["evidence"] = [{"kind": "required", "segment_id": "b", "quote": "Keep B."}]
        original = copy.deepcopy((clips, rules))
        result = plan(clips, rules)
        result["required_closure"].append("invented")
        result["selected_ids"].clear()
        self.assertEqual((clips, rules), original)

    def test_independent_reference_optimum_on_random_small_catalogs(self):
        rng = random.Random(8172)
        for trial in range(100):
            size = rng.randint(2, 8)
            clips = [segment(f"s{i}", rng.randint(1, 20), rng.randint(1, 10),
                             [f"s{j}" for j in range(i) if rng.random() < 0.15]) for i in range(size)]
            rules = constraints(rng.randint(1, 60), required=[c["id"] for c in clips if rng.random() < 0.1],
                                excluded=[c["id"] for c in clips if rng.random() < 0.1])
            feasible = []
            for width in range(1, size + 1):
                for indices in itertools.combinations(range(size), width):
                    selected = {clips[i]["id"] for i in indices}
                    if not set(rules["required_ids"]) <= selected or selected.intersection(rules["excluded_ids"]):
                        continue
                    if any(not set(clips[i]["requires"]) <= selected for i in indices):
                        continue
                    duration = sum(clips[i]["duration_ms"] for i in indices)
                    if duration <= rules["max_duration_ms"]:
                        feasible.append((-sum(clips[i]["value"] for i in indices), duration, indices))
            result = plan(clips, rules)
            with self.subTest(trial=trial):
                if not feasible:
                    self.assertEqual(result["status"], "infeasible")
                else:
                    expected = min(feasible)
                    self.assertEqual(result["selected_ids"], [clips[i]["id"] for i in expected[2]])


class ValidationTests(unittest.TestCase):
    def test_budget_requires_positive_integer_not_bool_float_or_string(self):
        for budget in [None, True, False, 0, -1, 1.5, "90000"]:
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                plan([segment("a", 10)], constraints(budget))

    def test_missing_unknown_duplicate_and_wrong_shape_fields_rejected(self):
        mutations = [
            lambda c: c.pop("required_ids"),
            lambda c: c.update(estimated_duration_ms=1),
            lambda c: c.update(required_ids=["ghost"]),
            lambda c: c.update(excluded_ids=["ghost"]),
            lambda c: c.update(required_ids=["a", "a"]),
            lambda c: c.update(excluded_ids=["a", "a"]),
            lambda c: c.update(required_ids="a"),
            lambda c: c.update(priorities={"ghost": 1}),
            lambda c: c.update(priorities={"a": True}),
            lambda c: c.update(priorities={"a": 0}),
            lambda c: c.update(priorities=[]),
            lambda c: c.update(ambiguities=[""]),
            lambda c: c.update(ambiguities=[False]),
            lambda c: c.update(evidence=[{"kind": "required", "segment_id": [], "quote": "keep"}]),
            lambda c: c.update(evidence=[{"kind": "required", "segment_id": "a", "quote": ""}]),
            lambda c: c.update(evidence=[{"kind": "required", "segment_id": "ghost", "quote": "keep"}]),
            lambda c: c.update(evidence=[{"kind": "required", "segment_id": "a", "quote": "keep", "extra": 1}]),
        ]
        for index, mutate in enumerate(mutations):
            rules = constraints()
            mutate(rules)
            with self.subTest(mutation=index), self.assertRaises(ValueError):
                plan([segment("a", 10)], rules)

    def test_invalid_catalogs_rejected(self):
        bad_catalogs = [[], [segment(f"s{i}", 1) for i in range(19)], [None],
                        [segment("a", 10), segment("a", 10)], [segment("bad id", 10)],
                        [segment("a", 0)], [segment("a", True)], [segment("a", 10, 11)],
                        [segment("a", 10, requires=["unknown"])], [segment("a", 10, requires=["a"])],
                        [segment("a", 10, requires=["b"]), segment("b", 10, requires=["a"])],
                        [segment("a", 10, requires=["b"]), segment("b", 10)],
                        [segment("a", 10), segment("b", 10, requires=["a", "a"])]]
        for index, clips in enumerate(bad_catalogs):
            with self.subTest(catalog=index), self.assertRaises(ValueError):
                plan(clips, constraints())

    def test_global_evidence_allows_null_segment(self):
        rules = constraints(10)
        rules["evidence"] = [{"kind": "duration", "segment_id": None, "quote": "10 milliseconds."}]
        self.assertEqual(plan([segment("a", 10)], rules)["status"], "feasible")


class IndependentVerificationTests(unittest.TestCase):
    def setUp(self):
        self.clips = [segment("context", 10), segment("result", 20, requires=["context"]),
                      segment("optional", 5)]
        self.rules = constraints(30, required=["result"], excluded=["optional"])

    def test_accepts_complete_selection_and_recomputes_duration(self):
        check = verify_selection(self.clips, self.rules, ["context", "result"])
        self.assertTrue(check["valid"])
        self.assertEqual(check["duration_ms"], 30)
        self.assertEqual(check["minimum_required_ms"], 30)

    def test_rejects_tampered_selections(self):
        cases = [([], "nonempty_cut"), (["result"], "dependencies"), (["context"], "required_closure"),
                 (["result", "context"], "source_order"),
                 (["context", "context", "result"], "unique_ids"),
                 (["context", "result", "optional"], "excluded_absent"),
                 (["context", "result", "ghost"], "known_ids")]
        for selected, failed_check in cases:
            with self.subTest(selected=selected):
                report = verify_selection(self.clips, self.rules, selected)
                self.assertFalse(report["valid"])
                self.assertFalse(next(c["passed"] for c in report["checks"] if c["name"] == failed_check))

    def test_rejects_over_budget_and_ambiguous_selections(self):
        for rules, failed_check in [(constraints(29, required=["result"]), "duration_budget"),
                                    (constraints(30, ambiguities=["Unclear requirement"]), "resolved_brief")]:
            check = verify_selection(self.clips, rules, ["context", "result"])
            self.assertFalse(check["valid"])
            self.assertFalse(next(c["passed"] for c in check["checks"] if c["name"] == failed_check))


if __name__ == "__main__":
    unittest.main()
