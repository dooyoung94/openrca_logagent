"""Meaningful boundaries for the separate local-model experiment."""
import json
import unittest

from logagent_bench.hf_worker import diagnosis_from_output, prompt_for


class LocalHfContract(unittest.TestCase):
    def packet(self):
        return {"common_evidence": {"context": {}, "notes": [], "available_counts": {},
                "metrics": [{"entity": "observed-service", "evidence_id": "M1", "scope": "component",
                             "metric": "cpu", "normal": {"n": 0}, "incident": {"n": 1, "max": 2}}],
                "edges": [], "services": [], "error_templates": []},
                "logagent_hints": [{"causal_component": "fallible-candidate"}],
                "hint_note": "Fallible hint"}

    def test_control_never_receives_candidate_answers(self):
        packet = self.packet()
        original = json.dumps(packet, sort_keys=True)
        control = prompt_for(packet, "summary_llm")
        treatment = prompt_for(packet, "logagent_llm")
        self.assertNotIn("fallible-candidate", control)
        self.assertIn("fallible-candidate", treatment)
        self.assertIn("observed-service", control)
        self.assertIn("observed-service", treatment)
        self.assertEqual(original, json.dumps(packet, sort_keys=True))

    def test_model_answer_not_repaired_to_candidate_or_alias(self):
        value = {"abstain": False, "causal_scope": "dependency_edge", "causal_component": None,
            "edge_source": "destination", "edge_destination": "source", "mechanism_code": "call_path_delay",
            "fault_category": "cpu"}
        answer = diagnosis_from_output(value)
        self.assertEqual(answer["edge_source"], "destination")
        self.assertEqual(answer["edge_destination"], "source")
        self.assertEqual(answer["fault_category"], "cpu")

    def test_abstention_remains_no_diagnosis(self):
        self.assertIsNone(diagnosis_from_output({"abstain": True}))

    def test_unknown_arm_fails_before_inference(self):
        with self.assertRaises(ValueError):
            prompt_for(self.packet(), "raw")


if __name__ == "__main__":
    unittest.main()
