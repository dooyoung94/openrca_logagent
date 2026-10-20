"""Four cells on one real isolated database; seal before private case scoring."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from logagent_bench.datasets import ROOT, BENCHMARK_REVISION, cohort, digest
from logagent_bench.hf_environment import DATABASE, download_binary, raw_environment
from logagent_bench.hf_local import code_hashes, download_model
from logagent_bench.hf_loop import CONFIG, EXPERIMENT, MODEL
from logagent_bench.runner import prepare_input

SCRIPTS = ("scripts/hf_loop_case.py", "scripts/hf_loop_collect.py", ".github/workflows/hf-tool-loop.yml")


def sanitize(record, evaluation, filename, sealed):
    run = record["run"]
    diagnosis = run["diagnosis"]
    kept = None if diagnosis is None else {key:diagnosis.get(key) for key in (
        "causal_scope", "causal_component", "edge_source", "edge_destination", "causal_operation",
        "mechanism_code", "fault_category")}
    tool_summary = [{"tool_name":item["tool_name"], "error":bool(item["error"]),
        "query_sha256":hashlib.sha256(json.dumps(item["input"],sort_keys=True).encode()).hexdigest(),
        "result_sha256":hashlib.sha256(json.dumps(item["output"],sort_keys=True).encode()).hexdigest(),
        "database_load":item.get("database_load")} for item in run["tool_calls"]]
    error = run.get("error") or ""
    error_kind = ("CONTEXT_CAPACITY" if "context capacity" in error else
                  "OUTPUT_LIMIT" if "token ceiling" in error else
                  "TURN_LIMIT" if "within" in error and "turns" in error else "RUNNER_ERROR") if error else None
    return {key:record[key] for key in ("case_id","dataset","arm","repetition","seed","llm_used")} | {
        "diagnosis":kept, "runner_error":bool(error), "error_kind":error_kind,
        "tool_budget_exhausted":run["tool_budget_exhausted"],
        "elapsed_seconds":run["elapsed_seconds"], "architecture":record["architecture"],
        "usage":{"input_tokens":sum(turn["prompt_tokens"] for turn in record["generation_trace"]),
                 "output_tokens":sum(turn["completion_tokens"] for turn in record["generation_trace"]),
                 "reasoning_tokens":0},
        "sdk_accepted_response_usage":run["usage"],
        "token_usage_complete":record["provider_invocations"]==len(record["generation_trace"]),
        "database_load":record["database_load"],
        "provider_invocations":record["provider_invocations"], "actual_transport":record["actual_transport"],
        "generation_trace":record["generation_trace"], "tool_summary":tool_summary,
        "upstream_case_evaluation":{key:evaluation[key] for key in (
            "diagnosis_correct","causal_locus_match","causal_scope_match","fault_category_match",
            "mechanism_code_match","citations_execution_valid","execution_reliability",
            "efficiency_eligible","auditable_completion","success","cited_evidence_count","valid_evidence_count")},
        "sealed_private_prediction_sha256":sealed[filename],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    ordinal = int(args.case_id)-1
    selected = cohort()[ordinal]
    name = selected["opaque_case_id"]
    source_sha = os.environ.get("GITHUB_SHA") or subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    root = ROOT / ".runs/hf-tool-loop" / name
    root.mkdir(parents=True, exist_ok=False)
    binary = download_binary()
    download_model()
    protocol = {"experiment":EXPERIMENT, "status":"FROZEN_BEFORE_INFERENCE",
        "frozen_at":datetime.now(timezone.utc).isoformat(), "configuration":CONFIG, "model":MODEL,
        "database":DATABASE, "binary_sha256":digest(binary), "benchmark_revision":BENCHMARK_REVISION,
        "case":{"case_id":name,"dataset":selected["dataset"],"ordinal":ordinal},
        "source_files_sha256":selected["source_files_sha256"], "files_sha256":code_hashes(),
        "orchestration_sha256":{path:digest(ROOT/path) for path in SCRIPTS},
        "source_commit":source_sha, "github_run_id":os.environ.get("GITHUB_RUN_ID"),
        "runtime":{"python":platform.python_version(), "cpu_count":os.cpu_count(),
            "llama_cpp_python":importlib.metadata.version("llama-cpp-python"),
            "packages":{package:importlib.metadata.version(package) for package in
                ("agent-rca-bench","pyarrow","pydantic","sqlglot","numpy","anthropic")}},
        "deviations_from_original":["local Qwen3-1.7B Q8, non-thinking, fixed sampling and seeds",
            "one model-selected tool per turn through a JSON serialization adapter; original SDK loop unchanged",
            "32k native context; fail without transcript truncation on capacity exhaustion",
            "public checksum-pinned GreptimeDB release differs from original benchmark source build",
            "Raw versus LogAgent only; no Split or Semantic Graph treatment",
            "case-level private scoring follows four sealed predictions; no trajectory-based code changes",
            "public strict diagnosis rescore after all 56 cells; private query payloads are not published"],
        "previous_HF_pilot":"separate experiment; previous predictions and scores are not reused"}
    (root/"protocol.json").write_text(json.dumps(protocol,indent=2))
    with raw_environment(selected, root, binary) as (client, case_input, audit):
        (root/"case_input.json").write_text(case_input.model_dump_json(indent=2))
        prepare_input(selected, ROOT/".cache", root/"input")
        shutil.copyfile(ROOT/"configs/hypothesis.yaml",root/"policy.yaml")
        print(f"[HF source/storage preflight] {name} PASS",flush=True)
        if args.preflight_only:
            return
        subprocess.run([sys.executable,"-m","logagent_bench.hf_loop_worker","--run-root",str(root),
            "--model",str(ROOT/".cache/hf-model"/MODEL["filename"]),"--endpoint",client.endpoint],check=True)
    if code_hashes()!=protocol["files_sha256"]:
        raise RuntimeError("Frozen source changed during inference")
    sealed=json.loads((root/"sealed_private_predictions.json").read_text())
    if len(sealed)!=4:
        raise RuntimeError("Incomplete case schedule; scoring is prohibited")
    private_paths=sorted((root/"private/predictions").glob("*.json"))
    if {path.name:digest(path) for path in private_paths} != sealed:
        raise ValueError("Sealed prediction drift before case scoring")
    # All four cells finished. Scoring fixtures only enter this control process
    # now, not the model/selector workers. No scoring feedback returns to them.
    from agent_rca_bench.contracts import AgentRun,ApiTransport
    from agent_rca_bench.datasets.openrca2_transfer import TransferCaseSpec
    from agent_rca_bench.transfer_scorer import evaluate_transfer_run
    spec=TransferCaseSpec.model_validate({key:value for key,value in selected.items() if key!="dataset"})
    artifact=ROOT/".runs/public-hf-loop-case"
    artifact.mkdir(parents=True,exist_ok=False)
    for path in private_paths:
        record=json.loads(path.read_text())
        evaluation=evaluate_transfer_run(AgentRun.model_validate(record["run"]),spec,
            expected_model=MODEL["repo_id"], expected_transport=ApiTransport.ANTHROPIC_MESSAGES,
            expected_reasoning_effort=None,expected_max_output_tokens=CONFIG["max_output_tokens"],
            max_tool_calls=CONFIG["max_tool_calls"]).model_dump(mode="json")
        value=sanitize(record,evaluation,path.name,sealed)
        (artifact/path.name).write_text(json.dumps(value,indent=2))
    (artifact/"protocol.json").write_text(json.dumps(protocol,indent=2))
    (artifact/"preflight.json").write_text(json.dumps({"gates":audit["gates"],
        "binary_sha256":audit["binary_sha256"],"usage_telemetry_enabled":False,
        "private_audit_sha256":digest(root/"private/environment_audit.json")},indent=2))
    public_sealed={path.name:digest(path) for path in artifact.glob("*.json")}
    (artifact/"sealed_artifact.json").write_text(json.dumps(public_sealed,indent=2))
    print(f"[HF case sealed] {name} 4 completed cells; no scores displayed",flush=True)


if __name__ == "__main__":
    main()
