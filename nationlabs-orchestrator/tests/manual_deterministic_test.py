"""Deterministic pipeline test — costing validation, approval routing, follow-up stops."""
import json
import sys

sys.path.insert(0, ".")
from orchestrator.db import get_db, init_db
from orchestrator.config import CFG
from orchestrator.services import costing, followup

init_db(CFG.db_path)
conn = get_db(CFG.db_path)
conn.execute("DELETE FROM costing_checks WHERE quote_id IN (SELECT id FROM quotes WHERE opp_id='NL-OPP-2026-0001')")
conn.execute("DELETE FROM approvals WHERE opp_id='NL-OPP-2026-0001'")
conn.execute("DELETE FROM followups WHERE rfq_id IN (SELECT id FROM rfqs WHERE opp_id='NL-OPP-2026-0001')")
conn.execute("DELETE FROM quotes WHERE opp_id='NL-OPP-2026-0001'")
conn.execute("DELETE FROM rfqs WHERE opp_id='NL-OPP-2026-0001'")
conn.execute(
    """INSERT OR REPLACE INTO opportunities
       (opp_id, status, customer_org, requirement_title, submission_deadline, extraction_json)
       VALUES ('NL-OPP-2026-0001','Ready for Proposal','Dubai Municipality',
               'Cisco AMC Renewal','2026-08-15', ?)""",
    (json.dumps({"requirement": {"quantity": "45 switches"}}),),
)

quote = {
    "quote_ref": "ING-882", "quote_date": "2026-08-01", "quote_expiry": "2026-09-30",
    "currency": "AED",
    "line_items": [{"part_number": "CON-SNT-C9300", "description": "Catalyst 9300 SNT support",
                    "quantity": 45, "unit_price": 3000.0, "discount_percent": 0,
                    "line_total": 135000.0}],
    "subtotal": 135000.0, "vat_amount": 6750.0, "total": 141750.0,
    "lead_time": "N/A", "payment_terms": "30 days",
}
cur = conn.execute(
    """INSERT INTO quotes(opp_id,vendor_id,quote_ref,currency,total_after_vat,extracted_json,status)
       VALUES ('NL-OPP-2026-0001',2,'ING-882','AED',141750,?,'Incomplete')""",
    (json.dumps(quote),))
qid1 = cur.lastrowid

quote2 = dict(quote)
quote2.update({
    "line_items": [{"part_number": "X", "description": "GPU cluster", "quantity": 1,
                    "unit_price": 500000.0, "line_total": 500000.0}],
    "subtotal": 500000.0, "vat_amount": 25000.0, "total": 525000.0,
})
cur = conn.execute(
    """INSERT INTO quotes(opp_id,vendor_id,quote_ref,currency,total_after_vat,extracted_json,status)
       VALUES ('NL-OPP-2026-0001',1,'CSC-101','AED',525000,?,'Incomplete')""",
    (json.dumps(quote2),))
qid2 = cur.lastrowid
conn.commit()

r1 = costing.validate_quote(conn, qid1)
print("quote1:", r1["status"], [(c["check"], c["result"]) for c in r1["checks"]])
r2 = costing.validate_quote(conn, qid2)
print("quote2:", r2["status"], [(c["check"], c["result"]) for c in r2["checks"]])

print("route:", costing.route_for_approval(conn, "NL-OPP-2026-0001"))

conn.execute(
    """INSERT INTO rfqs(opp_id,vendor_id,rfq_ref,status,sent_at)
       VALUES ('NL-OPP-2026-0001',2,'NL-RFQ-2026-0001','SENT','2026-07-31')""")
rid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
open_, stop = followup._rfq_still_open(conn, rid)
print("followup open?", open_, "| stop reason:", stop)
conn.commit()
print("DETERMINISTIC PIPELINE PASS")
