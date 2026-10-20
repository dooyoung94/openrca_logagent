"""Add one navigation tool while preserving the upstream runner and prompts."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

LOCK = threading.RLock()
THREAD_TOOL = {
    "name": "query_rca_threads",
    "description": "Return evidence-ranked RCA candidate Threads built from this incident's telemetry. These rankings are navigation hints, not independently valid source evidence. Verify the chosen cause with successful SQL or PromQL queries before citing evidence.",
    "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 5}}, "required": ["limit"], "additionalProperties": False},
}


@contextmanager
def thread_session(agent_module, candidate_loader, metrics):
    """The upstream runner creates sessions internally. Scope the extension
    under a process-wide lock and restore its class even after a provider error.
    All arms execute serially in this experiment; parallel use is prohibited.
    """
    original = agent_module.InvestigationSession
    cached = None

    class ThreadSession(original):
        def _execute(self, tool_name, arguments):
            nonlocal cached
            if tool_name != "query_rca_threads":
                return super()._execute(tool_name, arguments)
            limit = arguments.get("limit", 3)
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5:
                raise ValueError("limit must be an integer in 1..5")
            if cached is None:
                started = time.perf_counter()
                cached = candidate_loader()
                metrics["architecture_build_seconds"] += time.perf_counter() - started
            metrics["architecture_tool_calls"] += 1
            rows = []
            for thread in cached.get("threads", [])[:limit]:
                rows.append({k: thread.get(k) for k in ["thread_id", "causal_scope", "causal_component", "edge_source", "edge_destination", "mechanism_code", "fault_category", "score", "slice_id", "connections"]})
            # No source rows, oracle thresholds, source-case names, or reference
            # graphs are returned. The upstream evidence verifier rejects this
            # tool as a source citation, requiring real telemetry queries.
            return {"candidates": rows, "candidate_count": cached.get("candidate_count", 0),
                    "status": cached.get("status"), "navigation_only": True,
                    "source_evidence_required": True, "score_is_probability": False}

    with LOCK:
        agent_module.InvestigationSession = ThreadSession
        try:
            yield
        finally:
            agent_module.InvestigationSession = original


def run_logagent_agent(gateway, case_input, visibility, *, candidate_loader, metrics, **kwargs):
    import agent_rca_bench.agent as agent
    from agent_rca_bench.contracts import Visibility
    if visibility is not Visibility.RAW:
        raise ValueError("LogAgent arm extends only the frozen Raw tool surface")
    tools = agent._investigation_tools(Visibility.RAW, case_input.fault_taxonomy, kwargs.get("semantic_coverage"), promql=True)
    tools.append(THREAD_TOOL)
    with thread_session(agent, candidate_loader, metrics):
        result = agent.run_structured_api_agent(
            gateway, case_input, Visibility.RAW,
            model=kwargs["model"], api_transport=kwargs["api_transport"],
            reasoning_effort=kwargs.get("reasoning_effort"),
            system_prompt=agent._system_prompt(Visibility.RAW),
            user_prompt=agent._incident_prompt(case_input, kwargs["max_tool_calls"], Visibility.RAW),
            investigation_tools=tools, output_tool=agent._submit_tool(case_input.fault_taxonomy),
            validate_output=agent._validate_diagnosis_output,
            max_tool_calls=kwargs["max_tool_calls"], max_turns=kwargs["max_turns"],
            max_output_tokens=kwargs["max_output_tokens"], semantic_coverage=kwargs.get("semantic_coverage"), prompt_cache=True)
    return agent._diagnosis_agent_run(result, visibility=Visibility.RAW, model=kwargs["model"],
        api_transport=kwargs["api_transport"], reasoning_effort=kwargs.get("reasoning_effort"), max_output_tokens=kwargs["max_output_tokens"])
