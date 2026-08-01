"""pytest suite — LLM calls mocked; deterministic logic fully exercised.
Run: pytest tests/ -v
"""
import json
import sqlite3
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.db import get_db, init_db
from orchestrator.services import comms, costing, followup, vendor
from orchestrator.services.vendor import VendorCandidate
from orchestrator.statemachine import IllegalTransition, transition


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    db_path = tmp_path / "t.db"
    init_db(db_path)
    c = get_db(db_path)
    # isolate runtime dirs
    from orchestrator import config
    cfg = config.CFG
    cfg.outbox = tmp_path / "outbox"
    for sub in ("vendor_emails", "internal_alerts", "approval_requests"):
        (cfg.outbox / sub).mkdir(parents=True, exist_ok=True)
    cfg.rfp_archive = tmp_path / "archive"
    cfg.audit_dir = tmp_path / "audit"
    (cfg.rfp_archive).mkdir(exist_ok=True)
    cfg.audit_dir.mkdir(exist_ok=True)

    c.execute(
        """INSERT INTO vendors (vendor_name, tier, tech_domains, email, email_domain,
           vendor_authorised, deal_reg_capable, role, contact_status)
           VALUES ('TestOEM','OEM','["Networking"]','sales@oem.ae','oem.ae',1,1,
                   'ACCOUNT_MANAGER','Verified'),
                  ('TestReseller','RESELLER','["Networking"]','guy@reseller.ae',
                   'reseller.ae',1,0,'SALES','Verified')""")
    c.execute(
        """INSERT INTO opportunities (opp_id, status, customer_org, end_user_org,
           requirement_title, submission_deadline, extraction_json)
           VALUES ('NL-OPP-2026-0001','Ready for RFQ','TestCustomer','SECRET-BANK',
                   'Firewall refresh','2026-09-01','{}')""")
    c.commit()
    yield c
    c.close()


# ---- 1. Privacy rule: reseller NEVER receives end-user, even if "approved" ----
def test_reseller_disclosure_blocked(conn, monkeypatch):
    captured = {}
    def fake_llm(role, system, user, **kw):
        captured["payload"] = user
        return "To: x\nSubject: RFQ\n\nDear Vendor,\nBody"
    monkeypatch.setattr(comms, "call_llm", fake_llm)

    reseller = VendorCandidate(2, "TestReseller", "RESELLER", "Guy", "guy@reseller.ae",
                               "SALES", False, False)
    comms.create_rfq_draft(conn, "NL-OPP-2026-0001", reseller,
                           end_user_disclosure_approved=True, actor="test")
    payload = json.loads(captured["payload"].split("data:\n", 1)[1])
    assert payload["end_user_display"] == "CONFIDENTIAL"          # §11 enforced in code
    assert "SECRET-BANK" not in captured["payload"]
    blocked = conn.execute(
        "SELECT action FROM audit_log WHERE action='DISCLOSURE_BLOCKED'").fetchone()
    assert blocked is not None


def test_oem_disclosure_still_needs_approval(conn, monkeypatch):
    captured = {}
    monkeypatch.setattr(comms, "call_llm",
                        lambda r, s, u, **kw: captured.update(p=u) or "email text")
    oem = VendorCandidate(1, "TestOEM", "OEM", "Sales", "sales@oem.ae",
                          "ACCOUNT_MANAGER", True, True)
    comms.create_rfq_draft(conn, "NL-OPP-2026-0001", oem,
                           end_user_disclosure_approved=False, actor="test")
    payload = json.loads(captured["p"].split("data:\n", 1)[1])
    assert payload["end_user_display"] == "CONFIDENTIAL"          # no approval → no disclosure


# ---- 2. Classification ambiguity halts (state machine, not AI, controls flow) ----
def test_ambiguous_classification_halts(conn):
    transition(conn, "NL-OPP-2026-0001", "RFQ Drafted", actor="t")
    transition(conn, "NL-OPP-2026-0001", "Awaiting RFQ Approval", actor="t")
    with pytest.raises(IllegalTransition):
        transition(conn, "NL-OPP-2026-0001", "Awaiting Vendor Response", actor="t")


# ---- 3. 200K AED routing boundary ----
def _mk_quote(conn, opp_id, vendor_id, total, ref, deal_reg="Approved"):
    data = {"quote_ref": ref, "currency": "AED", "quote_expiry": "2027-01-01",
            "line_items": [{"description": "X", "quantity": 1, "unit_price": total,
                            "line_total": total}],
            "subtotal": total, "vat_amount": 0, "total": total,
            "lead_time": "2w", "payment_terms": "30d"}
    cur = conn.execute(
        """INSERT INTO quotes (opp_id, vendor_id, quote_ref, currency, total_after_vat,
           extracted_json, status) VALUES (?,?,?,?,?,?,'Complete')""",
        (opp_id, vendor_id, ref, "AED", total, json.dumps(data)))
    conn.execute(
        """INSERT INTO deal_registrations (opp_id, vendor_id, status) VALUES (?,?,?)
           ON CONFLICT(opp_id, vendor_id) DO UPDATE SET status=excluded.status""",
        (opp_id, vendor_id, deal_reg))
    return cur.lastrowid


