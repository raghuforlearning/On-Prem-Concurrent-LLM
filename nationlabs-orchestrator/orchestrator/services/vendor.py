"""Vendor service (spec §9, §10, §11, §18) — 100% deterministic. The LLM never
reads the vendor register, never invents contacts, never decides disclosure.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from ..audit import audit

TIER_RANK = {"OEM": 0, "DISTRIBUTOR": 1, "SUPPLIER": 2, "RESELLER": 3}
BLOCKED_STATUSES = {"Unverified", "Expired", "Inactive"}
ROLE_PRIORITY = {"ACCOUNT_MANAGER": 0, "SALES": 1, "PRESALES": 2,
                 "DEAL_REG": 3, "ESCALATION": 4}

# §11: end-user details may flow ONLY to these tiers (and only with owner approval)
DISCLOSURE_ALLOWED_TIERS = {"OEM", "DISTRIBUTOR"}

GENERIC_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "mail.com"}


@dataclass
class VendorCandidate:
    vendor_id: int
    vendor_name: str
    tier: str
    contact_name: str | None
    email: str
    role: str
    deal_reg_capable: bool
    may_disclose_end_user: bool
    block_reason: str | None = None


def match_vendors(conn: sqlite3.Connection, opp_id: str, tech_domains: list[str],
                  *, max_vendors: int = 5, min_vendors: int = 2,
                  actor: str = "system") -> list[VendorCandidate]:
    """§9/§10: match by domain, filter blocked contacts, rank tier > role."""
    rows = conn.execute(
        "SELECT * FROM vendors WHERE vendor_authorised = 1"
    ).fetchall()

    candidates: list[VendorCandidate] = []
    for r in rows:
        domains = json.loads(r["tech_domains"])
        if not set(d.lower() for d in domains) & {d.lower() for d in tech_domains}:
            continue
        reason = None
        if r["contact_status"] in BLOCKED_STATUSES:
            reason = f"contact_status={r['contact_status']}"
        elif (r["email_domain"] or "").lower() in GENERIC_DOMAINS:
            reason = "generic/personal email domain requires explicit approval"
        candidates.append(VendorCandidate(
            vendor_id=r["id"], vendor_name=r["vendor_name"], tier=r["tier"],
            contact_name=r["contact_name"], email=r["email"],
            role=r["role"] or "SALES",
            deal_reg_capable=bool(r["deal_reg_capable"]),
            may_disclose_end_user=r["tier"] in DISCLOSURE_ALLOWED_TIERS,
            block_reason=reason,
        ))

    eligible = [c for c in candidates if c.block_reason is None]
    eligible.sort(key=lambda c: (TIER_RANK[c.tier], ROLE_PRIORITY.get(c.role, 9)))
    selected = eligible[:max_vendors]

    with conn:
        audit(conn, opp_id=opp_id, actor=actor, component="vendor_svc",
              action="vendor_match",
              new_value=json.dumps([c.vendor_name for c in selected]),
              reason=f"domains={tech_domains}; eligible={len(eligible)}; "
                     f"blocked={len(candidates) - len(eligible)}")

    if len(selected) < min_vendors:
        with conn:
            audit(conn, opp_id=opp_id, actor=actor, component="vendor_svc",
                  action="VENDOR_SHORTAGE", reason=f"only {len(selected)} eligible "
                  f"vendors (< {min_vendors}); human expansion required")
    return selected


def disclosure_decision(candidate: VendorCandidate) -> tuple[bool, str]:
    """§11 policy engine: returns (allowed, reason). Owner approval is still
    required afterwards — this function can only say NO earlier, never grant by itself."""
    if candidate.tier not in DISCLOSURE_ALLOWED_TIERS:
        return False, f"tier {candidate.tier} is not OEM/DISTRIBUTOR"
    if not candidate.deal_reg_capable:
        return False, "vendor not deal-registration capable; no disclosure need"
    return True, "tier permitted; still requires opportunity-owner approval + audit"


def resolve_owner(conn: sqlite3.Connection, tech_domains: list[str],
                  oem: str | None = None) -> dict | None:
    """§18: never guess the owner. Fallback = Presales Manager (handled by caller)."""
    for domain in tech_domains:
        row = conn.execute(
            """SELECT * FROM ownership_matrix WHERE tech_domain = ?
               AND (oem IS NULL OR oem = ? OR ? IS NULL)
               ORDER BY CASE WHEN oem = ? THEN 0 ELSE 1 END LIMIT 1""",
            (domain, oem, oem, oem),
        ).fetchone()
        if row:
            return dict(row)
    return None
