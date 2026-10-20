"""Pinned, hash-verified source downloads; no source rows are redistributed."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPENRCA2_REVISION = "9ac09981c08ab02a0b923eab7830d778934851a8"
BENCHMARK_REVISION = "fdfbca65c87c36c6b06bddfa6d611544f13bfa34"
FIXTURES = (
    ("openrca2", "openrca2-transfer-v32-selection.json"),
    ("rca100", "rca100-transfer-node-selection.json"),
)
FORBIDDEN = {"injection.json", "env.json", "conclusion.parquet", "task.json", "topology.json", "causal_graph.json"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def cohort() -> list[dict]:
    cases = []
    for dataset, filename in FIXTURES:
        obj = json.loads((ROOT / "fixtures" / filename).read_text())
        for case in obj["selected_cases"]:
            cases.append({**case, "dataset": dataset})
    return cases


def source_url(case: dict, filename: str) -> str:
    if case["dataset"] == "openrca2":
        return ("https://huggingface.co/datasets/anon-ops/ops-lite/resolve/"
                f"{OPENRCA2_REVISION}/cases/{case['source_case']}/{filename}")
    return ("https://aiops-benchmark.oss-cn-hongkong.aliyuncs.com/rca/rca100/"
            f"v1.1/cases/{case['source_case']}/{filename}")


def download_one(case: dict, filename: str, cache: Path) -> dict:
    # Storage uses only opaque IDs. Answer-bearing metadata is isolated from
    # the inference input directory even when required for the source audit.
    sub = "metadata" if filename in FORBIDDEN else "telemetry"
    target = cache / case["opaque_case_id"] / sub / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = case["source_files_sha256"][filename]
    if target.is_file() and digest(target) == expected:
        return {"case_id": case["opaque_case_id"], "file": filename,
                "sha256": expected, "bytes": target.stat().st_size, "status": "verified_cache"}
    url = source_url(case, filename)
    part = target.with_suffix(target.suffix + ".part")
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "logagent-openrca-benchmark/0.1"})
            with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            actual = digest(part)
            if actual != expected:
                raise ValueError(f"SHA256 mismatch for {case['opaque_case_id']}/{filename}: {actual}")
            part.replace(target)
            return {"case_id": case["opaque_case_id"], "file": filename,
                    "sha256": actual, "bytes": target.stat().st_size, "status": "verified_download"}
        except Exception:
            part.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def fetch(cache: Path, workers: int = 6) -> dict:
    cases = cohort()
    jobs = [(case, filename) for case in cases for filename in case["source_files_sha256"]]
    records, errors = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(download_one, case, name, cache): (case, name) for case, name in jobs}
        for future in as_completed(pending):
            case, name = pending[future]
            try:
                record = future.result()
                records.append(record)
                print(f"[fetch] {len(records)}/{len(jobs)} {record['case_id']} {name}", flush=True)
            except Exception as error:
                errors.append({"case_id": case["opaque_case_id"], "file": name,
                               "error_type": type(error).__name__, "error": str(error)})
                print(f"[fetch] FAILED {case['opaque_case_id']} {name}: {type(error).__name__}", flush=True)
    result = {"expected_files": len(jobs), "verified_files": len(records),
              "records": sorted(records, key=lambda r: (r["case_id"], r["file"])), "errors": errors}
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "source_audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
