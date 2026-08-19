import os
import unittest
import uuid


class FakeBuilderAdapter:
    def __init__(self, *, fail_first=False, validation_passed=True):
        self.fail_first = fail_first
        self.validation_passed = validation_passed
        self.calls = []
        self.created = 0

    def validate_build(self, *, proposal_type, template_version, payload, payload_hash):
        self.calls.append(("validate", proposal_type, template_version, payload_hash, payload))
        if self.fail_first and self.created == 0:
            return {"valid": False, "errors": ["template missing marker"]}
        return {"valid": True, "errors": []}

    def create_build(self, *, proposal_type, template_version, payload, payload_hash):
        self.calls.append(("create", proposal_type, template_version, payload_hash, payload))
        self.created += 1
        return {"job_id": f"fake-builder-{self.created}"}

    def get_build(self, builder_job_id):
        self.calls.append(("get_build", builder_job_id))
        return {"state": "done"}

    def get_artifacts(self, builder_job_id):
        self.calls.append(("get_artifacts", builder_job_id))
        return {
            "artifacts": [
                {
                    "kind": "docx",
                    "ref": f"artifact://{builder_job_id}/cp.docx",
                    "sha256": "a" * 64,
                    "metadata": {"template_version": "cp-test-v1"},
                },
                {
                    "kind": "pdf",
                    "ref": f"artifact://{builder_job_id}/cp.pdf",
                    "sha256": "b" * 64,
                    "metadata": {"payload_hash": "recorded-by-builder"},
                },
            ],
            "validation": {
                "passed": self.validation_passed,
                "checks": [
                    {
                        "name": "golden_inline_shape_floor",
                        "passed": self.validation_passed,
                    }
                ],
            },
        }


