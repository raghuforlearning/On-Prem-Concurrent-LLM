"""P1-17 approved-content knowledge and pgvector retrieval service."""
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
import re
from typing import Any, Iterable


EMBEDDING_DIMENSIONS = 1024
APPROVER_ROLES = {"admin", "presales_lead", "technical_reviewer"}
SEARCH_ROLES = APPROVER_ROLES | {"presales_member", "knowledge_author"}
CONTENT_CLASSES = {
    "NATIONLABS_APPROVED",
    "HISTORICAL_REFERENCE",
    "VENDOR_PROVIDED",
    "CUSTOMER_PROVIDED",
}
PURPOSE_CLASSES = {
    "CUSTOMER_DRAFT": ("NATIONLABS_APPROVED",),
    "INTERNAL_RESEARCH": tuple(sorted(CONTENT_CLASSES)),
}


KNOWLEDGE_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_documents (
    document_id       BIGSERIAL PRIMARY KEY,
    document_key      TEXT NOT NULL,
    version_no        INT NOT NULL,
    title             TEXT NOT NULL,
    source_uri        TEXT NOT NULL,
    source_sha256     TEXT NOT NULL,
    content_text      TEXT NOT NULL,
    content_class     TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'DRAFT',
    security_status   TEXT NOT NULL DEFAULT 'CLEARED',
    security_flags    JSONB NOT NULL DEFAULT '[]'::jsonb,
    owner             TEXT NOT NULL,
    customer_scope    TEXT,
    vendor_scope      TEXT,
    valid_from        DATE,
    expires_at        DATE,
    supersedes_id     BIGINT REFERENCES knowledge_documents(document_id),
    approved_by       TEXT,
    approved_at       TIMESTAMPTZ,
    created_by        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_key, version_no),
    UNIQUE (document_key, source_sha256),
    CHECK (content_class IN ('NATIONLABS_APPROVED','HISTORICAL_REFERENCE',
        'VENDOR_PROVIDED','CUSTOMER_PROVIDED')),
    CHECK (status IN ('DRAFT','APPROVED','REJECTED','EXPIRED','SUPERSEDED')),
    CHECK (security_status IN ('CLEARED','FLAGGED'))
);
CREATE INDEX IF NOT EXISTS idx_knowledge_document_filter
    ON knowledge_documents (status,content_class,security_status,expires_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_document_scope
    ON knowledge_documents (customer_scope,vendor_scope);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id          BIGSERIAL PRIMARY KEY,
    document_id       BIGINT NOT NULL REFERENCES knowledge_documents(document_id),
    chunk_no          INT NOT NULL,
    section_ref       TEXT NOT NULL,
    page_ref          TEXT,
    content           TEXT NOT NULL,
    content_sha256    TEXT NOT NULL,
    search_vector     TSVECTOR GENERATED ALWAYS AS
        (to_tsvector('english', content)) STORED,
    UNIQUE (document_id, chunk_no)
);
-- Repeated approved boilerplate can occur under distinct sections; retain
-- both chunks because their section provenance differs.
ALTER TABLE knowledge_chunks DROP CONSTRAINT IF EXISTS
    knowledge_chunks_document_id_content_sha256_key;
CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_fts
    ON knowledge_chunks USING GIN (search_vector);

