"""Verify all 56 sealed HF investigations, then rescore and aggregate."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from logagent_bench.datasets import cohort, digest
from logagent_bench.hf_environment import DATABASE
from logagent_bench.hf_loop import CONFIG, EXPERIMENT, MODEL


def collect(artifacts, output, source_commit, source_run_id):
    references = {case["opaque_case_id"]:case for case in cohort()}
    protocols, records, seen, seals = [], [], set(), {}
    source_bindings = None
    for folder in sorted(artifacts.iterdir()):
        if not folder.is_dir():
            continue
        sealed = json.loads((folder/"sealed_artifact.json").read_text())
        if any(digest(folder/name)!=checksum for name,checksum in sealed.items()):
            raise ValueError("Case artifact checksum mismatch")
        protocol = json.loads((folder/"protocol.json").read_text())
        if (protocol["experiment"]!=EXPERIMENT or protocol["configuration"]!=CONFIG
                or protocol["model"]!=MODEL or protocol["database"]!=DATABASE
                or protocol["source_commit"]!=source_commit
                or str(protocol["github_run_id"])!=str(source_run_id)):
            raise ValueError("Mixed or drifted HF protocols")
        binding = (protocol["files_sha256"],protocol["orchestration_sha256"],protocol["binary_sha256"],protocol["runtime"]["packages"])
        if source_bindings is None:
            source_bindings=binding
        elif binding!=source_bindings:
            raise ValueError("Source code or binary differs across cases")
        case_id=protocol["case"]["case_id"]
        reference=references[case_id]
        if protocol["source_files_sha256"]!=reference["source_files_sha256"]:
            raise ValueError("Frozen source files mismatch")
        preflight=json.loads((folder/"preflight.json").read_text())
        if preflight["gates"]["all_passed"] is not True or preflight["usage_telemetry_enabled"] is not False:
            raise ValueError("Case did not pass source/storage preflight")
        predictions=[folder/name for name in sealed if name not in ("protocol.json","preflight.json")]
        if len(predictions)!=4:
            raise ValueError("Incomplete four-cell artifact")
        for path in predictions:
            row=json.loads(path.read_text())
            key=(row["case_id"],row["arm"],row["repetition"])
            if (key in seen or row["case_id"]!=case_id or row["arm"] not in CONFIG["arms"]
                    or row["repetition"] not in (0,1)
                    or row["seed"]!=CONFIG["seeds"][row["repetition"]]
                    or row["dataset"]!=reference["dataset"]):
                raise ValueError("Duplicate, missing or unscheduled cell")
            seen.add(key)
            records.append(row)
            seals[path.name]=digest(path)
        protocols.append(protocol)
    expected={(case_id,arm,repetition) for case_id in references for arm in CONFIG["arms"] for repetition in range(2)}
    if seen!=expected or len(protocols)!=14:
        raise ValueError("Do not report accuracy on an incomplete cohort")
    output.mkdir(parents=True,exist_ok=False)
    (output/"sealed_predictions.json").write_text(json.dumps(seals,indent=2))
    # Every model output and the complete schedule have been verified before
    # the independent primary diagnosis scorer is imported.
    from logagent_bench.canonical_scoring import official_diagnosis_score
    for row in records:
        score=official_diagnosis_score(row,references[row["case_id"]])
        if score["diagnosis_correct"] != row["upstream_case_evaluation"]["diagnosis_correct"]:
            raise ValueError("Full SDK case score and independent diagnosis rescore disagree")
        row["score"]=score
    summary={}
    for dataset in ("openrca2","rca100","all"):
        summary[dataset]={}
        for arm in CONFIG["arms"]:
            rows=[row for row in records if row["arm"]==arm and (dataset=="all" or row["dataset"]==dataset)]
            correct=sum(row["score"]["diagnosis_correct"] for row in rows)
            summary[dataset][arm]={
                "independent_cases":len(rows)//2,"executions":len(rows),
                "correct_executions":correct,"diagnosis_accuracy":correct/len(rows),
                "location_correct_executions":sum(row["score"]["location_match"] for row in rows),
                "full_upstream_successes":sum(row["upstream_case_evaluation"]["success"] for row in rows),
                "auditable_completions":sum(row["upstream_case_evaluation"]["auditable_completion"] for row in rows),
                "citations_execution_valid":sum(row["upstream_case_evaluation"]["citations_execution_valid"] for row in rows),
                "runner_errors":sum(row["runner_error"] for row in rows),
                "tool_budget_exhausted":sum(row["tool_budget_exhausted"] for row in rows),
                "cells_with_investigation_tools":sum(bool(row["tool_summary"]) for row in rows),
                "investigation_tool_calls":sum(len(row["tool_summary"]) for row in rows),
                "completed_model_generations":sum(len(row["generation_trace"]) for row in rows),
                "model_generation_attempts":sum(row["provider_invocations"] for row in rows),
                "token_usage_complete":all(row["token_usage_complete"] for row in rows),
                "input_tokens":sum(row["usage"]["input_tokens"] for row in rows),
                "output_tokens":sum(row["usage"]["output_tokens"] for row in rows),
                "pipeline_elapsed_seconds":sum(row["elapsed_seconds"] for row in rows),
            }
    report={"experiment":EXPERIMENT,"status":"COMPLETED","measured_at":datetime.now(timezone.utc).isoformat(),
        "source_commit":source_commit,"source_run_id":str(source_run_id),"configuration":CONFIG,"model":MODEL,
        "database":DATABASE,"independent_cases":14,"completed_cells":56,
        "total_model_forward_calls":sum(len(row["generation_trace"]) for row in records),
        "total_generation_attempts":sum(row["provider_invocations"] for row in records),
        "summary_by_dataset":summary,"protocols":protocols,"records":sorted(records,key=lambda row:(row["case_id"],row["arm"],row["repetition"])),
        "primary_evaluation":"unchanged official diagnosis scorer; case errors remain in the denominator",
        "secondary_evaluation":"full official case scorer after each case's four sealed predictions; query payloads private, not independently reproducible from the public projections",
        "provider_api_fee":0,"cost_note":"Public weights on CPU; infrastructure/electricity cost not estimated",
        "historical_six_model_comparison":"not a matched replication of historical six-model or Graph scores",
        "development_status":"same public cases after previous pilot; no unseen holdout; no post-run answer repair"}
    (output/"results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    lines=["# Hugging Face with the original investigation loop","",
        "Same Qwen3-1.7B Q8 model, real GreptimeDB telemetry queries, 14 independent cases, two arms and two repetitions.","",
        "| Dataset | Raw HF | LogAgent candidates + HF |","|---|---:|---:|"]
    for dataset,arms in summary.items():
        values=[f"{arms[arm]['correct_executions']}/{arms[arm]['executions']} ({100*arms[arm]['diagnosis_accuracy']:.2f}%)" for arm in CONFIG["arms"]]
        lines.append(f"| {dataset} | {' | '.join(values)} |")
    lines += ["",f"Completed investigations: 56. Actual model forward calls: {report['total_model_forward_calls']}.","",
        "The model, local JSON tool serialization, native context and GreptimeDB build differ from the historical six-model experiment. The original runner loop, Raw query tools, final schema, validation feedback and diagnosis scorer are reused.","",
        "Primary accuracy includes runner failures and does not imply grounded evidence. See results.json for citation validity, complete upstream success and actual query usage. Original source telemetry, model responses and private query results are not published."]
    (output/"RESULTS.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(summary,indent=2),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--source-commit",default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--source-run-id",default=os.environ.get("GITHUB_RUN_ID"))
    args=parser.parse_args()
    collect(args.artifacts,args.output,args.source_commit,args.source_run_id)


if __name__=="__main__":
    main()
