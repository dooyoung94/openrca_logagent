"""Telemetry-only evidence packets for a separately labelled local-HF pilot."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from .adapter import load_bundle
from .engine import evaluate, quantile
from .worker import deny_label_reads


def compact_stats(rows):
    if not rows:
        return {"n": 0}
    values = [r["value"] for r in rows]
    return {"n": len(values), "p50": round(quantile(values, .5), 6),
            "p95": round(quantile(values, .95), 6), "min": round(min(values), 6),
            "max": round(max(values), 6)}


def change_score(before, after):
    if not before or not after:
        return 0.0
    a, b = compact_stats(before), compact_stats(after)
    return max(abs(b[key]-a[key])/max(abs(a[key]), abs(b[key]), 1e-9)
               for key in ("p50", "p95", "max"))


def evidence_packet(bundle, policy):
    context = bundle["context"]
    onset = context["abnormal_window"][0]*10**9
    grouped = defaultdict(dict)
    for row in bundle["metrics"]:
        key = (row["scope"], row["entity"], row["metric"])
        previous = grouped[key].get(row["time_ns"])
        if previous is None or row["value"] > previous["value"]:
            grouped[key][row["time_ns"]] = row
    metrics = []
    for (scope, entity, metric), samples in sorted(grouped.items()):
        before = [r for t, r in samples.items() if t < onset]
        after = [r for t, r in samples.items() if t >= onset]
        metrics.append((change_score(before, after), {
            "scope": scope, "entity": entity, "metric": metric,
            "normal": compact_stats(before), "incident": compact_stats(after)}))
    metrics.sort(key=lambda r: (-r[0], r[1]["entity"], r[1]["metric"]))

    # Exact witnessed parent/span joins, identical in both arms. Never import
    # publisher topology and never infer dependencies from component names.
    index = {(s["trace"], s["span"]): s for s in bundle["spans"]}
    edges = defaultdict(list)
    services = defaultdict(list)
    for child in index.values():
        if child["kind"] == "Server" and child["end_ns"] >= child["time_ns"]:
            services[child["service"]].append({"time_ns": child["time_ns"],
                "value": (child["end_ns"]-child["time_ns"])/1e6, "error": child["error"]})
        parent = index.get((child["trace"], child["parent"]))
        if (parent and parent["kind"] == "Client" and child["kind"] == "Server"
                and parent["service"] != child["service"]):
            gap = (child["time_ns"]-parent["time_ns"])/1e6
            if gap >= 0:
                edges[(parent["service"], child["service"])].append(
                    {"time_ns": child["time_ns"], "value": gap})

    def paired(rows):
        return ([r for r in rows if r["time_ns"] < onset],
                [r for r in rows if r["time_ns"] >= onset])

    edge_rows = []
    for edge, rows in sorted(edges.items()):
        before, after = paired(rows)
        edge_rows.append((change_score(before, after), {"source": edge[0], "destination": edge[1],
            "signal": "paired Server start minus Client start (ms)",
            "normal": compact_stats(before), "incident": compact_stats(after)}))
    edge_rows.sort(key=lambda r: (-r[0], r[1]["source"], r[1]["destination"]))
    service_rows = []
    for entity, rows in sorted(services.items()):
        before, after = paired(rows)
        service_rows.append((change_score(before, after), {"entity": entity, "signal": "Server duration (ms)",
            "normal": {**compact_stats(before), "errors": sum(r["error"] for r in before)},
            "incident": {**compact_stats(after), "errors": sum(r["error"] for r in after)}}))
    service_rows.sort(key=lambda r: (-r[0], r[1]["entity"]))

    # Error templates are observations, not mechanism labels. Injection-tool
    # strings are excluded with the previously frozen architecture policy.
    logs = defaultdict(lambda: [0, 0])
    for event in bundle["events"]:
        text = event["message"]
        if not event.get("entity") or re.search(policy["exclude_event_regex"], text):
            continue
        if not re.search(r"(?i)(error|exception|fail|panic|fatal|timeout|not.?ready|unreachable|oom|out of memory|disk|restart)", text):
            continue
        template = re.sub(r"\b[0-9a-f]{16,}\b", "<id>", text, flags=re.I)
        template = re.sub(r"\d+(?:\.\d+)?", "<n>", template)
        template = re.sub(r"\s+", " ", template).strip()[:200]
        key = (event["scope"], str(event["entity"]), template)
        logs[key][int(event["time_ns"] >= onset)] += 1
    normal_seconds = context["normal_window"][1]-context["normal_window"][0]
    incident_seconds = context["abnormal_window"][1]-context["abnormal_window"][0]
    log_rows = []
    for (scope, entity, template), (normal, incident) in logs.items():
        delta = incident/incident_seconds-normal/normal_seconds
        log_rows.append((delta, {"scope": scope, "entity": entity, "template": template,
            "normal_count": normal, "incident_count": incident}))
    log_rows.sort(key=lambda r: (-r[0], r[1]["entity"], r[1]["template"]))
    common = {"context": context, "notes": [
        "Statistics preserve source-native units; CPU cores are not percent.",
        "Metric duplicates use a maximum envelope per entity/metric/timestamp.",
        "Lists are bounded change-ranked summaries; omitted observations may matter.",
        "A witnessed dependency or correlated symptom is not proof of causation."],
        "metrics": [r[1] for r in metrics[:24]],
        "edges": [r[1] for r in edge_rows[:10]],
        "services": [r[1] for r in service_rows[:6]],
        "error_templates": [r[1] for r in log_rows[:10]],
        "available_counts": {"metric_groups": len(metrics), "edges": len(edge_rows),
                             "services": len(service_rows), "error_templates": len(log_rows)}}
    for prefix, key in (("M", "metrics"), ("E", "edges"), ("S", "services"), ("L", "error_templates")):
        for i, row in enumerate(common[key]):
            row["evidence_id"] = prefix+str(i+1)
    analysis = evaluate(bundle, policy)
    hints = []
    for thread in analysis["threads"][:6]:
        hints.append({k: thread[k] for k in ("causal_scope", "causal_component", "edge_source",
            "edge_destination", "mechanism_code", "score", "slice_id")})
        hints[-1]["signals"] = [e["signal"] for e in thread["evidence"][:3]]
        hints[-1]["connected_symptoms"] = len(thread["connections"])
    return {"common_evidence": common, "logagent_hints": hints,
            "hint_note": "Fallible architecture candidates, not labels or source evidence. Score is not probability.",
            "guard": {"labels_read": False, "publisher_graph_read": False}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    sys.addaudithook(deny_label_reads)
    result = evidence_packet(load_bundle(args.input), yaml.safe_load(args.config.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
