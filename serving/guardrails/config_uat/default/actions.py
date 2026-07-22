# AI Guardrail Policy v1.1 Section 10.1 - Layer 2 structured audit logging
# (UAT rollout, 22-Jul-2026).
#
# Emits ONE structured log line per rail decision (input/output), reusing the
# Layer 1 OTel -> Loki pipe already deployed and verified (see RUNBOOK.md
# Section 6.5) - no new export path, no new container. This file is
# auto-discovered by NeMo Guardrails because it is named exactly `actions.py`
# inside the config directory (confirmed: "Actions defined in actions.py or
# the actions/ package are automatically registered when the configuration
# is loaded" - NeMo Guardrails custom-actions docs).
#
# Fields match Section 10.1 exactly: category, severity, action taken,
# timestamp (via the log record itself), model, consumer, environment.
#
# Privacy rule (policy Section 10.1): for allowed/normal traffic, only
# metadata is logged - NOT message content. For flagged/blocked events, the
# actual prompt/response text is also captured, since a human needs it to
# review whether the guardrail called the block correctly.
#
# v1 scope, stated explicitly: category is determined via keyword-heuristic
# matching against the blocked text, NOT a second LLM classification call.
# This deliberately avoids adding a new LLM call - and a new, unverified
# LLM-injection pattern - to the safety-critical block/allow path on first
# rollout. The actual blocked text is always logged alongside the category,
# so a human reviewer is never dependent on the heuristic being precise.
# Swapping in an LLM-based classifier later is a self-contained follow-up,
# not a redesign - it would only change `_classify()`.
#
# "Consumer" (which caller - NL-Proposal-Builder vs which agent) is read from
# the shared $context dict, which NeMo Guardrails populates from the client's
# `guardrails.context` request field if sent (see server/schemas: there is no
# top-level OpenAI "user" field read anywhere in nemoguardrails' server code -
# confirmed from source - `guardrails.context` is the only supported
# passthrough). No client sends this yet (NL-Proposal-Builder integration is
# Phase 5, not built), so this reads as "unspecified" until then - a known,
# documented gap, not an oversight.

import logging
import os
from typing import Optional

from nemoguardrails.actions import action

audit_log = logging.getLogger("guardrail_audit")


def _parse_environment() -> str:
    # Reuses the OTEL_RESOURCE_ATTRIBUTES env var already set for Layer 1
    # (see docker-compose.yml) instead of adding a second, redundant env var
    # for the same fact.
    raw = os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "")
    for pair in raw.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            if k.strip() == "deployment.environment":
                return v.strip()
    return os.environ.get("OTEL_SERVICE_NAME", "unknown")


ENVIRONMENT = _parse_environment()
# Label only, for the log line - does not affect model routing. Set via
# GUARDRAILS_MAIN_MODEL in docker-compose.yml; must match config.yml's
# `type: main` model.
MAIN_MODEL = os.environ.get("GUARDRAILS_MAIN_MODEL", "unknown")

# Category keyword heuristics, keyed to AI Guardrail Policy v1.0 Sections 2,
# 6, 7's block categories (see prompts.yml for the exact rules these mirror).
# Coarse by design (v1 scope, see module docstring) - the actual blocked text
# is always logged alongside the category so a human reviewer isn't
# dependent on this label being perfectly precise.
_CATEGORY_KEYWORDS = {
    "weapons_drugs_cbrn": [
        "bomb", "explosive", "weapon", "poison", "nerve agent", "synthesize",
        "narcotic", "chemical weapon", "biological weapon", "nuclear device",
    ],
    "self_harm": [
        "suicide", "self-harm", "self harm", "kill myself", "end my life",
    ],
    "malware_exploit": [
        "malware", "ransomware", "exploit", "keylogger", "sql injection",
        "credential harvest", "phishing kit",
    ],
    "data_leak": [
        "credential", "api key", "internal ip", "password",
        "infrastructure detail", "internal system",
    ],
    "violence": [
        "kill", "attack", "murder", "assault", "graphic violence",
    ],
    "hate_speech": [
        "hate speech", "racial slur", "harassment", "ethnic slur",
    ],
    "sexual_content": [
        "sexual", "explicit content", "porn",
    ],
    "extremist_content": [
        "extremist", "terrorist", "hate ideology", "radicalize",
    ],
    "prompt_injection": [
        "ignore previous instructions", "ignore all previous",
        "developer mode", "you are now", "system prompt", "bypass",
    ],
}

_SEVERITY_MAP = {
    "weapons_drugs_cbrn": "critical",
    "self_harm": "critical",
    "malware_exploit": "critical",
    "data_leak": "critical",
    "violence": "high",
    "hate_speech": "high",
    "extremist_content": "high",
    "sexual_content": "medium",
    "prompt_injection": "medium",
    "uncategorized": "medium",
}


def _classify(text: Optional[str]) -> str:
    if not text:
        return "uncategorized"
    lowered = text.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return category
    return "uncategorized"


def _get_consumer(context: dict) -> str:
    return context.get("consumer", "unspecified")


def _emit(rail: str, allowed: bool, consumer: str, content: Optional[str]) -> None:
    action_taken = "allowed" if allowed else "blocked"
    extra = {
        "audit_rail": rail,
        "audit_action": action_taken,
        "audit_environment": ENVIRONMENT,
        "audit_model": MAIN_MODEL,
        "audit_consumer": consumer,
    }
    message = f"guardrail_decision rail={rail} action={action_taken} environment={ENVIRONMENT}"

    if not allowed:
        category = _classify(content)
        severity = _SEVERITY_MAP.get(category, "medium")
        extra["audit_category"] = category
        extra["audit_severity"] = severity
        # Privacy rule (policy Section 10.1): content captured ONLY for
        # blocked events, never for allowed traffic.
        extra["audit_content"] = content or ""
        message += f" category={category} severity={severity}"

    audit_log.info(message, extra=extra)


@action(name="audit_log_input", is_system_action=True)
async def audit_log_input(context: Optional[dict] = None, allowed: bool = True, **kwargs):
    context = context or {}
    _emit("input", allowed, _get_consumer(context), context.get("user_message"))
    return True


@action(name="audit_log_output", is_system_action=True)
async def audit_log_output(context: Optional[dict] = None, allowed: bool = True, **kwargs):
    context = context or {}
    _emit("output", allowed, _get_consumer(context), context.get("bot_message"))
    return True
