"""Matched upstream replication plus a LogAgent navigation-tool treatment.

No provider is called until dependencies, credentials, pricing, source storage
audits, an explicit paid flag and a bounded batch have all been checked.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
import uuid
from pathlib import Path

import yaml

from .adapter import load_bundle
from .datasets import ROOT, OPENRCA2_REVISION, cohort, digest
from .engine import evaluate
from .experiment import environment_check, canonical_sha
from .runner import prepare_input
from .upstream_bridge import run_logagent_agent


def materialize_upstream_cache(cache, root):
    for case in cohort():
        folder = root / ("openrca2/cases" if case["dataset"] == "openrca2" else "rca100") / case["source_case"]
        folder.mkdir(parents=True, exist_ok=True)
        for name, expected in case["source_files_sha256"].items():
            category = "telemetry" if (cache / case["opaque_case_id"] / "telemetry" / name).exists() else "metadata"
            source = cache / case["opaque_case_id"] / category / name
            if digest(source) != expected:
                raise ValueError("Pinned telemetry hash mismatch before LLM preflight")
            target = folder / name
            if not target.exists():
                os.link(source, target)
            elif digest(target) != expected:
                raise ValueError("Upstream source cache drift")
    manifest = root / "openrca2/manifest.jsonl"
    if not manifest.exists():
        url = f"https://huggingface.co/datasets/anon-ops/ops-lite/resolve/{OPENRCA2_REVISION}/manifest.jsonl"
        with urllib.request.urlopen(url, timeout=60) as response:
            manifest.write_bytes(response.read())
    return manifest


def public_record(item, cell, metrics):
    run = item["run"]
    diagnosis = run.get("diagnosis")
    kept = None if diagnosis is None else {k: diagnosis.get(k) for k in
        ["causal_scope", "causal_component", "edge_source", "edge_destination", "mechanism_code", "fault_category", "alternative_candidates"]}
    native_usage = [r.get("usage") for r in run.get("responses", []) if isinstance(r, dict) and isinstance(r.get("usage"), dict)]
    return {**cell, "evaluation": item["evaluation"], "diagnosis": kept,
            "elapsed_seconds": run["elapsed_seconds"], "architecture": metrics,
            "usage": run["usage"], "native_usage": native_usage,
            "cost": None, "cost_status": "requires cache-aware interpretation of native provider usage; missing fields are not zero",
            "database_load": item["database_load"], "tool_calls": len(run["tool_calls"]),
            "runner_error": bool(run.get("error")), "tool_budget_exhausted": run["tool_budget_exhausted"],
            "source_semantic_sha256": item["source_semantic_sha256"],
            "private_record_sha256": canonical_sha(item)}


def run_matched(plan, args):
    if not args.confirm_paid_api:
        raise ValueError("Paid API execution requires --confirm-paid-api after reviewing the exact bounded batch")
    if not args.max_new_runs or args.max_new_runs < 1 or not args.run_root:
        raise ValueError("Set --run-root and positive --max-new-runs; full-cost implicit execution is prohibited")
    check = environment_check(plan, args.greptimedb_repo, args.pricing_snapshot)
    if check["status"] != "ENVIRONMENT_READY_FOR_SOURCE_PREFLIGHT":
        return {**plan, "status": "BLOCKED_BEFORE_MODEL_CALLS", "preflight": check, "provider_calls_made": 0}
    # All imports below are upstream pinned code; its original source-fidelity
    # checks and official diagnosis/citation/evidence scorer remain unchanged.
    import agent_rca_bench.agent as upstream_agent
    from agent_rca_bench.transfer_protocol import load_transfer_protocol
    from agent_rca_bench.transfer_formal import (TransferEnvironmentConfig, prepare_transfer_environment,
                                               execute_transfer_cell, source_semantic_sha256)

    root = args.run_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "ACTIVE.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise RuntimeError("Another or interrupted runner owns this root; inspect its journal before recovery")
    os.close(descriptor)
    try:
        plan_path = root / "frozen_plan.json"
        if plan_path.exists():
            frozen = json.loads(plan_path.read_text())
            if frozen["protocol_sha256"] != plan["protocol_sha256"]:
                raise ValueError("Resume protocol differs; previous records cannot be mixed")
        else:
            plan_path.write_text(json.dumps(plan, indent=2))
        report_path = root / "report.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {**plan, "records": []}
        completed = {r["cell_index"] for r in report["records"]}
        pending = [c for c in plan["schedule"] if c["cell_index"] not in completed][:args.max_new_runs]
        for cell in pending:
            active = root / "journal" / f"cell-{cell['cell_index']:04d}.json"
            if active.exists() and json.loads(active.read_text()).get("status") == "STARTED":
                raise RuntimeError("Unresolved paid cell; automatic retry would risk duplicate billing")
        cache = ROOT / ".cache"
        source_root = root / "source_cache"
        manifest = materialize_upstream_cache(cache, source_root)
        loaded = {name: load_transfer_protocol(ROOT / "fixtures/upstream" / name) for name in
                  {m["upstream_protocol"] for m in plan["models"]}}
        cohort_spec = next(iter(loaded.values()))[1]
        specifications = {s.opaque_case_id: s for s in cohort_spec.selected_cases}
        model_config = {m["model"]: m for m in plan["models"]}
        for case_id in dict.fromkeys(c["case_id"] for c in pending):
            cells = [c for c in pending if c["case_id"] == case_id]
            protocol = loaded[model_config[cells[0]["model"]]["upstream_protocol"]][0]
            config = TransferEnvironmentConfig(cache_dir=source_root / "openrca2", manifest_path=manifest,
                greptimedb_repo=args.greptimedb_repo, run_dir=root / "environments" / f"{case_id}-{uuid.uuid4().hex[:8]}",
                database=case_id.replace("-", "_"), node_cache_dir=source_root / "rca100")
            own_case = next(c for c in cohort() if c["opaque_case_id"] == case_id)
            isolated = root / "inputs" / case_id
            prepare_input(own_case, cache, isolated)
            # This context audits protocol ingestion, schema, identity, source
            # mechanism transitions, trace visibility and split-stack fidelity
            # before yielding; environment failures are never model failures.
            with prepare_transfer_environment(protocol, specifications[case_id], config) as prepared:
                source_hash = source_semantic_sha256(prepared.source_audit)
                for cell in cells:
                    active = root / "journal" / f"cell-{cell['cell_index']:04d}.json"
                    active.parent.mkdir(exist_ok=True)
                    active.write_text(json.dumps({"status": "STARTED", "cell": cell}))
                    protocol = loaded[model_config[cell["model"]]["upstream_protocol"]][0]
                    metrics = {"architecture_build_seconds": 0.0, "architecture_tool_calls": 0}
                    def loader():
                        return evaluate(load_bundle(isolated), yaml.safe_load((ROOT / "configs/hypothesis.yaml").read_text()))
                    fn = upstream_agent.run_agent
                    if cell["arm"] == "logagent":
                        def fn(gateway, case_input, visibility, **kwargs):
                            return run_logagent_agent(gateway, case_input, visibility, candidate_loader=loader, metrics=metrics, **kwargs)
                    official_cell = {**cell, "visibility": "raw" if cell["arm"] == "logagent" else cell["arm"]}
                    item = execute_transfer_cell(protocol, prepared, official_cell, source_semantic_hash=source_hash, run_agent_fn=fn)
                    private = root / "private" / f"cell-{cell['cell_index']:04d}.json"
                    private.parent.mkdir(exist_ok=True)
                    private.write_text(json.dumps(item, indent=2))
                    record = public_record(item, cell, metrics)
                    report["records"].append(record)
                    report["completed_cells"] = len(report["records"])
                    report["status"] = "COMPLETED" if report["completed_cells"] == report["expected_cells"] else "PARTIAL_NO_COMPARATIVE_CLAIM"
                    from .llm_summary import summarize
                    report["summary_by_dataset"] = summarize(report)
                    report_path.write_text(json.dumps(report, indent=2))
                    active.write_text(json.dumps({"status": "COMPLETED", "cell": cell, "private_sha256": digest(private)}))
                    print(f"[LLM] {cell['model']} {case_id} {cell['arm']} rep={cell['repetition']} correct={record['evaluation']['diagnosis_correct']}", flush=True)
        return report
    finally:
        lock.unlink(missing_ok=True)
