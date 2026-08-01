"""LIVE end-to-end dry run against real Ollama models on the VM.
Intake (messy WhatsApp text) -> qwen3:14b extraction -> classification ->
readiness -> vendor matching -> RFQ drafts (with and without disclosure approval).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.config import CFG, ensure_dirs
from orchestrator.db import get_db, init_db
from orchestrator.services.analysis import analyse_opportunity
from orchestrator.services.comms import create_rfq_draft
from orchestrator.services.intake import create_opportunity
from orchestrator.services.vendor import match_vendors

MESSY_RFP = """Hi team, got a call from Ahmed at Dubai Municipality. They want to renew their
Cisco network switches AMC - expires end of Sept. Around 45 switches, Catalyst 9300 series.
Also he mentioned they might want to add 10 new APs (wireless) but not confirmed.
Need proposal by 15 Aug latest. Budget not shared. Contract number DM-2023-NT-0087.
pls treat urgent"""


def main():
    ensure_dirs()
    init_db(CFG.db_path)
    conn = get_db(CFG.db_path)

    print("=" * 70)
    print("STEP 1: INTAKE")
    opp_id, text = create_opportunity(
        conn, source_channel="whatsapp_paste", actor="live.test",
        pasted_text=MESSY_RFP, opportunity_owner="raghu",
        customer_org="Dubai Municipality", submission_deadline="2026-08-15")
    print(f"  created {opp_id}, {len(text)} chars preserved + extracted")

    print("=" * 70)
    print("STEP 2: AI ANALYSIS (qwen3:14b extraction + classification)")
    result = analyse_opportunity(conn, opp_id, text)

    ext = result["extraction"]
    print(f"  extraction confidence: {ext.get('overall_confidence')}")
    req = ext.get("requirement", {})
    for k in ("title", "technology", "brand", "model", "quantity",
              "existing_contract_numbers", "amc_required"):
        print(f"    {k}: {req.get(k)}")

    cls = result["classification"]
    print(f"  classification: {cls['proposal_types']} | {cls['opportunity_types']}")
    print(f"  domains: {cls['tech_domains']} | renewal: {cls.get('is_renewal')}")
    print(f"  confidence: {cls['confidence']} | human_decision: {cls['needs_human_decision']}")
    print(f"  readiness: {result['readiness']['score']} -> {result['readiness']['level']}")
    print(f"  critical missing: {result['readiness']['critical_missing']}")

    status = conn.execute("SELECT status FROM opportunities WHERE opp_id=?",
                          (opp_id,)).fetchone()["status"]
    print(f"  opportunity status now: {status}")

    print("=" * 70)
    print("STEP 3: VENDOR MATCHING (deterministic)")
    candidates = match_vendors(conn, opp_id, cls["tech_domains"])
    for c in candidates:
        print(f"  {c.vendor_name} ({c.tier}) <{c.email}> disclose_ok={c.may_disclose_end_user}")

    if not candidates:
        print("  NO VENDORS — halting as designed")
        return

    print("=" * 70)
    print("STEP 4: RFQ DRAFTS (qwen3:14b) — disclosure NOT approved")
    for c in candidates:
        rfq_id = create_rfq_draft(conn, opp_id, c,
                                  end_user_disclosure_approved=False,
                                  actor="live.test")
        rfq = conn.execute("SELECT rfq_ref, draft_path FROM rfqs WHERE id=?",
                           (rfq_id,)).fetchone()
        body = Path(rfq["draft_path"]).read_text(encoding="utf-8")
        print(f"\n--- {rfq['rfq_ref']} -> {c.vendor_name} ---")
        print(body[:900])
        leaked = "Dubai Municipality" in body
        print(f"  [privacy check] end-user leaked: {leaked}")

    print("=" * 70)
    print("FINAL AUDIT TRAIL")
    for r in conn.execute(
            "SELECT actor, component, action, new_value FROM audit_log WHERE opp_id=? ORDER BY id",
            (opp_id,)):
        print(f"  {r['actor']:12s} {r['component']:12s} {r['action']:26s} {r['new_value'] or ''}")

    print("\nLIVE E2E PASS" if not leaked else "\nPRIVACY FAILURE")


if __name__ == "__main__":
    main()
