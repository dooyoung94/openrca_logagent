import copy
import importlib.util
import json
import types
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from logagent_bench.datasets import ROOT, cohort
from logagent_bench.experiment import make_plan
from logagent_bench.paired_stats import case_pair_effect, holm, compare_report
from logagent_bench.upstream_bridge import thread_session, THREAD_TOOL, run_logagent_agent

SDK = importlib.util.find_spec("agent_rca_bench") is not None


class PlanTests(unittest.TestCase):
    def test_same_frozen_cohort_models_and_budgets(self):
        plan = make_plan()
        self.assertEqual(plan["expected_cells"], 672)
        self.assertEqual(len(plan["models"]), 6)
        self.assertEqual(plan["independent_cases"], 14)
        self.assertEqual(Counter(c["arm"] for c in plan["schedule"]), {a:168 for a in ["raw","semantic_graph","split_pillars","logagent"]})
        self.assertEqual({m["max_output_tokens"] for m in plan["models"]}, {16384})
        self.assertIsNone(plan["accuracy"])

    def test_no_model_substitution(self):
        with self.assertRaises(ValueError):
            make_plan(["unrequested-cheaper-model"])

    def test_session_restored_after_error(self):
        original = type("Original", (), {})
        module = types.SimpleNamespace(InvestigationSession=original)
        with self.assertRaises(RuntimeError):
            with thread_session(module, lambda: {}, {}):
                self.assertIsNot(module.InvestigationSession, original)
                raise RuntimeError("injected transport failure")
        self.assertIs(module.InvestigationSession, original)

    def test_repetitions_do_not_inflate_case_sample(self):
        result = case_pair_effect({"a":[0,0],"b":[1,1]}, {"a":[1,1],"b":[1,1]})
        self.assertEqual(result["independent_cases"], 2)
        self.assertEqual(result["difference"], .5)
        with self.assertRaises(ValueError):
            case_pair_effect({"a":[0,0]}, {"b":[1,1]})
        self.assertEqual(holm([.01,.03,.2]), [.03,.06,.2])

    def test_incomplete_llm_results_never_claim_accuracy(self):
        result = compare_report({"expected_cells":672,"completed_cells":0})
        self.assertIsNone(result["accuracy"])


@unittest.skipUnless(SDK, "Install .[llm] to test the pinned upstream contract")
class UpstreamTests(unittest.TestCase):
    def test_system_and_incident_prompts_identical(self):
        import agent_rca_bench.agent as a
        from agent_rca_bench.contracts import CaseInput,Visibility,ApiTransport,AgentUsage
        case = CaseInput(case_token="opaque",time_start=0,time_end=100,alert_time=50)
        fake = a.StructuredAgentResult(output=None,error=None,tool_calls=[],rejected_tool_calls=[],tool_calls_requested=0,
            tool_budget_exhausted=False,usage=AgentUsage(),elapsed_seconds=0,responses=[])
        captured=[]
        def runner(*args,**kw):
            captured.append(kw)
            return fake
        settings=dict(model="gpt-5.6-sol",api_transport=ApiTransport.OPENAI_RESPONSES,reasoning_effort="medium",
                      max_tool_calls=48,max_turns=58,max_output_tokens=16384,semantic_coverage=None)
        with patch.object(a,"run_structured_api_agent",runner):
            a.run_agent(None,case,Visibility.RAW,**settings)
            run_logagent_agent(None,case,Visibility.RAW,candidate_loader=lambda:{},metrics={},**settings)
        for field in ["system_prompt","user_prompt","model","api_transport","reasoning_effort","max_tool_calls","max_turns","max_output_tokens","output_tool"]:
            self.assertEqual(captured[0][field],captured[1][field])
        self.assertEqual(captured[1]["investigation_tools"],captured[0]["investigation_tools"]+[THREAD_TOOL])

    def test_thread_navigation_is_not_valid_source_evidence(self):
        from agent_rca_bench.contracts import ToolTrace
        from agent_rca_bench.evidence import is_valid_evidence_trace
        hint=ToolTrace(tool_name="query_rca_threads",input={"limit":1},query_id="q01",output={"navigation_only":True})
        self.assertFalse(is_valid_evidence_trace([hint]))

    def test_accepted_alternative_mechanism_from_original_scorer(self):
        from logagent_bench.canonical_scoring import official_diagnosis_score
        reference = next(c for c in cohort() if c["opaque_case_id"].endswith("001"))
        self.assertIn("configuration_error",[x["mechanism_code"] for x in reference["direct_log_mechanism_evidence"]])
        prediction={"diagnosis":{"causal_scope":"component","causal_component":reference["causal_component"],
                                 "fault_category":"other","mechanism_code":"configuration_error"}}
        self.assertTrue(official_diagnosis_score(prediction,reference)["diagnosis_correct"])
        prediction["diagnosis"]["mechanism_code"]="dependency_unavailable"
        self.assertFalse(official_diagnosis_score(prediction,reference)["diagnosis_correct"])

    def test_both_edge_endpoints_required(self):
        from logagent_bench.canonical_scoring import official_diagnosis_score
        reference = next(c for c in cohort() if c["opaque_case_id"].endswith("005"))
        prediction={"diagnosis":{k:reference[k] for k in ["causal_scope","edge_source","edge_destination","mechanism_code","fault_category"]}}
        self.assertTrue(official_diagnosis_score(prediction,reference)["diagnosis_correct"])
        prediction["diagnosis"]["edge_destination"]="incorrect-service"
        self.assertFalse(official_diagnosis_score(prediction,reference)["diagnosis_correct"])


if __name__ == "__main__":
    unittest.main()
