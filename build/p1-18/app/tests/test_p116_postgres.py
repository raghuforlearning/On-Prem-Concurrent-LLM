import os
from pathlib import Path
import unittest
import uuid


APP_ROOT = Path(__file__).parents[1]


class QuoteValidationSchemaTests(unittest.TestCase):
    def test_schema_contains_validation_history_status_and_review_link(self):
        source = (APP_ROOT / "quotes.py").read_text(encoding="utf-8")
        for required in (
            "quote_validation_results",
            "validation_status",
            "computed_subtotal",
            "computed_vat",
            "computed_total",
            "quote_validation_blocked",
            "quote_id BIGINT REFERENCES quotes(quote_id)",
        ):
            self.assertIn(required, source)

    def test_api_and_review_board_expose_validation_workflow(self):
        main_source = (APP_ROOT / "main.py").read_text(encoding="utf-8")
        ui_source = (APP_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('@app.post("/quotes/{quote_id}/validate")', main_source)
        self.assertIn('@app.get("/quotes/{quote_id}/validation")', main_source)
        self.assertIn("Quote Validation Reviews", ui_source)
        self.assertIn("refreshQuoteReviews", ui_source)


@unittest.skipUnless(
    os.environ.get("P116_TEST_PG_DSN"),
    "set P116_TEST_PG_DSN to a disposable PostgreSQL Orchestrator test database",
)
class LivePostgresQuoteValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PG_DSN"] = os.environ["P116_TEST_PG_DSN"]
        import psycopg
        import db
        import followup
        import quotes
        import vendors

        cls.psycopg = psycopg
        cls.quotes = quotes
        db.init_schema()
        with psycopg.connect(os.environ["P116_TEST_PG_DSN"]) as conn:
            if conn.execute("SELECT to_regclass('audit_log')").fetchone()[0] is None:
                raise unittest.SkipTest("test database must contain the P1-02 audit_log schema")
            vendors.init_vendors(conn)
            followup.init_followups(conn)
            quotes.init_quotes(conn)

    def setUp(self):
        self.suffix = uuid.uuid4().hex[:12]
        self.opp_id = f"P116-OPP-{self.suffix}"
        self.rfq_ref = f"P116-RFQ-{self.suffix}"
        self.response_id = None
        self.quote_id = None
        self.vendor_id = None

    def tearDown(self):
        dsn = os.environ["P116_TEST_PG_DSN"]
        with self.psycopg.connect(dsn) as conn:
            if self.quote_id:
                conn.execute("DELETE FROM quote_validation_results WHERE quote_id=%s", (self.quote_id,))
            if self.response_id:
                conn.execute("DELETE FROM quote_review_queue WHERE response_id=%s", (self.response_id,))
                conn.execute(
                    "DELETE FROM quote_ingestion_attempts WHERE response_id=%s", (self.response_id,)
                )
            if self.quote_id:
                conn.execute("DELETE FROM quote_line_items WHERE quote_id=%s", (self.quote_id,))
                conn.execute("DELETE FROM quotes WHERE quote_id=%s", (self.quote_id,))
            if self.response_id:
                conn.execute("DELETE FROM vendor_responses WHERE id=%s", (self.response_id,))
            conn.execute("DELETE FROM rfqs WHERE rfq_ref=%s", (self.rfq_ref,))
            if self.vendor_id:
                conn.execute("DELETE FROM vendors WHERE vendor_id=%s", (self.vendor_id,))
            conn.execute("DELETE FROM opportunities WHERE opp_id=%s", (self.opp_id,))
            conn.commit()

    def _seed_quote(self, *, first_line_total="25000.00", currency_detected=True):
        dsn = os.environ["P116_TEST_PG_DSN"]
        with self.psycopg.connect(dsn) as conn:
            conn.execute(
                "INSERT INTO opportunities (opp_id,status,raw_text,raw_sha256) "
                "VALUES (%s,'READY','p116 test','p116-test')",
                (self.opp_id,),
            )
            self.vendor_id = conn.execute(
                "INSERT INTO vendors "
                "(vendor_name,tier,tech_domains,vendor_authorised,deal_reg_capable) "
                "VALUES (%s,'OEM','{Testing}',true,true) RETURNING vendor_id",
                (f"P116 Vendor {self.suffix}",),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO rfqs (rfq_ref,opp_id,vendor_id,status,idempotency_key) "
                "VALUES (%s,%s,%s,'BLOCKED_PENDING_DEAL_REG',%s)",
                (self.rfq_ref, self.opp_id, self.vendor_id, self.rfq_ref),
            )
            self.response_id = conn.execute(
                "INSERT INTO vendor_responses "
                "(rfq_ref,response_type,original_filename,content_type,raw_doc_path,raw_sha256,"
                "raw_size_bytes,parse_status) "
                "VALUES (%s,'QUOTE','p116.pdf','application/pdf','/tmp/p116.pdf',%s,100,'PARSED') "
                "RETURNING id",
                (self.rfq_ref, f"sha-{self.suffix}"),
            ).fetchone()[0]
            self.quote_id = conn.execute(
                "INSERT INTO quotes "
                "(quote_group_id,opp_id,vendor_id,response_id,version_no,is_current,currency,"
                "currency_detected,status,builder_result) "
                "VALUES (%s,%s,%s,%s,1,true,'AED',%s,'PARSED','{}') RETURNING quote_id",
                (
                    f"{self.rfq_ref}:P116",
                    self.opp_id,
                    self.vendor_id,
                    self.response_id,
                    currency_detected,
                ),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO quote_line_items "
                "(quote_id,line_no,part_number,description,quantity,unit_price,line_total,raw_item) "
                "VALUES (%s,1,'FG-100F','Firewall',2,12500,%s,'{}'),"
                "(%s,2,'PS-SVC','Services',1,3500,3500,'{}')",
                (self.quote_id, first_line_total, self.quote_id),
            )
            conn.commit()

    @staticmethod
    def _claims():
        from quote_validation import CommercialClaims

        return CommercialClaims.create(
            stated_subtotal="28500",
            vat_rate_percent="5",
            stated_vat="1425",
            stated_total="29925",
            validity_terms="30 days",
            payment_terms="30 days",
            delivery_terms="2-4 weeks",
        )

    @staticmethod
    def _policy():
        from quote_validation import ValidationPolicy

        return ValidationPolicy(
            require_currency_detected=True,
            require_stated_totals=True,
            require_vat=True,
            required_terms=("validity", "payment", "delivery"),
        )

    def test_valid_quote_proceeds_and_persists_validation_history(self):
        self._seed_quote()
        repository = self.quotes.PostgresQuoteRepository(os.environ["P116_TEST_PG_DSN"])
        result = repository.validate_quote(
            quote_id=self.quote_id,
            claims=self._claims(),
            policy=self._policy(),
            actor="p116-test",
        )
        self.assertEqual(result["status"], "VALIDATED")
        self.assertTrue(result["may_proceed"])
        self.assertIsNone(result["review_id"])
        latest = repository.latest_validation(self.quote_id)
        self.assertEqual(latest["validation_id"], result["validation_id"])
        self.assertEqual(latest["computed_total"], "29925.00")
        with self.psycopg.connect(os.environ["P116_TEST_PG_DSN"]) as conn:
            status = conn.execute(
                "SELECT validation_status FROM quotes WHERE quote_id=%s", (self.quote_id,)
            ).fetchone()[0]
            action = conn.execute(
                "SELECT action FROM audit_log WHERE opp_id=%s AND component='quote_validation' "
                "ORDER BY seq DESC LIMIT 1",
                (self.opp_id,),
            ).fetchone()[0]
        self.assertEqual(status, "VALIDATED")
        self.assertEqual(action, "quote_validation_passed")

    def test_mismatch_is_blocked_reviewed_audited_and_never_auto_fixed(self):
        self._seed_quote(first_line_total="24900.00")
        repository = self.quotes.PostgresQuoteRepository(os.environ["P116_TEST_PG_DSN"])
        first = repository.validate_quote(
            quote_id=self.quote_id,
            claims=self._claims(),
            policy=self._policy(),
            actor="p116-test",
        )
        second = repository.validate_quote(
            quote_id=self.quote_id,
            claims=self._claims(),
            policy=self._policy(),
            actor="p116-test",
        )
        self.assertEqual((first["status"], second["status"]), ("BLOCKED", "BLOCKED"))
        self.assertIn("LINE_TOTAL_MISMATCH", {issue["code"] for issue in first["issues"]})
        self.assertIsNotNone(first["review_id"])
        self.assertEqual(first["review_id"], second["review_id"])
        with self.psycopg.connect(os.environ["P116_TEST_PG_DSN"]) as conn:
            line_total = conn.execute(
                "SELECT line_total FROM quote_line_items WHERE quote_id=%s AND line_no=1",
                (self.quote_id,),
            ).fetchone()[0]
            review = conn.execute(
                "SELECT error_code,status,quote_id FROM quote_review_queue WHERE response_id=%s",
                (self.response_id,),
            ).fetchone()
            audit_count = conn.execute(
                "SELECT count(*) FROM audit_log WHERE opp_id=%s "
                "AND component='quote_validation' AND action='quote_validation_blocked'",
                (self.opp_id,),
            ).fetchone()[0]
        self.assertEqual(str(line_total), "24900.0000")
        self.assertEqual(review, ("QUOTE_VALIDATION_BLOCKED", "OPEN", self.quote_id))
        self.assertEqual(audit_count, 2)


if __name__ == "__main__":
    unittest.main()
