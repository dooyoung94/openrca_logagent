"""Pinned real GreptimeDB Raw storage for the separate HF tool-loop experiment."""
from __future__ import annotations

import json
import os
import shutil
import tarfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import requests

from .datasets import ROOT, OPENRCA2_REVISION, digest, download_one

DATABASE = {
    "release": "v1.3.0-beta.2",
    "source_commit": "a788cd977af3aa9e97bf2ff475607e995f5bb51a",
    "archive_sha256": "949e51a3096ed6a29d05bc993e7c402f21226f302193bc2f71d875de6a26cf7a",
    "archive_url": "https://github.com/GreptimeTeam/greptimedb/releases/download/v1.3.0-beta.2/greptime-linux-amd64-v1.3.0-beta.2.tar.gz",
    "upstream_original_revision": "15317a131bc63a680d3571e5f681bee4acc86228",
    "original_revision_match": False,
    "usage_telemetry_enabled": False,
}


def download_binary():
    folder = ROOT / ".cache/greptimedb"
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / (DATABASE["release"] + ".tar.gz")
    if not archive.is_file() or digest(archive) != DATABASE["archive_sha256"]:
        part = archive.with_suffix(".part")
        with requests.get(DATABASE["archive_url"], stream=True, timeout=120) as response:
            response.raise_for_status()
            with part.open("wb") as handle:
                for block in response.iter_content(1024*1024):
                    handle.write(block)
        if digest(part) != DATABASE["archive_sha256"]:
            raise ValueError("GreptimeDB release archive checksum mismatch")
        part.replace(archive)
    binary = folder / "greptime"
    with tarfile.open(archive) as handle:
        member = next(item for item in handle.getmembers()
                      if item.isfile() and Path(item.name).name == "greptime")
        with handle.extractfile(member) as source:
            with binary.open("wb") as destination:
                shutil.copyfileobj(source, destination)
    binary.chmod(0o755)
    return binary


def prepare_source(case_spec, root):
    cache = ROOT / ".cache"
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = list(pool.map(lambda name: download_one(case_spec, name, cache), case_spec["source_files_sha256"]))
    base = root / ("openrca2/cases" if case_spec["dataset"] == "openrca2" else "rca100") / case_spec["source_case"]
    base.mkdir(parents=True, exist_ok=False)
    for record in records:
        name = record["file"]
        source = cache / case_spec["opaque_case_id"] / ("telemetry" if (cache / case_spec["opaque_case_id"] / "telemetry" / name).exists() else "metadata") / name
        if digest(source) != case_spec["source_files_sha256"][name]:
            raise ValueError("Pinned source hash mismatch")
        os.link(source, base / name)
    manifest = root / "openrca2/manifest.jsonl"
    if case_spec["dataset"] == "openrca2":
        manifest.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(f"https://huggingface.co/datasets/anon-ops/ops-lite/resolve/{OPENRCA2_REVISION}/manifest.jsonl", timeout=120)
        response.raise_for_status()
        manifest.write_bytes(response.content)
    else:
        from agent_rca_bench.datasets.rca100 import SOURCE_BASE_URL
        answer_folder = root / "rca100/answer_key"
        answer_folder.mkdir(parents=True, exist_ok=True)
        for name in (case_spec["source_case"]+".gt.json", "taxonomy.json"):
            response = requests.get(f"{SOURCE_BASE_URL}/answer_key/{name}", timeout=120)
            response.raise_for_status()
            (answer_folder / name).write_bytes(response.content)
    return manifest


@contextmanager
def raw_environment(case_spec, run_root, binary):
    from agent_rca_bench.contracts import CausalScope
    from agent_rca_bench.datasets.openrca2_transfer import TransferCaseSpec
    from agent_rca_bench.greptimedb.client import GreptimeClient
    from agent_rca_bench.greptimedb.server import ManagedGreptime
    from agent_rca_bench.inspect import (assert_semantic_graph_isolated, assert_semantic_graph_window_empty,
                                        inspect_semantic_surfaces, summarize_semantic_surfaces)
    from agent_rca_bench.transfer_formal import (_CASE_ADAPTERS, TransferEnvironmentConfig,
        _empty_before_ingest, _audit_greptimedb_promql, mechanism_evidence_audit)

    manifest = prepare_source(case_spec, run_root / "source")
    spec = TransferCaseSpec.model_validate({key:value for key,value in case_spec.items() if key != "dataset"})
    config = TransferEnvironmentConfig(
        cache_dir=run_root / "source/openrca2", manifest_path=manifest, greptimedb_repo=run_root,
        run_dir=run_root / "database", database=spec.opaque_case_id.replace("-", "_"),
        node_cache_dir=run_root / "source/rca100",
    )
    adapter = _CASE_ADAPTERS[spec.causal_scope is CausalScope.INFRASTRUCTURE_NODE]
    case = adapter.load_case(config, spec)
    managed = ManagedGreptime(binary, config.run_dir, startup_timeout=180)
    try:
        # Official standalone opt-out; the child inherits it before startup.
        # https://docs.greptime.com/reference/telemetry/
        with patch.dict(os.environ, {"GREPTIMEDB_STANDALONE__ENABLE_TELEMETRY": "false"}):
            managed.start()
        with GreptimeClient(managed.endpoint, database=config.database, timeout=120) as client:
            client.create_database(config.database)
            assert_semantic_graph_isolated(client, config.database)
            empty = assert_semantic_graph_window_empty(client, case.input)
            source = adapter.source_audit(case, spec)
            counts = adapter.ingest(client, case, spec)
            stored = adapter.validate_ingest(client, case, counts, source)
            surfaces = inspect_semantic_surfaces(client, case.input)
            coverage = surfaces.get("coverage")
            if not isinstance(coverage, dict):
                coverage = summarize_semantic_surfaces(surfaces)
            equality = adapter.edge_equality(client, spec, source)
            mechanism = mechanism_evidence_audit(client, spec)
            gates = adapter.gates(case, spec, source, stored, equality, mechanism,
                isolated=_empty_before_ingest(empty),
                semantic_surface_contract=coverage.get("surface_contract", {}).get("current") is True)
            series = adapter.split_source(case, spec).metric_series
            promql = _audit_greptimedb_promql(client, series, window=(spec.normal_window[0],spec.abnormal_window[1]))
            gates["greptimedb_promql_works"] = promql["pass"] is True
            gates["all_passed"] = all(value for key,value in gates.items() if key != "all_passed")
            audit = {"database": DATABASE, "binary_sha256": digest(binary), "server_status": client.status(),
                "source": source, "ingestion": stored, "edge_equality": equality,
                "mechanism_evidence": mechanism, "semantic_coverage": coverage,
                "greptimedb_promql": promql, "gates": gates,
                "split_stack": "not part of this Raw-versus-LogAgent HF protocol"}
            (run_root / "private").mkdir(exist_ok=True)
            (run_root / "private/environment_audit.json").write_text(json.dumps(audit, indent=2))
            if not gates["all_passed"]:
                raise RuntimeError("HF Raw source/storage preflight failed: "+json.dumps({key:value for key,value in gates.items() if not value}))
            yield client, case.input, audit
    finally:
        managed.stop()
