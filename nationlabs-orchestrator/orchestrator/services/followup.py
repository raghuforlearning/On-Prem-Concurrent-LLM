"""Follow-up scheduler (spec §15) — deterministic. Runs via cron/APScheduler.
Drafts templated follow-ups to outbox (auto-followups still produce FILES for
dispatch; no SMTP). Implements all §15 stop conditions and the escalation ladder.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..audit import audit
from ..config import CFG, Config
from ..ollama_client import call_llm
from ..prompts.rfq_drafter_v1 import FOLLOWUP_SYSTEM

log = logging.getLogger("orchestrator.followup")
try:
    TZ = ZoneInfo(CFG.timezone)
except Exception:  # Windows Python without tzdata: Dubai is fixed UTC+4, no DST
    TZ = timezone(timedelta(hours=4), name="GST")


def is_business_day(d: datetime, cfg: Config = CFG) -> bool:
    if d.weekday() not in cfg.business_days:
        return False
    return d.date().isoformat() not in set(cfg.uae_holidays)


def next_business_morning(after: datetime, cfg: Config = CFG) -> datetime:
    hh, mm = map(int, cfg.followup_time.split(":"))
    d = after.astimezone(TZ) + timedelta(days=1)
    while not is_business_day(d, cfg):
        d += timedelta(days=1)
    return d.replace(hour=hh, minute=mm, second=0, microsecond=0)


def _rfq_still_open(conn: sqlite3.Connection, rfq_id: int) -> tuple[bool, str | None]:
    """§15 stop conditions. Returns (open, stop_reason)."""
    rfq = conn.execute("SELECT * FROM rfqs WHERE id=?", (rfq_id,)).fetchone()
    if rfq is None or rfq["status"] != "SENT":
        return False, "rfq not in SENT state"
    opp = conn.execute("SELECT status FROM opportunities WHERE opp_id=?",
                       (rfq["opp_id"],)).fetchone()
    if opp["status"] in ("Quote Received", "Quote Under Validation", "Ready for Proposal",
                         "On Hold", "Cancelled", "Finance Approval Required",
                         "Final Verification", "Ready for Customer Submission"):
        return False, f"opportunity status is {opp['status']}"
    resp = conn.execute(
        "SELECT response_type FROM vendor_responses WHERE rfq_id=? ORDER BY received_at DESC LIMIT 1",
        (rfq_id,)).fetchone()
    if resp and resp["response_type"] in ("Commercial quotation", "No-bid",
                                          "Clarification request"):
        return False, f"vendor response received: {resp['response_type']}"
    if not rfq["auto_followup_enabled"]:
        return False, "auto follow-up disabled by owner"
    return True, None


def schedule_initial_followup(conn: sqlite3.Connection, rfq_id: int,
                              cfg: Config = CFG) -> None:
    when = next_business_morning(datetime.now(TZ), cfg)
    conn.execute(
        "INSERT OR IGNORE INTO followups (rfq_id, followup_n, scheduled_at) VALUES (?,?,?)",
        (rfq_id, 1, when.isoformat()),
    )


def run_due_followups(conn: sqlite3.Connection, *, cfg: Config = CFG,
                      now: datetime | None = None) -> list[int]:
    """Called by cron each business morning. Returns followup IDs processed."""
    now = now or datetime.now(TZ)
    if not is_business_day(now, cfg):
        log.info("not a UAE business day — skipping")
        return []

    due = conn.execute(
        "SELECT * FROM followups WHERE status='PENDING' AND scheduled_at <= ?",
        (now.isoformat(),)).fetchall()
    processed = []
    for fu in due:
        rfq = conn.execute("SELECT * FROM rfqs WHERE id=?", (fu["rfq_id"],)).fetchone()
        open_, stop = _rfq_still_open(conn, fu["rfq_id"])
        with conn:
            if not open_:
                conn.execute("UPDATE followups SET status='STOPPED', stop_reason=? WHERE id=?",
                             (stop, fu["id"]))
                audit(conn, opp_id=rfq["opp_id"], actor="system", component="followup",
                      action="followup_stopped", reason=stop, new_value=rfq["rfq_ref"])
                continue

            vendor = conn.execute("SELECT vendor_name, email FROM vendors WHERE id=?",
                                  (rfq["vendor_id"],)).fetchone()
            level = fu["followup_n"]
            if level > cfg.followup_max_before_escalation:
                # §15 escalation: alert internal owner + vendor manager, stop auto follow-ups
                _write_escalation(conn, rfq, vendor, level, cfg)
                conn.execute("UPDATE followups SET status='ESCALATED' WHERE id=?", (fu["id"],))
                audit(conn, opp_id=rfq["opp_id"], actor="system", component="followup",
                      action="followup_escalated", new_value=rfq["rfq_ref"])
                continue

            email = _draft_followup(rfq, vendor, level, cfg)
            path = cfg.outbox / "vendor_emails" / f"{rfq['rfq_ref']}_followup{level}.txt"
            path.write_text(email, encoding="utf-8")
            conn.execute("UPDATE followups SET status='SENT', sent_at=datetime('now') WHERE id=?",
                         (fu["id"],))
            audit(conn, opp_id=rfq["opp_id"], actor="system", component="followup",
                  action="followup_drafted", new_value=str(path))
            # schedule next
            nxt = next_business_morning(now, cfg)
            conn.execute(
                "INSERT OR IGNORE INTO followups (rfq_id, followup_n, scheduled_at) VALUES (?,?,?)",
                (fu["rfq_id"], level + 1, nxt.isoformat()))
            processed.append(fu["id"])
    return processed


def _draft_followup(rfq, vendor, level: int, cfg: Config) -> str:
    try:
        return call_llm(
            "fast", FOLLOWUP_SYSTEM,
            f"RFQ ref: {rfq['rfq_ref']}\nVendor: {vendor['vendor_name']} <{vendor['email']}>\n"
            f"Original RFQ sent: {rfq['sent_at']}\nEscalation level: {level} of "
            f"{cfg.followup_max_before_escalation}\nDraft the follow-up email.",
            num_ctx=2048, cfg=cfg,
        )
    except Exception as e:  # LLM down → deterministic template fallback
        log.warning("LLM follow-up draft failed (%s); using template", e)
        return (f"To: {vendor['email']}\nSubject: Follow-Up: RFQ {rfq['rfq_ref']} | NationLabs\n\n"
                f"Dear {vendor['vendor_name']} Team,\n\n"
                f"Following up on our RFQ {rfq['rfq_ref']} sent on {rfq['sent_at']}.\n"
                f"Kindly confirm receipt and share your expected response timeline.\n\n"
                f"Best regards,\nNationLabs Procurement\n")


def _write_escalation(conn, rfq, vendor, level: int, cfg: Config) -> None:
    opp = conn.execute("SELECT * FROM opportunities WHERE opp_id=?",
                       (rfq["opp_id"],)).fetchone()
    text = (f"FOLLOW-UP ESCALATION\nOpportunity: {rfq['opp_id']}\nVendor: {vendor['vendor_name']} "
            f"<{vendor['email']}>\nRFQ: {rfq['rfq_ref']} sent {rfq['sent_at']}\n"
            f"{level - 1} follow-ups sent with no response.\n"
            f"Owner: {opp['opportunity_owner']} | Deadline: {opp['submission_deadline']}\n"
            f"ACTION: owner to contact vendor manager directly or reassign vendor.\n")
    path = cfg.outbox / "internal_alerts" / f"{rfq['rfq_ref']}_escalation.txt"
    path.write_text(text, encoding="utf-8")
