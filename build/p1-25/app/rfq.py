"""P1-09 — Deal-registration gate + RFQ drafting (human-controlled sending).

BUSINESS RULES (Architecture v2.0 §5, prototype-proven):
1. RFQ to an OEM or deal-reg-capable Distributor REQUIRES an approved deal
   registration. Without it: status = BLOCKED_PENDING_DEAL_REG. Structural —
   enforced in code, never a prompt request.
2. End-user identity is disclosed ONLY when (a) vendor tier is OEM/Distributor
   AND (b) a named human approved disclosure. Resellers never see end-user.
3. Sending is ALWAYS human-triggered (approved decision #8). Idempotency key
   makes double-clicks send exactly one RFQ.
4. Rejected/expired deal regs are retained — never deleted (v2.0 §5.9).
"""
import json
import os
import time
import httpx
import psycopg
from db import PG_DSN, audit
from vendors import match_vendors

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
DRAFT_MODEL = os.environ.get("DRAFT_MODEL", "qwen3:14b")

RFQ_DRAFT_SYSTEM = """You are the RFQ drafting module of NationLabs FZ LLC, a UAE IT
value-added reseller. Draft a professional vendor RFQ inquiry email.
RULES:
1. Output plain text email only. Subject line first ("Subject: ..."), then body.
2. Request: itemized pricing (AED), stock/lead time, and quote validity >= 30 days.
3. If DEAL REGISTRATION is requested in the input, include a formal deal
   registration request paragraph naming the end-user opportunity ONLY if
   end-user details were supplied; otherwise request registration without naming.
4. Never invent pricing, part numbers, or commitments. Professional, concise."""


def _next_rfq_ref(conn) -> str:
    from datetime import datetime
    year = datetime.now().year
    row = conn.execute(
        "SELECT rfq_ref FROM rfqs WHERE rfq_ref LIKE %s ORDER BY rfq_ref DESC LIMIT 1",
        (f"NL-RFQ-{year}-%",)).fetchone()
    seq = int(row[0].rsplit("-", 1)[1]) + 1 if row else 1
    return f"NL-RFQ-{year}-{seq:04d}"


def _draft_email(vendor: dict, extraction: dict, disclose: bool, need_reg: bool) -> tuple[str, int, int, int]:
    """LLM-drafted RFQ email. Returns (body, prompt_tokens, completion_tokens, latency_ms)."""
    req = extraction.get("requirement", {})
    cust = extraction.get("customer", {})
    user_msg = {
        "vendor": vendor["vendor_name"],
        "items": extraction.get("raw_summary") or req,
        "quantities": req.get("quantity"),
        "deal_registration_requested": need_reg,
        "end_user": cust.get("end_user_org") if disclose else None,
        "buyer_contact": cust.get("contact_name"),
    }
    payload = {
        "model": DRAFT_MODEL,
        "system": RFQ_DRAFT_SYSTEM,
        "prompt": json.dumps(user_msg),
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 900},
    }
    t0 = time.time()
    r = httpx.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=300)
    r.raise_for_status()
    body = r.json()
    return body["response"].strip(), body.get("prompt_eval_count"), body.get("eval_count"), int((time.time() - t0) * 1000)


