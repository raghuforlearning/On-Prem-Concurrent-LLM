"""P1-07 — NationLabs Orchestrator API (FastAPI modular monolith).
Adds workflow endpoints on top of the P1-03 health/audit skeleton.
"""
import os
import time
import json
from hashlib import sha256
from decimal import Decimal
from datetime import date
import httpx
import psycopg
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from db import PG_DSN, init_schema
import workflow
import rfq
import followup
import approvals
import quotes as quote_store
import knowledge as knowledge_store
import quote_comparison as comparison_store
import proposals as proposal_store
import benchmarks as benchmark_store
import security as security_store
import document_render_queue as render_queue_store
from vendors import init_vendors
from integrations.proposal_builder import (
    BuilderError,
    ExistingProposalBuilderClient,
    ProposalBuilderClient,
)
from quote_lifecycle import QuoteArchive, QuoteIngestionService
from quote_validation import CommercialClaims, ValidationPolicy
from integrations.ollama import OllamaClient

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://host.docker.internal:11434")
BOOT_TS = time.time()

app = FastAPI(title="NationLabs Orchestrator", version="1.0.0-p1.25")


@app.get("/ui", include_in_schema=False)
def ui():
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")


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
        approvals.init_approvals(conn)
        quote_store.init_quotes(conn)
    knowledge_store.init_knowledge(PG_DSN)
    comparison_store.init_quote_comparison(PG_DSN)
    proposal_store.init_proposals(PG_DSN)
    benchmark_store.init_benchmarks(PG_DSN)
    security_store.init_security(PG_DSN)
    render_queue_store.init_document_render_queue(PG_DSN)


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


@app.get("/opportunities")
def list_opportunities():
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT opp_id, status, readiness_score, extraction_json->'requirement'->>'title', "
            "created_at FROM opportunities ORDER BY created_at DESC LIMIT 100").fetchall()
    return [{"opp_id": r[0], "status": r[1], "readiness_score": r[2],
             "title": r[3], "created_at": str(r[4])} for r in rows]


@app.get("/metrics/tokens")
def token_metrics():
    with psycopg.connect(PG_DSN) as conn:
        r = conn.execute(
            "SELECT count(*), coalesce(sum(prompt_tokens),0), coalesce(sum(completion_tokens),0), "
            "avg(latency_ms) FROM token_metrics").fetchone()
    return {"total_calls": r[0], "prompt_tokens": r[1], "completion_tokens": r[2],
            "avg_latency_ms": round(r[3]) if r[3] else None}


@app.post("/opportunities")
def create_opportunity(body: IntakeIn):
    with psycopg.connect(PG_DSN) as conn:
        opp_id = workflow.intake(body.raw_text, body.source_channel, conn)
    try:
        result = workflow.run_workflow(opp_id)
    except Exception as e:
        raise HTTPException(502, f"workflow failed: {e}")
    return {"opp_id": opp_id, "status": result["status"]}


import intake_files
from pathlib import Path

ARCHIVE = Path("/srv/data/rfp_archive")
QUOTE_ARCHIVE = Path("/srv/data/quote_archive")
MAX_QUOTE_BYTES = 50 * 1024 * 1024
MAX_RENDER_ARTIFACT_BYTES = 100 * 1024 * 1024


