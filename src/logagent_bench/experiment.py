"""A provider-free plan and guarded entry point for matched LLM replication."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .datasets import BENCHMARK_REVISION, ROOT, cohort, digest
from .candidates import CANDIDATE_LIMIT

ARMS = ("split_pillars", "raw", "semantic_graph", "logagent")
PROTOCOL_FILES = ("transfer-v34-protocol.json", "transfer-v34-two-model-extension-protocol.json")
KEYS = {"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
        "zhipu-bigmodel": "BIGMODEL_API_KEY", "google": "GEMINI_API_KEY", "alibaba-cloud-model-studio": "DASHSCOPE_API_KEY"}


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def models():
    values = []
    for filename in PROTOCOL_FILES:
        doc = json.loads((ROOT / "fixtures/upstream" / filename).read_text())
        if (doc["max_tool_calls"], doc["max_turns"], doc["repetitions_per_model"]) != (48, 58, 2):
            raise ValueError("Upstream budget drift")
        for model in doc["models"]:
            values.append({**model, "upstream_protocol": filename})
    return values


def make_plan(selected_models=None):
    roster = models()
    if selected_models:
        known = {m["model"] for m in roster}
        if set(selected_models) - known:
            raise ValueError("Unknown model; substitutions require a new protocol")
        roster = [m for m in roster if m["model"] in selected_models]
    selected_cases = cohort()
    case_ids = [c["opaque_case_id"] for c in selected_cases]
    case_datasets = {c["opaque_case_id"]: c["dataset"] for c in selected_cases}
    schedule = []
    for case_index, case_id in enumerate(case_ids):
        for model_index, model in enumerate(roster):
            for repetition in range(2):
                offset = (case_index + model_index + repetition) % len(ARMS)
                for arm in ARMS[offset:] + ARMS[:offset]:
                    schedule.append({"cell_index": len(schedule), "case_id": case_id, "dataset": case_datasets[case_id],
                                     "model": model["model"], "repetition": repetition, "arm": arm})
    binding = {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted((ROOT / "src/logagent_bench").glob("*.py"))}
    binding["configs/hypothesis.yaml"] = digest(ROOT / "configs/hypothesis.yaml")
    for p in sorted((ROOT / "fixtures").rglob("*.json")):
        binding[p.relative_to(ROOT).as_posix()] = digest(p)
    runtime = {}
    for package in ("agent-rca-bench", "openai", "anthropic", "pyarrow", "pydantic", "sqlglot"):
        try:
            runtime[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            runtime[package] = None
    protocol = {"revision": "logagent-matched-llm-v2", "upstream_revision": BENCHMARK_REVISION,
                "models": roster, "arms": list(ARMS), "repetitions": 2, "max_tool_calls": 48,
                "max_turns": 58, "query_timeout_seconds": 120, "runtime_package_versions": runtime,
                "provider_default_sampling": True, "no_seed_sent": True,
                "provider_concurrency": 1, "case_independent_unit": True,
                "arm_order": "deterministic counterbalanced rotation by case/model/repetition",
                "new_arm": "LogAgent preselects ranked candidates before the unmodified upstream Raw LLM loop",
                "candidate_limit": CANDIDATE_LIMIT,
                "candidate_selection": "same frozen Python engine/policy; telemetry-only isolated subprocess; no Top-1 handoff",
                "candidate_shortlist_policy": "navigation only; LLM may reject or investigate outside the shortlist; empty shortlist does not force abstention",
                "candidate_timing": "preselection is outside the 48 investigation tool calls; included in pipeline elapsed time and separately recorded",
                "identical_raw_graph_logagent_system_prompt": True,
                "identical_raw_logagent_investigation_tools": True,
                "incident_prompt": "original bytes unchanged as prefix; LogAgent arm appends candidate navigation context only",
                "same_upstream_runner_output_schema_validation_and_scorer": True,
                "invalid_final_output_policy": "unchanged upstream in-loop validation feedback within 58 turns; no post-run repairs or retrying scored cells",
                "primary_comparison": {"baseline": "raw", "treatment": "logagent", "metric": "diagnosis_correct"},
                "secondary_comparison": {"baseline": "semantic_graph", "treatment": "logagent"},
                "primary_test": "paired sign test on per-case mean correctness; Holm across selected models",
                "secondary_efficiency_family": "calls and input tokens; eligible cases only; Holm separately",
                "missing_and_failed_cells": "included as failures, never silently dropped",
                "historical_public_scores": "reference only; not matched samples",
                "policy_status": "v2 development protocol after the HF summary pilot; engine and hypothesis policy unchanged; not an unseen-case confirmatory result",
                "answer_semantics": "unchanged upstream Top-1 scorer; declared identity aliases and alternative mechanisms accepted; alternative_candidates retained but not promoted to correct answers",
                "files_sha256": binding}
    targets = {dataset: {"cases": sum(c["dataset"] == dataset for c in selected_cases),
                         "models": len(roster), "repetitions": 2,
                         "runs_per_arm": sum(c["dataset"] == dataset for c in selected_cases) * len(roster) * 2}
               for dataset in sorted(set(case_datasets.values()))}
    plan = {"schema_version": 1, "status": "PLANNED_NOT_EXECUTED", "protocol": protocol,
            "protocol_sha256": canonical_sha(protocol), "independent_cases": len(case_ids),
            "expected_cells": len(schedule), "completed_cells": 0, "models": roster,
            "schedule": schedule, "matched_denominators": targets, "accuracy": None, "cost": None}
    from .llm_summary import summarize
    plan["summary_by_dataset"] = summarize(plan)
    return plan


def environment_check(plan, greptimedb_repo=None, pricing_snapshot=None):
    sdk = importlib.util.find_spec("agent_rca_bench") is not None
    credentials = {m["model"]: bool(os.environ.get(KEYS[m["provider"]])) for m in plan["models"]}
    checks = {"pinned_upstream_sdk_installed": sdk, "docker_cli_present": shutil.which("docker") is not None,
              "provider_credentials_present": all(credentials.values()),
              "greptimedb_revision_matches": False, "release_binary_exists": False,
              "pricing_snapshot_supplied": pricing_snapshot is not None and pricing_snapshot.is_file()}
    sdk_commit = None
    if sdk:
        direct = importlib.metadata.distribution("agent-rca-bench").read_text("direct_url.json")
        if direct:
            sdk_commit = json.loads(direct).get("vcs_info", {}).get("commit_id")
        checks["pinned_upstream_sdk_installed"] = sdk_commit == BENCHMARK_REVISION
    if greptimedb_repo and greptimedb_repo.is_dir():
        head = subprocess.run(["git", "-C", str(greptimedb_repo), "rev-parse", "HEAD"], capture_output=True, text=True)
        checks["greptimedb_revision_matches"] = head.returncode == 0 and head.stdout.strip() == "15317a131bc63a680d3571e5f681bee4acc86228"
        checks["release_binary_exists"] = (greptimedb_repo / "target/release/greptime").is_file()
    if any(m["provider"] == "alibaba-cloud-model-studio" for m in plan["models"]):
        checks["dashscope_runtime_endpoint_present"] = bool(os.environ.get("DASHSCOPE_BASE_URL"))
    # A dated user-reviewed snapshot is mandatory. Unknown cache usage remains
    # unknown; this check never invents historical or current rates.
    if checks["pricing_snapshot_supplied"]:
        pricing = json.loads(pricing_snapshot.read_text())
        checks["pricing_snapshot_covers_models"] = bool(pricing.get("verified_at")) and all(m["model"] in pricing.get("models", {}) for m in plan["models"])
    return {"status": "ENVIRONMENT_READY_FOR_SOURCE_PREFLIGHT" if all(checks.values()) else "BLOCKED_BEFORE_MODEL_CALLS",
            "checks": checks, "credential_presence": credentials, "upstream_sdk_commit": sdk_commit,
            "provider_calls_made": 0, "model_availability_verified": False,
            "source_storage_gates": "must pass for every case before any paid cell"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["plan", "doctor", "run", "compare"])
    p.add_argument("--models", nargs="+")
    p.add_argument("--output", type=Path, default=ROOT / "experiments/llm_plan.json")
    p.add_argument("--greptimedb-repo", type=Path)
    p.add_argument("--pricing-snapshot", type=Path)
    p.add_argument("--run-root", type=Path)
    p.add_argument("--confirm-paid-api", action="store_true")
    p.add_argument("--max-new-runs", type=int)
    p.add_argument("--input", type=Path)
    args = p.parse_args()
    if args.command == "compare":
        from .paired_stats import compare_report
        result = compare_report(json.loads(args.input.read_text()))
    else:
        plan = make_plan(args.models)
        if args.command == "doctor":
            result = environment_check(plan, args.greptimedb_repo, args.pricing_snapshot)
        elif args.command == "run":
            from .llm_runner import run_matched
            result = run_matched(plan, args)
        else:
            result = plan
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps({k:v for k,v in result.items() if k not in {"schedule", "protocol", "records"}}, indent=2))
    if args.command == "doctor" and result["status"] == "BLOCKED_BEFORE_MODEL_CALLS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
