import os
import unittest
import uuid

from test_p119_postgres import FakeBuilderAdapter


@unittest.skipUnless(
    os.environ.get("P122_TEST_PG_DSN"),
    "set P122_TEST_PG_DSN to a disposable PostgreSQL Orchestrator test database",
)
class LivePostgresProposalReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PG_DSN"] = os.environ["P122_TEST_PG_DSN"]
        import psycopg
        import approvals
        import db
        import followup
        import proposals
        import quote_comparison
        import quotes
        import vendors

        cls.psycopg = psycopg
        cls.proposals = proposals
        cls.quote_comparison = quote_comparison
        db.init_schema()
        with psycopg.connect(os.environ["P122_TEST_PG_DSN"]) as conn:
            if conn.execute("SELECT to_regclass('audit_log')").fetchone()[0] is None:
                raise unittest.SkipTest("test database must contain the P1-02 audit_log schema")
            vendors.init_vendors(conn)
            followup.init_followups(conn)
            approvals.init_approvals(conn)
            quotes.init_quotes(conn)
        quote_comparison.init_quote_comparison(os.environ["P122_TEST_PG_DSN"])
        proposals.init_proposals(os.environ["P122_TEST_PG_DSN"])

    def setUp(self):
        self.suffix = uuid.uuid4().hex[:12]
        self.opp_id = f"P122-OPP-{self.suffix}"
        self.vendor_ids = []
        self.rfq_refs = []
        self.response_ids = []
        self.quote_ids = []
        self.run_ids = []
        self.selection_ids = []
        self.proposal_ids = []
        self.version_ids = []
        self.job_ids = []
        self.release_ids = []
        with self.psycopg.connect(os.environ["P122_TEST_PG_DSN"]) as conn:
            conn.execute(
                "INSERT INTO opportunities (opp_id,status,raw_text,raw_sha256) "
                "VALUES (%s,'READY','p122 release','p122-test')",
                (self.opp_id,),
            )
            conn.commit()

    def tearDown(self):
        with self.psycopg.connect(os.environ["P122_TEST_PG_DSN"]) as conn:
            if self.release_ids:
                conn.execute("DELETE FROM proposal_submissions WHERE release_package_id=ANY(%s)", (self.release_ids,))
                conn.execute("DELETE FROM proposal_release_artifacts WHERE release_package_id=ANY(%s)", (self.release_ids,))
                conn.execute("DELETE FROM proposal_release_packages WHERE release_package_id=ANY(%s)", (self.release_ids,))
            if self.job_ids:
                conn.execute("DELETE FROM document_validation_results WHERE build_job_id=ANY(%s)", (self.job_ids,))
                conn.execute("DELETE FROM proposal_artifacts WHERE build_job_id=ANY(%s)", (self.job_ids,))
                conn.execute("DELETE FROM document_build_jobs WHERE build_job_id=ANY(%s)", (self.job_ids,))
            if self.version_ids:
                conn.execute("DELETE FROM proposal_versions WHERE proposal_version_id=ANY(%s)", (self.version_ids,))
            if self.proposal_ids:
                conn.execute("DELETE FROM proposals WHERE proposal_id=ANY(%s)", (self.proposal_ids,))
            if self.selection_ids:
                conn.execute("DELETE FROM quote_selection_decisions WHERE selection_id=ANY(%s)", (self.selection_ids,))
                conn.execute("DELETE FROM quote_selections WHERE selection_id=ANY(%s)", (self.selection_ids,))
            if self.run_ids:
                conn.execute("DELETE FROM quote_comparison_inputs WHERE comparison_run_id=ANY(%s)", (self.run_ids,))
                conn.execute("DELETE FROM quote_comparison_runs WHERE comparison_run_id=ANY(%s)", (self.run_ids,))
            if self.quote_ids:
                conn.execute("DELETE FROM quote_validation_results WHERE quote_id=ANY(%s)", (self.quote_ids,))
                conn.execute("DELETE FROM quote_line_items WHERE quote_id=ANY(%s)", (self.quote_ids,))
                conn.execute("DELETE FROM quotes WHERE quote_id=ANY(%s)", (self.quote_ids,))
            if self.response_ids:
                conn.execute("DELETE FROM vendor_responses WHERE id=ANY(%s)", (self.response_ids,))
            conn.execute("DELETE FROM approvals WHERE opp_id=%s", (self.opp_id,))
            conn.execute("DELETE FROM deal_registrations WHERE opp_id=%s", (self.opp_id,))
            if self.rfq_refs:
                conn.execute("DELETE FROM rfqs WHERE rfq_ref=ANY(%s)", (self.rfq_refs,))
            if self.vendor_ids:
                conn.execute("DELETE FROM vendors WHERE vendor_id=ANY(%s)", (self.vendor_ids,))
            conn.execute("DELETE FROM opportunities WHERE opp_id=%s", (self.opp_id,))
            conn.commit()

    def _seed_quote(self, vendor_no, total, *, deal_reg_capable):
        rfq_ref = f"P122-RFQ-{vendor_no}-{self.suffix}"
        self.rfq_refs.append(rfq_ref)
        subtotal = str(total)
        vat = str(round(total * 0.05, 2))
        grand_total = str(round(total * 1.05, 2))
        with self.psycopg.connect(os.environ["P122_TEST_PG_DSN"]) as conn:
            vendor_id = conn.execute(
                "INSERT INTO vendors (vendor_name,tier,tech_domains,vendor_authorised,deal_reg_capable) "
                "VALUES (%s,'OEM','{Testing}',true,%s) RETURNING vendor_id",
                (f"P122 Vendor {vendor_no} {self.suffix}", deal_reg_capable),
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
                "VALUES (%s,'QUOTE','p122.pdf','application/pdf','/tmp/p122.pdf',%s,100,'PARSED') RETURNING id",
                (rfq_ref, f"sha-{vendor_no}-{self.suffix}"),
            ).fetchone()[0]
            self.response_ids.append(response_id)
            quote_id = conn.execute(
                "INSERT INTO quotes "
                "(quote_group_id,opp_id,vendor_id,response_id,version_no,is_current,currency,"
                "currency_detected,status,builder_result,validation_status) "
                "VALUES (%s,%s,%s,%s,1,true,'AED',true,'PARSED','{}','VALIDATED') RETURNING quote_id",
                (f"group-{vendor_no}-{self.suffix}", self.opp_id, vendor_id, response_id),
            ).fetchone()[0]
            self.quote_ids.append(quote_id)
            conn.execute(
                "INSERT INTO quote_line_items "
                "(quote_id,line_no,part_number,description,quantity,unit_price,line_total,raw_item) "
                "VALUES (%s,1,%s,'Firewall',1,%s,%s,'{}')",
                (quote_id, f"SKU-{vendor_no}", subtotal, subtotal),
            )
            conn.execute(
                "INSERT INTO quote_validation_results "
                "(quote_id,engine_version,status,currency,policy_snapshot,claims_snapshot,"
                "computed_subtotal,computed_vat,computed_total,issues,validated_by) "
                "VALUES (%s,'p122-test','VALIDATED','AED','{}',%s,%s,%s,%s,'[]','p122')",
                (
                    quote_id,
                    '{"validity_terms":"30 days","payment_terms":"30 days","delivery_terms":"2 weeks"}',
                    subtotal,
                    vat,
                    grand_total,
                ),
            )
            if deal_reg_capable:
                conn.execute(
                    "INSERT INTO deal_registrations (opp_id,vendor_id,status,reg_reference) "
                    "VALUES (%s,%s,'APPROVED','DR-P122')",
                    (self.opp_id, vendor_id),
                )
            conn.commit()
        return {"quote_id": quote_id, "vendor_id": vendor_id}

    def _seed_selection_and_approval(self):
        first = self._seed_quote(1, 10000, deal_reg_capable=True)
        second = self._seed_quote(2, 12000, deal_reg_capable=False)
        repository = self.quote_comparison.QuoteComparisonRepository(os.environ["P122_TEST_PG_DSN"])
        run = repository.create_comparison(
            opp_id=self.opp_id,
            quote_ids=[first["quote_id"], second["quote_id"]],
            exchange_rate_ids={},
            actor="p122.user",
        )
        self.run_ids.append(run["comparison_run_id"])
        selected = repository.select_quote(
            comparison_run_id=run["comparison_run_id"],
            quote_id=first["quote_id"],
            actor="p122.approver",
            reason="Best approved quote",
        )
        self.selection_ids.append(selected["selection_id"])
        with self.psycopg.connect(os.environ["P122_TEST_PG_DSN"]) as conn:
            conn.execute(
                "INSERT INTO approvals "
                "(opp_id,kind,amount_aed,routed_to_role,rule_id,status,decided_by,decided_at) "
                "VALUES (%s,'PROPOSAL_VALUE',10500,'FINAL_VERIFIER','AM-R1','APPROVED','finance',now())",
                (self.opp_id,),
            )
            conn.commit()

    def _completed_proposal(self):
        self._seed_selection_and_approval()
        repository = self.proposals.ProposalRepository(os.environ["P122_TEST_PG_DSN"])
        assembled = repository.assemble(
            opp_id=self.opp_id,
            proposal_type="CP",
            template_version="cp-release-v1",
            actor="p122.presales",
        )
        self.proposal_ids.append(assembled["proposal_id"])
        self.version_ids.append(assembled["proposal_version_id"])
        adapter = FakeBuilderAdapter()
        submitted = repository.submit_build(
            proposal_id=assembled["proposal_id"],
            adapter=adapter,
            actor="p122.presales",
        )
        self.job_ids.append(submitted["build_job_id"])
        repository.refresh_build(
            build_job_id=submitted["build_job_id"],
            adapter=adapter,
            actor="p122.presales",
        )
        return repository, assembled, submitted

    def test_release_package_requires_final_artifacts_and_records_submission_audit(self):
        repository, assembled, submitted = self._completed_proposal()
        package = repository.prepare_release_package(
            proposal_id=assembled["proposal_id"],
            build_job_id=submitted["build_job_id"],
            reviewed_by="sales.director",
            actor="p122.reviewer",
            review_comment="Final package approved for customer submission",
        )
        self.release_ids.append(package["release_package_id"])
        self.assertEqual(package["status"], "READY_FOR_SUBMISSION")
        self.assertEqual([item["kind"] for item in package["artifacts"]], ["docx", "pdf"])
        repeated = repository.prepare_release_package(
            proposal_id=assembled["proposal_id"],
            build_job_id=submitted["build_job_id"],
            reviewed_by="sales.director",
            actor="p122.reviewer",
            review_comment="Final package approved for customer submission",
        )
        self.assertTrue(repeated["existing"])
        submission = repository.record_submission(
            release_package_id=package["release_package_id"],
            method="MANUAL_EMAIL",
            recipient="customer@example.invalid",
            evidence_ref="evidence://mailbox/sent/123",
            evidence_sha256="c" * 64,
            submitted_by="raghu",
            actor="p122.user",
            notes="Submitted by human through Outlook",
        )
        self.assertFalse(submission["existing"])
        repeated_submission = repository.record_submission(
            release_package_id=package["release_package_id"],
            method="MANUAL_EMAIL",
            recipient="customer@example.invalid",
            evidence_ref="evidence://mailbox/sent/123",
            evidence_sha256="c" * 64,
            submitted_by="raghu",
            actor="p122.user",
        )
        self.assertTrue(repeated_submission["existing"])
        fetched = repository.release_package(package["release_package_id"])
        self.assertEqual(fetched["status"], "SUBMITTED")
        self.assertEqual(fetched["submission"]["evidence_sha256"], "c" * 64)
        with self.psycopg.connect(os.environ["P122_TEST_PG_DSN"]) as conn:
            opp_status = conn.execute(
                "SELECT status FROM opportunities WHERE opp_id=%s",
                (self.opp_id,),
            ).fetchone()[0]
            actions = [
                row[0]
                for row in conn.execute(
                    "SELECT action FROM audit_log WHERE opp_id=%s AND component='proposal_release' ORDER BY seq",
                    (self.opp_id,),
                ).fetchall()
            ]
        self.assertEqual(opp_status, "SUBMITTED")
        self.assertEqual(actions, ["proposal_release_package_ready", "proposal_submission_recorded"])

    def test_release_blocks_without_pdf_artifact_or_validation_pass(self):
        repository, assembled, submitted = self._completed_proposal()
        with self.psycopg.connect(os.environ["P122_TEST_PG_DSN"]) as conn:
            conn.execute(
                "DELETE FROM proposal_artifacts WHERE build_job_id=%s AND artifact_kind='pdf'",
                (submitted["build_job_id"],),
            )
            conn.commit()
        with self.assertRaisesRegex(PermissionError, "DOCX and PDF"):
            repository.prepare_release_package(
                proposal_id=assembled["proposal_id"],
                reviewed_by="sales.director",
                actor="p122.reviewer",
            )


if __name__ == "__main__":
    unittest.main()