@app.post("/opportunities/upload")
async def upload_opportunity(file: UploadFile = File(...)):
    """File intake: PDF / XLSX / CSV / DOCX / image / txt. Original preserved
    byte-for-byte + hashed; extracted text flows into the same workflow."""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in intake_files.SUPPORTED:
        raise HTTPException(400, f"unsupported type {suffix}; allowed: {sorted(intake_files.SUPPORTED)}")
    data = await file.read()
    digest = intake_files.sha256_bytes(data)
    opp_dir = ARCHIVE / digest[:16]
    opp_dir.mkdir(parents=True, exist_ok=True)
    original = opp_dir / f"original{suffix}"
    original.write_bytes(data)
    try:
        text, method = intake_files.extract_text(original)
    except ValueError as e:
        raise HTTPException(422, str(e))
    with psycopg.connect(PG_DSN) as conn:
        opp_id = workflow.intake(text, f"upload:{suffix}", conn,
                                 extraction_method=method,
                                 original_path=str(original),
                                 original_filename=file.filename)
    try:
        result = workflow.run_workflow(opp_id)
    except Exception as e:
        raise HTTPException(502, f"workflow failed: {e}")
    return {"opp_id": opp_id, "status": result["status"],
            "extraction_method": method, "sha256": digest, "chars": len(text)}


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
            "r.disclosure_approved_by, r.sent_at, left(r.draft_body, 400), v.vendor_id "
            "FROM rfqs r JOIN vendors v ON v.vendor_id=r.vendor_id WHERE r.opp_id=%s "
            "ORDER BY r.created_at", (opp_id,)).fetchall()
    return [{"rfq_ref": r[0], "vendor": r[1], "tier": r[2], "status": r[3],
             "disclose_end_user": r[4], "disclosure_approved_by": r[5],
             "sent_at": str(r[6]) if r[6] else None, "draft_preview": r[7],
             "vendor_id": r[8]} for r in rows]


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


# ---------- P1-15: quote lifecycle / frozen Proposal Builder adapter ----------

def _proposal_builder_quote_client() -> ProposalBuilderClient:
    return ProposalBuilderClient(
        os.environ.get("PROPOSAL_BUILDER_URL", ""),
        os.environ.get("PROPOSAL_BUILDER_USERNAME", ""),
        os.environ.get("PROPOSAL_BUILDER_PASSWORD", ""),
        timeout_s=float(os.environ.get("PROPOSAL_BUILDER_TIMEOUT_S", "120")),
    )


def _proposal_builder_build_client() -> ProposalBuilderClient:
    base_url = (
        os.environ.get("PROPOSAL_BUILDER_BUILD_URL")
        or os.environ.get("PROPOSAL_BUILDER_URL", "")
    )
    username = os.environ.get("PROPOSAL_BUILDER_USERNAME", "")
    password = os.environ.get("PROPOSAL_BUILDER_PASSWORD", "")
    timeout_s = float(os.environ.get("PROPOSAL_BUILDER_TIMEOUT_S", "120"))
    transport = os.environ.get("PROPOSAL_BUILDER_BUILD_TRANSPORT", "existing_sync").strip().lower()
    if transport == "existing_sync":
        source_roots = [
            item.strip()
            for item in os.environ.get(
                "PROPOSAL_BUILDER_SOURCE_ARTIFACT_ROOTS",
                "/srv/data/rfp_archive,/srv/data/quote_archive,/srv/data/proposal_artifacts",
            ).split(",")
            if item.strip()
        ]
        return ExistingProposalBuilderClient(
            base_url,
            username,
            password,
            artifact_root=os.environ.get(
                "PROPOSAL_BUILDER_ARTIFACT_ROOT", "/srv/data/proposal_artifacts"
            ),
            source_artifact_roots=source_roots,
            timeout_s=timeout_s,
        )
    if transport != "v1_async":
        raise ValueError(
            "PROPOSAL_BUILDER_BUILD_TRANSPORT must be v1_async or existing_sync"
        )
    return ProposalBuilderClient(
        base_url,
        username,
        password,
        timeout_s=timeout_s,
    )


@app.get("/integrations/proposal-builder/health")
def proposal_builder_health():
    if not os.environ.get("PROPOSAL_BUILDER_URL"):
        return {"status": "unconfigured"}
    client = _proposal_builder_quote_client()
    try:
        return client.health()
    except BuilderError as exc:
        return {"status": "degraded", "error_code": exc.code, "detail": str(exc)}
    finally:
        client.close()


@app.get("/integrations/proposal-builder/build-health")
def proposal_builder_build_health():
    if not (os.environ.get("PROPOSAL_BUILDER_BUILD_URL") or os.environ.get("PROPOSAL_BUILDER_URL")):
        return {"status": "unconfigured"}
    try:
        client = _proposal_builder_build_client()
        result = client.health()
        result["transport"] = getattr(client, "transport", "v1_async")
        return result
    except (BuilderError, ValueError) as exc:
        return {
            "status": "degraded",
            "error_code": getattr(exc, "code", "BUILDER_CONFIGURATION_INVALID"),
            "detail": str(exc),
        }
    finally:
        if "client" in locals():
            client.close()


