"""LIVE E2E part 2 — vendor quote lifecycle:
approve+send RFQs -> paste TWO vendor replies (Ingram quote, Cisco clarification)
-> gemma3:4b classifies -> qwen3:14b extracts quote -> costing validates ->
approval routing. Uses the live opp NL-OPP-2026-0004 from part 1.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.config import CFG
from orchestrator.db import get_db
from orchestrator.services import costing, responses
from orchestrator.services.comms import approve_rfq, confirm_rfq_sent

OPP = "NL-OPP-2026-0004"

INGRAM_QUOTE = """Dear NationLabs Team,

Thank you for your RFQ NL-RFQ-2026-0003. Please find our quotation:

Ref: IM-QT-77812 | Date: 01-Aug-2026 | Valid until: 05-Sep-2026 | Currency: AED

Item | Part Number | Description | Qty | Unit Price | Total
1 | CON-SNT-C9300 | Cisco Catalyst 9300 SNT 8x5 NBD support, 1Y | 45 | 2,800.00 | 126,000.00
2 | CON-AP-C9105 | Catalyst 9105 AP SNT support, 1Y | 10 | 450.00 | 4,500.00

Subtotal: AED 130,500.00
VAT (5%): AED 6,525.00
Grand Total: AED 137,025.00

Lead time: N/A (support contract activation, 5 business days)
Payment terms: Net 30 | Incoterms: N/A
Deal registration: DR-77812 submitted, pending Cisco approval. Price protection 60 days.
Assumptions: serial numbers to be provided at activation. Excludes onsite support.

Regards, Omar - Ingram Micro Presales"""

CISCO_CLARIFICATION = """Hello,

Re: your RFQ NL-RFQ-2026-0002 - before we can quote, please confirm:
1. Are the 45 Catalyst 9300 switches covered under an existing Cisco EA agreement?
2. Do you need DNA licensing included or SNT support only?
3. Can you share the end-user entity so we can process deal registration?

Regards, Jane - Cisco"""


def main():
    conn = get_db(CFG.db_path)
    rfqs = conn.execute(
        "SELECT r.id, r.rfq_ref, v.vendor_name FROM rfqs r JOIN vendors v ON v.id=r.vendor_id "
        "WHERE r.opp_id=?", (OPP,)).fetchall()
    by_vendor = {r["vendor_name"]: dict(r) for r in rfqs}

    print("STEP 1: approve + confirm sent (simulating human dispatch)")
    for r in rfqs:
        st = conn.execute("SELECT status FROM rfqs WHERE id=?", (r["id"],)).fetchone()["status"]
        if st == "AWAITING_APPROVAL":
            approve_rfq(conn, r["id"], approver="raghu")
            st = "APPROVED"
        if st == "APPROVED":
            confirm_rfq_sent(conn, r["id"], actor="raghu", response_deadline="2026-08-05")
        print(f"  {r['rfq_ref']} ({r['vendor_name']}) SENT, follow-up #1 scheduled")

    print("\nSTEP 2: Ingram replies with a QUOTE")
    res = responses.process_vendor_response(conn, by_vendor["Ingram Micro"]["id"],
                                            INGRAM_QUOTE, actor="live.test")
    print(f"  gemma3 classified: {res['classification']['response_type']} "
          f"(conf {res['classification']['confidence']})")
    print(f"  gemma3 summary: {res['classification']['summary']}")
    qid = res.get("quote_id")
    if qid:
        q = conn.execute("SELECT * FROM quotes WHERE id=?", (qid,)).fetchone()
        data = json.loads(q["extracted_json"])
        print(f"  qwen3 extracted: ref={data.get('quote_ref')} total={data.get('total')} "
              f"{data.get('currency')} items={len(data['line_items'])}")
        for it in data["line_items"]:
            print(f"    - {it.get('part_number')}: {it.get('quantity')}x "
                  f"{it.get('unit_price')} = {it.get('line_total')}")
        print(f"  deal_reg_ref={data.get('deal_reg_reference')} expiry={data.get('quote_expiry')}")

    print("\nSTEP 3: Cisco replies with a CLARIFICATION REQUEST")
    res2 = responses.process_vendor_response(conn, by_vendor["Cisco"]["id"],
                                             CISCO_CLARIFICATION, actor="live.test")
    print(f"  gemma3 classified: {res2['classification']['response_type']}")
    print(f"  summary: {res2['classification']['summary']}")
    alerts = list((CFG.outbox / "internal_alerts").glob("*alert*"))
    print(f"  internal alerts written: {[a.name for a in alerts]}")

    print("\nSTEP 4: costing validation on Ingram quote")
    if qid:
        result = costing.validate_quote(conn, qid, actor="live.test")
        print(f"  status: {result['status']}")
        for c in result["checks"]:
            mark = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}[c["result"]]
            print(f"    {mark} {c['check']}: {c['actual'] or 'ok'}")

    print("\nSTEP 5: approval routing")
    # only 1 quote so far — routing must REFUSE (need >=2)
    try:
        dest = costing.route_for_approval(conn, OPP, actor="live.test")
        print(f"  routed to {dest}")
    except ValueError as e:
        print(f"  correctly refused: {e}")

    status = conn.execute("SELECT status FROM opportunities WHERE opp_id=?", (OPP,)).fetchone()
    print(f"\n  opportunity status: {status['status']}")
    print("\nLIVE E2E PART 2 DONE")


if __name__ == "__main__":
    main()
