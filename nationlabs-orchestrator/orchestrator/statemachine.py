"""Deterministic opportunity state machine (spec §24, §29).

The LLM NEVER transitions state directly. Services call transition(); the machine
validates the edge, applies it, and audit-logs it. Unknown/illegal transitions raise.
"""
from __future__ import annotations

import sqlite3

from .audit import audit

# MVP subset of §24 — 16 statuses. Transitions are explicit; anything unlisted is illegal.
STATUSES = {
    "New Intake", "Under Analysis", "Clarification Required",
    "Awaiting Customer Information", "Ready for RFQ", "RFQ Drafted",
    "Awaiting RFQ Approval", "RFQ Sent", "Awaiting Vendor Response",
    "Quote Received", "Quote Under Validation", "Ready for Proposal",
    "Finance Approval Required", "Final Verification",
    "Ready for Customer Submission", "On Hold", "Cancelled",
}

EDGES: dict[str, set[str]] = {
    "New Intake": {"Under Analysis", "Cancelled"},
    "Under Analysis": {"Clarification Required", "Ready for RFQ", "On Hold", "Cancelled"},
    "Clarification Required": {"Awaiting Customer Information", "Under Analysis",
                               "Ready for RFQ", "On Hold"},
    "Awaiting Customer Information": {"Under Analysis", "On Hold", "Cancelled"},
    "Ready for RFQ": {"RFQ Drafted", "On Hold", "Cancelled"},
    "RFQ Drafted": {"Awaiting RFQ Approval", "Ready for RFQ"},
    "Awaiting RFQ Approval": {"RFQ Sent", "RFQ Drafted"},          # approve / return for edit
    "RFQ Sent": {"Awaiting Vendor Response"},
    "Awaiting Vendor Response": {"Quote Received", "Clarification Required", "On Hold", "Cancelled"},
    "Quote Received": {"Quote Under Validation"},
    "Quote Under Validation": {"Ready for Proposal", "Quote Received", "Clarification Required"},
    "Ready for Proposal": {"Finance Approval Required", "Final Verification", "On Hold"},
    "Finance Approval Required": {"Final Verification", "Ready for Proposal"},
    "Final Verification": {"Ready for Customer Submission", "Ready for Proposal"},
    "Ready for Customer Submission": set(),                         # terminal (submission is manual)
    "On Hold": {"Under Analysis", "Awaiting Vendor Response", "Ready for Proposal", "Cancelled"},
    "Cancelled": set(),
}


class IllegalTransition(RuntimeError):
    pass


def transition(
    conn: sqlite3.Connection,
    opp_id: str,
    to_status: str,
    *,
    actor: str,
    reason: str | None = None,
) -> None:
    row = conn.execute(
        "SELECT status FROM opportunities WHERE opp_id = ?", (opp_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown opportunity {opp_id}")
    current = row["status"]
    if to_status not in STATUSES:
        raise IllegalTransition(f"unknown status {to_status!r}")
    if to_status == current:
        audit(conn, opp_id=opp_id, actor=actor, component="statemachine",
              action="status_reaffirmed", previous_value=current,
              new_value=to_status, reason=reason)
        return
    if to_status not in EDGES[current]:
        raise IllegalTransition(f"{current} -> {to_status} not permitted")
    conn.execute(
        "UPDATE opportunities SET status = ?, updated_at = datetime('now') WHERE opp_id = ?",
        (to_status, opp_id),
    )
    audit(conn, opp_id=opp_id, actor=actor, component="statemachine",
          action="status_transition", previous_value=current,
          new_value=to_status, reason=reason)
