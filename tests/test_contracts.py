from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from logagent_bench.adapter import iter_records, load_bundle, service_alias_index, resolve_service
from logagent_bench.datasets import ROOT
from logagent_bench.engine import evaluate
from logagent_bench.scoring import aggregate, score_case
from logagent_bench.worker import deny_label_reads


POLICY = yaml.safe_load((ROOT / "configs/hypothesis.yaml").read_text())


def empty_bundle():
    return {"context": {"case_id": "opaque-test", "dataset": "openrca2", "normal_window": [0, 100], "abnormal_window": [100, 200]},
            "metrics": [], "spans": [], "events": [], "coverage": {}}


def cpu_bundle():
    b = empty_bundle()
    for index, (t, value) in enumerate([(10, .01), (20, .02), (110, .9), (120, 1.0)]):
        b["metrics"].append({"scope": "component", "entity": "service-a", "metric": "container.cpu.usage",
                             "value": value, "time_ns": t*10**9, "source": str(index)})
    return b


class ContractTests(unittest.TestCase):
    def test_blank_restart_service_resolves_by_observed_pod_identity(self):
        row = {"service_name": "api", "attr.k8s.namespace.name": "test", "attr.k8s.pod.name": "opaque-pod"}
        aliases = service_alias_index([row])
        self.assertEqual(resolve_service({**row, "service_name": ""}, aliases), "api")
        self.assertIsNone(resolve_service({**row, "service_name": "", "attr.k8s.pod.name": "api-other"}, aliases))
        ambiguous = service_alias_index([row, {**row, "service_name": "other"}])
        self.assertIsNone(resolve_service({**row, "service_name": ""}, ambiguous))

    def test_cpu_transition_localizes_cause(self):
        result = evaluate(cpu_bundle(), POLICY)
        self.assertEqual(result["diagnosis"]["causal_component"], "service-a")
        self.assertEqual(result["diagnosis"]["mechanism_code"], "cpu_saturation")
        self.assertEqual([x["slice_id"] for x in result["time_segments"]], ["T1", "T2", "T3", "T4"])
        self.assertFalse(result["selected_thread"]["score_is_probability"])

    def test_stable_high_cpu_is_not_new_fault(self):
        bundle = cpu_bundle()
        for row in bundle["metrics"]:
            row["value"] = .95
        self.assertIsNone(evaluate(bundle, POLICY)["diagnosis"])

    def test_missing_baseline_abstains(self):
        bundle = cpu_bundle()
        bundle["metrics"] = bundle["metrics"][2:]
        self.assertEqual(evaluate(bundle, POLICY)["status"], "ABSTAIN_INSUFFICIENT_EVIDENCE")

    def test_duplicates_do_not_improve_support(self):
        original = cpu_bundle()
        repeated = copy.deepcopy(original)
        repeated["metrics"] *= 10
        a, b = evaluate(original, POLICY), evaluate(repeated, POLICY)
        self.assertEqual(a["selected_thread"]["score"], b["selected_thread"]["score"])
        self.assertEqual(a["candidate_count"], b["candidate_count"])
        self.assertEqual(a["diagnosis"], b["diagnosis"])

    def test_future_metrics_cannot_change_diagnosis(self):
        bundle = cpu_bundle()
        row = copy.deepcopy(bundle["metrics"][0])
        row.update(entity="wrong-future-cause", value=999, time_ns=200*10**9)
        bundle["metrics"].append(row)
        self.assertEqual(evaluate(bundle, POLICY)["diagnosis"], evaluate(cpu_bundle(), POLICY)["diagnosis"])

    def test_parent_identity_required_for_edge(self):
        bundle = empty_bundle()
        for t in [10, 20, 110, 120]:
            bundle["spans"] += [{"trace": str(t), "span": "a", "parent": "", "service": "a", "operation": "/a",
                                  "kind": "Client", "time_ns": t*10**9, "end_ns": t*10**9+10**9, "error": False, "source": str(t)+"a"},
                                 {"trace": str(t), "span": "b", "parent": "missing", "service": "b", "operation": "/b",
                                  "kind": "Server", "time_ns": t*10**9+600000000, "end_ns": t*10**9+10**9, "error": False, "source": str(t)+"b"}]
        self.assertEqual(evaluate(bundle, POLICY)["ontology"]["witnessed_call_edges"], [])
        self.assertIsNone(evaluate(bundle, POLICY)["diagnosis"])

    def test_slow_server_duration_does_not_imply_network_delay(self):
        bundle = empty_bundle()
        for t in [10, 20, 110, 120]:
            start = t*10**9
            duration = 10000000 if t < 100 else 10**10
            bundle["spans"] += [{"trace": str(t), "span": "a", "parent": "", "service": "a", "operation": "/a",
                                  "kind": "Client", "time_ns": start, "end_ns": start+duration, "error": False, "source": str(t)+"a"},
                                 {"trace": str(t), "span": "b", "parent": "a", "service": "b", "operation": "/b",
                                  "kind": "Server", "time_ns": start+1000, "end_ns": start+duration, "error": False, "source": str(t)+"b"}]
        result = evaluate(bundle, POLICY)
        self.assertEqual(result["ontology"]["witnessed_call_edges"], [["a", "b"]])
        self.assertIsNone(result["diagnosis"])

    def test_nanosecond_precision_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"source.parquet"
            value = 1777717510123456789
            pq.write_table(pa.table({"time": pa.array([value], type=pa.timestamp("ns", tz="UTC"))}), path)
            self.assertEqual(next(iter_records(path))["time"], value)

    def test_labels_cannot_enter_inference_context(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            (p/"case.json").write_text(json.dumps({**empty_bundle()["context"], "mechanism_code": "cpu_saturation"}))
            with self.assertRaises(ValueError):
                load_bundle(p)
        for value in ["/case/metadata/injection.json", "/project/fixtures/selection.json", "/case/causal_graph.json"]:
            with self.assertRaises(PermissionError):
                deny_label_reads("open", (value, "r", 0))

    def test_node_and_service_granularity_are_distinct(self):
        expected = {"causal_scope": "infrastructure_node", "causal_component": "a", "mechanism_code": "cpu_saturation", "fault_category": "cpu"}
        prediction = {"diagnosis": {**expected, "causal_scope": "component"}}
        self.assertFalse(score_case(prediction, expected)["diagnosis_correct"])

    def test_directed_edges_and_abstentions_count(self):
        expected = {"causal_scope": "dependency_edge", "edge_source": "a", "edge_destination": "b", "mechanism_code": "call_path_delay", "fault_category": "delay"}
        prediction = {"diagnosis": {**expected, "edge_source": "b", "edge_destination": "a"}}
        self.assertFalse(score_case(prediction, expected)["diagnosis_correct"])
        abstention = score_case({"diagnosis": None}, expected)
        records = [{"dataset": "openrca2", "repetition": i, "score": abstention} for i in range(2)]
        report = aggregate(records)["all"]
        self.assertEqual(report["independent_cases"], 1)
        self.assertEqual(report["accuracy"], 0)
        self.assertEqual(report["abstentions"], 1)


if __name__ == "__main__":
    unittest.main()
