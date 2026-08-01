"""FastAPI web UI — intake, pipeline board, approvals, vendor-response paste-in.
Air-gap safe: HTMX vendored locally in web/static/, no CDNs/fonts/telemetry.
Run: uvicorn orchestrator.web.app:app --host 0.0.0.0 --port 8100
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import CFG, ensure_dirs
from ..db import get_db, init_db
from ..ollama_client import LLMOutputError
from ..services import analysis, comms, costing, responses
from ..services.intake import create_opportunity, extract_text
from ..services.vendor import match_vendors

app = FastAPI(title="NationLabs Presales Orchestrator", docs_url=None, redoc_url=None)
BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


def db() -> sqlite3.Connection:
    ensure_dirs()
    init_db(CFG.db_path)
    return get_db(CFG.db_path)


def actor(request: Request) -> str:
    return request.headers.get("X-NL-User", "web.user")  # Phase 2: real auth


@app.on_event("startup")
def _startup() -> None:
    ensure_dirs()
    init_db(CFG.db_path)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    return templates.TemplateResponse(
        request, "message.html",
        {"msg": f"Something went wrong: {type(exc).__name__}: {exc}. "
                f"Nothing was sent or approved — check the audit log.", "opp_id": None},
        status_code=500)


# ---------- Board ----------
@app.get("/", response_class=HTMLResponse)
def board(request: Request):
    conn = db()
    rows = conn.execute(
        """SELECT opp_id, status, customer_org, requirement_title, readiness_score,
                  submission_deadline, opportunity_owner, updated_at
           FROM opportunities ORDER BY updated_at DESC LIMIT 100""").fetchall()
    pending = conn.execute(
        """SELECT a.id, a.opp_id, a.kind, a.request_path, a.created_at
           FROM approvals a WHERE a.decision IS NULL ORDER BY a.created_at""").fetchall()
    return templates.TemplateResponse(request, "board.html", {"opps": rows, "approvals": pending})


# ---------- Intake ----------
@app.get("/intake", response_class=HTMLResponse)
def intake_form(request: Request):
    return templates.TemplateResponse(request, "intake.html", {})


@app.post("/intake")
async def intake_submit(
    request: Request,
    pasted_text: str = Form(""),
    customer_org: str = Form(""),
    end_user_org: str = Form(""),
    opportunity_owner: str = Form(""),
    submission_deadline: str = Form(""),
    file: UploadFile | None = File(None),
):
    tmp_path = None
    try:
        if file and file.filename:
            tmp_path = CFG.inbox / file.filename
            tmp_path.write_bytes(await file.read())
        opp_id, text = create_opportunity(
            db(), source_channel="file" if tmp_path else "whatsapp_paste",
            actor=actor(request),
            pasted_text=pasted_text or None, file_path=tmp_path,
            customer_org=customer_org or None, end_user_org=end_user_org or None,
            opportunity_owner=opportunity_owner or None,
            submission_deadline=submission_deadline or None)
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


# ---------- Opportunity detail ----------
@app.get("/opportunity/{opp_id}", response_class=HTMLResponse)
def detail(request: Request, opp_id: str):
    conn = db()
    opp = conn.execute("SELECT * FROM opportunities WHERE opp_id=?", (opp_id,)).fetchone()
    if opp is None:
        return HTMLResponse("not found", 404)
    rfqs = conn.execute(
        """SELECT r.*, v.vendor_name FROM rfqs r JOIN vendors v ON v.id=r.vendor_id
           WHERE r.opp_id=?""", (opp_id,)).fetchall()
    quotes = conn.execute(
        """SELECT q.*, v.vendor_name FROM quotes q JOIN vendors v ON v.id=q.vendor_id
           WHERE q.opp_id=?""", (opp_id,)).fetchall()
    trail = conn.execute(
        "SELECT ts, actor, action, new_value, reason FROM audit_log WHERE opp_id=? ORDER BY id DESC LIMIT 30",
        (opp_id,)).fetchall()
    return templates.TemplateResponse(request, "detail.html", {"opp": opp,
        "extraction": json.loads(opp["extraction_json"] or "null"),
        "classification": json.loads(opp["classification_json"] or "null"),
        "rfqs": rfqs, "quotes": quotes, "trail": trail})


@app.post("/opportunity/{opp_id}/analyse")
def analyse(request: Request, opp_id: str):
    conn = db()
    opp = conn.execute("SELECT * FROM opportunities WHERE opp_id=?", (opp_id,)).fetchone()
    try:
        src = Path(opp["source_raw_path"])
        derived = src.parent / "extracted_text.txt"
        if derived.exists():
            text = derived.read_text(encoding="utf-8", errors="replace")
        elif src.suffix.lower() == ".txt":
            text = src.read_text(encoding="utf-8", errors="replace")
        else:
            text = extract_text(src)
        if not text.strip():
            raise ValueError("no readable text (OCR engine not available on this machine)")
        analysis.analyse_opportunity(conn, opp_id, text)
        msg = "analysis complete"
    except LLMOutputError as e:
        msg = f"LLM FAILED — human review needed: {e}"
    except Exception as e:
        msg = (f"Could not read source: {e}. The original file is preserved — "
               f"paste the text manually via a new intake instead.")
    return templates.TemplateResponse(request, "message.html", {"msg": msg, "opp_id": opp_id})


@app.post("/opportunity/{opp_id}/clarify")
def clarify(request: Request, opp_id: str,
            customer_org: str = Form(""), end_user_org: str = Form(""),
            submission_deadline: str = Form(""), clarification_note: str = Form("")):
    """Human answers to clarification questions — authoritative per spec §3."""
    conn = db()
    opp = conn.execute("SELECT * FROM opportunities WHERE opp_id=?", (opp_id,)).fetchone()
    if opp is None:
        return HTMLResponse("not found", 404)
    updates, params = [], []
    for col, val in (("customer_org", customer_org), ("end_user_org", end_user_org),
                     ("submission_deadline", submission_deadline)):
        if val:
            updates.append(f"{col}=?")
            params.append(val)
    with conn:
        if updates:
            conn.execute(
                f"UPDATE opportunities SET {', '.join(updates)}, updated_at=datetime('now') "
                f"WHERE opp_id=?", (*params, opp_id))
        if clarification_note:
            conn.execute(
                "INSERT INTO clarifications (opp_id, question, answer, is_critical, answered_at) "
                "VALUES (?, 'clarification_note', ?, 0, datetime('now'))",
                (opp_id, clarification_note))
        from ..audit import audit
        audit(conn, opp_id=opp_id, actor=actor(request), component="web",
              action="clarification_provided",
              new_value="; ".join(f"{c.split('=')[0]}" for c in updates) or "note only")
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


@app.post("/opportunity/{opp_id}/draft_rfqs")
def draft_rfqs(request: Request, opp_id: str,
               disclose_end_user: str = Form("off")):
    conn = db()
    opp = conn.execute("SELECT * FROM opportunities WHERE opp_id=?", (opp_id,)).fetchone()
    cls = json.loads(opp["classification_json"] or "{}")
    domains = cls.get("tech_domains") or ["Other"]
    candidates = match_vendors(conn, opp_id, domains)
    approved = disclose_end_user == "on"
    made = [comms.create_rfq_draft(conn, opp_id, c,
                                   end_user_disclosure_approved=approved,
                                   actor=actor(request))
            for c in candidates]
    return templates.TemplateResponse(request, "message.html", {"msg": f"drafted {len(made)} RFQs (disclosure approved: {approved}) — awaiting approval",
        "opp_id": opp_id})


# ---------- Approvals ----------
@app.post("/rfq/{rfq_id}/approve")
def approve(request: Request, rfq_id: int):
    path = comms.approve_rfq(db(), rfq_id, approver=actor(request))
    return HTMLResponse(f"APPROVED. Dispatch this file manually: <code>{path}</code> "
                        f"then confirm: <form method='post' action='/rfq/{rfq_id}/confirm_sent'>"
                        f"<button>Confirm Sent</button></form>")


@app.post("/rfq/{rfq_id}/confirm_sent")
def confirm_sent(request: Request, rfq_id: int):
    conn = db()
    comms.confirm_rfq_sent(conn, rfq_id, actor=actor(request))
    opp_id = conn.execute("SELECT opp_id FROM rfqs WHERE id=?", (rfq_id,)).fetchone()["opp_id"]
    return RedirectResponse(f"/opportunity/{opp_id}", status_code=303)


# ---------- Vendor response paste-in ----------
@app.get("/rfq/{rfq_id}/respond", response_class=HTMLResponse)
def respond_form(request: Request, rfq_id: int):
    return templates.TemplateResponse(request, "respond.html", {"rfq_id": rfq_id})


@app.post("/rfq/{rfq_id}/respond")
def respond_submit(request: Request, rfq_id: int, response_text: str = Form(...)):
    conn = db()
    try:
        result = responses.process_vendor_response(conn, rfq_id, response_text,
                                                   actor=actor(request))
        msg = (f"classified as: {result['classification']['response_type']} "
               f"(conf {result['classification']['confidence']})"
               + (f" | quote_id={result['quote_id']}" if "quote_id" in result else ""))
    except LLMOutputError as e:
        msg = f"LLM FAILED — classify manually: {e}"
    rfq = conn.execute("SELECT opp_id FROM rfqs WHERE id=?", (rfq_id,)).fetchone()
    return templates.TemplateResponse(request, "message.html", {"msg": msg,
                                       "opp_id": rfq["opp_id"]})


# ---------- Quotes: validate & route ----------
@app.post("/quote/{quote_id}/validate")
def validate(request: Request, quote_id: int):
    conn = db()
    result = costing.validate_quote(conn, quote_id, actor=actor(request))
    opp_id = conn.execute("SELECT opp_id FROM quotes WHERE id=?", (quote_id,)).fetchone()["opp_id"]
    summary = "; ".join(f"{c['check']}={c['result']}" for c in result["checks"])
    return templates.TemplateResponse(request, "message.html", {"msg": f"quote status: {result['status']} — {summary}", "opp_id": opp_id})


@app.post("/opportunity/{opp_id}/route")
def route(request: Request, opp_id: str):
    conn = db()
    try:
        dest = costing.route_for_approval(conn, opp_id, actor=actor(request))
        msg = f"routed to: {dest}"
    except ValueError as e:
        msg = str(e)
    return templates.TemplateResponse(request, "message.html", {"msg": msg, "opp_id": opp_id})
