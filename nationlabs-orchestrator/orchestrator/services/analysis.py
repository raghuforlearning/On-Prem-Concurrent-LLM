"""Analysis service — extraction (§5), classification (§6), readiness (§7),
mandatory initial output (§31). LLM interprets; readiness score is computed in code.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3

from ..audit import audit
from ..config import CFG, Config
from ..ollama_client import call_llm, wrap_untrusted
from ..prompts.classification_v1 import CLASSIFICATION_SCHEMA, CLASSIFICATION_SYSTEM
from ..prompts.extraction_v1 import EXTRACTION_SCHEMA, EXTRACTION_SYSTEM
from ..statemachine import transition

log = logging.getLogger("orchestrator.analysis")

# §7 readiness fields with weights (critical fields weigh more)
READINESS_WEIGHTS = {
    "customer_org": 10, "end_user_org": 8, "title": 8, "technology": 12,
    "quantity": 8, "existing_environment": 4, "subscription_duration": 3,
    "support_duration": 3, "delivery_location": 4, "submission_deadline": 10,
    "delivery_deadline": 4, "budget": 3, "compliance_requirements": 3,
    "brand": 5, "contact_name": 5, "business_objective": 5,
    "implementation_scope": 5,  # derived: any of implementation/migration/services flags set
}
CRITICAL_FIELDS = {"customer_org", "end_user_org", "technology", "submission_deadline", "quantity"}


def _rescue_trapped_values(section: dict) -> None:
    """Legacy/junk guard: if any composite 'value:X, status:Y' strings survive in a
    model-generated field_status map, rescue X into the real top-level field.
    Also drops keys that are not part of the schema section."""
    fs = section.get("field_status")
    if isinstance(fs, dict):
        for key, raw in fs.items():
            if isinstance(raw, str):
                m = re.match(r"\s*value:(.*?)\s*,\s*status:", raw, re.IGNORECASE)
                if m and not section.get(key):
                    section[key] = m.group(1).strip()
        section.pop("field_status", None)
    allowed = set(SECTION_FIELDS[section["__section__"]])
    for key in list(section.keys()):
        if key not in allowed and key != "__section__":
            section.pop(key, None)


def _compute_field_status(section: dict, source_lower: str) -> dict:
    """Deterministic status per field — replaces model-generated statuses.
    Confirmed: value appears verbatim in source. Inferred: present but not verbatim.
    Missing: null/absent. Booleans: Confirmed when set, Missing when null."""
    name = section.pop("__section__")
    status = {}
    for field in SECTION_FIELDS[name]:
        val = section.get(field)
        if val is None:
            status[field] = "Missing"
        elif isinstance(val, bool):
            status[field] = "Confirmed"
        else:
            status[field] = "Confirmed" if str(val).lower() in source_lower else "Inferred"
    return status


SECTION_FIELDS = {
    "customer": ["customer_org", "end_user_org", "contact_name", "contact_details",
                 "submission_deadline", "delivery_deadline"],
    "requirement": ["title", "business_objective", "existing_environment", "technology",
                    "brand", "model", "quantity", "licence_quantity",
                    "subscription_duration", "support_duration", "warranty_duration",
                    "implementation_required", "migration_required", "professional_services",
                    "managed_services", "amc_required", "sla_required", "training_required",
                    "compliance_requirements", "delivery_location", "budget",
                    "mandatory_specs", "existing_serial_numbers", "existing_contract_numbers",
                    "existing_subscription_ids", "renewal_expiry_dates"],
}


def _sanitize_extraction(data: dict, source_text: str) -> dict:
    source_lower = source_text.lower()
    for name in ("customer", "requirement"):
        section = data.setdefault(name, {})
        section["__section__"] = name
        _rescue_trapped_values(section)
        data[name]["field_status"] = _compute_field_status(section, source_lower)
    # Compose a title deterministically when the model leaves it null —
    # derivable data should not cost LLM tokens.
    req, cust = data["requirement"], data["customer"]
    if not req.get("title"):
        parts = [str(req.get("quantity") or "").strip() + "x" if req.get("quantity") else "",
                 req.get("brand"), req.get("model"), req.get("technology")]
        label = " ".join(p for p in parts if p)
        org = cust.get("customer_org")
        if label:
            req["title"] = f"{label} - {org}" if org else label
            req["field_status"]["title"] = "Inferred"
    return data


def _compact_extraction(extraction: dict) -> dict:
    """Non-null fields only, no field_status — the token-lean classification input."""
    out: dict = {}
    for name in ("customer", "requirement"):
        section = extraction.get(name, {})
        vals = {k: v for k, v in section.items()
                if k != "field_status" and v is not None and v != ""}
        if vals:
            out[name] = vals
    return out


def run_extraction(conn: sqlite3.Connection, opp_id: str, source_text: str,
                   *, actor: str = "qwen3:14b", cfg: Config = CFG) -> dict:
    data = call_llm(
        "main", EXTRACTION_SYSTEM,
        "Extract the requirement from this content:\n" + wrap_untrusted(source_text),
        json_schema=EXTRACTION_SCHEMA, num_ctx=4096, cfg=cfg,
    )
    data = _sanitize_extraction(data, source_text)
    with conn:
        conn.execute("UPDATE opportunities SET extraction_json=?, updated_at=datetime('now') WHERE opp_id=?",
                     (json.dumps(data), opp_id))
        audit(conn, opp_id=opp_id, actor=actor, component="analysis",
              action="extraction_complete", confidence=data.get("overall_confidence"))
    return data


def run_classification(conn: sqlite3.Connection, opp_id: str, extraction: dict,
                       *, thinking: bool = False, source_excerpt: str | None = None,
                       cfg: Config = CFG) -> dict:
    prompt = "Classify this opportunity extraction:\n" + json.dumps(
        _compact_extraction(extraction), separators=(",", ":"))
    if source_excerpt:
        prompt += ("\n\nOriginal source excerpt (explicit statements here about needed "
                   "proposal types MUST be honored):\n" + wrap_untrusted(source_excerpt[:800]))
    data = call_llm(
        "main", CLASSIFICATION_SYSTEM, prompt,
        json_schema=CLASSIFICATION_SCHEMA, thinking=thinking, num_ctx=3072, cfg=cfg,
    )
    with conn:
        conn.execute("UPDATE opportunities SET classification_json=?, updated_at=datetime('now') WHERE opp_id=?",
                     (json.dumps(data), opp_id))
        audit(conn, opp_id=opp_id, actor="qwen3:14b", component="analysis",
              action="classification_complete",
              new_value=",".join(data["proposal_types"]),
              confidence=data["confidence"]["proposal_type"])
    return data


def compute_readiness(extraction: dict) -> tuple[int, str, list[str], list[str]]:
    """§7 deterministic readiness. Returns (score, level, critical_missing, noncritical_missing)."""
    cust = extraction.get("customer", {})
    req = extraction.get("requirement", {})
    merged = {**{k: v for k, v in cust.items() if k != "field_status"},
              **{k: v for k, v in req.items() if k != "field_status"}}
    merged["implementation_scope"] = bool(
        req.get("implementation_required") or req.get("migration_required")
        or req.get("professional_services") or req.get("amc_required")) or None

    score, crit_missing, other_missing = 0, [], []
    for fname, weight in READINESS_WEIGHTS.items():
        val = merged.get(fname)
        present = val is not None and val is not False and str(val).strip() not in ("", "null")
        if present:
            score += weight
        elif fname in CRITICAL_FIELDS:
            crit_missing.append(fname)
        else:
            other_missing.append(fname)

    if score >= 85 and not crit_missing:
        level = "READY"
    elif score >= 65:
        level = "READY_WITH_ASSUMPTIONS"
    else:
        level = "CLARIFICATION_REQUIRED"
    return score, level, crit_missing, other_missing


def analyse_opportunity(conn: sqlite3.Connection, opp_id: str, source_text: str,
                        *, cfg: Config = CFG) -> dict:
    """Full §31 pipeline: extract → classify → readiness → state update."""
    extraction = run_extraction(conn, opp_id, source_text, cfg=cfg)
    classification = run_classification(conn, opp_id, extraction,
                                        source_excerpt=source_text, cfg=cfg)

    # Form-entered fields (human input at intake) count toward readiness too —
    # credit them into the extraction before scoring (§3: human data is authoritative).
    opp = conn.execute("SELECT customer_org, end_user_org, submission_deadline "
                       "FROM opportunities WHERE opp_id=?", (opp_id,)).fetchone()
    cust = extraction.setdefault("customer", {})
    for field, col in (("customer_org", opp["customer_org"]),
                       ("end_user_org", opp["end_user_org"]),
                       ("submission_deadline", opp["submission_deadline"])):
        if col and not cust.get(field):
            cust[field] = col
            cust.setdefault("field_status", {})[field] = "Confirmed"

    score, level, crit, other = compute_readiness(extraction)

    with conn:
        conn.execute("UPDATE opportunities SET extraction_json=? WHERE opp_id=?",
                     (json.dumps(extraction), opp_id))
        conn.execute(
            """UPDATE opportunities SET readiness_score=?, readiness_level=?,
               customer_org=COALESCE(customer_org, ?), end_user_org=COALESCE(end_user_org, ?),
               requirement_title=?, submission_deadline=COALESCE(submission_deadline, ?),
               updated_at=datetime('now') WHERE opp_id=?""",
            (score, level,
             extraction.get("customer", {}).get("customer_org"),
             extraction.get("customer", {}).get("end_user_org"),
             extraction.get("requirement", {}).get("title"),
             extraction.get("customer", {}).get("submission_deadline"),
             opp_id),
        )
        audit(conn, opp_id=opp_id, actor="system", component="analysis",
              action="readiness_computed", new_value=f"{score}/{level}")

        if classification["needs_human_decision"] or level == "CLARIFICATION_REQUIRED":
            transition(conn, opp_id, "Clarification Required", actor="system",
                       reason=classification.get("ambiguity_reason")
                       or f"readiness {score} < 65; missing: {', '.join(crit)}")
        else:
            transition(conn, opp_id, "Ready for RFQ", actor="system",
                       reason=f"readiness {score}, level {level}")

    return {
        "opp_id": opp_id,
        "extraction": extraction,
        "classification": classification,
        "readiness": {"score": score, "level": level,
                      "critical_missing": crit, "noncritical_missing": other},
    }
