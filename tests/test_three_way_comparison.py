"""Guard against invalid denominators and unsupported benchmark claims."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("comparison_report", ROOT / "scripts/build_three_way_comparison.py")
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


class ComparisonIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ("experiments/three_way_comparison_protocol.json", "fixtures/openrca2-transfer-v32-selection.json",
                     "fixtures/rca100-transfer-node-selection.json", "results/v1/results.json",
                     "results/v1/upstream_scorer_validation.json", "results/baseline_public.json"):
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value))

    def test_actual_frozen_sources_and_missing_hf_have_distinct_status(self):
        report = comparison.build(self.root)
        python, treatment, control = report["methods"]
        self.assertEqual(python["results"]["all"]["correct_executions"], 22)
        self.assertEqual(python["results"]["all"]["independent_cases"], 14)
        self.assertIsNone(treatment["results"]["all"])
        self.assertIsNone(control["results"]["all"])
        self.assertEqual(report["historical_references"][0]["results"]["all"]["executions"], 168)
        self.assertIsNone(report["paper_metrics"]["python_logagent"]["EM"]["value"])

    def test_partial_hf_cells_are_not_scored_as_zero_or_excluded(self):
        spec = comparison.read(self.root / "experiments/three_way_comparison_protocol.json")["hf_measurement"]
        self.write(spec["source"], {"status": "COMPLETED", "completed_cells": 55})
        with self.assertRaisesRegex(ValueError, "fixed comparison"):
            comparison.build(self.root)

    def test_claiming_56_cells_does_not_bypass_record_validation(self):
        spec = comparison.read(self.root / "experiments/three_way_comparison_protocol.json")["hf_measurement"]
        self.write(spec["source"], {"status": "COMPLETED", "completed_cells": 56,
                   "source_run_id": spec["source_run_id"], "source_commit": spec["source_commit"],
                   "experiment": spec["experiment"], "model": {"repo_id": spec["model_repo"],
                   "revision": spec["model_revision"], "sha256": spec["model_sha256"]}, "records": []})
        with self.assertRaisesRegex(ValueError, "incomplete"):
            comparison.build(self.root)

    def test_independent_scorer_disagreement_stops_the_table(self):
        path = "results/v1/upstream_scorer_validation.json"
        source = comparison.read(self.root / path)
        source["records"][0]["diagnosis_correct"] = False
        self.write(path, source)
        with self.assertRaisesRegex(ValueError, "disagree"):
            comparison.build(self.root)

    def test_historical_wrong_denominator_stops_the_table(self):
        path = "results/baseline_public.json"
        source = comparison.read(self.root / path)
        source["diagnosis_by_dataset"]["openrca2"]["runs"]["raw"] = 119
        self.write(path, source)
        with self.assertRaisesRegex(ValueError, "denominators"):
            comparison.build(self.root)


if __name__ == "__main__":
    unittest.main()
