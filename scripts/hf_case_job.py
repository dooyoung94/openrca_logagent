"""One isolated, unscored case job for the parallel Hugging Face pilot."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from logagent_bench.datasets import ROOT, cohort, digest, download_one
from logagent_bench.hf_local import CONFIG, MODEL, code_hashes, download_model
from logagent_bench.runner import prepare_input


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--case-id", required=True)
    args = p.parse_args()
    cases = cohort()
    ordinal = int(args.case_id)-1
    case = cases[ordinal]
    name = case["opaque_case_id"]
    root = ROOT / ".runs/hf-actions" / name
    root.mkdir(parents=True)
    for filename in case["source_files_sha256"]:
        download_one(case, filename, ROOT / ".cache")
    download_model()
    prepare_input(case, ROOT / ".cache", root / "inputs" / name)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONHASHSEED": "0"}
    packet = root / "packets" / (name+".json")
    subprocess.run([sys.executable, "-m", "logagent_bench.hf_packet", "--input", str(root / "inputs" / name),
        "--config", str(ROOT / "configs/hypothesis.yaml"), "--output", str(packet)], env=env, check=True)
    protocol = {"experiment": "hf-actions-parallel-v1", "configuration": CONFIG, "model": MODEL,
        "cases": [{"case_id": name, "dataset": case["dataset"], "ordinal": ordinal}],
        "files_sha256": code_hashes(),
        "orchestration_sha256": {s: digest(ROOT / s) for s in
            ("scripts/hf_case_job.py", "scripts/hf_collect_jobs.py", ".github/workflows/hf-benchmark.yml")},
        "source_commit": os.environ["GITHUB_SHA"], "github_run_id": os.environ["GITHUB_RUN_ID"],
        "runtime": {"python": platform.python_version(), "cpu_count": os.cpu_count(),
                    "llama_cpp_python": importlib.metadata.version("llama-cpp-python")},
        "source_files_sha256": case["source_files_sha256"], "packet_sha256": digest(packet),
        "source_rows_or_labels_published": False, "scoring_in_case_job": False}
    (root / "protocol.json").write_text(json.dumps(protocol, indent=2))
    subprocess.run([sys.executable, "-m", "logagent_bench.hf_worker", "--run-root", str(root),
        "--model", str(ROOT / ".cache/hf-model" / MODEL["filename"])], env=env, check=True)
    if code_hashes() != protocol["files_sha256"] or digest(packet) != protocol["packet_sha256"]:
        raise RuntimeError("Implementation or evidence drift")
    predictions = [p for p in (root / "predictions").glob("*.json") if not p.name.endswith(".response.json")]
    if len(predictions) != 4:
        raise RuntimeError("Incomplete four-cell case schedule")
    artifact = ROOT / ".runs/public-case-artifact"
    artifact.mkdir()
    (artifact / "protocol.json").write_text(json.dumps(protocol, indent=2))
    (artifact / "context_preflight.json").write_bytes((root / "context_preflight.json").read_bytes())
    sealed = {}
    for source in predictions:
        # These structured files contain model diagnoses, hashes, usage and
        # errors, never telemetry packets or generated free-text responses.
        value = json.loads(source.read_text())
        if value["case_id"] != name:
            raise ValueError("Case identity mismatch")
        (artifact / source.name).write_bytes(source.read_bytes())
        sealed[source.name] = digest(source)
    (artifact / "sealed_predictions.json").write_text(json.dumps(sealed, indent=2))
    print(f"Sealed {len(sealed)} unscored model predictions for {name}", flush=True)


if __name__ == "__main__":
    main()
