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
#
# INPUT RAIL - WHY THIS ISN'T A SIMPLE SECOND execute STATEMENT (found and
# fixed 22-Jul-2026 in UAT, via a real deployment test, not guessed):
# the built-in `self_check_input` action, when it blocks, returns an
# ActionResult carrying a `mask_prev_user_message` event (verified from
# nemoguardrails/library/self_check/input_check/actions.py source). The
# Colang v1.0 runtime processes that event - including a global reaction
# that jumps straight to `bot refuse to respond` - BEFORE control ever
# returns to run a second statement in the calling flow. A first version of
# this file tried `$allowed = execute self_check_input` followed by a
# separate `execute audit_log_input(...)` line; live testing showed the
# second line never ran for blocked requests (confirmed via the full event
# trace in Loki - no audit_log_input execution anywhere in the trace,
# despite it being registered at startup). Blocking itself was NOT affected
# by this bug - only the audit log for blocked input was silently missing,
# which is exactly the event policy Section 10.1 cares about most.
#
# Fix: log INSIDE a Python action that wraps `self_check_input` directly, so
# the log call is synchronous and completes before the function even
# returns - before the runtime has anything to race against. Confirmed safe
# to call the underlying function directly (not through the dispatcher):
# `@action(...)` (nemoguardrails/actions/actions.py, read from the running
# container) is a plain metadata-tagging decorator - `return fn_or_cls`
# unchanged, no wrapping - so calling the imported function IS calling the
# exact same code the dispatcher would call. `self_check_input` also has no
# `output_mapping` (unlike `self_check_output`, which does) so there is no
# separate transformation step to worry about replicating.
#
# OUTPUT RAIL is deliberately NOT wrapped the same way: `self_check_output`
# (verified from its own source) never returns an ActionResult or extra
# events - just a plain bool - so there is no competing event to race
# against, and the original two-statement design (execute, then log, then
# check) is safe as originally written for that rail.
#
# BUG FOUND AND FIXED 26-Jul-2026, while building the separate Flag+Log tier
# (see bottom of this file): the wrapper above was declared with a parameter
# literally named `llm`, expecting nemoguardrails' auto-routing to swap in
# the lightweight self_check_input model (gemma3:4b) instead of the main
# model. That auto-routing (colang/v1_0/runtime/runtime.py, ~line 644) keys
# off `f"{action_name}_llm"` being a registered param -- i.e. it requires the
# ACTION's own name to equal the MODEL TYPE name in config.yml. Renaming this
# action to "self_check_input_with_audit" (to dodge the flow-name collision
# above) silently broke that match: no
# "self_check_input_with_audit_llm" param was ever registered, only
# "self_check_input_llm" was (from config.yml's `type: self_check_input`
# model) -- so the generic `llm` param fell back to the registered "llm" key,
# which IS always present and points at the MAIN model. Net effect: every
# input self-check since this wrapper was built (22-Jul-2026, both UAT and
# Prod) has been running on qwen3:14b, not gemma3:4b as documented in the
# Phase 3 testing report and project memory -- a real latency/cost
# regression, not a security hole (the block/allow decision itself was still
# correct, just made by a bigger/slower model than intended).
#
# Confirmed via a standalone reproduction of the exact runtime.py param-
# injection logic against this real function (not guessed, not assumed from
# reading the docs alone) -- see the commit message for this fix for the
# reproduction script's result.
#
# FIX: the parameter is renamed from the generic `llm` to the SPECIFIC
# `self_check_input_llm`, matching the auto-registered key exactly, and
# passed through explicitly to `_self_check_input_impl(llm=self_check_input_llm, ...)`.
# The self_check_output rail was NOT affected by this bug -- it calls the
# built-in `self_check_output` action directly (name matches its model type
# exactly), never wrapped/renamed, confirmed via the same reproduction.

import logging
import os
from typing import Optional

from nemoguardrails.actions import action
from nemoguardrails.actions.actions import ActionResult
from nemoguardrails.library.self_check.input_check.actions import (
    self_check_input as _self_check_input_impl,
)

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


@action(name="self_check_input_with_audit", is_system_action=True)
async def self_check_input_with_audit(
    llm_task_manager=None,
    context: Optional[dict] = None,
    self_check_input_llm=None,  # NOT "llm" -- see module docstring's 26-Jul-2026
                                 # bug note. This exact param name is what
                                 # nemoguardrails auto-populates with the
                                 # gemma3:4b client registered for config.yml's
                                 # `type: self_check_input` model.
    config=None,
    **kwargs,
):
    """Wraps the built-in self_check_input action - calls it, logs the
    decision synchronously (before any downstream event processing can
    race ahead), then returns the exact same result unchanged so every
    other behavior (masking, exceptions, block enforcement) is preserved
    byte-for-byte. See module docstring for why this exists.
    """
    context = context or {}
    result = await _self_check_input_impl(
        llm_task_manager=llm_task_manager,
        context=context,
        llm=self_check_input_llm,
        config=config,
        **kwargs,
    )
    allowed = result.return_value if isinstance(result, ActionResult) else result
    # Read user_message BEFORE returning - masking (if triggered) happens
    # later, as a side effect of the runtime processing the returned event,
    # which can only happen after this function returns.
    _emit("input", bool(allowed), _get_consumer(context), context.get("user_message"))
    return result


@action(name="audit_log_output", is_system_action=True)
async def audit_log_output(context: Optional[dict] = None, allowed: bool = True, **kwargs):
    context = context or {}
    _emit("output", allowed, _get_consumer(context), context.get("bot_message"))
    return True


