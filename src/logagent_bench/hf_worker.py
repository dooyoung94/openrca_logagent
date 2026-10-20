"""Resident local model; receives frozen telemetry packets, never answer keys."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from .worker import deny_label_reads

SYSTEM = """You diagnose software incidents from telemetry evidence. Select ONE best-supported causal locus and mechanism, or abstain. Distinguish a faulty component, a directed dependency edge, and an infrastructure node. An affected caller is not automatically the cause. Use exact observed entity names. Never invent an entity. Candidate hints can be wrong; verify them against the common evidence. Metrics retain their native units. Distinguish CPU saturation, memory pressure, disk I/O degradation, restart, unavailability, configuration error, and call-path delay. A dependency edge needs both endpoints. Cite evidence IDs from the supplied summary. Return the required JSON only. /no_think"""

SCHEMA = {"type": "object", "properties": {
    "abstain": {"type": "boolean"},
    "causal_scope": {"type": "string", "enum": ["component", "dependency_edge", "infrastructure_node"]},
    "causal_component": {"type": ["string", "null"]},
    "edge_source": {"type": ["string", "null"]},
    "edge_destination": {"type": ["string", "null"]},
    "mechanism_code": {"type": "string", "enum": ["cpu_saturation", "memory_pressure",
        "call_path_delay", "disk_io_degradation", "workload_restart", "host_unavailable",
        "dependency_unavailable", "configuration_error"]},
    "fault_category": {"type": "string", "enum": ["cpu", "memory", "delay", "disk", "other"]},
    "evidence_ids": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 4}},
    "explanation": {"type": "string", "maxLength": 160}},
    "required": ["abstain", "causal_scope", "causal_component", "edge_source", "edge_destination",
                 "mechanism_code", "fault_category", "evidence_ids", "explanation"],
    "additionalProperties": False}


def compact_evidence(common):
    """Lossless table serialization: headers once, identical values/order."""
    keys = ("n", "p50", "p95", "min", "max")
    def stat(value):
        return [value.get(k) for k in keys]
    result = {k: common[k] for k in ("context", "notes", "available_counts")}
    result["stat_columns"] = list(keys)
    result["metrics_columns"] = ["evidence_id", "scope", "entity", "metric", "normal_stats", "incident_stats"]
    result["metrics"] = [[r["evidence_id"], r["scope"], r["entity"], r["metric"],
                           stat(r["normal"]), stat(r["incident"])] for r in common["metrics"]]
    result["edges_columns"] = ["evidence_id", "source", "destination", "signal", "normal_stats", "incident_stats"]
    result["edges"] = [[r["evidence_id"], r["source"], r["destination"], r["signal"],
                         stat(r["normal"]), stat(r["incident"])] for r in common["edges"]]
    result["services_columns"] = ["evidence_id", "entity", "signal", "normal_stats", "normal_errors", "incident_stats", "incident_errors"]
    result["services"] = [[r["evidence_id"], r["entity"], r["signal"], stat(r["normal"]), r["normal"]["errors"],
                            stat(r["incident"]), r["incident"]["errors"]] for r in common["services"]]
    result["error_templates_columns"] = ["evidence_id", "scope", "entity", "template", "normal_count", "incident_count"]
    result["error_templates"] = [[r[k] for k in result["error_templates_columns"]] for r in common["error_templates"]]
    return result


def prompt_for(packet, arm):
    # Header/row encoding changes serialization only; no observation is dropped.
    supplied = {"common_evidence": compact_evidence(packet["common_evidence"])}
    if arm == "logagent_llm":
        supplied.update({"logagent_hints": packet["logagent_hints"], "hint_note": packet["hint_note"]})
    elif arm != "summary_llm":
        raise ValueError("Unknown local HF arm")
    user = "Diagnose this incident. Output schema: "+json.dumps(SCHEMA, separators=(",", ":"))
    user += "\nEvidence:\n"+json.dumps(supplied, ensure_ascii=False, separators=(",", ":"))+"\n/no_think"
    # Qwen's documented ChatML format with the non-thinking prefix. Do not
    # rely on a library's changing default chat template.
    return ("<|im_start|>system\n"+SYSTEM+"<|im_end|>\n<|im_start|>user\n"+user
            +"<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")


def diagnosis_from_output(value):
    if value["abstain"]:
        return None
    # No repairing entity names, selecting a hint, or mapping mechanisms after
    # generation. Category and directed endpoints remain the model's answer.
    return {k: value[k] for k in ("causal_scope", "causal_component", "edge_source",
                                "edge_destination", "mechanism_code", "fault_category")}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-root", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    args = p.parse_args()
    sys.addaudithook(deny_label_reads)
    from llama_cpp import Llama, LlamaGrammar
    protocol = json.loads((args.run_root / "protocol.json").read_text())
    config = protocol["configuration"]
    model = Llama(model_path=str(args.model), n_ctx=config["context_tokens"],
        n_batch=512, n_threads=8, n_threads_batch=8, verbose=False)
    grammar = LlamaGrammar.from_json_schema(json.dumps(SCHEMA), verbose=False)
    jobs = []
    for case in protocol["cases"]:
        packet_file = args.run_root / "packets" / (case["case_id"]+".json")
        packet = json.loads(packet_file.read_text())
        for repetition, seed in enumerate(config["seeds"]):
            # Alternate order by case and repetition, fixed before execution.
            arms = config["arms"] if (case["ordinal"]+repetition)%2 == 0 else list(reversed(config["arms"]))
            for arm in arms:
                prompt = prompt_for(packet, arm)
                count = len(model.tokenize(prompt.encode(), add_bos=True))
                if count+config["max_output_tokens"] > config["context_tokens"]:
                    raise ValueError("Preflight context overflow; no model cells executed")
                jobs.append((case, repetition, seed, arm, prompt, count))
    preflight = {"planned_cells": len(jobs), "max_prompt_tokens": max(j[-1] for j in jobs),
                 "min_prompt_tokens": min(j[-1] for j in jobs)}
    (args.run_root / "context_preflight.json").write_text(json.dumps(preflight, indent=2))
    print("[HF preflight] "+json.dumps(preflight), flush=True)
    output = args.run_root / "predictions"
    output.mkdir()
    previous_case = None
    for ordinal, (case, repetition, seed, arm, prompt, prompt_tokens) in enumerate(jobs):
        name = f"{case['case_id']}-{arm}-rep{repetition}"
        destination = output / (name+".json")
        (output / (name+".started")).write_text(str(time.time()))
        started = time.perf_counter()
        result = {"case_id": case["case_id"], "dataset": case["dataset"], "arm": arm,
                  "repetition": repetition, "seed": seed, "diagnosis": None,
                  "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                  "prompt_tokens_preflight": prompt_tokens, "llm_used": True}
        try:
            # Within one case, llama.cpp reuses only the exact token prefix of
            # the new prompt. Divergent suffix/generated tokens are removed by
            # its prefix matcher. Reset across cases as an additional boundary.
            if previous_case != case["case_id"]:
                model.reset()
            previous_case = case["case_id"]
            completion = model.create_completion(prompt=prompt, max_tokens=config["max_output_tokens"],
                temperature=config["temperature"], top_p=config["top_p"], top_k=config["top_k"],
                min_p=0, repeat_penalty=1, seed=seed, stop=["<|im_end|>"], grammar=grammar)
            (output / (name+".response.json")).write_text(json.dumps(completion, ensure_ascii=False))
            choice = completion["choices"][0]
            result["usage"] = completion["usage"]
            result["finish_reason"] = choice["finish_reason"]
            if choice["finish_reason"] == "length":
                raise ValueError("Output budget exhausted; retained as failure")
            value = json.loads(choice["text"])
            result["diagnosis"] = diagnosis_from_output(value)
            result["submitted_evidence_ids"] = value["evidence_ids"]
            result["response_sha256"] = hashlib.sha256(choice["text"].encode()).hexdigest()
        except Exception as error:
            result["runner_error"] = type(error).__name__+": "+str(error)[:300]
        result["elapsed_seconds"] = round(time.perf_counter()-started, 6)
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"[HF inference] {ordinal+1}/{len(jobs)} {name} status={'ERROR' if result.get('runner_error') else 'ABSTAIN' if not result['diagnosis'] else 'GENERATED'} elapsed={result['elapsed_seconds']:.2f}s", flush=True)


if __name__ == "__main__":
    main()