@app.post("/rfqs/{rfq_ref}/quotes")
async def ingest_quote(
    rfq_ref: str,
    file: UploadFile = File(...),
    quote_reference: str | None = Form(None),
    actor: str = Form("api.user"),
):
    """Archive and parse a vendor quote without applying the proposal DR gate.

    Deal Registration may be pending: P1-15 records and parses the quote, while
    proposal generation/release remains responsible for the later gate.
    """
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty quote file")
    if len(data) > MAX_QUOTE_BYTES:
        raise HTTPException(413, f"quote exceeds {MAX_QUOTE_BYTES // (1024 * 1024)} MB limit")
    client = _proposal_builder_quote_client()
    try:
        service = QuoteIngestionService(
            quote_store.PostgresQuoteRepository(),
            client,
            QuoteArchive(QUOTE_ARCHIVE),
        )
        outcome = service.ingest(
            rfq_ref=rfq_ref,
            content=data,
            filename=file.filename or "quote.bin",
            content_type=file.content_type,
            quote_reference=quote_reference,
            actor=actor,
        )
        return outcome.as_dict()
    finally:
        client.close()


@app.get("/rfqs/{rfq_ref}/quotes")
def list_quotes(rfq_ref: str):
    return quote_store.PostgresQuoteRepository().list_for_rfq(rfq_ref)


@app.get("/quote-reviews")
def quote_reviews():
    return quote_store.PostgresQuoteRepository().list_open_reviews()


# ---------- P1-16: deterministic quote validation ----------

def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _quote_validation_policy() -> ValidationPolicy:
    required_terms = tuple(
        item.strip().lower()
        for item in os.environ.get("QUOTE_VALIDATION_REQUIRED_TERMS", "").split(",")
        if item.strip()
    )
    return ValidationPolicy(
        money_tolerance=Decimal(os.environ.get("QUOTE_VALIDATION_MONEY_TOLERANCE", "0.01")),
        require_currency_detected=_env_bool(
            "QUOTE_VALIDATION_REQUIRE_CURRENCY_DETECTED", True
        ),
        require_stated_totals=_env_bool("QUOTE_VALIDATION_REQUIRE_STATED_TOTALS", False),
        require_vat=_env_bool("QUOTE_VALIDATION_REQUIRE_VAT", False),
        required_terms=required_terms,
    )


class QuoteValidationIn(BaseModel):
    stated_subtotal: Decimal | None = None
    vat_rate_percent: Decimal | None = None
    stated_vat: Decimal | None = None
    stated_total: Decimal | None = None
    validity_terms: str | None = None
    payment_terms: str | None = None
    delivery_terms: str | None = None
    actor: str = "api.user"


@app.post("/quotes/{quote_id}/validate")
def validate_quote(quote_id: int, body: QuoteValidationIn):
    """Compare persisted vendor claims with deterministic Decimal calculations."""
    claims = CommercialClaims.create(
        stated_subtotal=body.stated_subtotal,
        vat_rate_percent=body.vat_rate_percent,
        stated_vat=body.stated_vat,
        stated_total=body.stated_total,
        validity_terms=body.validity_terms,
        payment_terms=body.payment_terms,
        delivery_terms=body.delivery_terms,
    )
    return quote_store.PostgresQuoteRepository().validate_quote(
        quote_id=quote_id,
        claims=claims,
        policy=_quote_validation_policy(),
        actor=body.actor,
    )


@app.get("/quotes/{quote_id}/validation")
def quote_validation(quote_id: int):
    result = quote_store.PostgresQuoteRepository().latest_validation(quote_id)
    if result is None:
        raise HTTPException(404, "quote has no validation result")
    return result


# ---------- P1-18: deterministic multi-vendor comparison and selection ----------

class ExchangeRateIn(BaseModel):
    currency: str
    aed_per_unit: Decimal
    rate_date: date
    source_reference: str
    actor: str = "api.user"


@app.post("/exchange-rates")
def record_exchange_rate(body: ExchangeRateIn):
    """Record a human-supplied AED rate; no network or LLM rate lookup exists."""
    return comparison_store.QuoteComparisonRepository(PG_DSN).record_exchange_rate(
        currency=body.currency,
        aed_per_unit=body.aed_per_unit,
        rate_date=body.rate_date,
        source_reference=body.source_reference,
        actor=body.actor,
    )


