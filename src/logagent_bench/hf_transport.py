"""Local Hugging Face weights behind the original structured tool loop.

This is a local serialization adapter, not an Anthropic model or paid API.
The SDK's Anthropic message branch is reused without replacing its loop,
query execution, output validation, citation feedback, or limits.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

LOCK = threading.RLock()
FORMAT = """Local tool transport: choose one available tool per response. Return a JSON object
with exactly two keys: tool_name and arguments. arguments must match that tool's input_schema.
Use submit_diagnosis to finish. Tool results and validation errors below are actual execution
feedback. Do not invent tool results or query IDs. /no_think"""


def plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    return value


def tool_envelope_schema(tools):
    return {"anyOf": [{
        "type": "object", "properties": {
            "tool_name": {"const": tool["name"]}, "arguments": tool["input_schema"],
        }, "required": ["tool_name", "arguments"], "additionalProperties": False,
    } for tool in tools]}


def serialize_request(system, tools, messages):
    # The upstream SRE system prompt is unchanged. Transport instructions and
    # complete, unmodified tool schemas are common to both experimental arms.
    prompt = "<|im_start|>system\n" + system + "<|im_end|>\n"
    prompt += "<|im_start|>user\n" + FORMAT + "\nAvailable tools:\n"
    prompt += json.dumps(tools, ensure_ascii=False, separators=(",", ":")) + "<|im_end|>\n"
    for message in messages:
        role, content = message["role"], plain(message["content"])
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
    return prompt + "<|im_start|>assistant\n<think>\n\n</think>\n\n"


class LocalToolClient:
    def __init__(self, model, config, private_dir: Path, seed: int):
        self.model, self.config, self.private_dir, self.seed = model, config, private_dir, seed
        self.messages = self
        self.calls = 0
        self.trace = []
        self._grammar = None
        self._tools_hash = None
        self.private_dir.mkdir(parents=True, exist_ok=False)
        self.model.reset()

    def create(self, *, model, max_tokens, system, tools, messages, **kwargs):
        from anthropic.types import Message
        from llama_cpp import LlamaGrammar

        prompt = serialize_request(system, tools, messages)
        tokens = len(self.model.tokenize(prompt.encode(), add_bos=True))
        if tokens + max_tokens > self.config["context_tokens"]:
            raise RuntimeError("Local HF context capacity exhausted; transcript is not truncated")
        schema = tool_envelope_schema(tools)
        tools_hash = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        if self._grammar is None:
            self._grammar = LlamaGrammar.from_json_schema(json.dumps(schema), verbose=False)
            self._tools_hash = tools_hash
        elif self._tools_hash != tools_hash:
            raise ValueError("Tool schemas changed during one investigation")
        started = time.perf_counter()
        ordinal = self.calls
        self.calls += 1
        completion = self.model.create_completion(
            prompt=prompt, max_tokens=max_tokens, grammar=self._grammar,
            temperature=self.config["temperature"], top_p=self.config["top_p"],
            top_k=self.config["top_k"], min_p=0, repeat_penalty=1,
            seed=self.seed + ordinal, stop=["<|im_end|>"],
        )
        # Provider payloads stay private; public results retain only hashes,
        # timing, token counts, diagnoses and sanitized execution metadata.
        (self.private_dir / f"turn-{ordinal:02d}.json").write_text(json.dumps(
            {"prompt": prompt, "completion": completion}, ensure_ascii=False
        ), encoding="utf-8")
        choice = completion["choices"][0]
        usage = completion["usage"]
        record = {"turn": ordinal, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                  "response_sha256": hashlib.sha256(choice["text"].encode()).hexdigest(),
                  "prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"],
                  "elapsed_seconds": round(time.perf_counter()-started, 6),
                  "finish_reason": choice["finish_reason"]}
        self.trace.append(record)
        if choice["finish_reason"] == "length":
            raise RuntimeError("Local HF output token ceiling exhausted; output is not repaired")
        value = json.loads(choice["text"])
        if value["tool_name"] not in {tool["name"] for tool in tools}:
            raise ValueError("Model selected an unavailable tool")
        print(f"[HF tool turn] {ordinal+1} tool={value['tool_name']} tokens={usage['completion_tokens']} elapsed={record['elapsed_seconds']:.2f}s", flush=True)
        return Message.model_validate({
            "id": f"local-hf-{ordinal}", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "tool_use", "id": f"local-call-{ordinal}",
                         "name": value["tool_name"], "input": value["arguments"]}],
            "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"]},
        })


@contextmanager
def local_transport(client):
    import agent_rca_bench.agent as agent
    # One investigation per process. Never fall through to a network client.
    with LOCK, patch.object(agent, "_anthropic_client", return_value=client):
        yield
