"""Offline diagnosis matching. Called only after all predictions are sealed.

This reproduces the four structured diagnosis dimensions from Agent RCA Bench,
using exact declared identities. It does not claim to reproduce provider/tool
eligibility, SQL evidence verification, latency, or the Capability index.
"""
from __future__ import annotations

import math
from collections import Counter


def score_case(prediction: dict, expected: dict) -> dict:
    diagnosis = prediction.get("diagnosis") or {}
    scope_ok = diagnosis.get("causal_scope") == expected["causal_scope"]
    if expected["causal_scope"] == "dependency_edge":
        locus_ok = (diagnosis.get("causal_component") is None
                    and diagnosis.get("edge_source") == expected["edge_source"]
                    and diagnosis.get("edge_destination") == expected["edge_destination"])
    else:
        locus_ok = (diagnosis.get("causal_component") == expected["causal_component"]
                    and diagnosis.get("edge_source") is None and diagnosis.get("edge_destination") is None)
    accepted = {expected["mechanism_code"], *(x["mechanism_code"] for x in expected.get("direct_log_mechanism_evidence", []))}
    mechanism_ok = diagnosis.get("mechanism_code") in accepted
    category_ok = diagnosis.get("fault_category") == expected["fault_category"]
    return {"scope_match": scope_ok, "location_match": scope_ok and locus_ok,
            "mechanism_match": mechanism_ok, "fault_category_match": category_ok,
            "diagnosis_correct": bool(scope_ok and locus_ok and mechanism_ok and category_ok),
            "abstained": not bool(diagnosis), "runner_error": prediction.get("runner_error"),
            "expected": {k: expected.get(k) for k in ("causal_scope", "causal_component", "edge_source", "edge_destination", "mechanism_code", "fault_category")},
            "predicted": diagnosis or None}


def wilson(successes: int, count: int) -> list[float] | None:
    if not count:
        return None
    z = 1.959963984540054
    p = successes / count
    denom = 1 + z*z/count
    center = (p + z*z/(2*count)) / denom
    half = z * math.sqrt(p*(1-p)/count + z*z/(4*count*count)) / denom
    return [round(max(0, center-half), 6), round(min(1, center+half), 6)]


def aggregate(records: list[dict]) -> dict:
    # Repetitions check determinism; they do not multiply independent cases.
    first = [r for r in records if r["repetition"] == 0]
    groups = {"all": first}
    for dataset in sorted({r["dataset"] for r in first}):
        groups[dataset] = [r for r in first if r["dataset"] == dataset]
    for mechanism in sorted({r["score"]["expected"]["mechanism_code"] for r in first}):
        groups[mechanism] = [r for r in first if r["score"]["expected"]["mechanism_code"] == mechanism]
    result = {}
    for name, rows in groups.items():
        n = len(rows)
        ok = sum(r["score"]["diagnosis_correct"] for r in rows)
        result[name] = {"independent_cases": n, "correct": ok, "accuracy": ok/n if n else None,
                        "accuracy_wilson_95": wilson(ok, n),
                        "location_correct": sum(r["score"]["location_match"] for r in rows),
                        "mechanism_correct": sum(r["score"]["mechanism_match"] for r in rows),
                        "abstentions": sum(r["score"]["abstained"] for r in rows),
                        "runner_errors": sum(bool(r["score"]["runner_error"]) for r in rows)}
    return result
