"""Telemetry-only candidate selection before the upstream LLM investigation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from .adapter import load_bundle
from .engine import evaluate
from .worker import deny_label_reads

CANDIDATE_LIMIT = 5
CANDIDATE_FIELDS = (
    "thread_id", "causal_scope", "causal_component", "edge_source", "edge_destination",
    "causal_operation", "mechanism_code", "fault_category", "score", "slice_id", "connections",
)


def select_candidates(result, limit=CANDIDATE_LIMIT):
    """Project already ranked Threads; do not expose the Python Top-1 verdict.

    The engine's score/order/policy are unchanged. No answer labels or scoring
    results are consulted, and an empty ranking stays empty.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= CANDIDATE_LIMIT:
        raise ValueError(f"limit must be an integer in 1..{CANDIDATE_LIMIT}")
    threads = result["threads"]
    rows = [{key: thread.get(key) for key in CANDIDATE_FIELDS} for thread in threads[:limit]]
    return {
        "schema_version": 1, "limit": limit, "candidate_count": len(threads),
        "shortlisted_count": len(rows), "candidates": rows,
        "navigation_only": True, "source_evidence_required": True, "score_is_probability": False,
    }


def shortlist_sha256(shortlist):
    return hashlib.sha256(json.dumps(
        shortlist, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()).hexdigest()


def build_isolated_shortlist(input_path, config_path, output_path):
    """Build in a fresh process whose file-open guard denies answer paths.

    Only isolated telemetry/context and the frozen policy are input. The full
    experiment process holds scoring fixtures; the selector process does not.
    """
    if output_path.exists():
        raise FileExistsError("Candidate output already exists; use a fresh cell")
    env = {**os.environ, "PYTHONHASHSEED": "0"}
    completed = subprocess.run([
        sys.executable, "-m", "logagent_bench.candidates",
        "--input", str(input_path.resolve()), "--config", str(config_path.resolve()),
        "--output", str(output_path.resolve()),
    ], env=env, capture_output=True, text=True, timeout=300)
    if completed.returncode:
        # Raw paths and error text stay private. A failed selector must not
        # silently turn into a Raw cell or reuse an earlier candidate file.
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.with_suffix(".error.txt").write_text(completed.stderr, encoding="utf-8")
        raise RuntimeError("Isolated candidate selector failed before any model call")
    return json.loads(output_path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.addaudithook(deny_label_reads)
    policy = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    result = evaluate(load_bundle(args.input), policy)
    shortlist = select_candidates(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves the exact payload seen by this cell.
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(shortlist, handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
