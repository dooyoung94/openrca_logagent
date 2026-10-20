"""Telemetry-only adapters; labels and publisher topology are never opened."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ALLOWED_OPENRCA2 = {f"{period}_{suffix}.parquet" for period in ("normal", "abnormal")
                    for suffix in ("metrics", "metrics_sum", "metrics_histogram", "traces", "logs")}
ALLOWED_RCA100 = {"metrics.parquet", "logs.parquet", "traces.parquet", "events.parquet", "alerts.parquet"}


def iter_records(path: Path):
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=2048):
        # Arrow's native unit is explicit. Never guess seconds from a value's
        # magnitude; nanosecond span alignment is preserved without floats.
        stamps = {}
        for i, field in enumerate(batch.schema):
            if pa.types.is_timestamp(field.type):
                factor = {"s": 10**9, "ms": 10**6, "us": 10**3, "ns": 1}[field.type.unit]
                stamps[field.name] = [None if x is None else x * factor
                                      for x in batch.column(i).cast(pa.int64()).to_pylist()]
        records = batch.to_pylist()
        for index, record in enumerate(records):
            for name, values in stamps.items():
                record[name] = values[index]
            yield record


def iso_ns(value: str) -> int:
    # All log timestamps carry zones. Fractional ns beyond datetime precision
    # are not needed for event ordering; trace and metric paths remain exact.
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 10**9)


def json_object(value):
    if isinstance(value, dict):
        return value
    try:
        obj = json.loads(value or "{}")
        return obj if isinstance(obj, dict) else {}
    except (ValueError, TypeError):
        return {}


def service_alias_index(rows):
    """Resolve empty service names through observed, unambiguous pod identity.

    Restarts often lack service_name while CPU/memory rows for the identical
    pod carry it. This is an exact telemetry join, never name-prefix guessing.
    """
    candidates = {}
    for row in rows:
        service = row.get("service_name")
        if not service:
            continue
        namespace = row.get("attr.k8s.namespace.name") or ""
        for field in ("attr.k8s.pod.name", "attr.k8s.container.name"):
            alias = row.get(field)
            if alias:
                candidates.setdefault((namespace, field, alias), set()).add(str(service))
    return {key: next(iter(values)) for key, values in candidates.items() if len(values) == 1}


def resolve_service(row, aliases):
    explicit = row.get("service_name") or row.get("attr.k8s.deployment.name") or row.get("attr.k8s.statefulset.name")
    if explicit:
        return str(explicit)
    namespace = row.get("attr.k8s.namespace.name") or ""
    for field in ("attr.k8s.pod.name", "attr.k8s.container.name"):
        value = aliases.get((namespace, field, row.get(field)))
        if value:
            return value
    return None


def load_bundle(input_directory: Path) -> dict:
    context = json.loads((input_directory / "case.json").read_text())
    if set(context) != {"case_id", "dataset", "normal_window", "abnormal_window"}:
        raise ValueError("Inference context must contain only opaque identity and time windows")
    normal, abnormal = context["normal_window"], context["abnormal_window"]
    if not normal[0] < normal[1] == abnormal[0] < abnormal[1]:
        raise ValueError("Invalid baseline and incident windows")
    begin, end = normal[0] * 10**9, abnormal[1] * 10**9
    dataset = context["dataset"]
    allowed = ALLOWED_OPENRCA2 if dataset == "openrca2" else ALLOWED_RCA100
    metrics, spans, events, counts, unavailable = [], [], [], Counter(), []
    telemetry = input_directory / "telemetry"
    aliases = {}
    if dataset == "openrca2":
        alias_rows = (row for period in ("normal", "abnormal")
                      for row in iter_records(telemetry / f"{period}_metrics.parquet")
                      if begin <= int(row["time"]) < end)
        aliases = service_alias_index(alias_rows)
        counts["observed_unambiguous_identity_aliases"] = len(aliases)
    for name in sorted(allowed):
        path = telemetry / name
        if not path.is_file():
            raise FileNotFoundError(f"Required source file missing: {name}")
        count, retained = 0, 0
        for index, row in enumerate(iter_records(path)):
            count += 1
            source = hashlib.sha256(f"{name}:{index}".encode()).hexdigest()[:20]
            if "metrics_histogram" in name:
                # Histogram min/max in ops-lite are often explicit zeros;
                # do not turn cumulative counts into per-request latency.
                continue
            if "metrics" in name:
                time_ns = int(row["time"]) * (1000 if dataset == "rca100" else 1)
                if not begin <= time_ns < end:
                    continue
                value = row.get("value")
                if value is None or not math.isfinite(float(value)):
                    continue
                if dataset == "openrca2":
                    service = resolve_service(row, aliases)
                    entity, scope = service, "component"
                    if not entity:
                        counts["metrics_unresolved_identity"] += 1
                        continue
                    host = row.get("attr.k8s.node.name")
                else:
                    entity = row.get("entity_name")
                    scope = "infrastructure_node" if row.get("entity_set") == "k8s.node" else "component"
                    service, host = row.get("service"), entity if scope == "infrastructure_node" else None
                if not entity:
                    counts["metrics_unresolved_identity"] += 1
                    continue
                metrics.append({"time_ns": time_ns, "metric": str(row["metric"]), "value": float(value),
                                "entity": str(entity), "scope": scope, "service": service, "host": host, "source": source})
                retained += 1
            elif "traces" in name:
                if dataset == "openrca2":
                    time_ns, duration = int(row["time"]), int(row["duration"])
                    if not begin <= time_ns < end:
                        continue
                    service = row.get("service_name")
                    if not service or duration < 0:
                        counts["invalid_spans"] += 1
                        continue
                    span = {"trace": str(row["trace_id"]), "span": str(row["span_id"]),
                            "parent": str(row.get("parent_span_id") or ""), "service": str(service),
                            "operation": str(row.get("span_name") or "unknown"), "time_ns": time_ns,
                            "end_ns": time_ns + duration, "kind": row.get("attr.span_kind"),
                            "error": row.get("attr.status_code") == "Error", "host": row.get("attr.k8s.node.name")}
                else:
                    time_ns, end_ns = int(row.get("startTime") or 0), int(row.get("endTime") or 0)
                    if not begin <= time_ns < end:
                        continue
                    resources = json_object(row.get("resources"))
                    span = {"trace": str(row.get("traceId") or ""), "span": str(row.get("spanId") or ""),
                            "parent": str(row.get("parentSpanId") or ""), "service": str(row.get("serviceName") or "unknown"),
                            "operation": str(row.get("spanName") or "unknown"), "time_ns": time_ns,
                            "end_ns": end_ns, "kind": {2: "Server", 3: "Client"}.get(int(row.get("kind") or 0), "Internal"),
                            "error": int(row.get("statusCode") or 0) == 2, "host": resources.get("k8s.node.name")}
                span["source"] = source
                spans.append(span)
                retained += 1
            elif "events" in name:
                event = json_object(row.get("eventId"))
                raw_time = event.get("lastTimestamp") or event.get("eventTime") or event.get("metadata", {}).get("creationTimestamp")
                if not raw_time:
                    continue
                time_ns = iso_ns(raw_time)
                if not begin <= time_ns < end:
                    continue
                involved = event.get("involvedObject") or {}
                # A node event can locate a node; a pod event's host does not
                # by itself make the node the cause of the pod failure.
                node_event = involved.get("kind") == "Node"
                entity = involved.get("name") if node_event else row.get("pod_name")
                events.append({"time_ns": time_ns, "entity": entity, "scope": "infrastructure_node" if node_event else "component",
                               "host": row.get("hostname") or event.get("source", {}).get("host"),
                               "message": str(event.get("reason") or "") + " " + str(event.get("message") or ""), "source": source})
                retained += 1
            elif "logs" in name:
                raw_time = row.get("time") if dataset == "openrca2" else row.get("_time_")
                if raw_time is None:
                    continue
                time_ns = int(raw_time) if dataset == "openrca2" else iso_ns(str(raw_time))
                if not begin <= time_ns < end:
                    continue
                events.append({"time_ns": time_ns,
                               "entity": row.get("service_name") if dataset == "openrca2" else row.get("_container_name_"),
                               "scope": "component", "host": row.get("attr.k8s.node.name") if dataset == "openrca2" else row.get("__tag__:_node_name_"),
                               "message": str(row.get("message") if dataset == "openrca2" else row.get("content") or ""), "source": source})
                retained += 1
            # Raw source alerts are intentionally not used to choose the root.
        counts[name + ":source_rows"] = count
        counts[name + ":retained_rows"] = retained
    return {"context": context, "metrics": metrics, "spans": spans, "events": events,
            "coverage": dict(counts), "unavailable": unavailable}
