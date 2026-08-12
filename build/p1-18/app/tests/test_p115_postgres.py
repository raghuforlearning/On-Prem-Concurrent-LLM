import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid


APP_ROOT = Path(__file__).parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "quotes" / "builder-success.json"


class QuoteSchemaDDLTests(unittest.TestCase):
    def test_schema_contains_lifecycle_and_review_invariants(self):
        source = (APP_ROOT / "quotes.py").read_text()
        for required in (
            "uq_vendor_response_source",
            "uq_quote_group_current",
            "quote_line_items",
            "quote_ingestion_attempts",
            "quote_review_queue",
            "FAILED_REVIEW",
        ):
            self.assertIn(required, source)


@unittest.skipUnless(
    os.environ.get("P115_TEST_PG_DSN"),
    "set P115_TEST_PG_DSN to a disposable PostgreSQL Orchestrator test database",
)
class LivePostgresQuoteLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PG_DSN"] = os.environ["P115_TEST_PG_DSN"]
        import psycopg
        import db
        import followup
        import quotes
        import vendors

        cls.psycopg = psycopg
        cls.db = db
        cls.quotes = quotes
        db.init_schema()
        with psycopg.connect(os.environ["P115_TEST_PG_DSN"]) as conn:
            if conn.execute("SELECT to_regclass('audit_log')").fetchone()[0] is None:
                raise unittest.SkipTest("test database must contain the P1-02 audit_log schema")
            vendors.init_vendors(conn)
            followup.init_followups(conn)
            quotes.init_quotes(conn)

    def test_postgres_persists_provenance_and_quote_revisions_while_dr_pending(self):
        suffix = uuid.uuid4().hex[:12]
        opp_id = f"P115-OPP-{suffix}"
        rfq_ref = f"P115-RFQ-{suffix}"
        vendor_name = f"P115 Vendor {suffix}"
        dsn = os.environ["P115_TEST_PG_DSN"]
        response_ids = []
        quote_ids = []
        vendor_id = None
        with tempfile.TemporaryDirectory() as tmp:
            try:
                with self.psycopg.connect(dsn) as conn:
                    conn.execute(
                        "INSERT INTO opportunities (opp_id,status,raw_text,raw_sha256) "
                        "VALUES (%s,'READY','p115 test','test')",
                        (opp_id,),
                    )
                    vendor_id = conn.execute(
                        "INSERT INTO vendors "
                        "(vendor_name,tier,tech_domains,vendor_authorised,deal_reg_capable) "
                        "VALUES (%s,'OEM','{Testing}',true,true) RETURNING vendor_id",
                        (vendor_name,),
                    ).fetchone()[0]
                    conn.execute(
                        "INSERT INTO rfqs "
                        "(rfq_ref,opp_id,vendor_id,status,idempotency_key) "
                        "VALUES (%s,%s,%s,'BLOCKED_PENDING_DEAL_REG',%s)",
                        (rfq_ref, opp_id, vendor_id, rfq_ref),
                    )
                    conn.commit()

                repository = self.quotes.PostgresQuoteRepository(dsn)
                from integrations.proposal_builder import QuoteExtractionResult

                result = QuoteExtractionResult.from_builder(json.loads(FIXTURE.read_text()))
                for version, content in enumerate((b"quote revision one", b"quote revision two"), 1):
                    path = Path(tmp) / f"quote-v{version}.pdf"
                    path.write_bytes(content)
                    digest = hashlib.sha256(content).hexdigest()
                    response = repository.create_or_get_response(
                        rfq_ref=rfq_ref,
                        filename=path.name,
                        content_type="application/pdf",
                        raw_sha256=digest,
                        raw_doc_path=str(path),
                        actor="p115-test",
                    )
                    response_ids.append(response["response_id"])
                    stored = repository.persist_success(
                        response_id=response["response_id"],
                        quote_reference="VENDOR-REF-1",
                        result=result,
                        actor="p115-test",
                    )
                    quote_ids.append(stored["quote_id"])
                    self.assertEqual(stored["version_no"], version)

                with self.psycopg.connect(dsn) as conn:
                    rows = conn.execute(
                        "SELECT version_no,is_current,status FROM quotes "
                        "WHERE quote_id=ANY(%s) ORDER BY version_no",
                        (quote_ids,),
                    ).fetchall()
                    self.assertEqual(rows, [(1, False, "SUPERSEDED"), (2, True, "PARSED")])
                    provenance = conn.execute(
                        "SELECT raw_sha256,raw_doc_path,parse_status FROM vendor_responses WHERE id=%s",
                        (response_ids[1],),
                    ).fetchone()
                    self.assertEqual(provenance[0], hashlib.sha256(b"quote revision two").hexdigest())
                    self.assertEqual(provenance[2], "PARSED")
            finally:
                with self.psycopg.connect(dsn) as conn:
                    if response_ids:
                        conn.execute(
                            "DELETE FROM quote_review_queue WHERE response_id=ANY(%s)", (response_ids,)
                        )
                        conn.execute(
                            "DELETE FROM quote_ingestion_attempts WHERE response_id=ANY(%s)",
                            (response_ids,),
                        )
                    if quote_ids:
                        conn.execute("DELETE FROM quote_line_items WHERE quote_id=ANY(%s)", (quote_ids,))
                        conn.execute("DELETE FROM quotes WHERE quote_id=ANY(%s)", (quote_ids,))
                    if response_ids:
                        conn.execute("DELETE FROM vendor_responses WHERE id=ANY(%s)", (response_ids,))
                    conn.execute("DELETE FROM rfqs WHERE rfq_ref=%s", (rfq_ref,))
                    if vendor_id:
                        conn.execute("DELETE FROM vendors WHERE vendor_id=%s", (vendor_id,))
                    conn.execute("DELETE FROM opportunities WHERE opp_id=%s", (opp_id,))
                    conn.commit()


if __name__ == "__main__":
    unittest.main()
