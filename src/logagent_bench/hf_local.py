"""Run a public Hugging Face model locally without an API key (separate pilot)."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .datasets import BENCHMARK_REVISION, ROOT, cohort, digest
from .runner import prepare_input

MODEL = {"repo_id": "Qwen/Qwen3-1.7B-GGUF",
         "revision": "90862c4b9d2787eaed51d12237eafdfe7c5f6077",
         "filename": "Qwen3-1.7B-Q8_0.gguf",
         "sha256": "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a"}

CONFIG = {"arms": ["summary_llm", "logagent_llm"], "seeds": [17, 29],
          "temperature": .7, "top_p": .8, "top_k": 20, "min_p": 0,
          "context_tokens": 8192, "max_output_tokens": 384,
          "thinking": False, "grammar": "frozen JSON schema",
          "per_cell_retries": 0, "tools": 0,
          "kv_cache": "exact prompt prefix reused only within the same case; reset between cases",
          "case_order": "frozen opaque ID order; alternating arm order"}


def code_hashes():
    files = sorted((ROOT / "src/logagent_bench").glob("*.py"))+[ROOT / "configs/hypothesis.yaml"]
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in files}


def download_model():
    from huggingface_hub import hf_hub_download
    target = ROOT / ".cache/hf-model"
    path = Path(hf_hub_download(MODEL["repo_id"], MODEL["filename"],
        revision=MODEL["revision"], local_dir=target))
    if digest(path) != MODEL["sha256"]:
        raise ValueError("Public model bytes differ from pinned SHA256")
    print(f"Verified {MODEL['repo_id']} at {MODEL['revision']}")


def run(args):
    model_path = (ROOT / ".cache/hf-model" / MODEL["filename"]).resolve()
    if not model_path.is_file() or digest(model_path) != MODEL["sha256"]:
        raise ValueError("Download and verify the pinned public model first")
    cases = cohort()
    run_root, output = args.run_root.resolve(), args.output.resolve()
    run_root.mkdir(parents=True, exist_ok=False)
    output.mkdir(parents=True, exist_ok=False)
    protocol = {"experiment": "hf-local-summary-pilot-v2", "status": "FROZEN_BEFORE_INFERENCE",
        "frozen_at": datetime.now(timezone.utc).isoformat(), "model": MODEL,
        "configuration": CONFIG, "benchmark_revision": BENCHMARK_REVISION,
        "cases": [{"case_id": c["opaque_case_id"], "dataset": c["dataset"], "ordinal": i}
                  for i, c in enumerate(cases)],
        "files_sha256": code_hashes(),
        "runtime": {"python": platform.python_version(), "cpu_count": os.cpu_count(),
            "llama_cpp_python": importlib.metadata.version("llama-cpp-python"),
            "cpu_only": True, "model_download_bytes": model_path.stat().st_size},
        "scoring": "unchanged upstream evaluate_transfer_run diagnosis fields, after all predictions are sealed",
        "data_boundary": "same 14 selected cases and windows; all 158 source hashes pinned; packets exclude labels",
        "differences_from_original": ["one local Qwen3-1.7B Q8 model replaces no original model",
            "bounded telemetry summaries, not original Raw/Semantic Graph querying",
            "single completion with JSON grammar, no SQL/PromQL investigation loop",
            "8192 context, 384 output tokens, non-thinking; different from original model budgets",
            "seeds 17 and 29; two repetitions, 56 model invocations",
            "candidate hints include evidence-derived architecture analysis beyond bounded summaries",
            "no claims of source citation grounding, Capability score, or six-model equivalence"],
        "post_score_tuning": False}
    (run_root / "protocol.json").write_text(json.dumps(protocol, indent=2))
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONHASHSEED": "0"}
    for case in cases:
        name = case["opaque_case_id"]
        destination = run_root / "inputs" / name
        prepare_input(case, args.cache.resolve(), destination)
        if args.packets_from:
            source = args.packets_from.resolve() / "packets" / (name+".json")
            expected = json.loads((args.packets_from.resolve() / "sealed_packets.json").read_text())
            if digest(source) != expected[source.name]:
                raise ValueError("Previously sealed packet changed")
            target = run_root / "packets" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        else:
            subprocess.run([sys.executable, "-m", "logagent_bench.hf_packet", "--input", str(destination),
                "--config", str(ROOT / "configs/hypothesis.yaml"), "--output", str(run_root / "packets" / (name+".json"))],
                env=env, check=True, timeout=300)
        print("[HF packet] "+name, flush=True)
    packet_hashes = {p.name: digest(p) for p in sorted((run_root / "packets").glob("*.json"))}
    (run_root / "sealed_packets.json").write_text(json.dumps(packet_hashes, indent=2))
    if code_hashes() != protocol["files_sha256"]:
        raise RuntimeError("Implementation drift before inference")
    subprocess.run([sys.executable, "-m", "logagent_bench.hf_worker", "--run-root", str(run_root),
                    "--model", str(model_path)], env=env, check=True)
    if code_hashes() != protocol["files_sha256"]:
        raise RuntimeError("Implementation drift invalidates experiment")
    if {p.name: digest(p) for p in sorted((run_root / "packets").glob("*.json"))} != packet_hashes:
        raise RuntimeError("Evidence packet drift invalidates experiment")
    predictions = sorted(p for p in (run_root / "predictions").glob("*.json") if not p.name.endswith(".response.json"))
    if len(predictions) != len(cases)*len(CONFIG["arms"])*len(CONFIG["seeds"]):
        raise RuntimeError("Incomplete schedule; do not publish completed accuracy")
    sealed = {p.name: digest(p) for p in predictions}
    (run_root / "sealed_predictions.json").write_text(json.dumps(sealed, indent=2))
    # Scorer is imported and expected answers are consulted only after sealing.
    from .canonical_scoring import official_diagnosis_score
    references = {c["opaque_case_id"]: c for c in cases}
    records = []
    for path in predictions:
        prediction = json.loads(path.read_text())
        try:
            score = official_diagnosis_score(prediction, references[prediction["case_id"]])
        except Exception as error:
            score = {"diagnosis_correct": False, "location_match": False,
                     "scoring_error": type(error).__name__+": "+str(error)[:300]}
        records.append({**prediction, "prediction_sha256": sealed[path.name], "score": score})
    summary = {}
    for dataset in ("openrca2", "rca100", "all"):
        summary[dataset] = {}
        for arm in CONFIG["arms"]:
            selected = [r for r in records if r["arm"] == arm and (dataset == "all" or r["dataset"] == dataset)]
            count = len(selected)
            correct = sum(r["score"]["diagnosis_correct"] for r in selected)
            summary[dataset][arm] = {"independent_cases": count//len(CONFIG["seeds"]),
                "executions": count, "correct_executions": correct,
                "diagnosis_accuracy": correct/count,
                "location_correct_executions": sum(r["score"]["location_match"] for r in selected),
                "abstentions": sum(r["diagnosis"] is None and not r.get("runner_error") for r in selected),
                "runner_errors": sum(bool(r.get("runner_error")) for r in selected),
                "scoring_errors": sum(bool(r["score"].get("scoring_error")) for r in selected),
                "prompt_tokens": sum(r.get("usage", {}).get("prompt_tokens", 0) for r in selected),
                "completion_tokens": sum(r.get("usage", {}).get("completion_tokens", 0) for r in selected),
                "inference_seconds": round(sum(r["elapsed_seconds"] for r in selected), 3)}
    report = {"experiment": protocol["experiment"], "status": "COMPLETED",
        "llm_calls": len(records), "protocol": protocol, "summary_by_dataset": summary,
        "packet_hashes": packet_hashes,
        "context_preflight": json.loads((run_root / "context_preflight.json").read_text()),
        "records": records, "provider_api_fee": 0,
        "cost_note": "Local inference; compute/electricity cost not estimated. No hosted provider API used.",
        "limitation": "Small selected public cohort, no untouched holdout; source SQL evidence grounding not evaluated."}
    (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    (output / "protocol.json").write_text(json.dumps(protocol, indent=2)+"\n")
    (output / "RESULTS.md").write_text(render_report(report))
    print(json.dumps(summary, indent=2), flush=True)


def render_report(report):
    lines = ["# Hugging Face local pilot: actual LLM measurements", "",
        "This is a separate Qwen3-1.7B Q8 summary-input experiment, not a replication of the six published model configurations.", "",
        "Same 14 end-to-end cases, two arms and two seeded repetitions: **56 actual model invocations**.", "",
        "| Dataset | Independent cases | Summary + LLM | LogAgent hints + LLM |", "|---|---:|---:|---:|"]
    for dataset, arms in report["summary_by_dataset"].items():
        a, b = arms["summary_llm"], arms["logagent_llm"]
        lines.append(f"| {dataset} | {a['independent_cases']} | {a['correct_executions']}/{a['executions']} ({100*a['diagnosis_accuracy']:.2f}%) | {b['correct_executions']}/{b['executions']} ({100*b['diagnosis_accuracy']:.2f}%) |")
    lines += ["", "Accuracy uses all executions including invalid answers, abstentions, output-budget failures and runner errors. Repetitions do not increase the number of independent cases.", "",
        "The original scorer evaluates diagnosis fields only. Summary evidence IDs are not original SQL citations and do not establish original grounding or efficiency eligibility.", "",
        "Both arms receive identical common telemetry summaries; the LogAgent arm additionally receives fallible candidates from the fixed architecture port. Bounded summaries omit observations. The extra hints can contain analysis of those omitted observations, so this measures the complete added architecture interface rather than isolating LLM reasoning.", "",
        "Model weights, source files, prompt/code/packet hashes, sampling parameters and per-run usage are recorded in results.json. Private telemetry packets and model response text are not published.", "",
        "The 6-model historical denominators (120 OpenRCA2 / 48 RCA100 per arm) must not be substituted for this one-model pilot's 20 / 8 executions. No superiority or generalization inference is made from this public selected cohort.", ""]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["download-model", "run"])
    p.add_argument("--cache", type=Path, default=ROOT / ".cache")
    p.add_argument("--run-root", type=Path, default=ROOT / ".runs/hf-local-v2")
    p.add_argument("--output", type=Path, default=ROOT / "results/hf-local-v2")
    p.add_argument("--packets-from", type=Path, help="Reuse hash-sealed telemetry packets, without modifying their facts")
    args = p.parse_args()
    download_model() if args.command == "download-model" else run(args)


if __name__ == "__main__":
    main()
