"""P1-15 PostgreSQL quote lifecycle and human-review persistence."""
import json
import os
from typing import Any

import psycopg

from db import PG_DSN, audit
from integrations.proposal_builder import QuoteExtractionResult


QUOTE_SCHEMA = """
ALTER TABLE vendor_responses ADD COLUMN IF NOT EXISTS original_filename TEXT;
ALTER TABLE vendor_responses ADD COLUMN IF NOT EXISTS content_type TEXT;
ALTER TABLE vendor_responses ADD COLUMN IF NOT EXISTS raw_doc_path TEXT;
ALTER TABLE vendor_responses ADD COLUMN IF NOT EXISTS raw_sha256 TEXT;
ALTER TABLE vendor_responses ADD COLUMN IF NOT EXISTS raw_size_bytes BIGINT;
ALTER TABLE vendor_responses ADD COLUMN IF NOT EXISTS parse_status TEXT NOT NULL DEFAULT 'PENDING';
ALTER TABLE vendor_responses ADD COLUMN IF NOT EXISTS parse_error_code TEXT;
ALTER TABLE vendor_responses ADD COLUMN IF NOT EXISTS parse_error_message TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_vendor_response_source
    ON vendor_responses (rfq_ref, raw_sha256) WHERE raw_sha256 IS NOT NULL;

CREATE TABLE IF NOT EXISTS quotes (
    quote_id           BIGSERIAL PRIMARY KEY,
    quote_group_id     TEXT NOT NULL,
    opp_id             TEXT NOT NULL REFERENCES opportunities(opp_id),
    vendor_id          INT NOT NULL REFERENCES vendors(vendor_id),
    response_id        BIGINT NOT NULL UNIQUE REFERENCES vendor_responses(id),
    version_no         INT NOT NULL,
    is_current         BOOLEAN NOT NULL DEFAULT TRUE,
    currency           CHAR(3) NOT NULL,
    currency_detected  BOOLEAN NOT NULL DEFAULT TRUE,
    status             TEXT NOT NULL DEFAULT 'PARSED',
    source_kind        TEXT,
    source_via         TEXT,
    warning            TEXT,
    notice             TEXT,
    builder_result     JSONB NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (quote_group_id, version_no)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_quote_group_current
    ON quotes (quote_group_id) WHERE is_current;

CREATE TABLE IF NOT EXISTS quote_line_items (
    line_id       BIGSERIAL PRIMARY KEY,
    quote_id      BIGINT NOT NULL REFERENCES quotes(quote_id),
    line_no       INT NOT NULL,
    part_number   TEXT,
    description   TEXT NOT NULL,
    quantity      NUMERIC(14,4) NOT NULL,
    unit_price    NUMERIC(16,4) NOT NULL,
    line_total    NUMERIC(16,4) NOT NULL,
    raw_item      JSONB NOT NULL,
    UNIQUE (quote_id, line_no)
);

CREATE TABLE IF NOT EXISTS quote_ingestion_attempts (
    attempt_id       BIGSERIAL PRIMARY KEY,
    response_id      BIGINT NOT NULL REFERENCES vendor_responses(id),
    attempt_no       INT NOT NULL,
    adapter_name     TEXT NOT NULL DEFAULT 'proposal_builder_http',
    status           TEXT NOT NULL,
    http_status      INT,
    error_code       TEXT,
    error_message    TEXT,
    response_payload JSONB,
    attempted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (response_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS quote_review_queue (
    review_id      BIGSERIAL PRIMARY KEY,
    response_id    BIGINT NOT NULL UNIQUE REFERENCES vendor_responses(id),
    opp_id         TEXT NOT NULL REFERENCES opportunities(opp_id),
    error_code     TEXT NOT NULL,
    reason         TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'OPEN',
    assigned_to    TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at    TIMESTAMPTZ,
    resolved_by    TEXT,
    resolution     TEXT
);
"""


def init_quotes(conn=None) -> None:
    if conn is not None:
        conn.execute(QUOTE_SCHEMA)
        conn.commit()
        return
    with psycopg.connect(PG_DSN) as owned:
        owned.execute(QUOTE_SCHEMA)
        owned.commit()


def _json(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True)