class QuoteComparisonIn(BaseModel):
    quote_ids: list[int]
    exchange_rate_ids: dict[int, int] = {}
    actor: str = "api.user"


@app.post("/opportunities/{opp_id}/quote-comparisons")
def create_quote_comparison(opp_id: str, body: QuoteComparisonIn):
    return comparison_store.QuoteComparisonRepository(PG_DSN).create_comparison(
        opp_id=opp_id,
        quote_ids=body.quote_ids,
        exchange_rate_ids=body.exchange_rate_ids,
        actor=body.actor,
    )


@app.get("/opportunities/{opp_id}/quote-comparisons")
def list_quote_comparisons(opp_id: str):
    return comparison_store.QuoteComparisonRepository(PG_DSN).list_comparisons(opp_id)


class QuoteSelectionIn(BaseModel):
    quote_id: int
    actor: str
    reason: str


@app.post("/quote-comparisons/{comparison_run_id}/select")
def select_comparison_quote(comparison_run_id: int, body: QuoteSelectionIn):
    """Freeze the exact human-selected quote/version and comparison snapshot."""
    return comparison_store.QuoteComparisonRepository(PG_DSN).select_quote(
        comparison_run_id=comparison_run_id,
        quote_id=body.quote_id,
        actor=body.actor,
        reason=body.reason,
    )


@app.get("/opportunities/{opp_id}/quote-selection")
def active_quote_selection(opp_id: str):
    result = comparison_store.QuoteComparisonRepository(PG_DSN).active_selection(opp_id)
    if result is None:
        raise HTTPException(404, "opportunity has no active quote selection")
    return result


# ---------- P1-19: Proposal Builder handoff ----------

class ProposalAssembleIn(BaseModel):
    opp_id: str
    template_version: str
    actor: str = "api.user"
    context: dict = Field(default_factory=dict)


@app.post("/proposals/{proposal_type}/assemble")
def assemble_proposal(proposal_type: str, body: ProposalAssembleIn):
    """Freeze an approved structured payload for the external Proposal Builder."""
    return proposal_store.ProposalRepository(PG_DSN).assemble(
        opp_id=body.opp_id,
        proposal_type=proposal_type,
        template_version=body.template_version,
        actor=body.actor,
        context=body.context,
    )


class ProposalBuildIn(BaseModel):
    actor: str = "api.user"


@app.post("/proposals/{proposal_id}/build")
def build_proposal(proposal_id: int, body: ProposalBuildIn):
    client = _proposal_builder_build_client()
    try:
        return proposal_store.ProposalRepository(PG_DSN).submit_build(
            proposal_id=proposal_id,
            adapter=client,
            actor=body.actor,
        )
    finally:
        client.close()


@app.post("/proposal-build-jobs/{build_job_id}/refresh")
def refresh_proposal_build(build_job_id: int, body: ProposalBuildIn):
    client = _proposal_builder_build_client()
    try:
        return proposal_store.ProposalRepository(PG_DSN).refresh_build(
            build_job_id=build_job_id,
            adapter=client,
            actor=body.actor,
        )
    finally:
        client.close()


@app.get("/proposals/{proposal_id}/artifacts")
def proposal_artifacts(proposal_id: int):
    return proposal_store.ProposalRepository(PG_DSN).artifacts(proposal_id)


# ---------- P1-21: durable isolated document-render queue ----------

class DocumentRenderEnqueueIn(BaseModel):
    security_clearance: dict
    actor: str = "api.user"
    renderer_profile: str = "word-com-v1"


@app.post("/proposal-build-jobs/{build_job_id}/render")
def enqueue_document_render(build_job_id: int, body: DocumentRenderEnqueueIn):
    """Queue a hash-cleared Builder DOCX; does not alter proposal content."""
    return render_queue_store.DocumentRenderQueue(PG_DSN).enqueue(
        build_job_id=build_job_id,
        security_clearance=body.security_clearance,
        actor=body.actor,
        renderer_profile=body.renderer_profile,
    )


