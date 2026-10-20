"""One inference subprocess. Answer-bearing paths are blocked by an audit hook."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .adapter import load_bundle
from .engine import evaluate


def deny_label_reads(event, args):
    if event != "open" or not args or not isinstance(args[0], (str, bytes)):
        return
    path = Path(args[0].decode() if isinstance(args[0], bytes) else args[0])
    forbidden_names = {"injection.json", "causal_graph.json", "topology.json", "task.json", "env.json", "conclusion.parquet"}
    if "fixtures" in path.parts or "metadata" in path.parts or path.name in forbidden_names:
        raise PermissionError("Answer-bearing paths are not accessible during inference")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.addaudithook(deny_label_reads)
    policy = yaml.safe_load(args.config.read_text())
    bundle = load_bundle(args.input)
    result = evaluate(bundle, policy)
    result["leakage_guard"] = {"label_reads_blocked": True, "opaque_case_context": True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