class PostgresQuoteRepository:
    def __init__(self, dsn: str = PG_DSN):
        self.dsn = dsn

    @staticmethod
    def _existing(conn, rfq_ref: str, raw_sha256: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT vr.id, vr.parse_status, q.quote_id, q.quote_group_id, q.version_no, "
            "qr.review_id, qr.error_code "
            "FROM vendor_responses vr "
            "LEFT JOIN quotes q ON q.response_id=vr.id "
            "LEFT JOIN quote_review_queue qr ON qr.response_id=vr.id AND qr.status='OPEN' "
            "WHERE vr.rfq_ref=%s AND vr.raw_sha256=%s",
            (rfq_ref, raw_sha256),
        ).fetchone()
        if not row:
            return None
        return {
            "response_id": row[0],
            "parse_status": row[1],
            "quote_id": row[2],
            "quote_group_id": row[3],
            "version_no": row[4],
            "review_id": row[5],
            "error_code": row[6],
            "existing": True,
        }

    def create_or_get_response(
        self,
        *,
        rfq_ref: str,
        filename: str,
        content_type: str | None,
        raw_sha256: str,
        raw_doc_path: str,
        actor: str,
    ) -> dict[str, Any]:
        with psycopg.connect(self.dsn) as conn:
            existing = self._existing(conn, rfq_ref, raw_sha256)
            if existing:
                return existing
            rfq = conn.execute(
                "SELECT opp_id FROM rfqs WHERE rfq_ref=%s", (rfq_ref,)
            ).fetchone()
            if not rfq:
                raise ValueError(f"unknown RFQ {rfq_ref}")
            inserted = conn.execute(
                "INSERT INTO vendor_responses "
                "(rfq_ref, response_type, original_filename, content_type, raw_doc_path, "
                "raw_sha256, raw_size_bytes, parse_status) "
                "VALUES (%s,'QUOTE',%s,%s,%s,%s,%s,'PENDING') "
                "ON CONFLICT (rfq_ref, raw_sha256) WHERE raw_sha256 IS NOT NULL DO NOTHING "
                "RETURNING id",
                (
                    rfq_ref,
                    filename,
                    content_type,
                    raw_doc_path,
                    raw_sha256,
                    os.path.getsize(raw_doc_path),
                ),
            ).fetchone()
            if not inserted:
                concurrent = self._existing(conn, rfq_ref, raw_sha256)
                if concurrent:
                    return concurrent
                raise RuntimeError("quote source idempotency conflict could not be resolved")
            response_id = inserted[0]
            audit(
                conn,
                actor,
                "quote",
                "quote_source_received",
                rfq[0],
                new=f"response={response_id};sha256={raw_sha256}",
            )
            conn.commit()
            return {"response_id": response_id, "parse_status": "PENDING", "existing": False}

    def persist_success(
        self,
        *,
        response_id: int,
        quote_reference: str | None,
        result: QuoteExtractionResult,
        actor: str,
    ) -> dict[str, Any]:
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT vr.rfq_ref, r.opp_id, r.vendor_id FROM vendor_responses vr "
                "JOIN rfqs r ON r.rfq_ref=vr.rfq_ref WHERE vr.id=%s FOR UPDATE",
                (response_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"unknown vendor response {response_id}")
            rfq_ref, opp_id, vendor_id = row
            existing = conn.execute(
                "SELECT quote_id, quote_group_id, version_no FROM quotes WHERE response_id=%s",
                (response_id,),
            ).fetchone()
            if existing:
                return {
                    "quote_id": existing[0],
                    "quote_group_id": existing[1],
                    "version_no": existing[2],
                }
            reference = (quote_reference or "default").strip()[:200] or "default"
            quote_group_id = f"{rfq_ref}:{reference}"
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (quote_group_id,))
            version_no = conn.execute(
                "SELECT coalesce(max(version_no),0)+1 FROM quotes WHERE quote_group_id=%s",
                (quote_group_id,),
            ).fetchone()[0]
            conn.execute(
                "UPDATE quotes SET is_current=false, status='SUPERSEDED' "
                "WHERE quote_group_id=%s AND is_current",
                (quote_group_id,),
            )
            quote_id = conn.execute(
                "INSERT INTO quotes "
                "(quote_group_id, opp_id, vendor_id, response_id, version_no, is_current, currency, "
                "currency_detected, status, source_kind, source_via, warning, notice, builder_result) "
                "VALUES (%s,%s,%s,%s,%s,true,%s,%s,'PARSED',%s,%s,%s,%s,%s) RETURNING quote_id",
                (
                    quote_group_id,
                    opp_id,
                    vendor_id,
                    response_id,
                    version_no,
                    result.currency,
                    result.currency_detected,
                    result.source,
                    result.via,
                    result.warning,
                    result.notice,
                    _json(result.raw_payload),
                ),
            ).fetchone()[0]
            for line in result.items:
                conn.execute(
                    "INSERT INTO quote_line_items "
                    "(quote_id,line_no,part_number,description,quantity,unit_price,line_total,raw_item) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        quote_id,
                        line.line_no,
                        line.part_number,
                        line.description,
                        line.quantity,
                        line.unit_price,
                        line.line_total,
                        _json(line.raw),
                    ),
                )
            attempt_no = conn.execute(
                "SELECT coalesce(max(attempt_no),0)+1 FROM quote_ingestion_attempts WHERE response_id=%s",
                (response_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO quote_ingestion_attempts "
                "(response_id,attempt_no,status,response_payload) VALUES (%s,%s,'SUCCEEDED',%s)",
                (response_id, attempt_no, _json(result.raw_payload)),
            )
            conn.execute(
                "UPDATE vendor_responses SET parse_status='PARSED', parse_error_code=NULL, "
                "parse_error_message=NULL WHERE id=%s",
                (response_id,),
            )
            conn.execute(
                "UPDATE quote_review_queue SET status='RESOLVED', resolved_at=now(), resolved_by=%s, "
                "resolution='parsed successfully' WHERE response_id=%s AND status='OPEN'",
                (actor, response_id),
            )
            audit(
                conn,
                actor,
                "quote",
                "quote_parsed",
                opp_id,
                new=f"quote={quote_id};group={quote_group_id};version={version_no}",
            )
            conn.commit()
            return {
                "quote_id": quote_id,
                "quote_group_id": quote_group_id,
                "version_no": version_no,
            }

    def mark_failed_review(
        self,
        *,
        response_id: int,
        error_code: str,
        error_message: str,
        http_status: int | None,
        details: Any,
        actor: str,
    ) -> dict[str, Any]:
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT r.opp_id FROM vendor_responses vr JOIN rfqs r ON r.rfq_ref=vr.rfq_ref "
                "WHERE vr.id=%s FOR UPDATE",
                (response_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"unknown vendor response {response_id}")
            opp_id = row[0]
            attempt_no = conn.execute(
                "SELECT coalesce(max(attempt_no),0)+1 FROM quote_ingestion_attempts WHERE response_id=%s",
                (response_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO quote_ingestion_attempts "
                "(response_id,attempt_no,status,http_status,error_code,error_message,response_payload) "
                "VALUES (%s,%s,'FAILED_REVIEW',%s,%s,%s,%s)",
                (
                    response_id,
                    attempt_no,
                    http_status,
                    error_code,
                    error_message,
                    _json(details) if details is not None else None,
                ),
            )
            conn.execute(
                "UPDATE vendor_responses SET parse_status='FAILED_REVIEW', parse_error_code=%s, "
                "parse_error_message=%s WHERE id=%s",
                (error_code, error_message, response_id),
            )
            review_id = conn.execute(
                "INSERT INTO quote_review_queue (response_id,opp_id,error_code,reason,status) "
                "VALUES (%s,%s,%s,%s,'OPEN') "
                "ON CONFLICT (response_id) DO UPDATE SET error_code=EXCLUDED.error_code, "
                "reason=EXCLUDED.reason, status='OPEN', resolved_at=NULL, resolved_by=NULL, resolution=NULL "
                "RETURNING review_id",
                (response_id, opp_id, error_code, error_message),
            ).fetchone()[0]
            audit(
                conn,
                actor,
                "quote",
                "quote_failed_review",
                opp_id,
                new=f"response={response_id};review={review_id};code={error_code}",
                reason=error_message,
            )
            conn.commit()
            return {"review_id": review_id}

    def list_for_rfq(self, rfq_ref: str) -> list[dict[str, Any]]:
        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute(
                "SELECT q.quote_id,q.quote_group_id,q.version_no,q.is_current,q.currency,q.status,"
                "q.source_kind,q.created_at,vr.raw_sha256,vr.original_filename,"
                "(SELECT count(*) FROM quote_line_items li WHERE li.quote_id=q.quote_id) "
                "FROM quotes q JOIN vendor_responses vr ON vr.id=q.response_id "
                "WHERE vr.rfq_ref=%s ORDER BY q.quote_group_id,q.version_no",
                (rfq_ref,),
            ).fetchall()
        return [
            {
                "quote_id": r[0],
                "quote_group_id": r[1],
                "version_no": r[2],
                "is_current": r[3],
                "currency": r[4],
                "status": r[5],
                "source": r[6],
                "created_at": str(r[7]),
                "raw_sha256": r[8],
                "original_filename": r[9],
                "line_count": r[10],
            }
            for r in rows
        ]

    def list_open_reviews(self) -> list[dict[str, Any]]:
        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute(
                "SELECT qr.review_id,qr.response_id,qr.opp_id,vr.rfq_ref,vr.original_filename,"
                "vr.raw_sha256,qr.error_code,qr.reason,qr.created_at "
                "FROM quote_review_queue qr JOIN vendor_responses vr ON vr.id=qr.response_id "
                "WHERE qr.status='OPEN' ORDER BY qr.created_at"
            ).fetchall()
        return [
            {
                "review_id": r[0],
                "response_id": r[1],
                "opp_id": r[2],
                "rfq_ref": r[3],
                "original_filename": r[4],
                "raw_sha256": r[5],
                "error_code": r[6],
                "reason": r[7],
                "created_at": str(r[8]),
            }
            for r in rows
        ]