def _require_document_worker_token(supplied: str | None) -> None:
    import hmac

    configured = os.environ.get("DOCUMENT_WORKER_TOKEN", "")
    if not configured:
        raise HTTPException(503, "document worker token is not configured")
    if not supplied or not hmac.compare_digest(supplied, configured):
        raise HTTPException(401, "invalid document worker token")


class DocumentWorkerClaimIn(BaseModel):
    worker_id: str
    lease_seconds: int = 120
    max_claims: int = 3


class DocumentWorkerLeaseIn(BaseModel):
    worker_id: str
    lease_seconds: int = 120


class DocumentWorkerCompleteIn(BaseModel):
    worker_id: str
    result: dict


@app.post("/internal/document-worker/jobs/claim")
def claim_document_render(
    body: DocumentWorkerClaimIn,
    x_document_worker_token: str | None = Header(default=None),
):
    _require_document_worker_token(x_document_worker_token)
    return render_queue_store.DocumentRenderQueue(PG_DSN).claim(
        worker_id=body.worker_id,
        lease_seconds=body.lease_seconds,
        max_claims=body.max_claims,
    )


@app.post("/internal/document-worker/jobs/{render_job_id}/start")
def start_document_render(
    render_job_id: int,
    body: DocumentWorkerLeaseIn,
    x_document_worker_token: str | None = Header(default=None),
):
    _require_document_worker_token(x_document_worker_token)
    return render_queue_store.DocumentRenderQueue(PG_DSN).start(
        render_job_id=render_job_id,
        worker_id=body.worker_id,
        lease_seconds=body.lease_seconds,
    )


@app.post("/internal/document-worker/jobs/{render_job_id}/heartbeat")
def heartbeat_document_render(
    render_job_id: int,
    body: DocumentWorkerLeaseIn,
    x_document_worker_token: str | None = Header(default=None),
):
    _require_document_worker_token(x_document_worker_token)
    return render_queue_store.DocumentRenderQueue(PG_DSN).heartbeat(
        render_job_id=render_job_id,
        worker_id=body.worker_id,
        lease_seconds=body.lease_seconds,
    )


@app.get("/internal/document-worker/jobs/{render_job_id}/source")
def document_render_source(
    render_job_id: int,
    worker_id: str,
    x_document_worker_token: str | None = Header(default=None),
):
    _require_document_worker_token(x_document_worker_token)
    source = render_queue_store.DocumentRenderQueue(PG_DSN).source_file(
        render_job_id=render_job_id,
        worker_id=worker_id,
        allowed_roots=[
            os.environ.get("PROPOSAL_BUILDER_ARTIFACT_ROOT", "/srv/data/proposal_artifacts")
        ],
    )
    from fastapi.responses import FileResponse

    return FileResponse(
        path=source["path"],
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"p121-{render_job_id}-source.docx",
        headers={
            "X-Document-SHA256": source["source_sha256"],
            "X-Document-Request-Hash": source["request_hash"],
        },
    )


@app.get("/internal/document-worker/jobs/{render_job_id}/source-manifest")
def document_render_source_manifest(
    render_job_id: int,
    worker_id: str,
    x_document_worker_token: str | None = Header(default=None),
):
    _require_document_worker_token(x_document_worker_token)
    return render_queue_store.DocumentRenderQueue(PG_DSN).source_manifest(
        render_job_id=render_job_id,
        worker_id=worker_id,
    )