CREATE TABLE IF NOT EXISTS knowledge_embeddings (
    embedding_id      BIGSERIAL PRIMARY KEY,
    chunk_id          BIGINT NOT NULL UNIQUE REFERENCES knowledge_chunks(chunk_id),
    model              TEXT NOT NULL,
    dimensions         INT NOT NULL,
    embedding          VECTOR(1024) NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (dimensions=1024)
);
CREATE INDEX IF NOT EXISTS idx_knowledge_embedding_hnsw
    ON knowledge_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS knowledge_retrieval_events (
    retrieval_id      BIGSERIAL PRIMARY KEY,
    opp_id            TEXT REFERENCES opportunities(opp_id),
    query_text        TEXT NOT NULL,
    purpose           TEXT NOT NULL,
    actor             TEXT NOT NULL,
    actor_role        TEXT NOT NULL,
    customer_scope    TEXT,
    vendor_scope      TEXT,
    chunk_ids         JSONB NOT NULL,
    scores            JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_knowledge_retrieval_opp
    ON knowledge_retrieval_events (opp_id,created_at DESC);

CREATE TABLE IF NOT EXISTS rag_draft_jobs (
    job_id             BIGSERIAL PRIMARY KEY,
    opp_id             TEXT NOT NULL REFERENCES opportunities(opp_id),
    accepted_quote_id  BIGINT NOT NULL REFERENCES quotes(quote_id),
    query_text         TEXT NOT NULL,
    actor              TEXT NOT NULL,
    actor_role         TEXT NOT NULL,
    customer_scope     TEXT,
    status             TEXT NOT NULL DEFAULT 'QUEUED',
    attempt_no         INT NOT NULL DEFAULT 0,
    error_message      TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at         TIMESTAMPTZ,
    completed_at       TIMESTAMPTZ,
    CHECK (status IN ('QUEUED','PROCESSING','COMPLETED','FAILED_REVIEW'))
);
CREATE INDEX IF NOT EXISTS idx_rag_draft_job_queue
    ON rag_draft_jobs (status,created_at);

CREATE TABLE IF NOT EXISTS rag_drafts (
    draft_id            BIGSERIAL PRIMARY KEY,
    job_id              BIGINT NOT NULL UNIQUE REFERENCES rag_draft_jobs(job_id),
    opp_id              TEXT NOT NULL REFERENCES opportunities(opp_id),
    retrieval_id        BIGINT NOT NULL REFERENCES knowledge_retrieval_events(retrieval_id),
    draft_text          TEXT NOT NULL,
    commercial_facts    JSONB NOT NULL,
    model               TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rag_draft_citations (
    draft_id            BIGINT NOT NULL REFERENCES rag_drafts(draft_id),
    chunk_id            BIGINT NOT NULL REFERENCES knowledge_chunks(chunk_id),
    citation_label      TEXT NOT NULL,
    PRIMARY KEY (draft_id,citation_label)
);
"""


INJECTION_PATTERNS = {
    "IGNORE_INSTRUCTIONS": re.compile(
        r"\b(ignore|disregard|override)\b.{0,40}\b(previous|prior|system|developer)\b.{0,20}\b(instruction|prompt|rule)s?\b",
        re.IGNORECASE,
    ),
    "SYSTEM_PROMPT_REQUEST": re.compile(
        r"\b(reveal|print|show|leak|expose)\b.{0,30}\b(system|developer)\b.{0,10}\b(prompt|message|instruction)s?\b",
        re.IGNORECASE,
    ),
    "TOOL_EXECUTION_REQUEST": re.compile(
        r"\b(run|execute|launch|invoke)\b.{0,25}\b(command|shell|powershell|terminal|tool|script)\b",
        re.IGNORECASE,
    ),
    "ROLE_HIJACK": re.compile(r"\b(system|assistant|developer)\s*:\s*", re.IGNORECASE),
}


def screen_untrusted_content(content: str) -> tuple[str, ...]:
    """Flag high-signal indirect prompt injection; approval remains fail-closed."""
    return tuple(code for code, pattern in INJECTION_PATTERNS.items() if pattern.search(content or ""))


@dataclass(frozen=True)
class Chunk:
    chunk_no: int
    section_ref: str
    content: str
    content_sha256: str


def _heading(line: str) -> str | None:
    cleaned = line.strip()
    if not cleaned:
        return None
    if cleaned.startswith("#"):
        return cleaned.lstrip("#").strip() or "Document"
    words = cleaned.rstrip(":").split()
    if cleaned.endswith(":") and len(words) <= 12:
        return cleaned.rstrip(":").strip()
    if len(words) <= 10 and cleaned.upper() == cleaned and any(c.isalpha() for c in cleaned):
        return cleaned.title()
    return None


def _pricing_row(line: str) -> bool:
    """Recognize common table rows so a commercial row is never split."""
    cleaned = line.strip()
    if not re.search(r"\d", cleaned):
        return False
    if cleaned.count("|") >= 2:
        return True
    if cleaned.count("\t") >= 2:
        return True
    if cleaned.count(",") >= 2 and re.search(
        r"(?:AED|USD|EUR|GBP|SAR|QAR|\d[\d,]*\.\d{2})", cleaned, re.IGNORECASE
    ):
        return True
    return False


def chunk_document(
    content: str,
    *,
    target_words: int = 600,
    overlap_words: int = 90,
) -> tuple[Chunk, ...]:
    if not content or not content.strip():
        raise ValueError("knowledge content cannot be empty")
    if target_words < 100 or target_words > 1000:
        raise ValueError("target_words must be between 100 and 1000")
    if overlap_words < 0 or overlap_words >= target_words:
        raise ValueError("overlap_words must be non-negative and smaller than target_words")

    sections: list[tuple[str, list[str]]] = []
    current_title = "Document"
    current_lines: list[str] = []
    for raw_line in content.splitlines():
        title = _heading(raw_line)
        if title is not None:
            if current_lines:
                sections.append((current_title, current_lines))
            current_title = title[:240]
            current_lines = []
        elif raw_line.strip():
            current_lines.append(raw_line.strip())
    if current_lines:
        sections.append((current_title, current_lines))
    if not sections:
        sections.append(("Document", [content.strip()]))

    chunks: list[Chunk] = []
    step = target_words - overlap_words
    def append_text(section_ref: str, text: str) -> None:
        chunks.append(
            Chunk(
                chunk_no=len(chunks) + 1,
                section_ref=section_ref,
                content=text,
                content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            )
        )

    def append_prose(section_ref: str, prose_lines: list[str]) -> None:
        words = "\n".join(prose_lines).split()
        for start in range(0, len(words), step):
            piece = words[start : start + target_words]
            if not piece:
                continue
            text = " ".join(piece)
            append_text(section_ref, text)
            if start + target_words >= len(words):
                break

    for section_ref, lines in sections:
        prose: list[str] = []
        for line in lines:
            if _pricing_row(line):
                append_prose(section_ref, prose)
                prose = []
                # A table row is an atomic unit even when it is unusually long.
                append_text(section_ref, line.strip())
            else:
                prose.append(line)
        append_prose(section_ref, prose)
    return tuple(chunks)


def vector_literal(values: Iterable[Any]) -> str:
    vector = [float(value) for value in values]
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"embedding must contain {EMBEDDING_DIMENSIONS} dimensions")
    if any(not math.isfinite(value) for value in vector):
        raise ValueError("embedding values must be finite")
    return "[" + ",".join(format(value, ".9g") for value in vector) + "]"


@dataclass(frozen=True)
class Citation:
    label: str
    chunk_id: int
    document_id: int
    title: str
    version_no: int
    content_class: str
    approval_status: str
    section_ref: str
    page_ref: str | None
    owner: str
    source_uri: str
    source_sha256: str
    valid_from: str | None
    approved_at: str | None
    score: float
    content: str

    def as_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        payload = {
            "label": self.label,
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "title": self.title,
            "version_no": self.version_no,
            "content_class": self.content_class,
            "approval_status": self.approval_status,
            "section_ref": self.section_ref,
            "page_ref": self.page_ref,
            "owner": self.owner,
            "source_uri": self.source_uri,
            "source_sha256": self.source_sha256,
            "valid_from": self.valid_from,
            "approved_at": self.approved_at,
            "score": self.score,
        }
        if include_content:
            payload["content"] = self.content
        return payload


@dataclass(frozen=True)
class RetrievalResult:
    retrieval_id: int
    citations: tuple[Citation, ...]

    def as_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        return {
            "retrieval_id": self.retrieval_id,
            "citations": [item.as_dict(include_content=include_content) for item in self.citations],
        }


class KnowledgeRepository:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def init_schema(self) -> None:
        import psycopg

        with psycopg.connect(self.dsn) as conn:
            conn.execute(KNOWLEDGE_SCHEMA)
            conn.commit()

    def ingest_document(
        self,
        *,
        document_key: str,
        title: str,
        source_uri: str,
        content: str,
        content_class: str,
        owner: str,
        actor: str,
        embedder: Any,
        customer_scope: str | None = None,
        vendor_scope: str | None = None,
        valid_from: date | None = None,
        expires_at: date | None = None,
    ) -> dict[str, Any]:
        import psycopg
        from db import audit

        normalized_class = content_class.strip().upper()
        if normalized_class not in CONTENT_CLASSES:
            raise ValueError("unsupported knowledge content_class")
        if normalized_class == "CUSTOMER_PROVIDED" and not customer_scope:
            raise ValueError("CUSTOMER_PROVIDED content requires customer_scope")
        if normalized_class == "VENDOR_PROVIDED" and not vendor_scope:
            raise ValueError("VENDOR_PROVIDED content requires vendor_scope")
        if expires_at is not None and valid_from is not None and expires_at <= valid_from:
            raise ValueError("expires_at must be later than valid_from")
        cleaned_key = document_key.strip()
        if not cleaned_key or not title.strip() or not source_uri.strip() or not owner.strip():
            raise ValueError("document key, title, source URI and owner are required")
        source_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        chunks = chunk_document(content)

        with psycopg.connect(self.dsn) as conn:
            existing = conn.execute(
                "SELECT document_id,version_no,status,security_status FROM knowledge_documents "
                "WHERE document_key=%s AND source_sha256=%s",
                (cleaned_key, source_sha256),
            ).fetchone()
            if existing:
                return {
                    "document_id": existing[0],
                    "version_no": existing[1],
                    "status": existing[2],
                    "security_status": existing[3],
                    "existing": True,
                }

        embeddings = embedder.embed([chunk.content for chunk in chunks])
        if len(embeddings) != len(chunks):
            raise ValueError("embedding count does not match chunk count")
        flags = screen_untrusted_content(content)
        security_status = "FLAGGED" if flags else "CLEARED"

        with psycopg.connect(self.dsn) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (cleaned_key,))
            prior = conn.execute(
                "SELECT document_id,version_no FROM knowledge_documents "
                "WHERE document_key=%s ORDER BY version_no DESC LIMIT 1",
                (cleaned_key,),
            ).fetchone()
            version_no = (prior[1] + 1) if prior else 1
            document_id = conn.execute(
                "INSERT INTO knowledge_documents "
                "(document_key,version_no,title,source_uri,source_sha256,content_text,content_class,"
                "status,security_status,security_flags,owner,customer_scope,vendor_scope,valid_from,"
                "expires_at,supersedes_id,created_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'DRAFT',%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "RETURNING document_id",
                (
                    cleaned_key,
                    version_no,
                    title.strip(),
                    source_uri.strip(),
                    source_sha256,
                    content,
                    normalized_class,
                    security_status,
                    json.dumps(flags),
                    owner.strip(),
                    customer_scope,
                    vendor_scope,
                    valid_from,
                    expires_at,
                    prior[0] if prior else None,
                    actor,
                ),
            ).fetchone()[0]
            for chunk, vector in zip(chunks, embeddings):
                chunk_id = conn.execute(
                    "INSERT INTO knowledge_chunks "
                    "(document_id,chunk_no,section_ref,content,content_sha256) "
                    "VALUES (%s,%s,%s,%s,%s) RETURNING chunk_id",
                    (
                        document_id,
                        chunk.chunk_no,
                        chunk.section_ref,
                        chunk.content,
                        chunk.content_sha256,
                    ),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO knowledge_embeddings (chunk_id,model,dimensions,embedding) "
                    "VALUES (%s,%s,%s,%s::vector)",
                    (
                        chunk_id,
                        getattr(embedder, "embedding_model", "test-embedding"),
                        EMBEDDING_DIMENSIONS,
                        vector_literal(vector),
                    ),
                )
            audit(
                conn,
                actor,
                "knowledge",
                "knowledge_document_ingested",
                new=json.dumps(
                    {
                        "document_id": document_id,
                        "version_no": version_no,
                        "source_sha256": source_sha256,
                        "content_class": normalized_class,
                        "security_status": security_status,
                        "security_flags": flags,
                    },
                    sort_keys=True,
                ),
            )
            conn.commit()
        return {
            "document_id": document_id,
            "version_no": version_no,
            "status": "DRAFT",
            "security_status": security_status,
            "security_flags": list(flags),
            "chunk_count": len(chunks),
            "source_sha256": source_sha256,
            "existing": False,
        }

    def approve_document(self, document_id: int, *, approver: str, actor_role: str) -> dict[str, Any]:
        import psycopg
        from db import audit

        if actor_role not in APPROVER_ROLES:
            raise PermissionError("actor role cannot approve knowledge content")
        if not approver.strip():
            raise ValueError("approver is required")
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT document_key,version_no,status,security_status,expires_at "
                "FROM knowledge_documents WHERE document_id=%s FOR UPDATE",
                (document_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"unknown knowledge document {document_id}")
            document_key, version_no, status, security_status, expires_at = row
            if status == "APPROVED":
                return {"document_id": document_id, "status": status, "version_no": version_no}
            if status != "DRAFT":
                raise ValueError(f"knowledge document in {status} cannot be approved")
            if security_status != "CLEARED":
                raise PermissionError("flagged knowledge content cannot be approved")
            if expires_at is not None and expires_at <= date.today():
                raise ValueError("expired knowledge content cannot be approved")
            conn.execute(
                "UPDATE knowledge_documents SET status='SUPERSEDED' "
                "WHERE document_key=%s AND status='APPROVED' AND document_id<>%s",
                (document_key, document_id),
            )
            conn.execute(
                "UPDATE knowledge_documents SET status='APPROVED',approved_by=%s,approved_at=now() "
                "WHERE document_id=%s",
                (approver, document_id),
            )
            audit(
                conn,
                approver,
                "knowledge",
                "knowledge_document_approved",
                previous="DRAFT",
                new=f"document={document_id};key={document_key};version={version_no}",
            )
            conn.commit()
        return {"document_id": document_id, "status": "APPROVED", "version_no": version_no}

    def search(
        self,
        *,
        query: str,
        query_vector: Iterable[Any],
        purpose: str,
        actor: str,
        actor_role: str,
        opp_id: str | None = None,
        customer_scope: str | None = None,
        vendor_scope: str | None = None,
        top_k: int = 5,
    ) -> RetrievalResult:
        import psycopg
        from db import audit

        normalized_purpose = purpose.strip().upper()
        if normalized_purpose not in PURPOSE_CLASSES:
            raise ValueError("unsupported retrieval purpose")
        if actor_role not in SEARCH_ROLES:
            raise PermissionError("actor role cannot retrieve knowledge content")
        if not query.strip():
            raise ValueError("knowledge query cannot be empty")
        if top_k < 1 or top_k > 20:
            raise ValueError("top_k must be between 1 and 20")
        classes = list(PURPOSE_CLASSES[normalized_purpose])
        vector = vector_literal(query_vector)

        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute(
                "SELECT c.chunk_id,d.document_id,d.title,d.version_no,d.content_class,d.status,"
                "c.section_ref,c.page_ref,d.owner,d.source_uri,d.source_sha256,d.valid_from,"
                "d.approved_at,c.content,"
                "GREATEST(0,1-(e.embedding <=> %s::vector)) AS semantic_score,"
                "ts_rank_cd(c.search_vector,websearch_to_tsquery('english',%s)) AS keyword_score "
                "FROM knowledge_chunks c "
                "JOIN knowledge_documents d ON d.document_id=c.document_id "
                "JOIN knowledge_embeddings e ON e.chunk_id=c.chunk_id "
                "WHERE d.status='APPROVED' AND d.security_status='CLEARED' "
                "AND d.content_class=ANY(%s) "
                "AND (d.valid_from IS NULL OR d.valid_from<=CURRENT_DATE) "
                "AND (d.expires_at IS NULL OR d.expires_at>CURRENT_DATE) "
                "AND (d.customer_scope IS NULL OR d.customer_scope=%s) "
                "AND (d.vendor_scope IS NULL OR d.vendor_scope=%s) "
                "ORDER BY ((e.embedding <=> %s::vector) - "
                "LEAST(ts_rank_cd(c.search_vector,websearch_to_tsquery('english',%s)),1)*0.15) "
                "LIMIT %s",
                (
                    vector,
                    query,
                    classes,
                    customer_scope,
                    vendor_scope,
                    vector,
                    query,
                    top_k,
                ),
            ).fetchall()
            citations = []
            for index, row in enumerate(rows, 1):
                semantic = float(row[14] or 0)
                keyword = min(float(row[15] or 0), 1.0)
                citations.append(
                    Citation(
                        label=f"K{index}",
                        chunk_id=row[0],
                        document_id=row[1],
                        title=row[2],
                        version_no=row[3],
                        content_class=row[4],
                        approval_status=row[5],
                        section_ref=row[6],
                        page_ref=row[7],
                        owner=row[8],
                        source_uri=row[9],
                        source_sha256=row[10],
                        valid_from=str(row[11]) if row[11] else None,
                        approved_at=str(row[12]) if row[12] else None,
                        content=row[13],
                        score=round((semantic * 0.85) + (keyword * 0.15), 6),
                    )
                )
            retrieval_id = conn.execute(
                "INSERT INTO knowledge_retrieval_events "
                "(opp_id,query_text,purpose,actor,actor_role,customer_scope,vendor_scope,chunk_ids,scores) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING retrieval_id",
                (
                    opp_id,
                    query,
                    normalized_purpose,
                    actor,
                    actor_role,
                    customer_scope,
                    vendor_scope,
                    json.dumps([item.chunk_id for item in citations]),
                    json.dumps([item.score for item in citations]),
                ),
            ).fetchone()[0]
            audit(
                conn,
                actor,
                "knowledge",
                "knowledge_retrieved",
                opp_id,
                new=json.dumps(
                    {
                        "retrieval_id": retrieval_id,
                        "purpose": normalized_purpose,
                        "chunk_ids": [item.chunk_id for item in citations],
                        "scores": [item.score for item in citations],
                    },
                    sort_keys=True,
                ),
            )
            conn.commit()
        return RetrievalResult(retrieval_id=retrieval_id, citations=tuple(citations))

    def accepted_commercial_facts(self, quote_id: int) -> dict[str, Any]:
        import psycopg

        with psycopg.connect(self.dsn) as conn:
            quote = conn.execute(
                "SELECT q.quote_id,q.opp_id,q.currency,q.version_no,v.vendor_name,"
                "vr.computed_subtotal,vr.computed_vat,vr.computed_total "
                "FROM quotes q JOIN vendors v ON v.vendor_id=q.vendor_id "
                "JOIN LATERAL (SELECT computed_subtotal,computed_vat,computed_total "
                "FROM quote_validation_results WHERE quote_id=q.quote_id "
                "AND status='VALIDATED' ORDER BY validation_id DESC LIMIT 1) vr ON true "
                "WHERE q.quote_id=%s AND q.is_current=true AND q.status='PARSED' "
                "AND q.validation_status='VALIDATED'",
                (quote_id,),
            ).fetchone()
            if not quote:
                raise PermissionError("commercial facts require a current validated quote")
            lines = conn.execute(
                "SELECT line_no,part_number,description,quantity,unit_price,line_total "
                "FROM quote_line_items WHERE quote_id=%s ORDER BY line_no",
                (quote_id,),
            ).fetchall()
        return {
            "authority": "ACCEPTED_VALIDATED_QUOTE",
            "quote_id": quote[0],
            "opp_id": quote[1],
            "currency": quote[2],
            "quote_version": quote[3],
            "vendor": quote[4],
            "subtotal": str(quote[5]),
            "vat": str(quote[6]),
            "total": str(quote[7]),
            "lines": [
                {
                    "line_no": row[0],
                    "part_number": row[1],
                    "description": row[2],
                    "quantity": str(row[3]),
                    "unit_price": str(row[4]),
                    "line_total": str(row[5]),
                }
                for row in lines
            ],
        }

    def enqueue_draft(
        self,
        *,
        opp_id: str,
        accepted_quote_id: int,
        query: str,
        actor: str,
        actor_role: str,
        customer_scope: str | None,
    ) -> dict[str, Any]:
        import psycopg
        from db import audit

        if actor_role not in SEARCH_ROLES:
            raise PermissionError("actor role cannot request a grounded draft")
        facts = self.accepted_commercial_facts(accepted_quote_id)
        if facts["opp_id"] != opp_id:
            raise PermissionError("accepted quote does not belong to the opportunity")
        with psycopg.connect(self.dsn) as conn:
            job_id = conn.execute(
                "INSERT INTO rag_draft_jobs "
                "(opp_id,accepted_quote_id,query_text,actor,actor_role,customer_scope,status) "
                "VALUES (%s,%s,%s,%s,%s,%s,'QUEUED') RETURNING job_id",
                (opp_id, accepted_quote_id, query, actor, actor_role, customer_scope),
            ).fetchone()[0]
            audit(
                conn,
                actor,
                "knowledge",
                "rag_draft_queued",
                opp_id,
                new=f"job={job_id};quote={accepted_quote_id}",
            )
            conn.commit()
        return {"job_id": job_id, "status": "QUEUED"}

    def claim_next_draft_job(self) -> dict[str, Any] | None:
        import psycopg

        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT job_id,opp_id,accepted_quote_id,query_text,actor,actor_role,customer_scope "
                "FROM rag_draft_jobs WHERE status='QUEUED' ORDER BY created_at "
                "FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE rag_draft_jobs SET status='PROCESSING',attempt_no=attempt_no+1,"
                "started_at=now(),error_message=NULL WHERE job_id=%s",
                (row[0],),
            )
            conn.commit()
        return {
            "job_id": row[0],
            "opp_id": row[1],
            "accepted_quote_id": row[2],
            "query": row[3],
            "actor": row[4],
            "actor_role": row[5],
            "customer_scope": row[6],
        }

    def complete_draft(
        self,
        *,
        job: dict[str, Any],
        retrieval: RetrievalResult,
        commercial_facts: dict[str, Any],
        draft_text: str,
        citations_used: list[str],
        model: str,
    ) -> dict[str, Any]:
        import psycopg
        from db import audit

        available = {item.label: item for item in retrieval.citations}
        unknown = sorted(set(citations_used) - set(available))
        if unknown:
            raise ValueError(f"draft cited unknown knowledge labels: {', '.join(unknown)}")
        if not draft_text.strip():
            raise ValueError("grounded draft cannot be empty")
        with psycopg.connect(self.dsn) as conn:
            draft_id = conn.execute(
                "INSERT INTO rag_drafts "
                "(job_id,opp_id,retrieval_id,draft_text,commercial_facts,model) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING draft_id",
                (
                    job["job_id"],
                    job["opp_id"],
                    retrieval.retrieval_id,
                    draft_text,
                    json.dumps(commercial_facts, sort_keys=True),
                    model,
                ),
            ).fetchone()[0]
            for label in citations_used:
                conn.execute(
                    "INSERT INTO rag_draft_citations (draft_id,chunk_id,citation_label) "
                    "VALUES (%s,%s,%s)",
                    (draft_id, available[label].chunk_id, label),
                )
            conn.execute(
                "UPDATE rag_draft_jobs SET status='COMPLETED',completed_at=now() WHERE job_id=%s",
                (job["job_id"],),
            )
            audit(
                conn,
                model,
                "knowledge",
                "rag_draft_completed",
                job["opp_id"],
                new=f"job={job['job_id']};draft={draft_id};retrieval={retrieval.retrieval_id}",
            )
            conn.commit()
        return {"job_id": job["job_id"], "draft_id": draft_id, "status": "COMPLETED"}

    def fail_draft(self, job_id: int, *, error_message: str, actor: str, opp_id: str) -> None:
        import psycopg
        from db import audit

        with psycopg.connect(self.dsn) as conn:
            conn.execute(
                "UPDATE rag_draft_jobs SET status='FAILED_REVIEW',error_message=%s,"
                "completed_at=now() WHERE job_id=%s",
                (error_message[:4000], job_id),
            )
            audit(
                conn,
                actor,
                "knowledge",
                "rag_draft_failed_review",
                opp_id,
                new=f"job={job_id}",
                reason=error_message[:2000],
            )
            conn.commit()

    def get_draft_job(self, job_id: int) -> dict[str, Any] | None:
        import psycopg

        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT j.job_id,j.opp_id,j.accepted_quote_id,j.status,j.attempt_no,j.error_message,"
                "j.created_at,j.started_at,j.completed_at,d.draft_id,d.draft_text,d.commercial_facts,"
                "d.model,d.retrieval_id FROM rag_draft_jobs j "
                "LEFT JOIN rag_drafts d ON d.job_id=j.job_id WHERE j.job_id=%s",
                (job_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "job_id": row[0],
            "opp_id": row[1],
            "accepted_quote_id": row[2],
            "status": row[3],
            "attempt_no": row[4],
            "error_message": row[5],
            "created_at": str(row[6]),
            "started_at": str(row[7]) if row[7] else None,
            "completed_at": str(row[8]) if row[8] else None,
            "draft_id": row[9],
            "draft": row[10],
            "commercial_facts": row[11],
            "model": row[12],
            "retrieval_id": row[13],
        }

    def list_retrievals(self, opp_id: str) -> list[dict[str, Any]]:
        import psycopg

        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute(
                "SELECT retrieval_id,query_text,purpose,actor,actor_role,customer_scope,"
                "vendor_scope,chunk_ids,scores,created_at FROM knowledge_retrieval_events "
                "WHERE opp_id=%s ORDER BY retrieval_id DESC",
                (opp_id,),
            ).fetchall()
        return [
            {
                "retrieval_id": row[0],
                "query": row[1],
                "purpose": row[2],
                "actor": row[3],
                "actor_role": row[4],
                "customer_scope": row[5],
                "vendor_scope": row[6],
                "chunk_ids": row[7],
                "scores": row[8],
                "created_at": str(row[9]),
            }
            for row in rows
        ]


def init_knowledge(dsn: str) -> None:
    KnowledgeRepository(dsn).init_schema()
