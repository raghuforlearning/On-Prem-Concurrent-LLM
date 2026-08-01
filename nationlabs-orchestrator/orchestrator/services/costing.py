"""Costing validation & approval routing (spec §19, §21, §22).
100% deterministic — no LLM anywhere in this module. Every check is recorded
individually in costing_checks with PASS/WARN/FAIL + evidence (§21).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime

from ..audit import audit
from ..config import CFG, Config
from ..statemachine import transition

log = logging.getLogger("orchestrator.costing")


def _record(conn, quote_id: int, name: str, result: str,
            expected=None, actual=None, evidence=None, correction=None) -> dict:
    conn.execute(
        """INSERT INTO costing_checks (quote_id, check_name, result, expected_value,
           actual_value, evidence_source, recommended_correction)
           VALUES (?,?,?,?,?,?,?)""",
        (quote_id, name, result,
         None if expected is None else str(expected),
         None if actual is None else str(actual), evidence, correction),
    )
    return {"check": name, "result": result, "expected": expected,
            "actual": actual, "correction": correction}


def validate_quote(conn: sqlite3.Connection, quote_id: int, *,
                   actor: str = "system", cfg: Config = CFG) -> dict:
    q = conn.execute("SELECT * FROM quotes WHERE id=?", (quote_id,)).fetchone()
    if q is None:
        raise KeyError(f"quote {quote_id}")
    data = json.loads(q["extracted_json"])
    items = data.get("line_items") or []
    checks = []

    # 1. Line arithmetic: qty × unit_price × (1 - discount) ≈ line_total
    arith_fail = []
    for i, it in enumerate(items):
        qty, price = it.get("quantity"), it.get("unit_price")
        lt = it.get("line_total")
        disc = (it.get("discount_percent") or 0) / 100.0
        if qty is not None and price is not None and lt is not None:
            expected = round(qty * price * (1 - disc), 2)
            if abs(expected - lt) > max(0.02, 0.005 * lt):
                arith_fail.append(f"line {i+1}: expected {expected}, got {lt}")
    checks.append(_record(conn, quote_id, "line_arithmetic",
                          "FAIL" if arith_fail else "PASS",
                          evidence="qty×price×(1-discount)=line_total",
                          actual="; ".join(arith_fail) if arith_fail else "all lines reconcile",
                          correction="request corrected quote" if arith_fail else None))

    # 2. Subtotal = Σ line_totals
    sum_lines = round(sum(it["line_total"] for it in items if it.get("line_total") is not None), 2)
    sub = data.get("subtotal")
    if sub is not None and sum_lines:
        ok = abs(sum_lines - sub) <= max(0.02, 0.005 * sub)
        checks.append(_record(conn, quote_id, "subtotal_reconciliation",
                              "PASS" if ok else "FAIL", expected=sum_lines, actual=sub))
    else:
        checks.append(_record(conn, quote_id, "subtotal_reconciliation", "WARN",
                              actual="subtotal missing", correction="request subtotal"))

    # 3. VAT: subtotal × vat% ≈ vat_amount; total = subtotal + vat
    vat_amt, total = data.get("vat_amount"), data.get("total")
    if sub and vat_amt is not None:
        exp_vat = round(sub * cfg.vat_percent / 100, 2)
        ok = abs(exp_vat - vat_amt) <= max(0.02, 0.01 * exp_vat)
        checks.append(_record(conn, quote_id, "vat_calculation",
                              "PASS" if ok else "FAIL", expected=exp_vat, actual=vat_amt,
                              evidence=f"UAE VAT {cfg.vat_percent}%"))
    elif sub:
        checks.append(_record(conn, quote_id, "vat_calculation", "WARN",
                              actual="VAT amount missing", correction="confirm VAT treatment"))
    if sub and vat_amt is not None and total is not None:
        exp_total = round(sub + vat_amt, 2)
        ok = abs(exp_total - total) <= max(0.02, 0.005 * exp_total)
        checks.append(_record(conn, quote_id, "total_reconciliation",
                              "PASS" if ok else "FAIL", expected=exp_total, actual=total))

    # 4. Missing core fields (§19 gate)
    missing = [f for f in ("quote_ref", "quote_expiry", "currency", "lead_time",
                           "payment_terms") if not data.get(f)]
    checks.append(_record(conn, quote_id, "core_fields_present",
                          "PASS" if not missing else "WARN",
                          actual="missing: " + ", ".join(missing) if missing else "all present"))

    # 5. Currency
    ccy = (data.get("currency") or "").upper()
    checks.append(_record(conn, quote_id, "currency_confirmed",
                          "PASS" if ccy in ("AED", "USD", "EUR") else "WARN",
                          actual=ccy or "missing",
                          correction=None if ccy == "AED" else "record FX source/date before costing"))

    # 6. Quote validity vs deadline
    validity_warn = None
    expiry, sub_deadline = data.get("quote_expiry"), None
    opp = conn.execute("SELECT submission_deadline FROM opportunities WHERE opp_id=?",
                       (q["opp_id"],)).fetchone()
    if expiry and opp and opp["submission_deadline"]:
        try:
            exp_d = datetime.fromisoformat(str(expiry)[:10])
            dl_d = datetime.fromisoformat(str(opp["submission_deadline"])[:10])
            if exp_d < dl_d:
                validity_warn = f"quote expires {expiry} BEFORE submission deadline {opp['submission_deadline']}"
        except ValueError:
            validity_warn = "unparseable expiry date — validate manually"
    elif not expiry:
        validity_warn = "no quote expiry given"
    checks.append(_record(conn, quote_id, "quote_validity_vs_deadline",
                          "PASS" if validity_warn is None else "WARN",
                          actual=validity_warn or "validity covers deadline"))

    # 7. Quantity match vs requirement (best-effort: requirement quantity string vs Σ qty)
    req_extraction = conn.execute("SELECT extraction_json FROM opportunities WHERE opp_id=?",
                                  (q["opp_id"],)).fetchone()
    if req_extraction and req_extraction["extraction_json"]:
        req_qty_str = (json.loads(req_extraction["extraction_json"])
                       .get("requirement", {}).get("quantity") or "")
        import re
        m = re.search(r"\d+", str(req_qty_str))
        if m and items:
            req_qty = int(m.group())
            quoted_qty = sum(it.get("quantity") or 0 for it in items)
            # main product line heuristic: max-qty line
            main_qty = max((it.get("quantity") or 0 for it in items), default=0)
            ok = req_qty in (quoted_qty, main_qty)
            checks.append(_record(conn, quote_id, "quantity_vs_requirement",
                                  "PASS" if ok else "WARN", expected=req_qty,
                                  actual=f"quoted main={main_qty}, total={quoted_qty}",
                                  correction=None if ok else "confirm scope coverage with vendor"))

    fails = [c for c in checks if c["result"] == "FAIL"]
    warns = [c for c in checks if c["result"] == "WARN"]

    new_status = ("Incomplete" if fails else
                  "Complete with assumptions" if warns else "Complete")
    with conn:
        conn.execute("UPDATE quotes SET status=? WHERE id=?", (new_status, quote_id))
        audit(conn, opp_id=q["opp_id"], actor=actor, component="costing",
              action="quote_validated", new_value=new_status,
              reason=f"{len(fails)} FAIL, {len(warns)} WARN")
    return {"quote_id": quote_id, "status": new_status, "checks": checks,
            "failures": fails, "warnings": warns}


def route_for_approval(conn: sqlite3.Connection, opp_id: str, *,
                       actor: str = "system", cfg: Config = CFG,
                       deal_reg_override: bool = False,
                       override_reason: str | None = None) -> str:
    """§22 routing. Returns 'FINANCE' or 'FINAL_VERIFIER'. Deterministic.
    §13 gate: the selected vendor's deal registration must be Approved (or Not
    required) before a proposal can be routed — price protection depends on it.
    A human may override with a reason; the override is audit-logged."""
    opp = conn.execute("SELECT * FROM opportunities WHERE opp_id=?", (opp_id,)).fetchone()
    if opp is None:
        raise KeyError(opp_id)

    quotes = conn.execute(
        """SELECT q.*, v.vendor_name, v.deal_reg_capable FROM quotes q
           JOIN vendors v ON v.id=q.vendor_id
           WHERE q.opp_id=? AND q.status IN ('Complete','Complete with assumptions')
           ORDER BY q.total_after_vat ASC""", (opp_id,)).fetchall()
    if len(quotes) < cfg.quotes_required_for_proposal:
        raise ValueError(f"need ≥{cfg.quotes_required_for_proposal} complete quotes; "
                         f"have {len(quotes)}")

    selected = quotes[0]  # lowest compliant quote (commercial evaluation is human;
                          # system pre-selects lowest for the approval packet)
    total = selected["total_after_vat"] or 0.0

    # §13 deal-registration gate
    dr = conn.execute(
        "SELECT status FROM deal_registrations WHERE opp_id=? AND vendor_id=?",
        (opp_id, selected["vendor_id"])).fetchone()
    dr_status = dr["status"] if dr else ("Not required" if not selected["deal_reg_capable"]
                                         else "Not submitted")
    if selected["deal_reg_capable"] and dr_status not in ("Approved", "Not required"):
        if not deal_reg_override:
            raise ValueError(
                f"DEAL REGISTRATION NOT SECURED for {selected['vendor_name']} "
                f"(status: {dr_status}). Routing blocked — proceeding without an approved "
                "registration loses price protection. Confirm the registration first, "
                "or override explicitly with a reason.")
        with conn:
            audit(conn, opp_id=opp_id, actor=actor, component="costing",
                  action="DEAL_REG_OVERRIDE",
                  new_value=f"{selected['vendor_name']} status={dr_status}",
                  reason=override_reason or "no reason given")

    # §22.3 additional triggers (MVP subset): any WARN/FAIL on costing → extra scrutiny flag
    warn_count = conn.execute(
        "SELECT COUNT(*) c FROM costing_checks WHERE quote_id=? AND result != 'PASS'",
        (selected["id"],)).fetchone()["c"]

    route = "FINANCE" if total > cfg.finance_threshold_aed else "FINAL_VERIFIER"
    requested_from = (cfg.finance_team_email if route == "FINANCE"
                      else (opp["opportunity_owner"] or "assigned verifier"))

    with conn:
        conn.execute(
            """INSERT INTO approvals (opp_id, kind, requested_from)
               VALUES (?, ?, ?)""",
            (opp_id, "FINANCE" if route == "FINANCE" else "FINAL_VERIFICATION",
             requested_from),
        )
        audit(conn, opp_id=opp_id, actor=actor, component="costing",
              action="approval_routed", new_value=route,
              reason=f"total={total:.2f} AED vs threshold {cfg.finance_threshold_aed}; "
                     f"selected={selected['vendor_name']}; open_check_flags={warn_count}; "
                     f"deal_reg={dr_status}")
        if opp["status"] == "Ready for Proposal":
            transition(conn, opp_id,
                       "Finance Approval Required" if route == "FINANCE" else "Final Verification",
                       actor=actor, reason=f"value {total:.0f} AED")

    # approval packet file
    packet = cfg.outbox / "approval_requests" / f"{opp_id}_{route}.txt"
    packet.write_text(
        f"PROPOSAL AWAITING APPROVAL — {route}\n"
        f"Opportunity: {opp_id} | {opp['requirement_title']}\n"
        f"Customer: {opp['customer_org']}\n"
        f"Selected quote: {selected['vendor_name']} — {total:,.2f} {selected['currency']}\n"
        f"Deal registration: {dr_status}\n"
        f"Deadline: {opp['submission_deadline']}\n"
        f"Open validation flags: {warn_count}\n"
        f"ACTION: review costing sheet and approve/reject.\n", encoding="utf-8")
    return route