def test_routing_under_threshold(conn):
    conn.execute("UPDATE opportunities SET status='Ready for Proposal' WHERE opp_id='NL-OPP-2026-0001'")
    _mk_quote(conn, "NL-OPP-2026-0001", 1, 150_000, "Q1")
    _mk_quote(conn, "NL-OPP-2026-0001", 2, 160_000, "Q2")
    assert costing.route_for_approval(conn, "NL-OPP-2026-0001") == "FINAL_VERIFIER"


def test_routing_over_threshold(conn):
    conn.execute("UPDATE opportunities SET status='Ready for Proposal' WHERE opp_id='NL-OPP-2026-0001'")
    _mk_quote(conn, "NL-OPP-2026-0001", 1, 300_000, "Q1")
    _mk_quote(conn, "NL-OPP-2026-0001", 2, 320_000, "Q2")
    assert costing.route_for_approval(conn, "NL-OPP-2026-0001") == "FINANCE"
    row = conn.execute("SELECT status FROM opportunities WHERE opp_id='NL-OPP-2026-0001'").fetchone()
    assert row["status"] == "Finance Approval Required"


def test_routing_needs_two_quotes(conn):
    conn.execute("UPDATE opportunities SET status='Ready for Proposal' WHERE opp_id='NL-OPP-2026-0001'")
    _mk_quote(conn, "NL-OPP-2026-0001", 1, 100_000, "Q1")
    with pytest.raises(ValueError):
        costing.route_for_approval(conn, "NL-OPP-2026-0001")


# ---- 4. Follow-up ladder + stop conditions ----
def test_followup_stops_on_quote(conn, monkeypatch):
    monkeypatch.setattr(followup, "call_llm",
                        lambda *a, **kw: "To: v\nSubject: fu\n\nfollowing up")
    conn.execute("UPDATE opportunities SET status='Quote Received' WHERE opp_id='NL-OPP-2026-0001'")
    conn.execute("""INSERT INTO rfqs (opp_id, vendor_id, rfq_ref, status, sent_at)
                    VALUES ('NL-OPP-2026-0001',1,'NL-RFQ-2026-0001','SENT','2026-07-30')""")
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    followup.schedule_initial_followup(conn, rid)
    from datetime import datetime, timedelta
    future = datetime.now(followup.TZ) + timedelta(days=30)
    processed = followup.run_due_followups(conn, now=future)
    assert processed == []
    fu = conn.execute("SELECT status, stop_reason FROM followups WHERE rfq_id=?", (rid,)).fetchone()
    assert fu["status"] == "STOPPED" and "Quote Received" in fu["stop_reason"]


def test_followup_escalates_after_limit(conn, monkeypatch):
    monkeypatch.setattr(followup, "call_llm",
                        lambda *a, **kw: "To: v\nSubject: fu\n\nfollowing up")
    conn.execute("UPDATE opportunities SET status='Awaiting Vendor Response' WHERE opp_id='NL-OPP-2026-0001'")
    conn.execute("""INSERT INTO rfqs (opp_id, vendor_id, rfq_ref, status, sent_at)
                    VALUES ('NL-OPP-2026-0001',1,'NL-RFQ-2026-0001','SENT','2026-07-20')""")
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    from datetime import datetime, timedelta
    now = datetime.now(followup.TZ) + timedelta(days=30)
    # simulate follow-ups 1..3 sent, 4th pending
    for n in (1, 2, 3):
        conn.execute("INSERT INTO followups (rfq_id, followup_n, scheduled_at, status) VALUES (?,?,?,'SENT')",
                     (rid, n, "2026-07-21"))
    conn.execute("INSERT INTO followups (rfq_id, followup_n, scheduled_at) VALUES (?,?,?)",
                 (rid, 4, now.isoformat()))
    conn.commit()
    followup.run_due_followups(conn, now=now)
    fu = conn.execute("SELECT status FROM followups WHERE rfq_id=? AND followup_n=4", (rid,)).fetchone()
    assert fu["status"] == "ESCALATED"
    esc = list((conn.execute("SELECT 1").connection and
                __import__("orchestrator.config", fromlist=["CFG"]).CFG.outbox
                / "internal_alerts").glob("*escalation*"))
    assert esc, "escalation alert file missing"


# ---- 5. JSON retry logic ----
def test_llm_retry_then_escalate(monkeypatch):
    from orchestrator import ollama_client
    calls = {"n": 0}
    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"response": "not json at all"}
    monkeypatch.setattr(ollama_client.requests, "post",
                        lambda *a, **kw: calls.update(n=calls["n"] + 1) or FakeResp())
    with pytest.raises(ollama_client.LLMOutputError):
        ollama_client.call_llm("fast", "sys", "user", json_schema={"type": "object"})
    assert calls["n"] == 2  # exactly one retry, never silent-guess


