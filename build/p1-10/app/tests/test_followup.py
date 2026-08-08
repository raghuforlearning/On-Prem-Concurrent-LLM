"""P1-12 — Ported follow-up regression tests (the 3 prototype failures, fixed).

Run INSIDE the nl-api container:  docker exec nl-api python -m pytest tests/ -q
Each test builds its own fixture rows with unique RFQ refs, then cleans up.
"""
import os
from datetime import datetime, timedelta, timezone
import psycopg
import pytest

from followup import process_followups, init_followups, MAX_FOLLOWUPS

PG_DSN = os.environ["PG_DSN"]
NOW = datetime.now(timezone.utc)


@pytest.fixture()
def fixture_rfq():
    """Create a SENT rfq + vendor + opp for testing; yield ref; clean up after."""
    ref = f"NL-RFQ-TEST-{os.getpid()}-{int(NOW.timestamp())}"
    with psycopg.connect(PG_DSN) as conn:
        init_followups(conn)
        conn.execute(
            "INSERT INTO vendors (vendor_name, tier, tech_domains, email, vendor_authorised, deal_reg_capable) "
            "VALUES (%s,'OEM','{Testing}','t@t.example',true,true) ON CONFLICT (vendor_name) DO NOTHING",
            (f"TestVendor-{ref}",))
        vid = conn.execute("SELECT vendor_id FROM vendors WHERE vendor_name=%s",
                           (f"TestVendor-{ref}",)).fetchone()[0]
        conn.execute(
            "INSERT INTO opportunities (opp_id, status, raw_text, raw_sha256) "
            "VALUES (%s,'READY','test','x') ON CONFLICT (opp_id) DO NOTHING", (f"OPP-{ref}",))
        conn.execute(
            "INSERT INTO rfqs (rfq_ref, opp_id, vendor_id, status, draft_body, idempotency_key, sent_at) "
            "VALUES (%s,%s,%s,'SENT','draft',%s,%s)",
            (ref, f"OPP-{ref}", vid, ref, NOW - timedelta(days=1)))
        conn.commit()
    yield ref
    with psycopg.connect(PG_DSN) as conn:
        for table, col in [("followups", "rfq_ref"), ("vendor_responses", "rfq_ref"),
                           ("internal_alerts", "rfq_ref"), ("rfqs", "rfq_ref")]:
            conn.execute(f"DELETE FROM {table} WHERE {col}=%s", (ref,))
        conn.execute("DELETE FROM internal_alerts WHERE opp_id=%s", (f"OPP-{ref}",))
        conn.execute("DELETE FROM opportunities WHERE opp_id=%s", (f"OPP-{ref}",))
        conn.commit()


def test_followup_stops_on_quote(fixture_rfq):
    """Prototype regression #1: a vendor response stops the cadence."""
    ref = fixture_rfq
    with psycopg.connect(PG_DSN) as conn:
        conn.execute("INSERT INTO vendor_responses (rfq_ref, response_type, raw_text) "
                     "VALUES (%s,'QUOTE','see attached')", (ref,))
        conn.commit()
    s = process_followups(NOW + timedelta(days=1))
    assert ref in s["stopped_on_response"] and ref not in [n["rfq_ref"] for n in s["nudged"]]


def test_followup_escalates_after_limit(fixture_rfq):
    """Prototype regression #2: after MAX nudges -> escalation alert, no more nudges."""
    ref = fixture_rfq
    t = NOW
    for day in range(1, MAX_FOLLOWUPS + 2):       # enough ticks to exceed the limit
        s = process_followups(t + timedelta(days=day))
    with psycopg.connect(PG_DSN) as conn:
        n = conn.execute("SELECT count(*) FROM followups WHERE rfq_ref=%s AND status='SENT'",
                         (ref,)).fetchone()[0]
        alert = conn.execute(
            "SELECT kind FROM internal_alerts WHERE rfq_ref=%s AND kind='ESCALATION'",
            (ref,)).fetchone()
    assert n == MAX_FOLLOWUPS and alert is not None


def test_no_followups_before_send(fixture_rfq):
    """Prototype regression #3 ('continues while deal-reg pending'): in the new
    design a BLOCKED RFQ structurally cannot receive follow-ups."""
    ref = fixture_rfq
    with psycopg.connect(PG_DSN) as conn:
        conn.execute("UPDATE rfqs SET status='BLOCKED_PENDING_DEAL_REG' WHERE rfq_ref=%s", (ref,))
        conn.commit()
    s = process_followups(NOW + timedelta(days=5))
    with psycopg.connect(PG_DSN) as conn:
        n = conn.execute("SELECT count(*) FROM followups WHERE rfq_ref=%s", (ref,)).fetchone()[0]
    assert n == 0 and ref not in [x["rfq_ref"] for x in s["nudged"]]
