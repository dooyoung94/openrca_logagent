"""Match the upstream descriptive denominators without filling unrun scores."""
import json
from collections import defaultdict

from .datasets import ROOT


def summarize(report):
    historical = json.loads((ROOT / "results/baseline_public.json").read_text())["diagnosis_by_dataset"]
    selected_models = {m["model"] for m in report["models"]}
    expected = defaultdict(set)
    for cell in report["schedule"]:
        expected[(cell["dataset"], cell["arm"])].add(cell["cell_index"])
    completed = defaultdict(dict)
    for row in report.get("records", []):
        key = row["dataset"], row["arm"]
        index = row["cell_index"]
        if index not in expected[key] or index in completed[key]:
            raise ValueError("Duplicate or unscheduled LLM cell")
        completed[key][index] = bool(row["evaluation"]["diagnosis_correct"])
    rows = []
    for (dataset, arm), indices in sorted(expected.items()):
        n, done = len(indices), completed[(dataset, arm)]
        old = historical[dataset]
        old_correct = None if arm == "logagent" else sum(old["diagnosis_correct_by_model"][m][arm] for m in selected_models)
        old_count = old["cases"] * 2 * len(selected_models)
        rows.append({"dataset": dataset, "arm": arm, "expected_runs": n, "completed_runs": len(done),
                     "correct": sum(done.values()) if len(done) == n else None,
                     "accuracy": sum(done.values())/n if len(done) == n else None,
                     "status": "COMPLETE" if len(done) == n else "NOT_COMPLETE_NO_ACCURACY",
                     "historical_public_reference_correct": old_correct,
                     "historical_public_reference_runs": old_count if old_correct is not None else None,
                     "historical_public_reference_accuracy": old_correct/old_count if old_correct is not None else None,
                     "statistics_role": "descriptive aggregation across models; inference remains paired within model"})
    return rows
