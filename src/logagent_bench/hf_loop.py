"""Frozen public-HF Raw versus LogAgent tool-loop experiment configuration."""
from __future__ import annotations

from .hf_local import MODEL

CONFIG = {
    "arms": ["raw_hf", "logagent_hf"], "seeds": [17, 29],
    "temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0,
    "context_tokens": 32768, "max_output_tokens": 16384,
    "max_tool_calls": 48, "max_turns": 58, "threads": 4,
    "thinking": False, "candidate_limit": 5,
    "actual_transport": "llama-cpp-local-json-tool-bridge",
    "sdk_transport_branch": "anthropic-messages; serialization only, no Anthropic model or network call",
    "tool_choice": "one model-selected tool per turn; grammar uses unchanged original tool argument schemas",
    "kv_cache": "reset for every cell; exact-prefix reuse within that cell only",
    "seed_policy": "cell seed plus zero-based provider turn",
    "context_overflow": "fail cell without dropping transcript or reducing output ceiling",
    "post_run_answer_repair": False, "failed_cell_retry": False,
    "case_scoring": "after all four case predictions are sealed; frozen source commit across all jobs",
    "aggregate_scoring": "independent diagnosis-field rescore after all 56 predictions are verified",
}

EXPERIMENT = "hf-original-tool-loop-v1"
