"""Ollama client — two-model routing, JSON-schema enforcement, one retry, audit hooks.

Hard rules implemented here (architecture doc):
- Only qwen3:14b ("main") and gemma3:4b ("fast") may ever be invoked.
- /no_think on routine main-model calls; thinking only when explicitly requested.
- Structured output: format=json + jsonschema validation + exactly ONE retry,
  then LLMOutputError → caller escalates to a human (never guesses).
- Prompt-injection hygiene: source text is always wrapped in delimiters and the
  system prompts instruct the model to treat it as untrusted data (spec §26).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Literal

import jsonschema
import requests

from .config import CFG, Config

log = logging.getLogger("orchestrator.ollama")

Role = Literal["main", "fast"]

MODELS: dict[Role, str] = {"main": CFG.model_main, "fast": CFG.model_fast}

ALLOWED_MODELS = frozenset(MODELS.values())

UNTRUSTED_OPEN = "<<<UNTRUSTED_SOURCE_CONTENT"
UNTRUSTED_CLOSE = "END_UNTRUSTED_SOURCE_CONTENT>>>"


class LLMOutputError(RuntimeError):
    """Raised after the single permitted retry still fails validation."""


def wrap_untrusted(text: str) -> str:
    return f"{UNTRUSTED_OPEN}\n{text}\n{UNTRUSTED_CLOSE}"


def call_llm(
    role: Role,
    system_prompt: str,
    user_prompt: str,
    *,
    json_schema: dict | None = None,
    thinking: bool = False,
    num_ctx: int = 8192,
    cfg: Config = CFG,
) -> str | dict[str, Any]:
    """Call the assigned model. Returns str, or validated dict when json_schema given."""
    model = MODELS[role]
    assert model in ALLOWED_MODELS, f"model {model} not permitted"

    # qwen3 thinking control: native Ollama `think` flag (reliable under
    # structured-output decoding, unlike the /no_think text directive)
    payload: dict[str, Any] = {
        "model": model,
        "system": system_prompt,
        "prompt": user_prompt,
        "stream": False,
        "think": bool(thinking),
        "options": {"num_ctx": num_ctx, "temperature": 0.1},
    }
    if json_schema is not None:
        payload["format"] = json_schema  # structured output: schema enforced at sampler level

    last_err: Exception | None = None
    for attempt in range(cfg.llm_max_retries + 1):
        t0 = time.monotonic()
        try:
            r = requests.post(
                f"{cfg.ollama_url}/api/generate", json=payload, timeout=cfg.llm_timeout_s
            )
            r.raise_for_status()
            resp = r.json()["response"]
            latency = time.monotonic() - t0
            log.info("llm_call model=%s attempt=%d latency=%.1fs", model, attempt, latency)
            if json_schema is None:
                return resp
            data = _parse_json(resp)
            jsonschema.validate(data, json_schema)
            return data
        except (requests.RequestException, ValueError, jsonschema.ValidationError) as e:
            last_err = e
            log.warning("llm attempt %d failed for %s: %s", attempt, model, e)
            # tighten the prompt for the single retry
            payload["prompt"] = (
                user_prompt
                + "\n\nREMINDER: output ONLY valid JSON matching the required schema. "
                "No prose, no markdown fences."
            )
    raise LLMOutputError(f"{model} failed after retry: {last_err}")


def _parse_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])
