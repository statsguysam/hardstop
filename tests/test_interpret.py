import copy
import json
from pathlib import Path
import unittest

from hardstop.interpret import InterpretationError, duration_supported, validate_interpretation


class InterpretationTests(unittest.TestCase):
    def setUp(self):
        self.brief = "Fit within 90 seconds. Keep the result and disclaimer. Remove rollout."
        self.segments = [{"id": "result", "title": "Pilot result"}, {"id": "disclaimer", "title": "Disclaimer"}, {"id": "rollout", "title": "Rollout"}]
        self.data = {"max_duration_seconds": 90, "duration_quote": "Fit within 90 seconds.",
                     "required": [{"segment_id": "result", "quote": "Keep the result and disclaimer."},
                                  {"segment_id": "disclaimer", "quote": "Keep the result and disclaimer."}],
                     "excluded": [{"segment_id": "rollout", "quote": "Remove rollout."}],
                     "priorities": [], "ambiguities": [], "summary": "A 90-second cut."}

    def test_grounded_interpretation(self):
        result = validate_interpretation(self.data, self.brief, self.segments)
        self.assertEqual(result["max_duration_ms"], 90000)
        self.assertEqual(result["required_ids"], ["result", "disclaimer"])
        self.assertEqual(result["ambiguities"], [])

    def test_hallucinated_evidence_cannot_authorize_a_cut(self):
        data = copy.deepcopy(self.data)
        data["required"][0]["quote"] = "The result is optional."
        with self.assertRaises(InterpretationError):
            validate_interpretation(data, self.brief, self.segments)

    def test_duration_evidence_is_recomputed(self):
        data = copy.deepcopy(self.data)
        data["max_duration_seconds"] = 120
        with self.assertRaises(InterpretationError):
            validate_interpretation(data, self.brief, self.segments)

    def test_unknown_segment_is_rejected(self):
        data = copy.deepcopy(self.data)
        data["required"][0]["segment_id"] = "nonexistent"
        with self.assertRaises(InterpretationError):
            validate_interpretation(data, self.brief, self.segments)

    def test_missing_duration_requires_review(self):
        data = copy.deepcopy(self.data)
        data.update(max_duration_seconds=None, duration_quote="", ambiguities=["Duration has not been confirmed."])
        result = validate_interpretation(data, self.brief, self.segments)
        self.assertTrue(result["ambiguities"])

    def test_quotes_must_name_the_selected_content(self):
        data = copy.deepcopy(self.data)
        data["required"][0]["quote"] = "Remove rollout."
        result = validate_interpretation(data, self.brief, self.segments)
        self.assertTrue(result["ambiguities"])

    def test_unit_conversion(self):
        self.assertTrue(duration_supported(120, "two minutes"))
        self.assertTrue(duration_supported(90, "1.5 minutes"))
        self.assertFalse(duration_supported(90, "90 minutes"))

    def test_omitted_mandatory_clip_stops_publication(self):
        data = copy.deepcopy(self.data)
        data["required"] = []
        result = validate_interpretation(data, self.brief, self.segments)
        self.assertTrue(any("omitted an explicit keep" in reason for reason in result["ambiguities"]))

    def test_omitted_removal_stops_publication(self):
        data = copy.deepcopy(self.data)
        data["excluded"] = []
        result = validate_interpretation(data, self.brief, self.segments)
        self.assertTrue(any("omitted an explicit removal" in reason for reason in result["ambiguities"]))

    def test_grounded_quote_with_reversed_polarity_stops_publication(self):
        data = copy.deepcopy(self.data)
        data["required"].append({"segment_id": "rollout", "quote": "Remove rollout."})
        data["excluded"] = []
        result = validate_interpretation(data, self.brief, self.segments)
        self.assertTrue(any("unsupported wording or polarity" in reason for reason in result["ambiguities"]))

    def _validate(self, brief, *, seconds=90, duration_quote="Fit within 90 seconds.", required=(), excluded=(), segments=None):
        data = {"max_duration_seconds": seconds, "duration_quote": duration_quote,
                "required": [{"segment_id": sid, "quote": quote} for sid, quote in required],
                "excluded": [{"segment_id": sid, "quote": quote} for sid, quote in excluded],
                "priorities": [], "ambiguities": [], "summary": "A whole-clip cut."}
        return validate_interpretation(data, brief, segments or self.segments)

    def test_negated_removal_means_keep_and_negated_keep_means_remove(self):
        brief = "Fit within 90 seconds. Don't remove the result. Do not include rollout."
        result = self._validate(brief, required=[("result", "Don't remove the result.")],
                                excluded=[("rollout", "Do not include rollout.")])
        self.assertEqual(result["ambiguities"], [])
        reversed_result = self._validate(brief, required=[("rollout", "Do not include rollout.")],
                                         excluded=[("result", "Don't remove the result.")])
        self.assertTrue(reversed_result["ambiguities"])

    def test_passive_list_and_removal_are_audited(self):
        brief = "Fit within 90 seconds. The result and disclaimer are mandatory. The rollout must be removed."
        result = self._validate(brief,
            required=[(sid, "The result and disclaimer are mandatory.") for sid in ("result", "disclaimer")],
            excluded=[("rollout", "The rollout must be removed.")])
        self.assertEqual(result["ambiguities"], [])

    def test_polite_imperative_is_supported(self):
        brief = "Fit within 90 seconds. Please keep result."
        self.assertEqual(self._validate(brief, required=[("result", "Please keep result.")])["ambiguities"], [])

    def test_unfamiliar_requirement_grammar_requires_review(self):
        for directive in ("Only keep result.", "Keep result or disclaimer.",
                          "Keep result unless space is tight.", "The result must stay.",
                          "Keep the important part.", "If space permits, keep result.",
                          "Keep result, not disclaimer.", "Keep all but result."):
            with self.subTest(directive=directive):
                result = self._validate("Fit within 90 seconds. " + directive)
                self.assertTrue(result["ambiguities"])

    def test_negated_passive_removal_is_mandatory(self):
        brief = "Fit within 90 seconds. The result must not be omitted."
        result = self._validate(brief, required=[("result", "The result must not be omitted.")])
        self.assertEqual(result["ambiguities"], [])

    def test_model_requirement_with_inner_negation_cannot_pass_as_positive(self):
        brief = "Fit within 90 seconds. Keep result, not disclaimer."
        result = self._validate(brief, required=[(sid, "Keep result, not disclaimer.")
                                                 for sid in ("result", "disclaimer")])
        self.assertTrue(result["ambiguities"])

    def test_mixed_historical_and_current_clause_requires_review(self):
        brief = "The new cap is 90 seconds, replacing the previous cap."
        self.assertTrue(self._validate(brief, duration_quote="90 seconds")["ambiguities"])

    def test_known_clip_name_does_not_hide_an_unsupported_edit_or_unknown_requirement(self):
        for directive in ("Keep result at double speed.", "Keep result and add a sponsor disclosure.",
                          "Keep result with rewritten narration."):
            with self.subTest(directive=directive):
                result = self._validate("Fit within 90 seconds. " + directive,
                                        required=[("result", directive)])
                self.assertTrue(result["ambiguities"])

    def test_preservation_whitelist_cannot_authorize_removing_narration(self):
        self.assertTrue(self._validate("Fit within 90 seconds. Remove the original narration.")["ambiguities"])

    def test_literal_catalog_title_with_not_is_not_treated_as_negation(self):
        segments = [{"id": "context", "title": "An illustration, not a customer study"}]
        directive = "Keep An illustration, not a customer study."
        result = self._validate("Fit within 90 seconds. " + directive,
                                required=[("context", directive)], segments=segments)
        self.assertEqual(result["ambiguities"], [])

    def test_unclear_order_reference_does_not_silently_disappear(self):
        for directive in ("Keep result before it.", "Keep result before the next section.", "Keep result before disclaimer."):
            with self.subTest(directive=directive):
                result = self._validate("Fit within 90 seconds. " + directive, required=[("result", directive)])
                self.assertTrue(result["ambiguities"])

    def test_per_clip_limit_cannot_be_used_as_total_duration(self):
        brief = "Fit within 90 seconds per clip."
        result = self._validate(brief, duration_quote="90 seconds")
        self.assertTrue(result["ambiguities"])

    def test_optional_mention_does_not_authorize_mandatory_selection(self):
        brief = "Fit within 90 seconds. Favor result over rollout."
        self.assertEqual(self._validate(brief)["ambiguities"], [])
        result = self._validate(brief, required=[("result", "Favor result over rollout.")])
        self.assertTrue(result["ambiguities"])

    def test_dependency_coverage_does_not_require_duplicate_required_entry(self):
        segments = [{"id": "pilot_context", "title": "Pilot context"},
                    {"id": "result", "title": "Result", "requires": ["pilot_context"]}]
        brief = "Fit within 90 seconds. Keep result. If we show result, retain pilot context before it."
        result = self._validate(brief, required=[("result", "Keep result.")], segments=segments)
        self.assertEqual(result["ambiguities"], [])

    def test_conditional_cannot_invent_a_dependency(self):
        brief = "Fit within 90 seconds. Keep result. If we show result, retain rollout."
        result = self._validate(brief, required=[("result", "Keep result.")])
        self.assertTrue(any("not a declared source prerequisite" in reason for reason in result["ambiguities"]))

    def test_order_instruction_cannot_reverse_source_order(self):
        brief = "Fit within 90 seconds. Keep result after rollout."
        result = self._validate(brief, required=[("result", "Keep result after rollout.")])
        self.assertTrue(any("conflicts with the immutable source order" in reason for reason in result["ambiguities"]))

    def test_old_numeric_quote_cannot_override_current_cap(self):
        brief = "Do not use the old 120 seconds. The new cap is 90 seconds."
        result = self._validate(brief, seconds=120, duration_quote="120 seconds")
        self.assertTrue(any("differs from the active upper bound" in reason for reason in result["ambiguities"]))
        current = self._validate(brief, duration_quote="The new cap is 90 seconds.")
        self.assertEqual(current["ambiguities"], [])

    def test_historical_cap_can_be_explicitly_replaced_in_separate_clause(self):
        brief = "The old cap was within 120 seconds. The new cap is 90 seconds."
        self.assertEqual(self._validate(brief, duration_quote="The new cap is 90 seconds.")["ambiguities"], [])

    def test_lower_bound_is_not_an_upper_bound(self):
        brief = "The video must be at least 90 seconds."
        result = self._validate(brief, duration_quote="at least 90 seconds")
        self.assertTrue(any("minimum duration" in reason for reason in result["ambiguities"]))

    def test_minimum_is_not_silently_ignored_when_maximum_exists(self):
        brief = "Fit within 90 seconds. The video must be at least 60 seconds."
        self.assertTrue(self._validate(brief)["ambiguities"])

    def test_negated_or_uncertain_upper_bound_requires_review(self):
        for brief in ("Do not fit within 90 seconds.", "Maybe fit within 90 seconds.",
                      "Fit within 90 seconds if possible.", "The original cap is 90 seconds."):
            with self.subTest(brief=brief):
                self.assertTrue(self._validate(brief, duration_quote="90 seconds")["ambiguities"])

    def test_incompatible_active_upper_bounds_require_review(self):
        brief = "Fit within 90 seconds. The cap is 120 seconds."
        self.assertTrue(self._validate(brief)["ambiguities"])

    def test_bare_numeric_mention_is_not_an_active_upper_bound(self):
        brief = "The recording lasts 90 seconds."
        self.assertTrue(self._validate(brief, duration_quote="90 seconds")["ambiguities"])

    def test_full_clause_audit_converts_decimal_minutes(self):
        brief = "Fit within 1.5 minutes."
        self.assertEqual(self._validate(brief, duration_quote=brief)["ambiguities"], [])

    def test_the_four_demo_briefs_retain_their_intended_classification(self):
        fixtures = Path(__file__).resolve().parents[1] / "fixtures"
        briefs = json.loads((fixtures / "briefs.json").read_text())
        segments = json.loads((fixtures / "catalog.json").read_text())["segments"]
        for name, seconds, duration, keep in (
            ("original", 120, "no longer than 120 seconds", "Keep the pilot result, the disclaimer and the final call to action."),
            ("amendment", 90, "no longer than 90 seconds", "The pilot result, disclaimer and final call to action are mandatory."),
            ("impossible", 30, "fit within 30 seconds", "The pilot result, disclaimer and final call to action are still mandatory."),
        ):
            with self.subTest(fixture=name):
                required = [(sid, keep) for sid in ("result", "disclaimer", "call_to_action")]
                if name != "original":
                    required.append(("pilot_context", "Keep the pilot context before the result."))
                excluded = [("rollout", "The rollout discussion must be removed.")] if name == "amendment" else []
                result = self._validate(briefs[name]["body"], seconds=seconds, duration_quote=duration,
                                        required=required, excluded=excluded, segments=segments)
                self.assertEqual(result["ambiguities"], [])
                self.assertEqual(result["max_duration_ms"], seconds * 1000)
        unclear = self._validate(briefs["ambiguous"]["body"], seconds=60, duration_quote="one minute", segments=segments)
        self.assertTrue(unclear["ambiguities"])


if __name__ == "__main__":
    unittest.main()