@unittest.skipUnless(
    os.environ.get("P119_TEST_PG_DSN"),
    "set P119_TEST_PG_DSN to a disposable PostgreSQL Orchestrator test database",
)
class LivePostgresProposalHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PG_DSN"] = os.environ["P119_TEST_PG_DSN"]
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
        with psycopg.connect(os.environ["P119_TEST_PG_DSN"]) as conn:
            if conn.execute("SELECT to_regclass('audit_log')").fetchone()[0] is None:
                raise unittest.SkipTest("test database must contain the P1-02 audit_log schema")
            vendors.init_vendors(conn)
            followup.init_followups(conn)
            approvals.init_approvals(conn)
            quotes.init_quotes(conn)
        quote_comparison.init_quote_comparison(os.environ["P119_TEST_PG_DSN"])
        proposals.init_proposals(os.environ["P119_TEST_PG_DSN"])

    def setUp(self):
        self.suffix = uuid.uuid4().hex[:12]
        self.opp_id = f"P119-OPP-{self.suffix}"
        self.vendor_ids = []
        self.rfq_refs = []
        self.response_ids = []
        self.quote_ids = []
        self.run_ids = []
        self.selection_ids = []
        self.proposal_ids = []
        self.version_ids = []
        self.job_ids = []
        with self.psycopg.connect(os.environ["P119_TEST_PG_DSN"]) as conn:
            conn.execute(
                "INSERT INTO opportunities (opp_id,status,raw_text,raw_sha256) "
                "VALUES (%s,'READY','p119 proposal','p119-test')",
                (self.opp_id,),
            )
            conn.commit()

    def tearDown(self):
        with self.psycopg.connect(os.environ["P119_TEST_PG_DSN"]) as conn:
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
        rfq_ref = f"P119-RFQ-{vendor_no}-{self.suffix}"
        self.rfq_refs.append(rfq_ref)
        subtotal = str(total)
        vat = str(round(total * 0.05, 2))
        grand_total = str(round(total * 1.05, 2))
        with self.psycopg.connect(os.environ["P119_TEST_PG_DSN"]) as conn:
            vendor_id = conn.execute(
                "INSERT INTO vendors (vendor_name,tier,tech_domains,vendor_authorised,deal_reg_capable) "
                "VALUES (%s,'OEM','{Testing}',true,%s) RETURNING vendor_id",
                (f"P119 Vendor {vendor_no} {self.suffix}", deal_reg_capable),
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
                "VALUES (%s,'QUOTE','p119.pdf','application/pdf','/tmp/p119.pdf',%s,100,'PARSED') RETURNING id",
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
            validation_id = conn.execute(
                "INSERT INTO quote_validation_results "
                "(quote_id,engine_version,status,currency,policy_snapshot,claims_snapshot,"
                "computed_subtotal,computed_vat,computed_total,issues,validated_by) "
                "VALUES (%s,'p119-test','VALIDATED','AED','{}',%s,%s,%s,%s,'[]','p119') "
                "RETURNING validation_id",
                (
                    quote_id,
                    '{"validity_terms":"30 days","payment_terms":"30 days","delivery_terms":"2 weeks"}',
                    subtotal,
                    vat,
                    grand_total,
                ),
            ).fetchone()[0]
            if deal_reg_capable:
                conn.execute(
                    "INSERT INTO deal_registrations (opp_id,vendor_id,status,reg_reference) "
                    "VALUES (%s,%s,'APPROVED','DR-P119')",
                    (self.opp_id, vendor_id),
                )
            conn.commit()
        return {"quote_id": quote_id, "vendor_id": vendor_id, "validation_id": validation_id}

    def _seed_selection_and_approval(self):
        first = self._seed_quote(1, 10000, deal_reg_capable=True)
        second = self._seed_quote(2, 12000, deal_reg_capable=False)
        repository = self.quote_comparison.QuoteComparisonRepository(os.environ["P119_TEST_PG_DSN"])
        run = repository.create_comparison(
            opp_id=self.opp_id,
            quote_ids=[first["quote_id"], second["quote_id"]],
            exchange_rate_ids={},
            actor="p119.user",
        )
        self.run_ids.append(run["comparison_run_id"])
        selected = repository.select_quote(
            comparison_run_id=run["comparison_run_id"],
            quote_id=first["quote_id"],
            actor="p119.approver",
            reason="Best approved quote",
        )
        self.selection_ids.append(selected["selection_id"])
        with self.psycopg.connect(os.environ["P119_TEST_PG_DSN"]) as conn:
            approval_id = conn.execute(
                "INSERT INTO approvals "
                "(opp_id,kind,amount_aed,routed_to_role,rule_id,status,decided_by,decided_at) "
                "VALUES (%s,'PROPOSAL_VALUE',10500,'FINAL_VERIFIER','AM-R1','APPROVED','finance',now()) "
                "RETURNING id",
                (self.opp_id,),
            ).fetchone()[0]
            conn.commit()
        return first, selected, approval_id

    def test_approved_cp_handoff_freezes_payload_records_job_artifacts_and_audit(self):
        self._seed_selection_and_approval()
        repository = self.proposals.ProposalRepository(os.environ["P119_TEST_PG_DSN"])
        assembled = repository.assemble(
            opp_id=self.opp_id,
            proposal_type="cp",
            template_version="cp-test-v1",
            actor="p119.presales",
            context={"customer_name": "ACME"},
        )
        self.proposal_ids.append(assembled["proposal_id"])
        self.version_ids.append(assembled["proposal_version_id"])
        self.assertEqual(assembled["proposal_type"], "CP")
        self.assertEqual(assembled["payload"]["commercial"]["aed_total"], "10500.00")
        self.assertEqual(assembled["payload_sha256"], self.proposals.payload_sha256(assembled["payload"]))
        repeated = repository.assemble(
            opp_id=self.opp_id,
            proposal_type="CP",
            template_version="cp-test-v1",
            actor="p119.presales",
            context={"customer_name": "ACME"},
        )
        self.assertTrue(repeated["existing"])
        adapter = FakeBuilderAdapter()
        submitted = repository.submit_build(
            proposal_id=assembled["proposal_id"],
            adapter=adapter,
            actor="p119.presales",
        )
        self.job_ids.append(submitted["build_job_id"])
        self.assertEqual(submitted["state"], "SUBMITTED")
        self.assertEqual(adapter.calls[0][3], assembled["payload_sha256"])
        self.assertEqual(adapter.calls[1][4]["commercial"]["aed_total"], "10500.00")
        refreshed = repository.refresh_build(
            build_job_id=submitted["build_job_id"],
            adapter=adapter,
            actor="p119.presales",
        )
        self.assertEqual(refreshed["state"], "DONE")
        self.assertEqual(refreshed["artifacts_saved"], 2)
        artifacts = repository.artifacts(assembled["proposal_id"])
        self.assertEqual([item["kind"] for item in artifacts["artifacts"]], ["docx", "pdf"])
        self.assertEqual(artifacts["status"], "PENDING_HUMAN_REVIEW")
        with self.psycopg.connect(os.environ["P119_TEST_PG_DSN"]) as conn:
            actions = [
                row[0]
                for row in conn.execute(
                    "SELECT action FROM audit_log WHERE opp_id=%s AND component='proposal' ORDER BY seq",
                    (self.opp_id,),
                ).fetchall()
            ]
        self.assertIn("proposal_payload_frozen", actions)
        self.assertIn("proposal_build_submitted", actions)
        self.assertIn("proposal_build_refreshed", actions)

    def test_missing_approval_blocks_assembly_and_failed_submission_can_retry(self):
        self._seed_selection_and_approval()
        with self.psycopg.connect(os.environ["P119_TEST_PG_DSN"]) as conn:
            conn.execute("DELETE FROM approvals WHERE opp_id=%s", (self.opp_id,))
            conn.commit()
        repository = self.proposals.ProposalRepository(os.environ["P119_TEST_PG_DSN"])
        with self.assertRaisesRegex(PermissionError, "PROPOSAL_VALUE"):
            repository.assemble(
                opp_id=self.opp_id,
                proposal_type="CP",
                template_version="cp-test-v1",
                actor="p119.presales",
            )
        with self.psycopg.connect(os.environ["P119_TEST_PG_DSN"]) as conn:
            conn.execute(
                "INSERT INTO approvals "
                "(opp_id,kind,amount_aed,routed_to_role,rule_id,status,decided_by,decided_at) "
                "VALUES (%s,'PROPOSAL_VALUE',10500,'FINAL_VERIFIER','AM-R1','APPROVED','finance',now())",
                (self.opp_id,),
            )
            conn.commit()
        assembled = repository.assemble(
            opp_id=self.opp_id,
            proposal_type="CP",
            template_version="cp-test-v1",
            actor="p119.presales",
        )
        self.proposal_ids.append(assembled["proposal_id"])
        self.version_ids.append(assembled["proposal_version_id"])
        failing = FakeBuilderAdapter(fail_first=True)
        failed = repository.submit_build(
            proposal_id=assembled["proposal_id"],
            adapter=failing,
            actor="p119.presales",
        )
        self.job_ids.append(failed["build_job_id"])
        self.assertEqual(failed["state"], "FAILED")
        retrying = FakeBuilderAdapter()
        retried = repository.submit_build(
            proposal_id=assembled["proposal_id"],
            adapter=retrying,
            actor="p119.presales",
        )
        self.assertEqual(retried["build_job_id"], failed["build_job_id"])
        self.assertEqual(retried["state"], "SUBMITTED")
        self.assertEqual(retried["attempts"], 2)

    def test_failed_document_validation_is_persisted_and_quarantined(self):
        self._seed_selection_and_approval()
        repository = self.proposals.ProposalRepository(os.environ["P119_TEST_PG_DSN"])
        assembled = repository.assemble(
            opp_id=self.opp_id,
            proposal_type="TP",
            template_version="tp-test-v1",
            actor="p120.presales",
            context={"proposal_builder": {"synthetic": True}},
        )
        self.proposal_ids.append(assembled["proposal_id"])
        self.version_ids.append(assembled["proposal_version_id"])
        adapter = FakeBuilderAdapter(validation_passed=False)
        submitted = repository.submit_build(
            proposal_id=assembled["proposal_id"],
            adapter=adapter,
            actor="p120.presales",
        )
        self.job_ids.append(submitted["build_job_id"])
        refreshed = repository.refresh_build(
            build_job_id=submitted["build_job_id"],
            adapter=adapter,
            actor="p120.presales",
        )
        self.assertEqual(refreshed["state"], "QUARANTINED")
        self.assertEqual(refreshed["artifacts_saved"], 2)
        self.assertTrue(refreshed["validation_saved"])
        artifacts = repository.artifacts(assembled["proposal_id"])
        self.assertEqual(artifacts["status"], "QUARANTINED")
        with self.psycopg.connect(os.environ["P119_TEST_PG_DSN"]) as conn:
            passed = conn.execute(
                "SELECT passed FROM document_validation_results "
                "WHERE build_job_id=%s ORDER BY validation_result_id DESC LIMIT 1",
                (submitted["build_job_id"],),
            ).fetchone()[0]
        self.assertFalse(passed)


if __name__ == "__main__":
    unittest.main()
