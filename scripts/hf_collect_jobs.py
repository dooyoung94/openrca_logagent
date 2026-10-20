"""Verify the entire 14-case schedule before consulting the official scorer."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from logagent_bench.datasets import ROOT, BENCHMARK_REVISION, cohort, digest
from logagent_bench.hf_local import CONFIG, MODEL, render_report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifacts", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    cases = cohort()
    records, protocols, seals = [], [], {}
    for case in cases:
        directory = args.artifacts / ("hf-case-"+case["opaque_case_id"].rsplit("-", 1)[-1])
        protocol = json.loads((directory / "protocol.json").read_text())
        assert protocol["configuration"] == CONFIG and protocol["model"] == MODEL
        assert protocol["source_commit"] == os.environ["GITHUB_SHA"]
        assert protocol["source_files_sha256"] == case["source_files_sha256"]
        assert protocol["cases"][0]["case_id"] == case["opaque_case_id"]
        manifest = json.loads((directory / "sealed_predictions.json").read_text())
        expected = {(arm, repetition) for arm in CONFIG["arms"] for repetition in range(2)}
        actual = set()
        for filename, expected_hash in manifest.items():
            path = directory / filename
            assert digest(path) == expected_hash
            prediction = json.loads(path.read_text())
            assert prediction["case_id"] == case["opaque_case_id"] and prediction["dataset"] == case["dataset"]
            assert prediction["seed"] == CONFIG["seeds"][prediction["repetition"]]
            assert prediction["llm_used"] is True
            actual.add((prediction["arm"], prediction["repetition"]))
            records.append({**prediction, "prediction_sha256": expected_hash})
            seals[filename] = expected_hash
        assert actual == expected and len(manifest) == 4
        protocols.append(protocol)
    assert len(records) == 56 and len(seals) == 56
    for key in ["files_sha256", "orchestration_sha256"]:
        assert all(p[key] == protocols[0][key] for p in protocols)
    args.output.mkdir(parents=True, exist_ok=False)
    # All 56 predictions have been hash-verified before this import and any
    # correctness evaluation. Case jobs never run a scorer.
    (args.output / "sealed_predictions.json").write_text(json.dumps(seals, indent=2))
    from logagent_bench.canonical_scoring import official_diagnosis_score
    references = {c["opaque_case_id"]: c for c in cases}
    for record in records:
        try:
            record["score"] = official_diagnosis_score(record, references[record["case_id"]])
        except Exception as error:
            record["score"] = {"diagnosis_correct": False, "location_match": False,
                "scoring_error": type(error).__name__+": "+str(error)[:300]}
    summary = {}
    for dataset in ["openrca2", "rca100", "all"]:
        summary[dataset] = {}
        for arm in CONFIG["arms"]:
            rows = [r for r in records if r["arm"] == arm and (dataset == "all" or r["dataset"] == dataset)]
            correct = sum(r["score"]["diagnosis_correct"] for r in rows)
            summary[dataset][arm] = {"independent_cases": len(rows)//2, "executions": len(rows),
                "correct_executions": correct, "diagnosis_accuracy": correct/len(rows),
                "location_correct_executions": sum(r["score"]["location_match"] for r in rows),
                "abstentions": sum(r["diagnosis"] is None and not r.get("runner_error") for r in rows),
                "runner_errors": sum(bool(r.get("runner_error")) for r in rows),
                "scoring_errors": sum(bool(r["score"].get("scoring_error")) for r in rows),
                "prompt_tokens": sum(r.get("usage", {}).get("prompt_tokens", 0) for r in rows),
                "completion_tokens": sum(r.get("usage", {}).get("completion_tokens", 0) for r in rows),
                "inference_seconds": round(sum(r["elapsed_seconds"] for r in rows), 3)}
    report = {"experiment": "hf-actions-parallel-v1", "status": "COMPLETED", "llm_calls": 56,
        "model": MODEL, "configuration": CONFIG, "benchmark_revision": BENCHMARK_REVISION,
        "source_commit": os.environ["GITHUB_SHA"], "github_run_id": os.environ["GITHUB_RUN_ID"],
        "summary_by_dataset": summary, "protocols_by_case": protocols, "records": records,
        "provider_api_fee": 0, "cost_note": "Public model local inference on standard public-repository Actions runners; not a paid model API.",
        "limitations": ["one small quantized HF model; not one of the six historical API configurations",
            "same 14 selected cases; bounded telemetry summaries; no tool-query investigation",
            "original scorer diagnosis fields only; no SQL grounding/Capability claim",
            "2 repetitions do not create 28 independent cases",
            "case-parallel CPU execution; latency is not comparable to the original agent experiment"]}
    (args.output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    (args.output / "RESULTS.md").write_text(render_report(report))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