# ── "Flag + Log" tier -- profanity / mild toxicity ──────────────────────────
# AI Guardrail Policy v1.0, added 26-Jul-2026. Read the actual policy tables
# via python-docx before building this (not guessed from memory):
#   Section 2: "Profanity / mild toxicity -> Flag + Log -> Logged for
#               visibility, not blocked"
#   Section 9 (Enforcement Behavior): "Medium (ambiguous/borderline) -> Flag
#               + log, allow through, queue for periodic review -> e.g.
#               Borderline profanity, unclear intent"
#
# This is DELIBERATELY separate from self_check_input/output's hard
# block/allow gate -- prompts.yml's self_check_input prompt already says
# "Do NOT block ordinary profanity or mild toxicity - that is handled
# separately" (written 21-Jul-2026, implemented here). Runs as a SECOND,
# non-blocking classification pass AFTER the hard-block gate has already
# allowed the message through (see config.yml's rails.input/output.flows
# ordering) -- it can only ever add a "flagged" audit log entry, never stop
# the pipeline or refuse a response.
#
# Uses a plain STRING task name ("content_flag_check") rather than one of
# the library's built-in Task enum members -- confirmed this is natively
# supported by reading llm/prompts.py's get_prompt()/get_task_model(), both
# typed `Union[str, Task]` with an explicit `str(task.value) if isinstance
# (task, Task) else task` fallback for plain strings.
#
# Does its OWN minimal Yes/No parsing rather than calling
# llm_task_manager.parse_task_output() -- that method is typed to only
# accept a real Task enum member (llm/taskmanager.py's signature), and
# self_check_input/output's use of it depends on a registered
# "is_content_safe" output parser that has no reason to exist for a brand
# new custom task. Manual parsing avoids relying on an internal fallback
# path this task was never registered for.
#
# Model routing: the action parameters below are named `content_flag_check_llm`
# (NOT the generic `llm`) so they pick up the lightweight model registered
# for config.yml's new `type: content_flag_check` entry (gemma3:4b, same
# tier as self_check_input/output) via nemoguardrails' auto-injection --
# built this way from the start given the real bug just found and fixed
# above in self_check_input_with_audit, which happened by using the
# generic `llm` param name on a renamed action.

from nemoguardrails.actions.llm.utils import llm_call, warn_if_truncated
from nemoguardrails.context import llm_call_info_var
from nemoguardrails.logging.explain import LLMCallInfo

_FLAG_TASK = "content_flag_check"


def _emit_flag(rail: str, consumer: str, content: Optional[str]) -> None:
    # Distinct "flagged" action -- separate from _emit()'s allowed/blocked.
    # Flagged traffic is NOT blocked (the request/response proceeds normally
    # either way) but is logged WITH content captured for the human review
    # queue the policy calls for ("queue for periodic review"), same privacy
    # carve-out _emit() already applies to blocked events.
    extra = {
        "audit_rail": rail,
        "audit_action": "flagged",
        "audit_environment": ENVIRONMENT,
        "audit_model": MAIN_MODEL,
        "audit_consumer": consumer,
        "audit_category": "profanity_mild_toxicity",
        "audit_severity": "medium",
        "audit_content": content or "",
    }
    audit_log.info(
        f"guardrail_decision rail={rail} action=flagged environment={ENVIRONMENT} "
        f"category=profanity_mild_toxicity severity=medium",
        extra=extra,
    )


async def _run_flag_check(llm_task_manager, llm, config, text: Optional[str]) -> bool:
    """Returns True if `text` should be flagged under the Flag+Log tier.
    Never raises on missing/empty text -- just returns False (nothing to
    check), same defensive pattern as self_check_input's own `if user_input`
    guard."""
    if not text:
        return False

    prompt = llm_task_manager.render_task_prompt(task=_FLAG_TASK, context={"text": text})
    stop = llm_task_manager.get_stop_tokens(task=_FLAG_TASK)
    max_tokens = llm_task_manager.get_max_tokens(task=_FLAG_TASK) or 1024

    llm_call_info_var.set(LLMCallInfo(task=_FLAG_TASK))
    llm_response = await llm_call(
        llm,
        prompt,
        stop=stop,
        llm_params={"temperature": config.lowest_temperature, "max_tokens": max_tokens},
    )
    warn_if_truncated(llm_response, _FLAG_TASK)
    response = (llm_response.content or "").strip().lower()
    audit_log.debug(f"flag-check raw response: `{response}`")
    return response.startswith("yes") or response.startswith('"yes') or " yes" in response[:20]


@action(name="flag_check_input", is_system_action=True)
async def flag_check_input(
    llm_task_manager=None,
    context: Optional[dict] = None,
    content_flag_check_llm=None,  # matches config.yml's `type: content_flag_check` model
    config=None,
    **kwargs,
):
    context = context or {}
    text = context.get("user_message")
    flagged = await _run_flag_check(llm_task_manager, content_flag_check_llm, config, text)
    if flagged:
        _emit_flag("input", _get_consumer(context), text)
    return True  # NEVER blocks -- always let the pipeline continue regardless of result


@action(name="flag_check_output", is_system_action=True)
async def flag_check_output(
    llm_task_manager=None,
    context: Optional[dict] = None,
    content_flag_check_llm=None,
    config=None,
    **kwargs,
):
    context = context or {}
    text = context.get("bot_message")
    flagged = await _run_flag_check(llm_task_manager, content_flag_check_llm, config, text)
    if flagged:
        _emit_flag("output", _get_consumer(context), text)
    return True