def create_rfqs(opp_id: str, disclose_end_user: bool = False) -> list[dict]:
    """Draft one RFQ per matched vendor. Applies the deal-reg gate per vendor."""
    results = []
    vendors = match_vendors(opp_id)
    with psycopg.connect(PG_DSN) as conn:
        ext = conn.execute("SELECT extraction_json FROM opportunities WHERE opp_id=%s",
                           (opp_id,)).fetchone()[0]
        for v in vendors:
            need_reg = v["tier"] in ("OEM", "Distributor") and v["deal_reg_capable"]
            rfq_ref = _next_rfq_ref(conn)
            idem = f"{opp_id}:{v['vendor_id']}"
            exists = conn.execute("SELECT rfq_ref, status FROM rfqs WHERE idempotency_key=%s",
                                  (idem,)).fetchone()
            if exists:                      # idempotency: never draft twice
                results.append({"rfq_ref": exists[0], "vendor": v["vendor_name"],
                                "status": exists[1], "note": "already exists (idempotent)"})
                continue

            if need_reg:
                conn.execute(
                    "INSERT INTO deal_registrations (opp_id, vendor_id, status, notes) "
                    "VALUES (%s,%s,'REQUESTED','auto-requested at RFQ drafting') "
                    "ON CONFLICT (opp_id, vendor_id) DO NOTHING", (opp_id, v["vendor_id"]))
                dr = conn.execute(
                    "SELECT status FROM deal_registrations WHERE opp_id=%s AND vendor_id=%s",
                    (opp_id, v["vendor_id"])).fetchone()[0]
                status = "DRAFT" if dr == "APPROVED" else "BLOCKED_PENDING_DEAL_REG"
            else:
                status = "DRAFT"

            disclose = disclose_end_user and v["tier"] in ("OEM", "Distributor")
            if status != "BLOCKED_PENDING_DEAL_REG":
                body, ptok, ctok, lat = _draft_email(v, ext, disclose, need_reg)
                conn.execute(
                    "INSERT INTO token_metrics (opp_id, node, model, prompt_tokens, completion_tokens, latency_ms) "
                    "VALUES (%s,'rfq_draft',%s,%s,%s,%s)", (opp_id, DRAFT_MODEL, ptok, ctok, lat))
            else:
                body = None
            conn.execute(
                "INSERT INTO rfqs (rfq_ref, opp_id, vendor_id, status, draft_body, disclose_end_user, idempotency_key) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (rfq_ref, opp_id, v["vendor_id"], status, body, disclose, idem))
            audit(conn, "system", "rfq", "rfq_drafted" if body else "rfq_blocked_deal_reg",
                  opp_id, new=f"{rfq_ref}:{v['vendor_name']}:{status}")
            results.append({"rfq_ref": rfq_ref, "vendor": v["vendor_name"], "tier": v["tier"],
                            "status": status, "needs_deal_reg": need_reg})
        conn.commit()
    return results


def approve_deal_reg(opp_id: str, vendor_id: int, reg_reference: str, approver: str) -> dict:
    """Vendor approved the deal registration -> unblock the RFQ and draft it."""
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            "UPDATE deal_registrations SET status='APPROVED', reg_reference=%s, updated_at=now() "
            "WHERE opp_id=%s AND vendor_id=%s", (reg_reference, opp_id, vendor_id))
        rfq = conn.execute(
            "SELECT rfq_ref, status FROM rfqs WHERE opp_id=%s AND vendor_id=%s",
            (opp_id, vendor_id)).fetchone()
        if rfq and rfq[1] == "BLOCKED_PENDING_DEAL_REG":
            ext = conn.execute("SELECT extraction_json FROM opportunities WHERE opp_id=%s",
                               (opp_id,)).fetchone()[0]
            v = conn.execute(
                "SELECT vendor_id, vendor_name, tier FROM vendors WHERE vendor_id=%s",
                (vendor_id,)).fetchone()
            vd = {"vendor_id": v[0], "vendor_name": v[1], "tier": v[2]}
            disclose = conn.execute(
                "SELECT disclose_end_user FROM rfqs WHERE rfq_ref=%s", (rfq[0],)).fetchone()[0]
            body, ptok, ctok, lat = _draft_email(vd, ext, disclose, True)
            conn.execute(
                "INSERT INTO token_metrics (opp_id, node, model, prompt_tokens, completion_tokens, latency_ms) "
                "VALUES (%s,'rfq_draft',%s,%s,%s,%s)", (opp_id, DRAFT_MODEL, ptok, ctok, lat))
            conn.execute("UPDATE rfqs SET status='DRAFT', draft_body=%s WHERE rfq_ref=%s", (body, rfq[0]))
        audit(conn, approver, "dealreg", "deal_reg_approved", opp_id,
              new=f"vendor {vendor_id}, ref {reg_reference}")
        conn.commit()
        return {"rfq_ref": rfq[0] if rfq else None, "status": "DRAFT"}


def approve_disclosure(rfq_ref: str, approver: str) -> dict:
    with psycopg.connect(PG_DSN) as conn:
        conn.execute(
            "UPDATE rfqs SET disclosure_approved_by=%s WHERE rfq_ref=%s", (approver, rfq_ref))
        audit(conn, approver, "rfq", "end_user_disclosure_approved", new=rfq_ref)
        conn.commit()
    return {"rfq_ref": rfq_ref, "disclosure_approved_by": approver}


def send_rfq(rfq_ref: str, sender: str) -> dict:
    """HUMAN-CONTROLLED send. Structural gates: draft must exist; disclosure of
    end-user requires recorded approval. Idempotent: already-SENT returns as-is."""
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT r.opp_id, r.status, r.draft_body, r.disclose_end_user, r.disclosure_approved_by, "
            "v.vendor_name, v.tier FROM rfqs r JOIN vendors v ON v.vendor_id=r.vendor_id "
            "WHERE r.rfq_ref=%s", (rfq_ref,)).fetchone()
        if not row:
            raise ValueError("unknown rfq")
        opp_id, status, body, disclose, disc_by, vname, tier = row
        if status == "SENT":
            return {"rfq_ref": rfq_ref, "status": "SENT", "note": "already sent (idempotent)"}
        if status == "BLOCKED_PENDING_DEAL_REG":
            raise PermissionError("RFQ blocked: deal registration not approved")
        if not body:
            raise ValueError("no draft body")
        if disclose and tier in ("OEM", "Distributor") and not disc_by:
            raise PermissionError("end-user disclosure requires recorded human approval")
        conn.execute("UPDATE rfqs SET status='SENT', sent_at=now() WHERE rfq_ref=%s", (rfq_ref,))
        audit(conn, sender, "rfq", "rfq_sent_human_triggered", opp_id, new=f"{rfq_ref}:{vname}")
        conn.commit()
    return {"rfq_ref": rfq_ref, "status": "SENT", "vendor": vname}
