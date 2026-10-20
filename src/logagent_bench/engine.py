"""Python RCA: observations -> ontology -> hypotheses -> Threads -> Top-1.

The design follows the uploaded LogAgent architecture. All thresholds, source
semantics, and time windows are explicit OpenRCA adaptations, not the original
production implementation. No expected answer is an input to this module.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict, deque
from statistics import median

CATEGORY = {"cpu_saturation": "cpu", "memory_pressure": "memory", "call_path_delay": "delay",
            "disk_io_degradation": "disk", "workload_restart": "other", "host_unavailable": "other",
            "dependency_unavailable": "other", "configuration_error": "other"}


def quantile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def segment(time_ns, context):
    begin = context["normal_window"][0] * 10**9
    end = context["abnormal_window"][1] * 10**9
    return "T" + str(min(4, max(1, 1 + int(4 * (time_ns - begin) // (end - begin)))))


def identity(scope, entity, mechanism, edge=None):
    value = [scope, entity, mechanism, list(edge) if edge else None]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:20]


def stats(rows):
    values = [r["value"] for r in rows]
    return {"count": len(values), "min": min(values), "max": max(values), "median": median(values),
            "p95": quantile(values, 0.95)} if values else {"count": 0}


def evaluate(bundle, policy):
    context = bundle["context"]
    onset, end = (x * 10**9 for x in context["abnormal_window"])
    baseline_begin = context["normal_window"][0] * 10**9
    threshold, names = policy["thresholds"], policy["metrics"]
    min_normal, min_abnormal = policy["minimum_baseline_samples"], policy["minimum_abnormal_samples"]
    groups = defaultdict(dict)
    duplicate_samples = 0
    for row in bundle["metrics"]:
        if not baseline_begin <= row["time_ns"] < end:
            continue
        key = (row["scope"], row["entity"], row["metric"])
        existing = groups[key].get(row["time_ns"])
        if existing is not None:
            duplicate_samples += 1
        # Multiple replicas are an explicit maximum-envelope projection, not a
        # sum or an invented per-container observation. Preserve its source.
        if existing is None or row["value"] > existing["value"]:
            groups[key][row["time_ns"]] = row

    candidates = []

    def add(scope, entity, mechanism, normal, abnormal, hits, strength, signal, *, edge=None, operation=None):
        if not hits:
            return
        first = min(r["time_ns"] for r in hits)
        proof = {"signal": signal, "normal": stats(normal), "abnormal": stats(abnormal),
                 "hit_count": len(hits), "first_seen_ns": first,
                 "source_refs": sorted({r["source"] for r in hits}),
                 "normal_source_refs": sorted({r["source"] for r in normal}),
                 "projection": "maximum per entity/metric/timestamp; duplicates do not increase support"}
        candidates.append({"candidate_id": identity(scope, entity, mechanism, edge),
                           "causal_scope": scope, "causal_component": None if edge else entity,
                           "edge_source": edge[0] if edge else None, "edge_destination": edge[1] if edge else None,
                           "mechanism_code": mechanism, "fault_category": CATEGORY[mechanism],
                           "causal_operation": operation, "first_seen_ns": first,
                           "slice_id": segment(first, context), "direct_strength": min(1.0, max(0.0, strength)),
                           "contrast": min(1.0, len(hits) / max(1, len(abnormal))), "evidence": [proof]})

    # Metric hypotheses use baseline transitions; a large stable value is not
    # evidence that a new fault occurred in the incident window.
    for (scope, entity, metric), samples in sorted(groups.items()):
        normal = sorted((r for t, r in samples.items() if t < onset), key=lambda r: r["time_ns"])
        abnormal = sorted((r for t, r in samples.items() if t >= onset), key=lambda r: r["time_ns"])
        if len(normal) < min_normal or len(abnormal) < min_abnormal:
            continue
        baseline, recent = median(r["value"] for r in normal), median(r["value"] for r in abnormal)
        hits, mechanism, floor = [], None, None
        if metric in names["restarts"]:
            floor = max(r["value"] for r in normal) + threshold["restart_counter_delta"]
            mechanism = "workload_restart"
            hits = [r for r in abnormal if r["value"] >= floor]
        elif metric in names["cpu_cores"]:
            floor = max(threshold["cpu_core_floor"], baseline + threshold["cpu_core_delta"], baseline * threshold["cpu_growth_ratio"])
            mechanism = "cpu_saturation"
            hits = [r for r in abnormal if r["value"] >= floor]
        elif metric in names["cpu_percent"]:
            floor = max(threshold["utilization_percent_floor"], baseline + threshold["utilization_delta_percentage_points"])
            mechanism = "cpu_saturation"
            hits = [r for r in abnormal if r["value"] >= floor]
        elif metric in names["memory_bytes"]:
            floor = max(threshold["memory_bytes_floor"], baseline + threshold["memory_bytes_delta"], baseline * threshold["memory_growth_ratio"])
            mechanism = "memory_pressure"
            hits = [r for r in abnormal if r["value"] >= floor]
        elif metric in names["memory_percent"]:
            floor = max(threshold["utilization_percent_floor"], baseline + threshold["utilization_delta_percentage_points"])
            mechanism = "memory_pressure"
            hits = [r for r in abnormal if r["value"] >= floor]
        elif metric in names["unavailable_when_zero"] and baseline >= 1:
            mechanism = "host_unavailable" if scope == "infrastructure_node" else "dependency_unavailable"
            hits = [r for r in abnormal if r["value"] == 0]
        elif metric in names["unavailable_when_one"] and baseline == 0:
            mechanism = "host_unavailable" if scope == "infrastructure_node" else "dependency_unavailable"
            hits = [r for r in abnormal if r["value"] >= 1]
        elif re.search(names["disk_io_regex"], metric) and baseline >= 0:
            floor = max(baseline * 3, baseline + 20)
            mechanism = "disk_io_degradation"
            hits = [r for r in abnormal if r["value"] >= floor]
        if mechanism and len(hits) >= min_abnormal:
            peak = max(r["value"] for r in hits)
            growth = (peak - baseline) / max(abs(baseline), 1e-9)
            strength = 0.85 if mechanism in {"workload_restart", "host_unavailable", "dependency_unavailable"} else 0.65 + 0.2 * min(growth / 4, 1)
            add(scope, entity, mechanism, normal, abnormal, hits, strength,
                {"kind": "metric_transition", "metric": metric, "threshold": floor,
                 "declared_unit": "cores" if metric in names["cpu_cores"] else "%" if metric in names["cpu_percent"] + names["memory_percent"] else "source-native"})

    # Ontology comes only from witnessed Client->Server parent-span links and
    # source-declared service->node placement. A name match is not a call edge.
    span_index, span_conflicts = {}, 0
    for span in bundle["spans"]:
        key = (span["trace"], span["span"])
        if key in span_index:
            if span_index[key] != span:
                span_conflicts += 1
            continue
        span_index[key] = span
    graph, placements, edge_groups = defaultdict(set), defaultdict(set), defaultdict(list)
    for child in span_index.values():
        if child.get("host"):
            placements[str(child["host"])].add(child["service"])
        parent = span_index.get((child["trace"], child["parent"]))
        if not parent or parent["kind"] != "Client" or child["kind"] != "Server":
            continue
        if parent["service"] == child["service"]:
            continue
        edge = (parent["service"], child["service"])
        graph[edge[0]].add(edge[1])
        if not baseline_begin <= child["time_ns"] < end:
            continue
        edge_groups[edge].append({"time_ns": child["time_ns"],
                                  "value": (child["time_ns"] - parent["time_ns"]) / 1e6,
                                  "source": hashlib.sha256((parent["source"] + child["source"]).encode()).hexdigest()[:20],
                                  "operation": child["operation"]})
    for edge, records in sorted(edge_groups.items()):
        normal = [r for r in records if r["time_ns"] < onset and r["value"] >= 0]
        abnormal = [r for r in records if r["time_ns"] >= onset and r["value"] >= 0]
        if len(normal) < min_normal or len(abnormal) < min_abnormal:
            continue
        baseline_p95 = quantile([r["value"] for r in normal], 0.95)
        floor = max(threshold["call_path_gap_ms"], baseline_p95 + threshold["call_path_gap_delta_ms"])
        hits = [r for r in abnormal if r["value"] >= floor]
        if len(hits) >= min_abnormal:
            add("dependency_edge", None, "call_path_delay", normal, abnormal, hits, 0.9,
                {"kind": "paired_client_server_start_gap", "threshold_ms": floor},
                edge=edge, operation=hits[0]["operation"])

    # Logs and Kubernetes events supplement mechanisms only when their rate
    # changes. Injection tool messages are excluded explicitly.
    event_groups = defaultdict(dict)
    for event in bundle["events"]:
        if not event.get("entity") or re.search(policy["exclude_event_regex"], event["message"]):
            continue
        for mechanism, pattern in policy["events"].items():
            if re.search(pattern, event["message"]):
                key = (event["scope"], str(event["entity"]), mechanism)
                stamp = (event["time_ns"], hashlib.sha256(event["message"].encode()).hexdigest())
                event_groups[key][stamp] = {"time_ns": event["time_ns"], "value": 1.0, "source": event["source"]}
    for (scope, entity, mechanism), records in sorted(event_groups.items()):
        normal = [r for r in records.values() if r["time_ns"] < onset]
        abnormal = [r for r in records.values() if r["time_ns"] >= onset]
        baseline_duration = onset - baseline_begin
        recent_duration = end - onset
        expected = len(normal) * recent_duration / baseline_duration
        if len(abnormal) >= min_abnormal and (not normal or len(abnormal) >= expected * threshold["event_rate_ratio"]):
            add(scope, entity, mechanism, normal, abnormal, abnormal, 0.8,
                {"kind": "event_signature_rate_transition", "signature": mechanism,
                 "baseline_count": len(normal), "abnormal_count": len(abnormal)})

    symptoms = detect_symptoms(list(span_index.values()), context, threshold)
    # Dedupe hypotheses at their declared causal scope. Repeated metric rows
    # or alternate memory gauges cannot create duplicate root threads.
    merged = {}
    for item in candidates:
        key = item["candidate_id"]
        if key not in merged:
            merged[key] = item
        else:
            merged[key]["evidence"].extend(item["evidence"])
            for name in ("direct_strength", "contrast"):
                merged[key][name] = max(merged[key][name], item[name])
            merged[key]["first_seen_ns"] = min(merged[key]["first_seen_ns"], item["first_seen_ns"])
            merged[key]["slice_id"] = segment(merged[key]["first_seen_ns"], context)

    threads = []
    for item in merged.values():
        connected = []
        causal_entity = item["edge_destination"] or item["causal_component"]
        possible = placements.get(causal_entity, set()) if item["causal_scope"] == "infrastructure_node" else {causal_entity}
        for symptom in symptoms:
            # Reverse traversal identifies callers affected by a faulty callee.
            path = impact_path(graph, possible, symptom["entity"])
            if path is None:
                continue
            if symptom["first_seen_ns"] + policy["temporal_tolerance_seconds"] * 10**9 < item["first_seen_ns"]:
                continue
            connected.append({"entity": symptom["entity"], "symptom": symptom["kind"],
                              "path": path, "slice_id": segment(symptom["first_seen_ns"], context),
                              "relation_verdict": "WITNESSED_STRUCTURE_AND_TEMPORAL_ASSOCIATION"})
        w = policy["scoring"]
        independent = min(len({e["signal"]["kind"] for e in item["evidence"]}) - 1, 2) / 2
        terms = {"direct_mechanism": w["direct_mechanism"] * item["direct_strength"],
                 "baseline_contrast": w["baseline_contrast"] * item["contrast"],
                 "temporal_ontology_connection": w["temporal_ontology_connection"] * min(len(connected) / 3, 1),
                 "independent_signal": w["independent_signal"] * independent}
        threads.append({**item, "thread_id": "thread-" + item["candidate_id"],
                        "score": round(sum(terms.values()), 6), "score_components": terms,
                        "connections": connected, "score_is_probability": False})
    threads.sort(key=lambda r: (-r["score"], r["first_seen_ns"], r["candidate_id"]))
    selected = threads[0] if threads else None
    diagnosis = None if selected is None else {k: selected[k] for k in
        ("causal_scope", "causal_component", "edge_source", "edge_destination", "mechanism_code", "fault_category", "causal_operation")}
    return {"schema_version": 1, "case_id": context["case_id"], "diagnosis": diagnosis,
            "selected_thread": selected, "threads": threads, "candidate_count": len(threads),
            "status": "CAUSE_CANDIDATE" if selected else "ABSTAIN_INSUFFICIENT_EVIDENCE",
            "time_segments": [{"slice_id": f"T{i+1}", "start_ns": baseline_begin + (end-baseline_begin)*i//4,
                               "end_ns": baseline_begin + (end-baseline_begin)*(i+1)//4} for i in range(4)],
            "ontology": {"witnessed_call_edges": sorted([list((s,t)) for s,targets in graph.items() for t in targets]),
                         "service_node_placements": sum(len(v) for v in placements.values()),
                         "publisher_topology_used": False, "reference_causal_graph_used": False},
            "coverage": {**bundle["coverage"], "duplicate_metric_samples_projected": duplicate_samples,
                         "conflicting_span_identities": span_conflicts, "symptom_count": len(symptoms)},
            "llm_used": False}


def detect_symptoms(spans, context, threshold):
    onset = context["abnormal_window"][0] * 10**9
    groups = defaultdict(list)
    for span in spans:
        if span["kind"] == "Server" and span["end_ns"] >= span["time_ns"]:
            groups[span["service"]].append(span)
    output = []
    for entity, rows in sorted(groups.items()):
        normal, recent = [x for x in rows if x["time_ns"] < onset], [x for x in rows if x["time_ns"] >= onset]
        if len(normal) < 2 or len(recent) < 2:
            continue
        base = quantile([(r["end_ns"] - r["time_ns"]) / 1e6 for r in normal], 0.95)
        floor = max(base * threshold["symptom_latency_ratio"], base + threshold["symptom_latency_delta_ms"])
        hits = [r for r in recent if (r["end_ns"] - r["time_ns"]) / 1e6 >= floor]
        if len(hits) >= 2:
            output.append({"entity": entity, "kind": "latency_increase", "first_seen_ns": min(r["time_ns"] for r in hits)})
        base_error = sum(r["error"] for r in normal) / len(normal)
        bad = [r for r in recent if r["error"]]
        if len(bad) >= 2 and len(bad) / len(recent) > max(0.05, 2 * base_error):
            output.append({"entity": entity, "kind": "error_increase", "first_seen_ns": min(r["time_ns"] for r in bad)})
    return output


def impact_path(graph, causes, symptom):
    if symptom in causes:
        return [symptom]
    queue = deque([(symptom, [symptom])])
    seen = {symptom}
    while queue:
        node, path = queue.popleft()
        if len(path) > 5:
            continue
        for target in sorted(graph.get(node, ())):
            if target in causes:
                return path + [target]
            if target not in seen:
                seen.add(target)
                queue.append((target, path + [target]))
    return None