@app.post("/internal/document-worker/jobs/{render_job_id}/artifacts")
async def upload_document_render_artifact(
    render_job_id: int,
    worker_id: str = Form(...),
    artifact_kind: str = Form(...),
    artifact_sha256: str = Form(...),
    file: UploadFile = File(...),
    x_document_worker_token: str | None = Header(default=None),
):
    """Return a rendered artifact to controlled Orchestrator storage."""
    _require_document_worker_token(x_document_worker_token)
    kind = artifact_kind.strip().lower()
    expected_hash = artifact_sha256.strip().lower()
    if kind not in {"docx", "pdf"}:
        raise HTTPException(400, "artifact_kind must be docx or pdf")
    if len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
        raise HTTPException(400, "artifact_sha256 must be a lowercase SHA-256 digest")
    root = Path(
        os.environ.get("DOCUMENT_RENDER_ARTIFACT_ROOT", "/srv/data/document_render_artifacts")
    ).resolve()
    destination_dir = (root / str(render_job_id)).resolve()
    if not (destination_dir == root or destination_dir.is_relative_to(root)):
        raise HTTPException(400, "invalid render artifact destination")
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"rendered.{kind}"
    temporary = destination_dir / f"rendered.{kind}.uploading"
    digest = sha256()
    size = 0
    try:
        with temporary.open("wb") as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_RENDER_ARTIFACT_BYTES:
                    raise HTTPException(413, "render artifact exceeds 100 MiB")
                digest.update(chunk)
                stream.write(chunk)
        if size == 0 or digest.hexdigest() != expected_hash:
            raise HTTPException(422, "render artifact size or SHA-256 verification failed")
        temporary.replace(destination)
        return render_queue_store.DocumentRenderQueue(PG_DSN).record_artifact(
            render_job_id=render_job_id,
            worker_id=worker_id,
            artifact_kind=kind,
            artifact_path=destination,
            artifact_sha256=expected_hash,
            size_bytes=size,
            allowed_root=root,
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


@app.post("/internal/document-worker/jobs/{render_job_id}/complete")
def complete_document_render(
    render_job_id: int,
    body: DocumentWorkerCompleteIn,
    x_document_worker_token: str | None = Header(default=None),
):
    _require_document_worker_token(x_document_worker_token)
    return render_queue_store.DocumentRenderQueue(PG_DSN).complete(
        render_job_id=render_job_id,
        worker_id=body.worker_id,
        result=body.result,
    )


# ---------- P1-22: proposal release flow ----------

class ProposalReleaseIn(BaseModel):
    reviewed_by: str
    actor: str = "api.user"
    review_comment: str = ""
    build_job_id: int | None = None


@app.post("/proposals/{proposal_id}/release-package")
def prepare_release_package(proposal_id: int, body: ProposalReleaseIn):
    """Prepare a gated release package from final artifacts; does not send externally."""
    return proposal_store.ProposalRepository(PG_DSN).prepare_release_package(
        proposal_id=proposal_id,
        build_job_id=body.build_job_id,
        reviewed_by=body.reviewed_by,
        actor=body.actor,
        review_comment=body.review_comment,
    )


class ProposalSubmissionIn(BaseModel):
    method: str
    recipient: str
    evidence_ref: str
    evidence_sha256: str
    submitted_by: str
    actor: str = "api.user"
    notes: str = ""


@app.post("/proposal-release-packages/{release_package_id}/submit")
def record_proposal_submission(release_package_id: int, body: ProposalSubmissionIn):
    """Record human-controlled customer submission evidence; no email is sent."""
    return proposal_store.ProposalRepository(PG_DSN).record_submission(
        release_package_id=release_package_id,
        method=body.method,
        recipient=body.recipient,
        evidence_ref=body.evidence_ref,
        evidence_sha256=body.evidence_sha256,
        submitted_by=body.submitted_by,
        actor=body.actor,
        notes=body.notes,
    )


@app.get("/proposal-release-packages/{release_package_id}")
def get_release_package(release_package_id: int):
    return proposal_store.ProposalRepository(PG_DSN).release_package(release_package_id)


# ---------- P1-23: benchmark harness ----------

class BenchmarkRunIn(BaseModel):
    dataset_path: str
    evaluator_name: str = "fixture_predictions"
    actor: str = "api.user"


@app.post("/benchmarks/run")
def run_benchmark(body: BenchmarkRunIn):
    """Run an offline labelled-dataset benchmark and persist the report."""
    return benchmark_store.BenchmarkRepository(PG_DSN).run_dataset(
        dataset_path=body.dataset_path,
        evaluator_name=body.evaluator_name,
        actor=body.actor,
    )


@app.get("/benchmarks/runs")
def benchmark_runs(limit: int = 20):
    return benchmark_store.BenchmarkRepository(PG_DSN).latest_runs(limit=limit)


# ---------- P1-25: local security hardening ----------

@app.post("/security/files/scan")
async def scan_security_file(
    file: UploadFile = File(...),
    actor: str = Form("api.user"),
):
    data = await file.read()
    decision = security_store.scan_file_content(
        filename=file.filename or "upload.bin",
        content=data,
        claimed_content_type=file.content_type,
    )
    return security_store.SecurityRepository(PG_DSN).record_event(
        kind="FILE_SCAN",
        decision=decision,
        actor=actor,
        subject_ref=file.filename,
    )


class PromptInjectionIn(BaseModel):
    text: str
    actor: str = "api.user"
    subject_ref: str | None = None


@app.post("/security/prompt-injection/check")
def check_prompt_injection(body: PromptInjectionIn):
    decision = security_store.evaluate_prompt_injection(body.text)
    return security_store.SecurityRepository(PG_DSN).record_event(
        kind="PROMPT_INJECTION",
        decision=decision,
        actor=body.actor,
        subject_ref=body.subject_ref,
    )


class RbacCheckIn(BaseModel):
    role_name: str
    permission: str


@app.post("/security/rbac/check")
def rbac_check(body: RbacCheckIn):
    return security_store.SecurityRepository(PG_DSN).require_permission(
        role_name=body.role_name,
        permission=body.permission,
    )


class RestoreVerificationIn(BaseModel):
    restore_scope: str
    evidence_ref: str
    evidence_sha256: str
    audit_chain_verified: bool
    verified_by: str
    backup_age_hours: float | None = None
    notes: str = ""


@app.post("/security/restore-verifications")
def record_restore_verification(body: RestoreVerificationIn):
    return security_store.SecurityRepository(PG_DSN).record_restore_verification(
        restore_scope=body.restore_scope,
        evidence_ref=body.evidence_ref,
        evidence_sha256=body.evidence_sha256,
        audit_chain_verified=body.audit_chain_verified,
        verified_by=body.verified_by,
        backup_age_hours=body.backup_age_hours,
        notes=body.notes,
    )


@app.get("/security/events")
def security_events(limit: int = 50):
    return security_store.SecurityRepository(PG_DSN).latest_events(limit=limit)


# ---------- P1-17: approved-content RAG and queued grounded drafting ----------

def _ollama_rag_client() -> OllamaClient:
    return OllamaClient(
        OLLAMA_URL,
        embedding_model=os.environ.get("EMBEDDING_MODEL", "bge-m3"),
        draft_model=os.environ.get("RAG_DRAFT_MODEL", "qwen3:14b"),
        timeout_s=float(os.environ.get("RAG_OLLAMA_TIMEOUT_S", "300")),
    )


class KnowledgeDocumentIn(BaseModel):
    document_key: str
    title: str
    source_uri: str
    content: str
    content_class: str = "NATIONLABS_APPROVED"
    owner: str
    actor: str = "api.user"
    customer_scope: str | None = None
    vendor_scope: str | None = None
    valid_from: date | None = None
    expires_at: date | None = None


@app.post("/knowledge/documents")
def ingest_knowledge_document(body: KnowledgeDocumentIn):
    """Ingest and screen a document. Ingestion always creates a DRAFT."""
    client = _ollama_rag_client()
    try:
        return knowledge_store.KnowledgeRepository(PG_DSN).ingest_document(
            document_key=body.document_key,
            title=body.title,
            source_uri=body.source_uri,
            content=body.content,
            content_class=body.content_class,
            owner=body.owner,
            actor=body.actor,
            embedder=client,
            customer_scope=body.customer_scope,
            vendor_scope=body.vendor_scope,
            valid_from=body.valid_from,
            expires_at=body.expires_at,
        )
    finally:
        client.close()


class KnowledgeApprovalIn(BaseModel):
    approver: str
    actor_role: str


@app.post("/knowledge/documents/{document_id}/approve")
def approve_knowledge_document(document_id: int, body: KnowledgeApprovalIn):
    return knowledge_store.KnowledgeRepository(PG_DSN).approve_document(
        document_id,
        approver=body.approver,
        actor_role=body.actor_role,
    )


class KnowledgeSearchIn(BaseModel):
    query: str
    purpose: str = "CUSTOMER_DRAFT"
    actor: str = "api.user"
    actor_role: str = "presales_member"
    opp_id: str | None = None
    customer_scope: str | None = None
    vendor_scope: str | None = None
    top_k: int = 5


@app.post("/knowledge/search")
def search_knowledge(body: KnowledgeSearchIn):
    client = _ollama_rag_client()
    try:
        query_vector = client.embed([body.query])[0]
        result = knowledge_store.KnowledgeRepository(PG_DSN).search(
            query=body.query,
            query_vector=query_vector,
            purpose=body.purpose,
            actor=body.actor,
            actor_role=body.actor_role,
            opp_id=body.opp_id,
            customer_scope=body.customer_scope,
            vendor_scope=body.vendor_scope,
            top_k=body.top_k,
        )
        return result.as_dict()
    finally:
        client.close()


@app.get("/knowledge/retrievals/{opp_id}")
def knowledge_retrievals(opp_id: str):
    return knowledge_store.KnowledgeRepository(PG_DSN).list_retrievals(opp_id)


class GroundedDraftIn(BaseModel):
    accepted_quote_id: int
    query: str
    actor: str = "api.user"
    actor_role: str = "presales_member"
    customer_scope: str | None = None


@app.post("/opportunities/{opp_id}/solution/draft")
def enqueue_grounded_draft(opp_id: str, body: GroundedDraftIn):
    """Queue local-model generation; this request never runs heavy generation."""
    return knowledge_store.KnowledgeRepository(PG_DSN).enqueue_draft(
        opp_id=opp_id,
        accepted_quote_id=body.accepted_quote_id,
        query=body.query,
        actor=body.actor,
        actor_role=body.actor_role,
        customer_scope=body.customer_scope,
    )


@app.get("/rag/draft-jobs/{job_id}")
def grounded_draft_job(job_id: int):
    result = knowledge_store.KnowledgeRepository(PG_DSN).get_draft_job(job_id)
    if result is None:
        raise HTTPException(404, "draft job not found")
    return result


@app.get("/alerts")
def alerts():
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT id, rfq_ref, opp_id, kind, message, created_at FROM internal_alerts "
            "ORDER BY id DESC LIMIT 50").fetchall()
    return [{"id": r[0], "rfq_ref": r[1], "opp_id": r[2], "kind": r[3],
             "message": r[4], "at": str(r[5])} for r in rows]


