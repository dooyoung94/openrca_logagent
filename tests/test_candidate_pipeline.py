"""Verify the handoff and exercise the actual upstream tool loop offline.

Scripted provider responses are contract tests, never benchmark observations.
"""
import copy
import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from logagent_bench.candidates import build_isolated_shortlist, select_candidates, shortlist_sha256
from logagent_bench.upstream_bridge import run_logagent_agent

SDK = importlib.util.find_spec("agent_rca_bench") is not None


class CandidateTests(unittest.TestCase):
    def test_rank_limit_and_no_top1_or_answer_metadata_handoff(self):
        threads = [{"thread_id": f"thread-{i}", "score": 100-i,
                    "causal_component": f"service-{i}", "metadata": "hidden",
                    "evidence": ["private source rows"]} for i in range(7)]
        source = {"threads": threads, "diagnosis": {"causal_component": "VERDICT"},
                  "selected_thread": threads[0], "expected": "ANSWER"}
        frozen = copy.deepcopy(source)
        shortlist = select_candidates(source)
        self.assertEqual(source, frozen)
        self.assertEqual([r["thread_id"] for r in shortlist["candidates"]], [f"thread-{i}" for i in range(5)])
        self.assertEqual(shortlist["candidate_count"], 7)
        self.assertEqual(shortlist["shortlisted_count"], 5)
        serialized = json.dumps(shortlist)
        for forbidden in ("VERDICT", "ANSWER", "metadata", "private source rows", "diagnosis", "selected_thread"):
            self.assertNotIn(forbidden, serialized)
        self.assertEqual(shortlist_sha256(shortlist), shortlist_sha256(copy.deepcopy(shortlist)))

    def test_empty_ranking_stays_empty(self):
        self.assertEqual(select_candidates({"threads": []})["candidates"], [])
        for limit in (True, 0, 6):
            with self.assertRaises(ValueError):
                select_candidates({"threads": []}, limit)

    def test_selector_subprocess_blocks_label_reads_before_loading_telemetry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = root / "metadata" / "policy.yaml"
            policy.parent.mkdir()
            policy.write_text("{}")
            output = root / "candidate.json"
            with self.assertRaisesRegex(RuntimeError, "before any model call"):
                build_isolated_shortlist(root / "input", policy, output)
            self.assertFalse(output.exists())
            self.assertIn("Answer-bearing paths", output.with_suffix(".error.txt").read_text())


