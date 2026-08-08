"""P1-10/P1-12 — Follow-up engine (daily cadence, stop-on-quote, escalation).

Replaces prototype services/followup.py — including fixes for its 3 failing
regression tests (P1-12). Design decisions (BUILD LOG):
- Template-based follow-up bodies (deterministic, zero tokens, zero weirdness).
- Driven by host cron -> POST /followups/run (reboot-persistent, no loop daemon).
- Structural rule: follow-ups exist ONLY for SENT RFQs. A deal-reg-blocked RFQ
  can never accumulate follow-ups (ported regression: 'continues while deal-reg
  pending' becomes 'never starts before send').
"""
from datetime import datetime, timedelta, timezone
import psycopg
from db import PG_DSN, audit

MAX_FOLLOWUPS = 3            # after the original send, 3 nudges then escalate
MIN_GAP = timedelta(hours=20)   # "daily morning" enforced as >=20h between nudges

SCHEMA = """
CREATE TABLE IF NOT EXISTS followups (
    id          BIGSERIAL PRIMARY KEY,
    rfq_ref     TEXT NOT NULL REFERENCES rfqs(rfq_ref),
    followup_n  INT NOT NULL,
    scheduled_at TIMESTAMPTZ NOT NULL,
    sent_at     TIMESTAMPTZ,
    status      TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING/SENT/STOPPED/ESCALATED
    stop_reason TEXT
);
CREATE TABLE IF NOT EXISTS vendor_responses (
    id          BIGSERIAL PRIMARY KEY,
    rfq_ref     TEXT NOT NULL REFERENCES rfqs(rfq_ref),
    response_type TEXT NOT NULL,        -- QUOTE/CLARIFICATION/ACK/REJECTION
    raw_text    TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS internal_alerts (
    id          BIGSERIAL PRIMARY KEY,
    rfq_ref     TEXT,
    opp_id      TEXT,
    kind        TEXT NOT NULL,          -- ESCALATION/RESPONSE_RECEIVED
    message     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

FOLLOWUP_TEMPLATE = """Subject: Follow-up {n}: RFQ {rfq_ref} - NationLabs FZ LLC

Dear {vendor} Team,

Gentle reminder on our RFQ {rfq_ref} sent on {sent_date}. We would appreciate
your itemized quotation (AED), lead time, and validity at your earliest
convenience, as we are working against a client submission timeline.

Best regards,
NationLabs FZ LLC Presales
"""

ESCALATION_TEMPLATE = ("RFQ {rfq_ref} to {vendor}: no response after original send + "
                       "{n} follow-ups. Escalating to NL owner {owner} for phone/alternate contact.")


def init_followups(conn):
    conn.execute(SCHEMA)
    conn.commit()


def _has_response(conn, rfq_ref) -> bool:
    return conn.execute("SELECT 1 FROM vendor_responses WHERE rfq_ref=%s LIMIT 1",
                        (rfq_ref,)).fetchone() is not None


def process_followups(now: datetime | None = None) -> dict:
    """One scheduler tick. Returns a summary dict (also the acceptance evidence)."""
    now = now or datetime.now(timezone.utc)
    summary = {"nudged": [], "stopped_on_response": [], "escalated": [], "skipped_recent": []}
    with psycopg.connect(PG_DSN) as conn:
        sent_rfqs = conn.execute(
            "SELECT r.rfq_ref, r.opp_id, r.sent_at, v.vendor_name, v.assigned_nl_owner "
            "FROM rfqs r JOIN vendors v ON v.vendor_id=r.vendor_id WHERE r.status='SENT'"
        ).fetchall()
        for rfq_ref, opp_id, sent_at, vendor, owner in sent_rfqs:
            # Rule 1: stop-on-quote (any response stops the cadence)
            if _has_response(conn, rfq_ref):
                conn.execute(
                    "UPDATE followups SET status='STOPPED', stop_reason='response_received' "
                    "WHERE rfq_ref=%s AND status IN ('PENDING','SENT')", (rfq_ref,))
                conn.execute(
                    "INSERT INTO internal_alerts (rfq_ref, opp_id, kind, message) "
                    "VALUES (%s,%s,'RESPONSE_RECEIVED',%s) "
                    "ON CONFLICT DO NOTHING",
                    (rfq_ref, opp_id, f"Vendor {vendor} responded to {rfq_ref}; follow-ups stopped."))
                summary["stopped_on_response"].append(rfq_ref)
                continue
            n_sent = conn.execute(
                "SELECT count(*) FROM followups WHERE rfq_ref=%s AND status='SENT'",
                (rfq_ref,)).fetchone()[0]
            last_activity = conn.execute(
                "SELECT max(sent_at) FROM followups WHERE rfq_ref=%s AND status='SENT'",
                (rfq_ref,)).fetchone()[0] or sent_at
            # Rule 2: escalation after limit
            if n_sent >= MAX_FOLLOWUPS:
                already = conn.execute(
                    "SELECT 1 FROM internal_alerts WHERE rfq_ref=%s AND kind='ESCALATION'",
                    (rfq_ref,)).fetchone()
                if not already:
                    msg = ESCALATION_TEMPLATE.format(rfq_ref=rfq_ref, vendor=vendor,
                                                     n=n_sent, owner=owner or "management")
                    conn.execute(
                        "INSERT INTO internal_alerts (rfq_ref, opp_id, kind, message) "
                        "VALUES (%s,%s,'ESCALATION',%s)", (rfq_ref, opp_id, msg))
                    audit(conn, "system", "followup", "escalated", opp_id, new=rfq_ref)
                summary["escalated"].append(rfq_ref)
                continue
            # Rule 3: daily gap
            if now - last_activity < MIN_GAP:
                summary["skipped_recent"].append(rfq_ref)
                continue
            # Send the nudge
            n = n_sent + 1
            body = FOLLOWUP_TEMPLATE.format(n=n, rfq_ref=rfq_ref, vendor=vendor,
                                            sent_date=sent_at.date())
            conn.execute(
                "INSERT INTO followups (rfq_ref, followup_n, scheduled_at, sent_at, status) "
                "VALUES (%s,%s,%s,%s,'SENT')", (rfq_ref, n, now, now))
            audit(conn, "system", "followup", f"followup_{n}_sent", opp_id,
                  new=rfq_ref, reason=body.splitlines()[0])
            summary["nudged"].append({"rfq_ref": rfq_ref, "n": n, "preview": body.splitlines()[0]})
        conn.commit()
    return summary


def record_response(rfq_ref: str, response_type: str, raw_text: str, actor: str) -> dict:
    """Human pastes/registers a vendor response -> cadence stops on next tick."""
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            "INSERT INTO vendor_responses (rfq_ref, response_type, raw_text) VALUES (%s,%s,%s)",
            (rfq_ref, response_type, raw_text))
        audit(conn, actor, "followup", "vendor_response_recorded", new=f"{rfq_ref}:{response_type}")
        conn.commit()
    return {"rfq_ref": rfq_ref, "response_type": response_type, "followups": "will stop on next tick"}
