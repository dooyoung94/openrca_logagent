from __future__ import annotations

import argparse
from pathlib import Path

from .datasets import ROOT, fetch
from .runner import run


def main():
    parser = argparse.ArgumentParser(description="Evaluate the LogAgent architecture on a pinned OpenRCA cohort")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--cache", type=Path, default=ROOT / ".cache")
    p.add_argument("--workers", type=int, default=6)
    p = sub.add_parser("run")
    p.add_argument("--cache", type=Path, default=ROOT / ".cache")
    p.add_argument("--run-root", type=Path, required=True)
    p.add_argument("--output", type=Path, default=ROOT / "results" / "v1")
    p.add_argument("--config", type=Path, default=ROOT / "configs" / "hypothesis.yaml")
    p.add_argument("--repetitions", type=int, default=2)
    args = parser.parse_args()
    if args.command == "fetch":
        result = fetch(args.cache, args.workers)
        raise SystemExit(1 if result["errors"] else 0)
    run(args.cache, args.run_root, args.output, args.config, args.repetitions)


if __name__ == "__main__":
    main()