# ---------- P1-11: approval engine ----------

class EvaluateIn(BaseModel):
    amount_aed: float
    kind: str = "PROPOSAL_VALUE"
    actor: str = "system"


@app.post("/opportunities/{opp_id}/approvals/evaluate")
def approval_evaluate(opp_id: str, body: EvaluateIn):
    """Route an amount through the config matrix -> PENDING approval."""
    return approvals.evaluate(opp_id, body.amount_aed, body.kind, body.actor)


@app.get("/approvals")
def approvals_list(status: str = "PENDING"):
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT id, opp_id, kind, amount_aed, routed_to_role, rule_id, status, "
            "decided_by, decided_at, created_at FROM approvals WHERE status=%s "
            "ORDER BY id DESC LIMIT 50", (status,)).fetchall()
    return [{"id": r[0], "opp_id": r[1], "kind": r[2], "amount_aed": float(r[3]) if r[3] else None,
             "routed_to": r[4], "rule": r[5], "status": r[6], "decided_by": r[7],
             "decided_at": str(r[8]) if r[8] else None, "created_at": str(r[9])} for r in rows]


class DecisionIn(BaseModel):
    approver: str
    decision: str    # APPROVED / REJECTED
    comment: str = ""


@app.post("/approvals/{approval_id}/decide")
def approval_decide(approval_id: int, body: DecisionIn):
    return approvals.decide(approval_id, body.approver, body.decision, body.comment)


@app.get("/approval-rules")
def approval_rules():
    with psycopg.connect(PG_DSN) as conn:
        rows = conn.execute(
            "SELECT rule_id, min_aed, max_aed, approver_role, sla_hours, source, notes "
            "FROM approval_rules ORDER BY min_aed").fetchall()
    return [{"rule_id": r[0], "min_aed": float(r[1]),
             "max_aed": float(r[2]) if r[2] else None, "approver_role": r[3],
             "sla_hours": r[4], "source": r[5], "notes": r[6]} for r in rows]
