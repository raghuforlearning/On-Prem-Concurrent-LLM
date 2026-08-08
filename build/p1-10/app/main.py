"""P1-07 — NationLabs Orchestrator API (FastAPI modular monolith).
Adds workflow endpoints on top of the P1-03 health/audit skeleton.
"""
import os
import time
import json
import httpx
import psycopg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from db import PG_DSN, init_schema
import workflow
import rfq
import followup
from vendors import init_vendors

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
BOOT_TS = time.time()

app = FastAPI(title="NationLabs Orchestrator", version="0.4.0-p1.10")


@app.exception_handler(PermissionError)
async def permission_denied(_, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=403, content={"error": "FORBIDDEN", "detail": str(exc)})


@app.exception_handler(ValueError)
async def bad_request(_, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=400, content={"error": "BAD_REQUEST", "detail": str(exc)})


@app.on_event("startup")
def startup():
    init_schema()
    with psycopg.connect(PG_DSN) as conn:
        init_vendors(conn)
        followup.init_followups(conn)


@app.get("/healthz")
def healthz():
    checks = {}
    try:
        with psycopg.connect(PG_DSN, connect_timeout=3) as conn:
            checks["postgres"] = conn.execute("SELECT version()").fetchone()[0].split(",")[0]
    except Exception as e:
        checks["postgres"] = f"FAIL: {e}"
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        checks["ollama"] = f"ok, {len(r.json().get('models', []))} models"
    except Exception as e:
        checks["ollama"] = f"FAIL: {e}"
    ok = all(not str(v).startswith("FAIL") for v in checks.values())
    return {"status": "ok" if ok else "degraded", "uptime_s": round(time.time() - BOOT_TS, 1), **checks}


class IntakeIn(BaseModel):
    raw_text: str
    source_channel: str = "whatsapp"


@app.post("/opportunities")
def create_opportunity(body: IntakeIn):
    with psycopg.connect(PG_DSN) as conn:
        opp_id = workflow.intake(body.raw_text, body.source_channel, conn)
    try:
        result = workflow.run_workflow(opp_id)
    except Exception as e:
        raise HTTPException(502, f"workflow failed: {e}")
    return {"opp_id": opp_id, "status": result["status"]}


@app.get("/opportunities/{opp_id}")
def get_opportunity(opp_id: str):
    with psycopg.connect(PG_DSN) as conn:
        row = conn.execute(
            "SELECT opp_id, status, readiness_score, missing_fields, extraction_json, "
            "classification_json, created_at FROM opportunities WHERE opp_id=%s", (opp_id,)).fetchone()
        if not row:
            raise HTTPException(404, "not found")
        clarifs = conn.execute(
            "SELECT field, question, answer FROM clarifications WHERE opp_id=%s ORDER BY id",
            (opp_id,)).fetchall()
    return {
        "opp_id": row[0], "status": row[1], "readiness_score": row[2],
        "missing_fields": row[3], "extraction": row[4], "classification": row[5],
        "clarifications": [{"field": c[0], "question": c[1], "answer": c[2]} for c in clarifs],
    }


class AnswersIn(BaseModel):
    answers: dict   # {"customer.submission_deadline": "Aug 20", ...}


@app.post("/opportunities/{opp_id}/clarifications")
def answer_clarifications(opp_id: str, body: AnswersIn):
    result = workflow.submit_answers(opp_id, body.answers)
    return {"opp_id": opp_id, "status": result["status"]}


# ---------- P1-08 / P1-09: vendors, deal registration, RFQs ----------

class RfqCreateIn(BaseModel):
    disclose_end_user: bool = False


@app.post("/opportunities/{opp_id}/rfqs")
def create_rfqs(opp_id: str, body: RfqCreateIn):
    """Draft RFQs for all matched vendors; deal-reg gate applied per vendor."""
    return {"opp_id": opp_id, "rfqs": rfq.create_rfqs(opp_id, body.disclose_end_user)}


@app.get("/opportunities/{opp_id}/rfqs")
def list_rfqs(opp_id: str):
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT r.rfq_ref, v.vendor_name, v.tier, r.status, r.disclose_end_user, "
            "r.disclosure_approved_by, r.sent_at, left(r.draft_body, 400) "
            "FROM rfqs r JOIN vendors v ON v.vendor_id=r.vendor_id WHERE r.opp_id=%s "
            "ORDER BY r.created_at", (opp_id,)).fetchall()
    return [{"rfq_ref": r[0], "vendor": r[1], "tier": r[2], "status": r[3],
             "disclose_end_user": r[4], "disclosure_approved_by": r[5],
             "sent_at": str(r[6]) if r[6] else None, "draft_preview": r[7]} for r in rows]


class DealRegIn(BaseModel):
    vendor_id: int
    reg_reference: str
    approver: str


@app.post("/opportunities/{opp_id}/deal-reg/approve")
def deal_reg_approve(opp_id: str, body: DealRegIn):
    return rfq.approve_deal_reg(opp_id, body.vendor_id, body.reg_reference, body.approver)


class DisclosureIn(BaseModel):
    approver: str


@app.post("/rfqs/{rfq_ref}/approve-disclosure")
def disclosure_approve(rfq_ref: str, body: DisclosureIn):
    return rfq.approve_disclosure(rfq_ref, body.approver)


class SendIn(BaseModel):
    sender: str


@app.post("/rfqs/{rfq_ref}/send")
def rfq_send(rfq_ref: str, body: SendIn):
    """Human-controlled send. Idempotent. Structural gates enforced."""
    return rfq.send_rfq(rfq_ref, body.sender)


# ---------- P1-10 / P1-12: follow-up engine ----------

@app.post("/followups/run")
def followups_run():
    """Scheduler tick — driven by host cron every morning (08:07)."""
    return followup.process_followups()


class ResponseIn(BaseModel):
    response_type: str   # QUOTE/CLARIFICATION/ACK/REJECTION
    raw_text: str = ""
    actor: str = "api.user"


@app.post("/rfqs/{rfq_ref}/response")
def rfq_response(rfq_ref: str, body: ResponseIn):
    """Register a vendor response -> stops the follow-up cadence."""
    return followup.record_response(rfq_ref, body.response_type, body.raw_text, body.actor)


@app.get("/alerts")
def alerts():
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT id, rfq_ref, opp_id, kind, message, created_at FROM internal_alerts "
            "ORDER BY id DESC LIMIT 50").fetchall()
    return [{"id": r[0], "rfq_ref": r[1], "opp_id": r[2], "kind": r[3],
             "message": r[4], "at": str(r[5])} for r in rows]
