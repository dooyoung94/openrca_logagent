"""Preselect LogAgent candidates, then use the unmodified upstream API loop."""
from __future__ import annotations

import json
import time

from .candidates import CANDIDATE_LIMIT, shortlist_sha256

CANDIDATE_NOTE = """LogAgent candidate shortlist (navigation context, not source evidence):
The candidates below were preselected from this incident's telemetry. They can be wrong or
incomplete. Investigate them with the available tools; reject them or investigate beyond the
shortlist when the query evidence warrants it. Scores are rankings, not probabilities. Thread
IDs are not query IDs and cannot be cited. The original diagnosis and evidence contract applies.
"""


def candidate_prompt(original_prompt, shortlist):
    return original_prompt + "\n\n" + CANDIDATE_NOTE + json.dumps(
        shortlist, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def run_logagent_agent(gateway, case_input, visibility, *, candidate_loader, metrics, **kwargs):
    import agent_rca_bench.agent as agent
    from agent_rca_bench.contracts import Visibility

    if visibility is not Visibility.RAW:
        raise ValueError("LogAgent arm extends only the frozen Raw interface")

    # Always run the selector before the first provider request. The LLM never
    # receives engine.diagnosis/selected_thread as a fixed final answer.
    started = time.perf_counter()
    metrics["architecture_preselection_runs"] = 1
    try:
        shortlist = candidate_loader()
        if (shortlist.get("schema_version") != 1
                or shortlist.get("limit") != CANDIDATE_LIMIT
                or shortlist.get("navigation_only") is not True
                or shortlist.get("source_evidence_required") is not True
                or shortlist.get("shortlisted_count") != len(shortlist.get("candidates", []))
                or len(shortlist.get("candidates", [])) > CANDIDATE_LIMIT):
            raise ValueError("Candidate selector contract drift")
    finally:
        metrics["architecture_build_seconds"] = time.perf_counter() - started
    metrics["shortlist_candidates"] = len(shortlist["candidates"])
    metrics["shortlist_sha256"] = shortlist_sha256(shortlist)

    # Same method, tools, output schema, validator, provider transport, cache
    # policy and limits as upstream run_agent(RAW). Only the candidate context
    # appended to the original incident prompt is the new treatment.
    tools = agent._investigation_tools(
        Visibility.RAW, case_input.fault_taxonomy, kwargs.get("semantic_coverage"), promql=True
    )
    result = agent.run_structured_api_agent(
        gateway, case_input, Visibility.RAW,
        model=kwargs["model"], api_transport=kwargs["api_transport"],
        reasoning_effort=kwargs.get("reasoning_effort"),
        system_prompt=agent._system_prompt(Visibility.RAW),
        user_prompt=candidate_prompt(
            agent._incident_prompt(case_input, kwargs["max_tool_calls"], Visibility.RAW), shortlist
        ),
        investigation_tools=tools, output_tool=agent._submit_tool(case_input.fault_taxonomy),
        validate_output=agent._validate_diagnosis_output,
        max_tool_calls=kwargs["max_tool_calls"], max_turns=kwargs["max_turns"],
        max_output_tokens=kwargs["max_output_tokens"],
        semantic_coverage=kwargs.get("semantic_coverage"), prompt_cache=True,
    )
    run = agent._diagnosis_agent_run(
        result, visibility=Visibility.RAW, model=kwargs["model"],
        api_transport=kwargs["api_transport"], reasoning_effort=kwargs.get("reasoning_effort"),
        max_output_tokens=kwargs["max_output_tokens"],
    )
    metrics["llm_elapsed_seconds"] = run.elapsed_seconds
    run.elapsed_seconds += metrics["architecture_build_seconds"]
    metrics["pipeline_elapsed_seconds"] = run.elapsed_seconds
    return run
