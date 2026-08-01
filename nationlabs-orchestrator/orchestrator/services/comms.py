"""Comms service (spec §11, §12, §13, §14) — RFQ drafts, disclosure enforcement,
approval queue, file outbox. This service has NO SMTP capability by design.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from ..audit import audit
from ..config import CFG, Config
from ..ollama_client import call_llm
from ..prompts.rfq_drafter_v1 import RFQ_DRAFTER_SYSTEM
from ..services.vendor import VendorCandidate, disclosure_decision
from ..statemachine import transition

log = logging.getLogger("orchestrator.comms")


def next_rfq_ref(conn: sqlite3.Connection) -> str:
    year = datetime.now().year
    row = conn.execute(
        "SELECT rfq_ref FROM rfqs WHERE rfq_ref LIKE ? ORDER BY rfq_ref DESC LIMIT 1",
        (f"NL-RFQ-{year}-%",),
    ).fetchone()
    seq = int(row["rfq_ref"].rsplit("-", 1)[1]) + 1 if row else 1
    return f"NL-RFQ-{year}-{seq:04d}"


def create_rfq_draft(
    conn: sqlite3.Connection,
    opp_id: str,
    candidate: VendorCandidate,
    *,
    end_user_disclosure_approved: bool,
    actor: str,
    cfg: Config = CFG,
) -> int:
    """Draft one RFQ email for one vendor. §11 enforced HERE, in code, at assembly."""
    opp = conn.execute("SELECT * FROM opportunities WHERE opp_id=?", (opp_id,)).fetchone()
    if opp is None:
        raise KeyError(opp_id)
    extraction = json.loads(opp["extraction_json"] or "{}")

    # ---- §11 disclosure gate (code, not prompt) ----
    policy_ok, policy_reason = disclosure_decision(candidate)
    disclose = bool(policy_ok and end_user_disclosure_approved)
    end_user = opp["end_user_org"] or extraction.get("customer", {}).get("end_user_org")
    end_user_display = end_user if (disclose and end_user) else "CONFIDENTIAL"
    if end_user_disclosure_approved and not policy_ok:
        with conn:
            audit(conn, opp_id=opp_id, actor=actor, component="comms",
                  action="DISCLOSURE_BLOCKED", reason=policy_reason,
                  new_value=candidate.vendor_name)

    rfq_ref = next_rfq_ref(conn)
    req = extraction.get("requirement", {})
    payload = {
        "rfq_ref": rfq_ref,
        "vendor_name": candidate.vendor_name,
        "vendor_email": candidate.email,
        "end_user_display": end_user_display,
        "requirement_title": req.get("title"),
        "requirement_summary": {
            k: v for k, v in req.items()
            if v not in (None, "", False) and k != "field_status"
        },
        "deal_registration_requested": candidate.deal_reg_capable,
        "min_quote_validity_days": cfg.min_quote_validity_days,
        "submission_deadline": opp["submission_deadline"],
        "nationlabs_contact": opp["opportunity_owner"],
    }
    email_text = call_llm(
        "main", RFQ_DRAFTER_SYSTEM,
        "Draft the RFQ email from this data:\n" + json.dumps(payload, indent=1, default=str),
        num_ctx=3072, cfg=cfg,
    )
    assert isinstance(email_text, str)

    draft_path = cfg.outbox / "vendor_emails" / f"{rfq_ref}_{candidate.vendor_name.replace(' ', '_')}.txt"
    draft_path.write_text(email_text, encoding="utf-8")

    with conn:
        cur = conn.execute(
            """INSERT INTO rfqs (opp_id, vendor_id, rfq_ref, draft_path,
               disclose_end_user, status) VALUES (?,?,?,?,?, 'AWAITING_APPROVAL')""",
            (opp_id, candidate.vendor_id, rfq_ref, str(draft_path), int(disclose)),
        )
        rfq_id = cur.lastrowid
        conn.execute(
            """INSERT INTO approvals (opp_id, kind, request_path, requested_from)
               VALUES (?, 'RFQ_FIRST_SEND', ?, ?)""",
            (opp_id, str(draft_path), opp["opportunity_owner"] or "opportunity owner"),
        )
        audit(conn, opp_id=opp_id, actor=actor, component="comms",
              action="rfq_drafted", new_value=rfq_ref,
              reason=f"vendor={candidate.vendor_name}; disclose={disclose}")
        # first RFQ for this opp moves it along
        if opp["status"] == "Ready for RFQ":
            transition(conn, opp_id, "RFQ Drafted", actor=actor)
            transition(conn, opp_id, "Awaiting RFQ Approval", actor=actor)
    return rfq_id


def approve_rfq(conn: sqlite3.Connection, rfq_id: int, *, approver: str,
                cfg: Config = CFG) -> Path:
    """Human approval → status APPROVED, file stays in outbox for manual dispatch (§14)."""
    rfq = conn.execute("SELECT * FROM rfqs WHERE id=?", (rfq_id,)).fetchone()
    if rfq is None or rfq["status"] != "AWAITING_APPROVAL":
        raise ValueError("RFQ not awaiting approval")
    with conn:
        conn.execute("UPDATE rfqs SET status='APPROVED', approved_by=?, approved_at=datetime('now') WHERE id=?",
                     (approver, rfq_id))
        conn.execute(
            """UPDATE approvals SET decision='APPROVED', decided_by=?, decided_at=datetime('now')
               WHERE opp_id=? AND kind='RFQ_FIRST_SEND' AND decision IS NULL""",
            (approver, rfq["opp_id"]),
        )
        audit(conn, opp_id=rfq["opp_id"], actor=approver, component="comms",
              action="rfq_approved", new_value=rfq["rfq_ref"])
    return Path(rfq["draft_path"])


def confirm_rfq_sent(conn: sqlite3.Connection, rfq_id: int, *, actor: str,
                     response_deadline: str | None = None, cfg: Config = CFG) -> None:
    """Called after a HUMAN actually dispatches the file. Schedules follow-up #1
    and opens the deal-registration tracker (§13) for this vendor."""
    rfq = conn.execute("SELECT * FROM rfqs WHERE id=?", (rfq_id,)).fetchone()
    if rfq is None or rfq["status"] != "APPROVED":
        raise ValueError("RFQ must be APPROVED before send-confirmation")
    vendor = conn.execute("SELECT deal_reg_capable, vendor_name FROM vendors WHERE id=?",
                          (rfq["vendor_id"],)).fetchone()
    with conn:
        conn.execute("UPDATE rfqs SET status='SENT', sent_at=datetime('now'), response_deadline=? WHERE id=?",
                     (response_deadline, rfq_id))
        audit(conn, opp_id=rfq["opp_id"], actor=actor, component="comms",
              action="rfq_sent_confirmed", new_value=rfq["rfq_ref"])
        # §13: deal registration tracking starts AT SEND, not at vendor response
        dr_status = "Submitted" if vendor["deal_reg_capable"] else "Not required"
        conn.execute(
            """INSERT INTO deal_registrations (opp_id, vendor_id, status, updated_at)
               VALUES (?,?,?, datetime('now'))
               ON CONFLICT(opp_id, vendor_id) DO NOTHING""",
            (rfq["opp_id"], rfq["vendor_id"], dr_status),
        )
        audit(conn, opp_id=rfq["opp_id"], actor="system", component="comms",
              action="deal_reg_requested", new_value=dr_status,
              reason=f"vendor={vendor['vendor_name']}; requested with {rfq['rfq_ref']}")
        from .followup import schedule_initial_followup
        schedule_initial_followup(conn, rfq_id, cfg)
        opp = conn.execute("SELECT status FROM opportunities WHERE opp_id=?",
                           (rfq["opp_id"],)).fetchone()
        if opp["status"] == "Awaiting RFQ Approval":
            transition(conn, rfq["opp_id"], "RFQ Sent", actor=actor)
            transition(conn, rfq["opp_id"], "Awaiting Vendor Response", actor=actor)
