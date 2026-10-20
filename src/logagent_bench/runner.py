"""Freeze protocol -> infer in isolated processes -> seal -> offline score."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .adapter import ALLOWED_OPENRCA2, ALLOWED_RCA100
from .datasets import BENCHMARK_REVISION, ROOT, cohort, digest
from .scoring import aggregate, score_case


def freeze_protocol(config: Path) -> dict:
    paths = sorted((ROOT / "src" / "logagent_bench").glob("*.py")) + [config]
    hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    return {"schema_version": 1, "implementation": "OpenRCA adaptation of LogAgent architecture",
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "benchmark_revision": BENCHMARK_REVISION, "files_sha256": hashes,
            "protocol_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
            "label_access": "inference subprocess blocks fixture/metadata reads",
            "post_score_tuning": False, "llm_used": False,
            "adaptations": ["dataset-provided baseline/incident windows", "equal chronological T1-T4 segments",
                            "telemetry-derived call/hosting ontology", "OpenRCA physical-mechanism hypotheses",
                            "no synthetic Jennifer SQL profiles", "Top-1 evidence-scored Thread"],
            "metric": "strict structured diagnosis agreement; not the upstream Capability index",
            "denominator": "all selected cases; abstentions and runner failures count as incorrect"}


def prepare_input(case: dict, cache: Path, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "telemetry"
    target.mkdir(exist_ok=True)
    names = ALLOWED_OPENRCA2 if case["dataset"] == "openrca2" else ALLOWED_RCA100
    for filename in sorted(names):
        source = cache / case["opaque_case_id"] / "telemetry" / filename
        if digest(source) != case["source_files_sha256"][filename]:
            raise ValueError("Source changed after download verification")
        path = target / filename
        if path.exists():
            if digest(path) != digest(source):
                raise ValueError("Prepared telemetry changed")
            continue
        os.link(source, path)
    public_context = {"case_id": case["opaque_case_id"], "dataset": case["dataset"],
                      "normal_window": case["normal_window"], "abnormal_window": case["abnormal_window"]}
    (destination / "case.json").write_text(json.dumps(public_context, indent=2))


def run(cache: Path, run_root: Path, output: Path, config: Path, repetitions: int = 2):
    if not 1 <= repetitions <= 5:
        raise ValueError("repetitions must be 1..5")
    run_root.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    if (run_root / "protocol.json").exists():
        raise FileExistsError("Use a fresh run root; previous measurements must not be overwritten")
    protocol = freeze_protocol(config)
    (run_root / "protocol.json").write_text(json.dumps(protocol, indent=2))
    cases = cohort()
    for case in cases:
        prepare_input(case, cache, run_root / "inputs" / case["opaque_case_id"])
    records = []
    sealed = []
    for case in cases:
        case_id = case["opaque_case_id"]
        for repetition in range(repetitions):
            path = run_root / "predictions" / f"{case_id}-rep{repetition}.json"
            started = time.perf_counter()
            env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONHASHSEED": "0"}
            completed = subprocess.run([sys.executable, "-m", "logagent_bench.worker", "--input",
                str((run_root / "inputs" / case_id).resolve()), "--config", str(config.resolve()),
                "--output", str(path.resolve())], env=env, text=True, capture_output=True, timeout=300)
            elapsed = time.perf_counter() - started
            if completed.returncode:
                path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps({"case_id": case_id, "diagnosis": None, "runner_error": completed.stderr[-4000:]}, indent=2))
            result = json.loads(path.read_text())
            sealed.append({"case_id": case_id, "repetition": repetition, "sha256": digest(path)})
            records.append({"case_id": case_id, "dataset": case["dataset"], "repetition": repetition,
                            "elapsed_seconds": round(elapsed, 6), "prediction_sha256": digest(path),
                            "prediction": result})
            print(f"[inference] {case_id} rep={repetition} candidates={result.get('candidate_count',0)} status={result.get('status', 'ERROR')} elapsed={elapsed:.2f}s", flush=True)
    # Seal every prediction before scoring reads expected answers. Configuration
    # or implementation drift invalidates this run instead of silently rescoring.
    (run_root / "sealed_predictions.json").write_text(json.dumps(sealed, indent=2))
    if freeze_protocol(config)["protocol_sha256"] != protocol["protocol_sha256"]:
        raise RuntimeError("Code or policy changed during inference")
    expected_by_id = {c["opaque_case_id"]: c for c in cases}
    for record in records:
        record["score"] = score_case(record["prediction"], expected_by_id[record["case_id"]])
    by_case = {}
    for record in records:
        # Timing is outside prediction files, so exact hashes test determinism.
        by_case.setdefault(record["case_id"], []).append(record["prediction_sha256"])
    audit = json.loads((cache / "source_audit.json").read_text())
    report = {"schema_version": 1, "protocol": protocol, "repetitions": repetitions,
              "independent_cases": len(cases), "runs": len(records),
              "deterministic_repetitions": all(len(set(v)) == 1 for v in by_case.values()),
              "source_audit": {k: audit[k] for k in ("expected_files", "verified_files", "errors")},
              "summary": aggregate(records), "records": records,
              "limitations": ["14 selected cases, not the complete OpenRCA2 dataset",
                              "new architecture port, not the original production binary",
                              "rules fixed before scoring, but adapted with knowledge of public dataset schema and fault taxonomy",
                              "no upstream provider loop, SQL citation verifier, or Capability score reproduced",
                              "source-native telemetry availability limits which mechanisms can be established"]}
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2))
    (output / "source_audit.json").write_text(json.dumps(audit, indent=2))
    render_markdown(report, output / "RESULTS.md")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2), flush=True)
    return report


def render_markdown(report, path):
    summary = report["summary"]
    lines = ["# LogAgent architecture port — measured results", "",
             "This is an OpenRCA-specific implementation of the uploaded architecture, not a rerun of its production binary.", "",
             f"Protocol SHA256: `{report['protocol']['protocol_sha256']}`", "",
             f"Independent cases: {report['independent_cases']}; executions: {report['runs']}; deterministic repeats: {report['deterministic_repetitions']}.", "",
             "| Cohort / mechanism | Correct | Cases | Strict diagnosis accuracy | Location correct |", "|---|---:|---:|---:|---:|"]
    for name, row in summary.items():
        lines.append(f"| {name} | {row['correct']} | {row['independent_cases']} | {100*row['accuracy']:.2f}% | {row['location_correct']} |")
    interval = summary["all"]["accuracy_wilson_95"]
    lines += ["", f"Wilson 95% interval on the {report['independent_cases']} independent cases: {100*interval[0]:.2f}%–{100*interval[1]:.2f}%.", "",
              "## Case-level results", "", "| Case | Expected mechanism | Predicted mechanism | Correct |", "|---|---|---|---|"]
    for row in report["records"]:
        if row["repetition"]:
            continue
        score = row["score"]
        prediction = score["predicted"] or {}
        lines.append(f"| {row['case_id']} | {score['expected']['mechanism_code']} | {prediction.get('mechanism_code','ABSTAIN')} | {score['diagnosis_correct']} |")
    lines += ["", "## Interpretation limits", ""] + ["- " + x for x in report["limitations"]]
    path.write_text("\n".join(lines) + "\n")