# ---- 6. Vendor matching excludes blocked contacts ----
def test_blocked_contacts_never_selected(conn):
    conn.execute("UPDATE vendors SET contact_status='Expired' WHERE vendor_name='TestOEM'")
    conn.commit()
    cands = vendor.match_vendors(conn, "NL-OPP-2026-0001", ["Networking"])
    names = [c.vendor_name for c in cands]
    assert "TestOEM" not in names and "TestReseller" in names


# ---- 7. §13 Deal registration: tracking starts at send ----
def test_deal_reg_tracking_created_at_send(conn, monkeypatch):
    monkeypatch.setattr(comms, "call_llm", lambda *a, **kw: "email text")
    oem = VendorCandidate(1, "TestOEM", "OEM", "Sales", "sales@oem.ae",
                          "ACCOUNT_MANAGER", True, True)
    rfq_id = comms.create_rfq_draft(conn, "NL-OPP-2026-0001", oem,
                                    end_user_disclosure_approved=False, actor="test")
    comms.approve_rfq(conn, rfq_id, approver="owner")
    comms.confirm_rfq_sent(conn, rfq_id, actor="owner")
    dr = conn.execute(
        "SELECT status FROM deal_registrations WHERE opp_id='NL-OPP-2026-0001' AND vendor_id=1"
    ).fetchone()
    assert dr["status"] == "Submitted"  # tracking opens AT SEND, not at vendor response


def test_deal_reg_not_required_for_non_capable_vendor(conn, monkeypatch):
    monkeypatch.setattr(comms, "call_llm", lambda *a, **kw: "email text")
    reseller = VendorCandidate(2, "TestReseller", "RESELLER", "Guy", "guy@reseller.ae",
                               "SALES", False, False)
    rfq_id = comms.create_rfq_draft(conn, "NL-OPP-2026-0001", reseller,
                                    end_user_disclosure_approved=False, actor="test")
    comms.approve_rfq(conn, rfq_id, approver="owner")
    comms.confirm_rfq_sent(conn, rfq_id, actor="owner")
    dr = conn.execute(
        "SELECT status FROM deal_registrations WHERE opp_id='NL-OPP-2026-0001' AND vendor_id=2"
    ).fetchone()
    assert dr["status"] == "Not required"


# ---- 8. §13 Deal registration: proposal gate ----
def test_routing_blocked_until_deal_reg_approved(conn):
    conn.execute("UPDATE opportunities SET status='Ready for Proposal' WHERE opp_id='NL-OPP-2026-0001'")
    _mk_quote(conn, "NL-OPP-2026-0001", 1, 150_000, "Q1", deal_reg="Submitted")
    _mk_quote(conn, "NL-OPP-2026-0001", 2, 160_000, "Q2", deal_reg="Not required")
    with pytest.raises(ValueError, match="DEAL REGISTRATION NOT SECURED"):
        costing.route_for_approval(conn, "NL-OPP-2026-0001")


def test_routing_override_is_audited(conn):
    conn.execute("UPDATE opportunities SET status='Ready for Proposal' WHERE opp_id='NL-OPP-2026-0001'")
    _mk_quote(conn, "NL-OPP-2026-0001", 1, 150_000, "Q1", deal_reg="Pending")
    _mk_quote(conn, "NL-OPP-2026-0001", 2, 160_000, "Q2", deal_reg="Not required")
    dest = costing.route_for_approval(conn, "NL-OPP-2026-0001",
                                      deal_reg_override=True,
                                      override_reason="vendor confirmed by phone; ref pending")
    assert dest == "FINAL_VERIFIER"
    row = conn.execute("SELECT reason FROM audit_log WHERE action='DEAL_REG_OVERRIDE'").fetchone()
    assert row is not None and "phone" in row["reason"]


# ---- 9. §13 Follow-up keeps chasing a pending registration even after a quote ----
def test_followup_continues_while_deal_reg_pending(conn, monkeypatch):
    captured = {}
    monkeypatch.setattr(followup, "call_llm",
                        lambda r, s, u, **kw: captured.update(p=u) or "follow-up email")
    conn.execute("UPDATE opportunities SET status='Awaiting Vendor Response' WHERE opp_id='NL-OPP-2026-0001'")
    conn.execute("""INSERT INTO rfqs (opp_id, vendor_id, rfq_ref, status, sent_at)
                    VALUES ('NL-OPP-2026-0001',1,'NL-RFQ-2026-0001','SENT','2026-07-20')""")
    rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("""INSERT INTO vendor_responses (rfq_id, response_type, raw_path)
                    VALUES (?,'Commercial quotation','x.txt')""", (rid,))
    conn.execute("""INSERT INTO deal_registrations (opp_id, vendor_id, status)
                    VALUES ('NL-OPP-2026-0001',1,'Submitted')""")
    conn.execute("INSERT INTO followups (rfq_id, followup_n, scheduled_at) VALUES (?,?,?)",
                 (rid, 1, "2026-07-21"))
    conn.commit()
    from datetime import datetime, timedelta
    now = datetime.now(followup.TZ) + timedelta(days=30)
    processed = followup.run_due_followups(conn, now=now)
    assert processed, "follow-up must continue while deal registration is pending"
    assert "deal registration" in captured["p"].lower()
