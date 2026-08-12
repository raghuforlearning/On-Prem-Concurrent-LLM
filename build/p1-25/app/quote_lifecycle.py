"""P1-15 quote-ingestion orchestration independent of transport and database.

Raw bytes are archived before any Proposal Builder call.  Once a response row
exists, every terminal adapter outcome is persisted as PARSED or FAILED_REVIEW.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Protocol

from integrations.proposal_builder import BuilderError, QuoteExtractionResult


class QuoteAdapter(Protocol):
    def extract_quote(
        self, content: bytes, filename: str, content_type: str | None = None
    ) -> QuoteExtractionResult: ...


class QuoteRepository(Protocol):
    def create_or_get_response(
        self,
        *,
        rfq_ref: str,
        filename: str,
        content_type: str | None,
        raw_sha256: str,
        raw_doc_path: str,
        actor: str,
    ) -> dict[str, Any]: ...

    def persist_success(
        self,
        *,
        response_id: int,
        quote_reference: str | None,
        result: QuoteExtractionResult,
        actor: str,
    ) -> dict[str, Any]: ...

    def mark_failed_review(
        self,
        *,
        response_id: int,
        error_code: str,
        error_message: str,
        http_status: int | None,
        details: Any,
        actor: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ArchivedQuote:
    path: str
    sha256: str
    size_bytes: int


class QuoteArchive:
    """Content-addressed local storage for immutable vendor quote originals."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    @staticmethod
    def _safe_filename(filename: str) -> str:
        name = Path(filename or "quote.bin").name
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
        return name[:160] or "quote.bin"

    def preserve(self, content: bytes, filename: str) -> ArchivedQuote:
        digest = hashlib.sha256(content).hexdigest()
        destination_dir = self.root / digest[:2] / digest
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / self._safe_filename(filename)
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"quote archive hash collision at {destination}")
        else:
            temporary = destination.with_suffix(destination.suffix + ".partial")
            temporary.write_bytes(content)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != digest:
                temporary.unlink(missing_ok=True)
                raise RuntimeError("quote archive verification failed")
            temporary.replace(destination)
        return ArchivedQuote(path=str(destination), sha256=digest, size_bytes=len(content))


@dataclass(frozen=True)
class QuoteIngestionOutcome:
    response_id: int
    parse_status: str
    raw_sha256: str
    raw_doc_path: str
    quote_id: int | None = None
    quote_group_id: str | None = None
    version_no: int | None = None
    review_id: int | None = None
    error_code: str | None = None
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "response_id": self.response_id,
            "parse_status": self.parse_status,
            "raw_sha256": self.raw_sha256,
            "raw_doc_path": self.raw_doc_path,
            "quote_id": self.quote_id,
            "quote_group_id": self.quote_group_id,
            "version_no": self.version_no,
            "review_id": self.review_id,
            "error_code": self.error_code,
            "note": self.note,
        }


class QuoteIngestionService:
    def __init__(self, repository: QuoteRepository, adapter: QuoteAdapter, archive: QuoteArchive):
        self.repository = repository
        self.adapter = adapter
        self.archive = archive

    def ingest(
        self,
        *,
        rfq_ref: str,
        content: bytes,
        filename: str,
        content_type: str | None,
        quote_reference: str | None,
        actor: str,
    ) -> QuoteIngestionOutcome:
        archived = self.archive.preserve(content, filename)
        response = self.repository.create_or_get_response(
            rfq_ref=rfq_ref,
            filename=filename,
            content_type=content_type,
            raw_sha256=archived.sha256,
            raw_doc_path=archived.path,
            actor=actor,
        )
        if response.get("existing"):
            return QuoteIngestionOutcome(
                response_id=response["response_id"],
                parse_status=response["parse_status"],
                raw_sha256=archived.sha256,
                raw_doc_path=archived.path,
                quote_id=response.get("quote_id"),
                quote_group_id=response.get("quote_group_id"),
                version_no=response.get("version_no"),
                review_id=response.get("review_id"),
                error_code=response.get("error_code"),
                note="identical source already recorded (idempotent)",
            )

        response_id = response["response_id"]
        try:
            result = self.adapter.extract_quote(content, filename, content_type)
        except BuilderError as exc:
            failed = self.repository.mark_failed_review(
                response_id=response_id,
                error_code=exc.code,
                error_message=str(exc),
                http_status=exc.http_status,
                details=exc.details,
                actor=actor,
            )
            return QuoteIngestionOutcome(
                response_id=response_id,
                parse_status="FAILED_REVIEW",
                raw_sha256=archived.sha256,
                raw_doc_path=archived.path,
                review_id=failed["review_id"],
                error_code=exc.code,
                note=str(exc),
            )
        except Exception as exc:
            failed = self.repository.mark_failed_review(
                response_id=response_id,
                error_code="ADAPTER_UNEXPECTED_ERROR",
                error_message=str(exc),
                http_status=None,
                details=None,
                actor=actor,
            )
            return QuoteIngestionOutcome(
                response_id=response_id,
                parse_status="FAILED_REVIEW",
                raw_sha256=archived.sha256,
                raw_doc_path=archived.path,
                review_id=failed["review_id"],
                error_code="ADAPTER_UNEXPECTED_ERROR",
                note=str(exc),
            )

        try:
            stored = self.repository.persist_success(
                response_id=response_id,
                quote_reference=quote_reference,
                result=result,
                actor=actor,
            )
        except Exception as exc:
            failed = self.repository.mark_failed_review(
                response_id=response_id,
                error_code="QUOTE_PERSISTENCE_ERROR",
                error_message=str(exc),
                http_status=None,
                details=result.raw_payload,
                actor=actor,
            )
            return QuoteIngestionOutcome(
                response_id=response_id,
                parse_status="FAILED_REVIEW",
                raw_sha256=archived.sha256,
                raw_doc_path=archived.path,
                review_id=failed["review_id"],
                error_code="QUOTE_PERSISTENCE_ERROR",
                note=str(exc),
            )
        return QuoteIngestionOutcome(
            response_id=response_id,
            parse_status="PARSED",
            raw_sha256=archived.sha256,
            raw_doc_path=archived.path,
            quote_id=stored["quote_id"],
            quote_group_id=stored["quote_group_id"],
            version_no=stored["version_no"],
        )
