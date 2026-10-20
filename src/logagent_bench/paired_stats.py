"""Paired inference with incident-level resampling, never repetition inflation."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from statistics import mean


def sign_p(positive, negative):
    n = positive + negative
    if not n:
        return 1.0
    small = min(positive, negative)
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(small + 1)) / (2**n))


def holm(values):
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    corrected, previous = [0.0] * len(values), 0.0
    for rank, (index, value) in enumerate(ordered):
        previous = max(previous, min(1.0, (len(values) - rank) * value))
        corrected[index] = previous
    return corrected


def case_pair_effect(baseline, treatment):
    if set(baseline) != set(treatment):
        raise ValueError("Paired case sets differ; missing cases must not be dropped")
    differences = [mean(treatment[k]) - mean(baseline[k]) for k in sorted(baseline)]
    if not differences:
        return {"status": "NOT_ESTIMABLE", "difference": None, "p": None}
    rng = random.Random(20261020)
    bootstrap = sorted(mean(rng.choices(differences, k=len(differences))) for _ in range(5000))
    positive, negative = sum(x > 0 for x in differences), sum(x < 0 for x in differences)
    return {"independent_cases": len(differences), "baseline_accuracy": mean(mean(v) for v in baseline.values()),
            "treatment_accuracy": mean(mean(v) for v in treatment.values()), "difference": mean(differences),
            "paired_case_bootstrap_95": [bootstrap[124], bootstrap[4874]],
            "positive_cases": positive, "negative_cases": negative, "tied_cases": len(differences)-positive-negative,
            "exact_sign_p": sign_p(positive, negative),
            "test_estimand": "sign of within-case mean correctness difference; not a test of the mean magnitude"}


def compare_report(report):
    if report.get("completed_cells") != report.get("expected_cells"):
        return {"status": "INCOMPLETE_NO_COMPARATIVE_CLAIM", "completed_cells": report.get("completed_cells", 0),
                "expected_cells": report.get("expected_cells"), "accuracy": None}
    records = report.get("records", [])
    if len(records) != report["expected_cells"]:
        raise ValueError("Completed cell count differs from recorded cells")
    grouped = defaultdict(lambda: defaultdict(list))
    unique = set()
    for row in records:
        key = (row["model"], row["case_id"], row["arm"], row["repetition"])
        if key in unique:
            raise ValueError("Duplicate cell")
        unique.add(key)
        grouped[(row["model"], row["arm"])][row["case_id"]].append(float(row["evaluation"]["diagnosis_correct"]))
    results = []
    for model in sorted(m["model"] for m in report["models"]):
        baseline, treatment = grouped[(model, "raw")], grouped[(model, "logagent")]
        if any(len(v) != 2 for v in [*baseline.values(), *treatment.values()]):
            raise ValueError("Every case must retain both repetitions")
        effect = case_pair_effect(baseline, treatment)
        results.append({"model": model, "baseline": "raw", "treatment": "logagent", **effect})
    adjusted = holm([r["exact_sign_p"] for r in results])
    for row, p in zip(results, adjusted):
        row.update(holm_p=p, significance_supported=p < .05, correction_family="primary accuracy; one endpoint per model")
    return {"status": "COMPLETE_PAIRED_ANALYSIS", "protocol_sha256": report["protocol_sha256"], "models": results,
            "historical_baseline_pooled": False, "repetitions_counted_as_independent": False}
