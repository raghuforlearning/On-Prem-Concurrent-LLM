import os
import unittest
import uuid


@unittest.skipUnless(
    os.environ.get("P118_TEST_PG_DSN"),
    "set P118_TEST_PG_DSN to a disposable PostgreSQL Orchestrator test database",
)
class LivePostgresQuoteComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PG_DSN"] = os.environ["P118_TEST_PG_DSN"]
        import psycopg
        import db
        import followup
        import quote_comparison
        import quotes
        import vendors

        cls.psycopg = psycopg
        cls.comparison = quote_comparison
        db.init_schema()
        with psycopg.connect(os.environ["P118_TEST_PG_DSN"]) as conn:
            if conn.execute("SELECT to_regclass('audit_log')").fetchone()[0] is None:
                raise unittest.SkipTest("test database must contain the P1-02 audit_log schema")
            vendors.init_vendors(conn)
            followup.init_followups(conn)
            quotes.init_quotes(conn)
        quote_comparison.init_quote_comparison(os.environ["P118_TEST_PG_DSN"])

    def setUp(self):
        self.suffix = uuid.uuid4().hex[:12]
        self.opp_id = f"P118-OPP-{self.suffix}"
        self.vendor_ids = []
        self.rfq_refs = []
        self.response_ids = []
        self.quote_ids = []
        self.rate_ids = []
        self.run_ids = []
        self.selection_ids = []
        with self.psycopg.connect(os.environ["P118_TEST_PG_DSN"]) as conn:
            conn.execute(
                "INSERT INTO opportunities (opp_id,status,raw_text,raw_sha256) "
                "VALUES (%s,'READY','p118 comparison','p118-test')",
                (self.opp_id,),
            )
            conn.commit()

    def tearDown(self):
        with self.psycopg.connect(os.environ["P118_TEST_PG_DSN"]) as conn:
            if self.selection_ids:
                conn.execute("DELETE FROM quote_selection_decisions WHERE selection_id=ANY(%s)", (self.selection_ids,))
                conn.execute("DELETE FROM quote_selections WHERE selection_id=ANY(%s)", (self.selection_ids,))
            if self.run_ids:
                conn.execute("DELETE FROM quote_comparison_inputs WHERE comparison_run_id=ANY(%s)", (self.run_ids,))
                conn.execute("DELETE FROM quote_comparison_runs WHERE comparison_run_id=ANY(%s)", (self.run_ids,))
            if self.rate_ids:
                conn.execute("DELETE FROM exchange_rates WHERE rate_id=ANY(%s)", (self.rate_ids,))
            if self.quote_ids:
                conn.execute("DELETE FROM quote_validation_results WHERE quote_id=ANY(%s)", (self.quote_ids,))
                conn.execute("DELETE FROM quote_line_items WHERE quote_id=ANY(%s)", (self.quote_ids,))
                conn.execute("DELETE FROM quotes WHERE quote_id=ANY(%s)", (self.quote_ids,))
            if self.response_ids:
                conn.execute("DELETE FROM vendor_responses WHERE id=ANY(%s)", (self.response_ids,))
            conn.execute("DELETE FROM deal_registrations WHERE opp_id=%s", (self.opp_id,))
            if self.rfq_refs:
                conn.execute("DELETE FROM rfqs WHERE rfq_ref=ANY(%s)", (self.rfq_refs,))
            if self.vendor_ids:
                conn.execute("DELETE FROM vendors WHERE vendor_id=ANY(%s)", (self.vendor_ids,))
            conn.execute("DELETE FROM opportunities WHERE opp_id=%s", (self.opp_id,))
            conn.commit()

    def _seed_quote(self, vendor_no, currency, subtotal, vat, total, *, deal_reg_capable, group=None, version=1, current=True):
        rfq_ref = f"P118-RFQ-{vendor_no}-{version}-{self.suffix}"
        self.rfq_refs.append(rfq_ref)
        with self.psycopg.connect(os.environ["P118_TEST_PG_DSN"]) as conn:
            vendor_id = conn.execute(
                "INSERT INTO vendors (vendor_name,tier,tech_domains,vendor_authorised,deal_reg_capable) "
                "VALUES (%s,'OEM','{Testing}',true,%s) RETURNING vendor_id",
                (f"P118 Vendor {vendor_no} {version} {self.suffix}", deal_reg_capable),
            ).fetchone()[0]
            self.vendor_ids.append(vendor_id)
            conn.execute(
                "INSERT INTO rfqs (rfq_ref,opp_id,vendor_id,status,idempotency_key) "
                "VALUES (%s,%s,%s,'SENT',%s)",
                (rfq_ref, self.opp_id, vendor_id, rfq_ref),
            )
            response_id = conn.execute(
                "INSERT INTO vendor_responses "
                "(rfq_ref,response_type,original_filename,content_type,raw_doc_path,raw_sha256,raw_size_bytes,parse_status) "
                "VALUES (%s,'QUOTE','p118.pdf','application/pdf','/tmp/p118.pdf',%s,100,'PARSED') RETURNING id",
                (rfq_ref, f"sha-{vendor_no}-{version}-{self.suffix}"),
            ).fetchone()[0]
            self.response_ids.append(response_id)
            quote_id = conn.execute(
                "INSERT INTO quotes "
                "(quote_group_id,opp_id,vendor_id,response_id,version_no,is_current,currency,currency_detected,status,builder_result,validation_status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,true,%s,'{}','VALIDATED') RETURNING quote_id",
                (group or f"group-{vendor_no}-{self.suffix}", self.opp_id, vendor_id, response_id, version, current, currency, "PARSED" if current else "SUPERSEDED"),
            ).fetchone()[0]
            self.quote_ids.append(quote_id)
            conn.execute(
                "INSERT INTO quote_line_items "
                "(quote_id,line_no,part_number,description,quantity,unit_price,line_total,raw_item) "
                "VALUES (%s,1,%s,'Firewall',1,%s,%s,'{}')",
                (quote_id, f"SKU-{vendor_no}", subtotal, subtotal),
            )
            validation_id = conn.execute(
                "INSERT INTO quote_validation_results "
                "(quote_id,engine_version,status,currency,policy_snapshot,claims_snapshot,computed_subtotal,computed_vat,computed_total,issues,validated_by) "
                "VALUES (%s,'p118-test','VALIDATED',%s,'{}',%s,%s,%s,%s,'[]','p118') RETURNING validation_id",
                (quote_id, currency, '{"validity_terms":"30 days","payment_terms":"30 days","delivery_terms":"2 weeks"}', subtotal, vat, total),
            ).fetchone()[0]
            conn.commit()
        return {"quote_id": quote_id, "vendor_id": vendor_id, "validation_id": validation_id, "group": group or f"group-{vendor_no}-{self.suffix}"}

    def _record_rate(self, currency, rate, source):
        from datetime import date

        saved = self.comparison.QuoteComparisonRepository(os.environ["P118_TEST_PG_DSN"]).record_exchange_rate(
            currency=currency,
            aed_per_unit=rate,
            rate_date=date(2026, 8, 12),
            source_reference=source,
            actor="p118.finance",
        )
        self.rate_ids.append(saved["rate_id"])
        return saved["rate_id"]

    def _seed_three(self):
        aed = self._seed_quote(1, "AED", "28500", "1425", "29925", deal_reg_capable=True)
        usd = self._seed_quote(2, "USD", "7000", "350", "7350", deal_reg_capable=True)
        eur = self._seed_quote(3, "EUR", "7600", "380", "7980", deal_reg_capable=False)
        with self.psycopg.connect(os.environ["P118_TEST_PG_DSN"]) as conn:
            conn.execute(
                "INSERT INTO deal_registrations (opp_id,vendor_id,status,reg_reference) VALUES "
                "(%s,%s,'APPROVED','DR-P118'),(%s,%s,'REQUESTED',NULL)",
                (self.opp_id, aed["vendor_id"], self.opp_id, usd["vendor_id"]),
            )
            conn.commit()
        return aed, usd, eur

    def test_three_vendor_matrix_is_repeatable_native_and_aed_normalized(self):
        aed, usd, eur = self._seed_three()
        usd_rate = self._record_rate("USD", "3.6725", "finance-sheet-usd")
        eur_rate = self._record_rate("EUR", "4.1000", "finance-sheet-eur")
        repository = self.comparison.QuoteComparisonRepository(os.environ["P118_TEST_PG_DSN"])
        rates = {usd["quote_id"]: usd_rate, eur["quote_id"]: eur_rate}
        first = repository.create_comparison(
            opp_id=self.opp_id,
            quote_ids=[eur["quote_id"], aed["quote_id"], usd["quote_id"]],
            exchange_rate_ids=rates,
            actor="p118.user",
        )
        second = repository.create_comparison(
            opp_id=self.opp_id,
            quote_ids=[usd["quote_id"], eur["quote_id"], aed["quote_id"]],
            exchange_rate_ids=rates,
            actor="p118.user",
        )
        self.run_ids.extend([first["comparison_run_id"], second["comparison_run_id"]])
        self.assertEqual(first["result_hash"], second["result_hash"])
        self.assertEqual(first["result"], second["result"])
        rows = {row["native_currency"]: row for row in first["result"]["quotes"]}
        self.assertEqual(rows["USD"]["native_total"], "7350.00")
        self.assertEqual(rows["USD"]["aed_total"], "26992.88")
        self.assertEqual(rows["USD"]["deal_registration"]["status"], "PENDING")
        self.assertEqual(rows["AED"]["deal_registration"]["status"], "APPROVED")
        self.assertEqual(rows["EUR"]["deal_registration"]["status"], "NOT_REQUIRED")
        with self.psycopg.connect(os.environ["P118_TEST_PG_DSN"]) as conn:
            texts = conn.execute(
                "SELECT result_json::text FROM quote_comparison_runs WHERE comparison_run_id=ANY(%s) ORDER BY comparison_run_id",
                (self.run_ids,),
            ).fetchall()
        self.assertEqual(texts[0][0], texts[1][0])
        pending_selection = repository.select_quote(
            comparison_run_id=first["comparison_run_id"],
            quote_id=usd["quote_id"],
            actor="p118.approver",
            reason="Commercially preferred pending deal registration",
        )
        self.selection_ids.append(pending_selection["selection_id"])
        self.assertEqual(pending_selection["deal_reg_status"], "PENDING")
        self.assertFalse(pending_selection["proposal_eligible"])

    def test_selection_freezes_version_records_nonselected_and_preserves_superseded_history(self):
        aed, usd, eur = self._seed_three()
        old_group = aed["group"]
        with self.psycopg.connect(os.environ["P118_TEST_PG_DSN"]) as conn:
            conn.execute("UPDATE quotes SET is_current=false,status='SUPERSEDED' WHERE quote_id=%s", (aed["quote_id"],))
            conn.commit()
        revised = self._seed_quote(4, "AED", "28000", "1400", "29400", deal_reg_capable=False, group=old_group, version=2)
        usd_rate = self._record_rate("USD", "3.6725", "finance-sheet-usd")
        eur_rate = self._record_rate("EUR", "4.1000", "finance-sheet-eur")
        repository = self.comparison.QuoteComparisonRepository(os.environ["P118_TEST_PG_DSN"])
        run = repository.create_comparison(
            opp_id=self.opp_id,
            quote_ids=[revised["quote_id"], usd["quote_id"], eur["quote_id"]],
            exchange_rate_ids={usd["quote_id"]: usd_rate, eur["quote_id"]: eur_rate},
            actor="p118.user",
        )
        self.run_ids.append(run["comparison_run_id"])
        selected = repository.select_quote(
            comparison_run_id=run["comparison_run_id"],
            quote_id=revised["quote_id"],
            actor="p118.approver",
            reason="Best validated total and acceptable terms",
        )
        self.selection_ids.append(selected["selection_id"])
        self.assertEqual(selected["quote_version_no"], 2)
        self.assertTrue(selected["proposal_eligible"])
        with self.assertRaisesRegex(PermissionError, "cannot be changed"):
            repository.select_quote(
                comparison_run_id=run["comparison_run_id"],
                quote_id=usd["quote_id"],
                actor="p118.approver",
                reason="Attempt to rewrite frozen decision",
            )
        active = repository.active_selection(self.opp_id)
        self.assertEqual(active["quote_id"], revised["quote_id"])
        self.assertEqual(active["commercial_snapshot"]["native_total"], "29400.00")
        with self.psycopg.connect(os.environ["P118_TEST_PG_DSN"]) as conn:
            old = conn.execute(
                "SELECT version_no,is_current,status FROM quotes WHERE quote_id=%s",
                (aed["quote_id"],),
            ).fetchone()
            decisions = conn.execute(
                "SELECT decision,count(*) FROM quote_selection_decisions WHERE selection_id=%s GROUP BY decision ORDER BY decision",
                (selected["selection_id"],),
            ).fetchall()
            audit_action = conn.execute(
                "SELECT action FROM audit_log WHERE opp_id=%s AND component='quote_comparison' ORDER BY seq DESC LIMIT 1",
                (self.opp_id,),
            ).fetchone()[0]
        self.assertEqual(old, (1, False, "SUPERSEDED"))
        self.assertEqual(decisions, [("NOT_SELECTED", 2), ("SELECTED", 1)])
        self.assertEqual(audit_action, "quote_selected_human")


if __name__ == "__main__":
    unittest.main()
