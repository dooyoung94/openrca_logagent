"""Investigate one isolated case with real HF inference and original SDK tools."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

from .worker import deny_label_reads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    # Import the SDK before installing the guard; it loads code, not reference
    # fixtures. Scoring and all answer-bearing files remain outside this worker.
    import agent_rca_bench.agent as agent
    from agent_rca_bench.contracts import AgentRun, AgentUsage, ApiTransport, CaseInput, Visibility
    from agent_rca_bench.greptimedb.client import GreptimeClient
    from agent_rca_bench.greptimedb.visibility import QueryGateway
    from llama_cpp import Llama
    from .candidates import build_isolated_shortlist
    from .datasets import digest
    from .hf_loop import CONFIG, MODEL
    from .hf_transport import LocalToolClient, local_transport
    from .upstream_bridge import run_logagent_agent

    sys.addaudithook(deny_label_reads)
    protocol = json.loads((args.run_root / "protocol.json").read_text())
    if protocol["configuration"] != CONFIG or protocol["model"] != MODEL:
        raise ValueError("Frozen inference protocol mismatch")
    if digest(args.model) != MODEL["sha256"]:
        raise ValueError("Model file checksum mismatch")
    case_input = CaseInput.model_validate_json((args.run_root / "case_input.json").read_text())
    model = Llama(model_path=str(args.model), n_ctx=CONFIG["context_tokens"], n_batch=512,
                  n_threads=CONFIG["threads"], n_threads_batch=CONFIG["threads"], verbose=False)
    output = args.run_root / "private/predictions"
    output.mkdir(parents=True, exist_ok=False)
    case = protocol["case"]
    with GreptimeClient(args.endpoint, database=case_input.database, timeout=120) as client:
        for repetition, seed in enumerate(CONFIG["seeds"]):
            arms = CONFIG["arms"] if (case["ordinal"]+repetition)%2 == 0 else list(reversed(CONFIG["arms"]))
            for arm in arms:
                name = f"{case['case_id']}-{arm}-rep{repetition}"
                (output / (name+".started")).write_text("STARTED")
                provider = LocalToolClient(model, CONFIG, args.run_root / "private/provider" / name, seed)
                gateway = QueryGateway(client, Visibility.RAW)
                settings = dict(model=MODEL["repo_id"], api_transport=ApiTransport.ANTHROPIC_MESSAGES,
                    reasoning_effort=None, max_tool_calls=CONFIG["max_tool_calls"], max_turns=CONFIG["max_turns"],
                    max_output_tokens=CONFIG["max_output_tokens"], semantic_coverage=None)
                metrics = {"architecture_build_seconds": 0.0, "architecture_preselection_runs": 0}
                def loader():
                    return build_isolated_shortlist(args.run_root / "input", args.run_root / "policy.yaml",
                        args.run_root / "private/candidates" / (name+".json"))
                started = time.perf_counter()
                with local_transport(provider), client.measure_query_load() as load:
                    try:
                        if arm == "logagent_hf":
                            run = run_logagent_agent(gateway, case_input, Visibility.RAW,
                                candidate_loader=loader, metrics=metrics, **settings)
                        else:
                            run = agent.run_agent(gateway, case_input, Visibility.RAW, **settings)
                    except Exception as error:
                        run = AgentRun(run_id=uuid.uuid4().hex, visibility=Visibility.RAW,
                            model=settings["model"], api_transport=settings["api_transport"], reasoning_effort=None,
                            max_output_tokens=settings["max_output_tokens"], diagnosis=None, error=str(error),
                            elapsed_seconds=time.perf_counter()-started,
                            tool_calls=[],usage=AgentUsage(),responses=[])
                private = {"case_id":case["case_id"], "dataset":case["dataset"], "arm":arm,
                    "repetition":repetition, "seed":seed, "llm_used":True,
                    "run":run.model_dump(mode="json"), "architecture":metrics,
                    "database_load":load.model_dump(mode="json"), "generation_trace":provider.trace,
                    "provider_invocations":provider.calls, "actual_transport":CONFIG["actual_transport"]}
                path = output / (name+".json")
                path.write_text(json.dumps(private, ensure_ascii=False, indent=2))
                print(f"[HF investigation] {name} generated={run.diagnosis is not None} turns={provider.calls} tools={len(run.tool_calls)} error={bool(run.error)}", flush=True)
    files = sorted(output.glob("*.json"))
    if len(files) != 4:
        raise RuntimeError("Incomplete case schedule")
    (args.run_root / "sealed_private_predictions.json").write_text(json.dumps(
        {path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in files}, indent=2))


if __name__ == "__main__":
    main()
