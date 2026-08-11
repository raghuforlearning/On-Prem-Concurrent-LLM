import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from integrations.proposal_builder import BuilderQuoteRejected, QuoteExtractionResult
from quote_lifecycle import QuoteArchive, QuoteIngestionService


FIXTURE = Path(__file__).parent / "fixtures" / "quotes" / "builder-success.json"


class FakeAdapter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def extract_quote(self, content, filename, content_type=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class FakeRepository:
    def __init__(self, rfq_status="BLOCKED_PENDING_DEAL_REG", persist_error=None):
        self.rfq_status = rfq_status
        self.persist_error = persist_error
        self.responses = {}
        self.quotes = []
        self.reviews = []
        self.next_response_id = 1

    def create_or_get_response(self, **data):
        key = (data["rfq_ref"], data["raw_sha256"])
        if key in self.responses:
            row = dict(self.responses[key])
            row["existing"] = True
            return row
        row = {
            "response_id": self.next_response_id,
            "parse_status": "PENDING",
            "raw_sha256": data["raw_sha256"],
            "raw_doc_path": data["raw_doc_path"],
            "existing": False,
            "rfq_ref": data["rfq_ref"],
        }
        self.next_response_id += 1
        self.responses[key] = row
        return dict(row)

    def _response(self, response_id):
        return next(row for row in self.responses.values() if row["response_id"] == response_id)

    def persist_success(self, *, response_id, quote_reference, result, actor):
        if self.persist_error:
            raise self.persist_error
        response = self._response(response_id)
        group = f'{response["rfq_ref"]}:{quote_reference or "default"}'
        for quote in self.quotes:
            if quote["quote_group_id"] == group and quote["is_current"]:
                quote["is_current"] = False
                quote["status"] = "SUPERSEDED"
        version = 1 + max(
            (q["version_no"] for q in self.quotes if q["quote_group_id"] == group),
            default=0,
        )
        quote = {
            "quote_id": len(self.quotes) + 1,
            "quote_group_id": group,
            "version_no": version,
            "is_current": True,
            "status": "PARSED",
            "line_count": len(result.items),
        }
        self.quotes.append(quote)
        response.update(
            parse_status="PARSED",
            quote_id=quote["quote_id"],
            quote_group_id=group,
            version_no=version,
        )
        return quote

    def mark_failed_review(self, *, response_id, error_code, error_message, **kwargs):
        response = self._response(response_id)
        review = {
            "review_id": len(self.reviews) + 1,
            "response_id": response_id,
            "error_code": error_code,
            "reason": error_message,
        }
        self.reviews.append(review)
        response.update(
            parse_status="FAILED_REVIEW",
            review_id=review["review_id"],
            error_code=error_code,
        )
        return review


def success_result():
    return QuoteExtractionResult.from_builder(json.loads(FIXTURE.read_text()))


class QuoteLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def _service(self, repository=None, adapter=None):
        repository = repository or FakeRepository()
        adapter = adapter or FakeAdapter(result=success_result())
        return QuoteIngestionService(repository, adapter, QuoteArchive(self.temp.name)), repository, adapter

    def test_valid_quote_is_archived_before_structured_result(self):
        service, repository, adapter = self._service()
        content = b"sample vendor quote bytes"
        outcome = service.ingest(
            rfq_ref="NL-RFQ-2026-0001",
            content=content,
            filename="Vendor Quote.pdf",
            content_type="application/pdf",
            quote_reference="VQ-100",
            actor="tester",
        )
        self.assertEqual(outcome.parse_status, "PARSED")
        self.assertEqual(outcome.raw_sha256, hashlib.sha256(content).hexdigest())
        self.assertEqual(Path(outcome.raw_doc_path).read_bytes(), content)
        self.assertEqual(repository.quotes[0]["line_count"], 2)
        self.assertEqual(adapter.calls, 1)

    def test_identical_source_is_idempotent_and_not_reparsed(self):
        service, _, adapter = self._service()
        args = dict(
            rfq_ref="NL-RFQ-2026-0001",
            content=b"same quote",
            filename="quote.pdf",
            content_type="application/pdf",
            quote_reference="VQ-100",
            actor="tester",
        )
        first = service.ingest(**args)
        second = service.ingest(**args)
        self.assertEqual(first.response_id, second.response_id)
        self.assertEqual(first.quote_id, second.quote_id)
        self.assertEqual(adapter.calls, 1)
        self.assertIn("idempotent", second.note)

    def test_builder_rejection_retains_source_and_opens_review(self):
        error = BuilderQuoteRejected(
            "totals disagree",
            rejection_code="QUOTE_NOT_RECONCILED",
            http_status=422,
            details={"reasons": ["line total mismatch"]},
        )
        service, repository, _ = self._service(adapter=FakeAdapter(error=error))
        content = b"arithmetic-error quote"
        outcome = service.ingest(
            rfq_ref="NL-RFQ-2026-0001",
            content=content,
            filename="bad.pdf",
            content_type="application/pdf",
            quote_reference="VQ-BAD",
            actor="tester",
        )
        self.assertEqual(outcome.parse_status, "FAILED_REVIEW")
        self.assertEqual(outcome.error_code, "QUOTE_NOT_RECONCILED")
        self.assertTrue(Path(outcome.raw_doc_path).exists())
        self.assertEqual(len(repository.reviews), 1)
        self.assertEqual(len(repository.quotes), 0)

    def test_revised_quote_preserves_prior_version(self):
        repository = FakeRepository()
        service, repository, _ = self._service(repository=repository)
        base = dict(
            rfq_ref="NL-RFQ-2026-0001",
            filename="quote.pdf",
            content_type="application/pdf",
            quote_reference="VQ-REV",
            actor="tester",
        )
        v1 = service.ingest(content=b"revision one", **base)
        v2 = service.ingest(content=b"revision two", **base)
        self.assertEqual((v1.version_no, v2.version_no), (1, 2))
        self.assertEqual(repository.quotes[0]["status"], "SUPERSEDED")
        self.assertFalse(repository.quotes[0]["is_current"])
        self.assertTrue(repository.quotes[1]["is_current"])

    def test_persistence_failure_is_not_silently_dropped(self):
        repository = FakeRepository(persist_error=RuntimeError("database write refused"))
        service, repository, _ = self._service(repository=repository)
        outcome = service.ingest(
            rfq_ref="NL-RFQ-2026-0001",
            content=b"valid parse but failed persistence",
            filename="persistence.pdf",
            content_type="application/pdf",
            quote_reference="VQ-PERSIST",
            actor="tester",
        )
        self.assertEqual(outcome.parse_status, "FAILED_REVIEW")
        self.assertEqual(outcome.error_code, "QUOTE_PERSISTENCE_ERROR")
        self.assertEqual(repository.reviews[0]["reason"], "database write refused")

    def test_quote_ingestion_is_allowed_while_deal_registration_pending(self):
        repository = FakeRepository(rfq_status="BLOCKED_PENDING_DEAL_REG")
        service, _, _ = self._service(repository=repository)
        outcome = service.ingest(
            rfq_ref="NL-RFQ-2026-0001",
            content=b"quote received while DR pending",
            filename="pending-dr.pdf",
            content_type="application/pdf",
            quote_reference=None,
            actor="tester",
        )
        self.assertEqual(outcome.parse_status, "PARSED")


if __name__ == "__main__":
    unittest.main()
