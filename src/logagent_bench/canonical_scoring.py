"""Offline validation with the pinned upstream diagnosis scorer, unchanged."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .datasets import ROOT, BENCHMARK_REVISION, cohort


def official_diagnosis_score(prediction, expected):
    from agent_rca_bench.contracts import Diagnosis, AgentRun, AgentUsage, Visibility, ApiTransport
    from agent_rca_bench.datasets.openrca2_transfer import TransferCaseSpec
    from agent_rca_bench.transfer_scorer import evaluate_transfer_run

    reference = TransferCaseSpec.model_validate({k:v for k,v in expected.items() if k != "dataset"})
    value = prediction.get("diagnosis")
    # Construct the scorer's data carrier only. No provider is invoked and no
    # runner or citation eligibility is claimed from this offline projection.
    diagnosis = None if not value else Diagnosis.model_validate({**value, "fault_type": value["mechanism_code"],
        "confidence": 0, "explanation": "Offline deterministic diagnosis-field validation only", "evidence": []})
    run = AgentRun(run_id=reference.opaque_case_id, visibility=Visibility.RAW, model="offline-python-projection",
        api_transport=ApiTransport.OPENAI_RESPONSES, reasoning_effort="medium", max_output_tokens=16384,
        diagnosis=diagnosis, tool_calls=[], usage=AgentUsage(), elapsed_seconds=0, responses=[])
    result = evaluate_transfer_run(run, reference, expected_model=run.model, expected_transport=run.api_transport,
        expected_reasoning_effort=run.reasoning_effort, expected_max_output_tokens=16384, max_tool_calls=48)
    return {"diagnosis_correct": result.diagnosis_correct, "location_match": result.causal_locus_match and result.causal_scope_match,
            "scope_match": result.causal_scope_match, "mechanism_match": result.mechanism_code_match,
            "fault_category_match": result.fault_category_match,
            "accepted_alternative_mechanisms": [str(x.mechanism_code) for x in reference.direct_log_mechanism_evidence],
            "source_identity_aliases_respected": True, "evaluation_scope": "diagnosis fields only"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=ROOT / "results/v1/results.json")
    p.add_argument("--output", type=Path, default=ROOT / "results/v1/upstream_scorer_validation.json")
    args = p.parse_args()
    report = json.loads(args.input.read_text())
    references = {c["opaque_case_id"]: c for c in cohort()}
    records = [{"case_id": r["case_id"], **official_diagnosis_score(r["prediction"], references[r["case_id"]])}
               for r in report["records"] if r["repetition"] == 0]
    result = {"upstream_commit": BENCHMARK_REVISION, "evaluation": "diagnosis fields only; not LLM or citation success",
              "correct": sum(r["diagnosis_correct"] for r in records), "cases": len(records), "records": records}
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k != "records"}, indent=2))


if __name__ == "__main__":
    main()