@unittest.skipUnless(SDK, "Install .[llm] for real upstream loop contract tests")
class OriginalLoopTests(unittest.TestCase):
    @staticmethod
    def diagnosis():
        return {
            "causal_scope": "component", "causal_component": "verified-service",
            "edge_source": None, "edge_destination": None,
            "fault_category": "cpu", "mechanism_code": "cpu_saturation",
            "fault_type": "CPU saturation", "confidence": 0.7,
            "evidence": [{"query_id": "q01", "claim": "CPU usage rose after onset.",
                          "claim_types": ["causal_locus", "fault_mechanism"]}],
            "alternative_candidates": [], "explanation": "The telemetry supports CPU saturation.",
        }

    @staticmethod
    def settings():
        from agent_rca_bench.contracts import ApiTransport
        return dict(model="glm-5.3", api_transport=ApiTransport.BIGMODEL_CHAT_COMPLETIONS,
                    reasoning_effort="high", max_tool_calls=48, max_turns=58,
                    max_output_tokens=16384, semantic_coverage=None)

    @staticmethod
    def response(name, arguments, ordinal):
        from openai.types.chat import ChatCompletion
        return ChatCompletion.model_validate({
            "id": f"test-{ordinal}", "object": "chat.completion", "created": 0,
            "model": "glm-5.3", "choices": [{"index": 0, "finish_reason": "tool_calls",
                "message": {"role": "assistant", "content": None,
                    "tool_calls": [{"id": f"call-{ordinal}", "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(arguments)}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    def investigate(self, calls, shortlist):
        import agent_rca_bench.agent as agent
        from agent_rca_bench.contracts import CaseInput, QueryResult, Visibility

        requests, events, executed = [], [], []
        responses = iter(self.response(name, value, i) for i, (name, value) in enumerate(calls))
        def create(**kwargs):
            events.append("provider")
            requests.append(copy.deepcopy(kwargs))
            return next(responses)
        def loader():
            events.append("selector")
            return shortlist
        def execute(query, **kwargs):
            executed.append(query)
            return QueryResult(query_id="private-id", columns=["service", "normal_cpu", "incident_cpu"],
                               rows=[["verified-service", 0.1, 4.2]], elapsed_seconds=0.01)
        gateway = types.SimpleNamespace(client=types.SimpleNamespace(), execute=execute)
        provider = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        metrics = {}
        with patch.object(agent, "_chat_completions_client", return_value=provider):
            result = run_logagent_agent(
                gateway, CaseInput(case_token="test", time_start=0, time_end=100, alert_time=50),
                Visibility.RAW, candidate_loader=loader, metrics=metrics, **self.settings(),
            )
        self.assertEqual(events[0], "selector")
        self.assertEqual(events.count("selector"), 1)
        return result, requests, executed, metrics

    def test_real_loop_queries_rejects_shape_and_citation_then_accepts_new_submission(self):
        valid = self.diagnosis()
        bad_shape = {**valid, "edge_source": "contradictory-edge"}
        bad_citation = {**valid, "evidence": [{**valid["evidence"][0], "query_id": "thread-0"}]}
        shortlist = select_candidates({"threads": [{"thread_id": "thread-0",
            "causal_scope": "component", "causal_component": "wrong-candidate", "score": 90}]})
        calls = [("execute_sql", {"query": "SELECT service, normal_cpu, incident_cpu FROM cpu_samples"}),
                 ("submit_diagnosis", bad_shape), ("submit_diagnosis", bad_citation),
                 ("submit_diagnosis", valid)]
        result, requests, executed, metrics = self.investigate(calls, shortlist)
        self.assertIsNone(result.error)
        self.assertEqual(result.diagnosis.causal_component, "verified-service")
        self.assertEqual(len(requests), 4)
        self.assertEqual(len(executed), 1)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertFalse(result.tool_budget_exhausted)
        feedback = [m["content"] for m in requests[-1]["messages"] if m["role"] == "tool"]
        self.assertTrue(any("must not define an edge" in value for value in feedback))
        self.assertTrue(any("replace invalid citations: thread-0" in value for value in feedback))
        self.assertEqual(result.diagnosis.evidence[0].query_id, "q01")
        self.assertEqual(metrics["shortlist_candidates"], 1)
        self.assertAlmostEqual(result.elapsed_seconds,
                               metrics["llm_elapsed_seconds"] + metrics["architecture_build_seconds"])

    def test_empty_shortlist_still_runs_original_investigation(self):
        result, requests, executed, _ = self.investigate([
            ("execute_sql", {"query": "SELECT service, normal_cpu, incident_cpu FROM cpu_samples"}),
            ("submit_diagnosis", self.diagnosis()),
        ], select_candidates({"threads": []}))
        self.assertIsNotNone(result.diagnosis)
        self.assertEqual(len(requests), 2)
        self.assertEqual(len(executed), 1)

    def test_invalid_output_is_not_repaired_after_turn_exhaustion(self):
        invalid = {**self.diagnosis(), "edge_source": "contradictory-edge"}
        result, requests, _, _ = self.investigate(
            [("submit_diagnosis", invalid)] * 58, select_candidates({"threads": []})
        )
        self.assertIsNone(result.diagnosis)
        self.assertIn("within 58 turns", result.error)
        self.assertEqual(len(requests), 58)

    def test_selector_failure_prevents_provider_calls(self):
        import agent_rca_bench.agent as agent
        from agent_rca_bench.contracts import CaseInput, Visibility
        with patch.object(agent, "_chat_completions_client") as provider:
            with self.assertRaisesRegex(RuntimeError, "selector failed"):
                run_logagent_agent(None, CaseInput(case_token="test", time_start=0, time_end=100, alert_time=50),
                    Visibility.RAW, candidate_loader=lambda: (_ for _ in ()).throw(RuntimeError("selector failed")),
                    metrics={}, **self.settings())
            provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
