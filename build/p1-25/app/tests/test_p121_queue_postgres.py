import os
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
import uuid


@unittest.skipUnless(
    os.environ.get("P121_TEST_PG_DSN"),
    "set P121_TEST_PG_DSN to a disposable PostgreSQL Orchestrator test database",
)
class DocumentRenderQueuePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PG_DSN"] = os.environ["P121_TEST_PG_DSN"]
        import approvals
        import db
        import document_render_queue
        import followup
        import proposals
        import psycopg
        import quote_comparison
        import quotes
        import vendors

        cls.psycopg = psycopg
        cls.queue_module = document_render_queue
        db.init_schema()
        with psycopg.connect(os.environ["P121_TEST_PG_DSN"]) as conn:
            if conn.execute("SELECT to_regclass('audit_log')").fetchone()[0] is None:
                raise unittest.SkipTest("test database must contain the P1-02 audit_log schema")
            vendors.init_vendors(conn)
            followup.init_followups(conn)
            approvals.init_approvals(conn)
            quotes.init_quotes(conn)
        quote_comparison.init_quote_comparison(os.environ["P121_TEST_PG_DSN"])
        proposals.init_proposals(os.environ["P121_TEST_PG_DSN"])
        document_render_queue.init_document_render_queue(os.environ["P121_TEST_PG_DSN"])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.artifact_root = Path(self.temp_dir.name).resolve()
        suffix = uuid.uuid4().hex[:12]
        self.opp_id = f"P121-OPP-{suffix}"
        self.ids = {}
        with self.psycopg.connect(os.environ["P121_TEST_PG_DSN"]) as conn:
            conn.execute(
                "INSERT INTO opportunities (opp_id,status,raw_text,raw_sha256) "
                "VALUES (%s,'READY','p121 queue','p121-test')",
                (self.opp_id,),
            )
            vendor_id = conn.execute(
                "INSERT INTO vendors (vendor_name,tier,tech_domains,vendor_authorised) "
                "VALUES (%s,'OEM','{Testing}',true) RETURNING vendor_id",
                (f"P121 Vendor {suffix}",),
            ).fetchone()[0]
            rfq_ref = f"P121-RFQ-{suffix}"
            conn.execute(
                "INSERT INTO rfqs (rfq_ref,opp_id,vendor_id,status,idempotency_key) "
                "VALUES (%s,%s,%s,'SENT',%s)",
                (rfq_ref, self.opp_id, vendor_id, rfq_ref),
            )
            response_id = conn.execute(
                "INSERT INTO vendor_responses (rfq_ref,response_type,raw_text,parse_status) "
                "VALUES (%s,'QUOTE','p121','PARSED') RETURNING id",
                (rfq_ref,),
            ).fetchone()[0]
            quote_id = conn.execute(
                "INSERT INTO quotes "
                "(quote_group_id,opp_id,vendor_id,response_id,version_no,is_current,currency,"
                "status,builder_result,validation_status) "
                "VALUES (%s,%s,%s,%s,1,true,'AED','PARSED','{}','VALIDATED') RETURNING quote_id",
                (f"p121-group-{suffix}", self.opp_id, vendor_id, response_id),
            ).fetchone()[0]
            comparison_id = conn.execute(
                "INSERT INTO quote_comparison_runs "
                "(opp_id,input_hash,result_hash,result_json,created_by) "
                "VALUES (%s,%s,%s,'{}','p121') RETURNING comparison_run_id",
                (self.opp_id, f"input-{suffix}", f"result-{suffix}"),
            ).fetchone()[0]
            selection_id = conn.execute(
                "INSERT INTO quote_selections "
                "(comparison_run_id,opp_id,quote_id,quote_version_no,commercial_snapshot,"
                "snapshot_sha256,deal_reg_status,proposal_eligible,status,selected_by,selection_reason) "
                "VALUES (%s,%s,%s,1,'{}',%s,'NOT_REQUIRED',true,'ACTIVE','p121','test') "
                "RETURNING selection_id",
                (comparison_id, self.opp_id, quote_id, "s" * 64),
            ).fetchone()[0]
            proposal_id = conn.execute(
                "INSERT INTO proposals (opp_id,proposal_type,selection_id,status,created_by) "
                "VALUES (%s,'CP',%s,'QUARANTINED','p121') RETURNING proposal_id",
                (self.opp_id, selection_id),
            ).fetchone()[0]
            version_id = conn.execute(
                "INSERT INTO proposal_versions "
                "(proposal_id,version_no,template_version,payload_json,payload_sha256,status,frozen_by) "
                "VALUES (%s,1,'cp-test','{}',%s,'FROZEN','p121') RETURNING proposal_version_id",
                (proposal_id, "p" * 64),
            ).fetchone()[0]
            conn.commit()
        self.ids.update(
            vendor_id=vendor_id,
            rfq_ref=rfq_ref,
            response_id=response_id,
            quote_id=quote_id,
            comparison_id=comparison_id,
            selection_id=selection_id,
            proposal_id=proposal_id,
            version_id=version_id,
        )

    def _build(self, number: int, state: str = "QUARANTINED") -> tuple[int, int, str]:
        digest = ("a" if number == 1 else "b") * 64
        with self.psycopg.connect(os.environ["P121_TEST_PG_DSN"]) as conn:
            build_id = conn.execute(
                "INSERT INTO document_build_jobs "
                "(proposal_version_id,request_hash,builder_job_id,state,attempts,completed_at) "
                "VALUES (%s,%s,%s,%s,1,now()) RETURNING build_job_id",
                (
                    self.ids["version_id"],
                    f"request-{number}-{uuid.uuid4().hex}",
                    f"builder-{number}",
                    state,
                ),
            ).fetchone()[0]
            artifact_id = conn.execute(
                "INSERT INTO proposal_artifacts "
                "(build_job_id,artifact_kind,artifact_ref,artifact_sha256,metadata_json) "
                "VALUES (%s,'docx',%s,%s,'{}') RETURNING artifact_id",
                (build_id, f"file:///controlled/builder-{number}.docx", digest),
            ).fetchone()[0]
            conn.commit()
        return build_id, artifact_id, digest

    @staticmethod
    def _clearance(digest: str) -> dict:
        return {
            "status": "CLEARED",
            "artifact_sha256": digest,
            "scanner": "p121-test-policy",
            "scanned_at": "2026-08-19T13:00:00+04:00",
        }

    def tearDown(self):
        with self.psycopg.connect(os.environ["P121_TEST_PG_DSN"]) as conn:
            conn.execute(
                "DELETE FROM document_render_artifacts WHERE render_job_id IN "
                "(SELECT render_job_id FROM document_render_jobs WHERE build_job_id IN "
                "(SELECT build_job_id FROM document_build_jobs WHERE proposal_version_id=%s))",
                (self.ids["version_id"],),
            )
            conn.execute(
                "DELETE FROM document_render_jobs WHERE build_job_id IN "
                "(SELECT build_job_id FROM document_build_jobs WHERE proposal_version_id=%s)",
                (self.ids["version_id"],),
            )
            conn.execute(
                "DELETE FROM proposal_artifacts WHERE build_job_id IN "
                "(SELECT build_job_id FROM document_build_jobs WHERE proposal_version_id=%s)",
                (self.ids["version_id"],),
            )
            conn.execute("DELETE FROM document_build_jobs WHERE proposal_version_id=%s", (self.ids["version_id"],))
            conn.execute("DELETE FROM proposal_versions WHERE proposal_version_id=%s", (self.ids["version_id"],))
            conn.execute("DELETE FROM proposals WHERE proposal_id=%s", (self.ids["proposal_id"],))
            conn.execute("DELETE FROM quote_selections WHERE selection_id=%s", (self.ids["selection_id"],))
            conn.execute("DELETE FROM quote_comparison_runs WHERE comparison_run_id=%s", (self.ids["comparison_id"],))
            conn.execute("DELETE FROM quotes WHERE quote_id=%s", (self.ids["quote_id"],))
            conn.execute("DELETE FROM vendor_responses WHERE id=%s", (self.ids["response_id"],))
            conn.execute("DELETE FROM rfqs WHERE rfq_ref=%s", (self.ids["rfq_ref"],))
            conn.execute("DELETE FROM vendors WHERE vendor_id=%s", (self.ids["vendor_id"],))
            conn.execute("DELETE FROM opportunities WHERE opp_id=%s", (self.opp_id,))
            conn.commit()
        self.temp_dir.cleanup()

    def test_idempotent_enqueue_serial_claim_heartbeat_and_completion(self):
        build_id, _, digest = self._build(1)
        queue = self.queue_module.DocumentRenderQueue(os.environ["P121_TEST_PG_DSN"])
        queued = queue.enqueue(
            build_job_id=build_id,
            security_clearance=self._clearance(digest),
            actor="p121.user",
        )
        repeated = queue.enqueue(
            build_job_id=build_id,
            security_clearance=self._clearance(digest),
            actor="p121.user",
        )
        self.assertFalse(queued["existing"])
        self.assertTrue(repeated["existing"])
        claimed = queue.claim(worker_id="worker-a", lease_seconds=60)
        self.assertEqual(claimed["render_job_id"], queued["render_job_id"])
        self.assertIsNone(queue.claim(worker_id="worker-b", lease_seconds=60))
        manifest = queue.source_manifest(render_job_id=queued["render_job_id"], worker_id="worker-a")
        self.assertEqual(manifest["source_sha256"], digest)
        started = queue.start(render_job_id=queued["render_job_id"], worker_id="worker-a", lease_seconds=60)
        self.assertEqual(started["state"], "RUNNING")
        with self.assertRaisesRegex(PermissionError, "another worker"):
            queue.heartbeat(render_job_id=queued["render_job_id"], worker_id="worker-b", lease_seconds=60)
        heartbeat = queue.heartbeat(render_job_id=queued["render_job_id"], worker_id="worker-a", lease_seconds=60)
        self.assertEqual(heartbeat["state"], "RUNNING")
        uploaded = []
        for kind, content in (("docx", b"rendered-docx"), ("pdf", b"rendered-pdf")):
            path = self.artifact_root / f"rendered.{kind}"
            path.write_bytes(content)
            uploaded.append(
                queue.record_artifact(
                    render_job_id=queued["render_job_id"],
                    worker_id="worker-a",
                    artifact_kind=kind,
                    artifact_path=path,
                    artifact_sha256=sha256(content).hexdigest(),
                    size_bytes=len(content),
                    allowed_root=self.artifact_root,
                )
            )
        self.assertEqual({item["kind"] for item in uploaded}, {"docx", "pdf"})
        completed = queue.complete(
            render_job_id=queued["render_job_id"],
            worker_id="worker-a",
            result={
                "status": "DONE",
                "artifacts": uploaded,
            },
        )
        self.assertEqual(completed["state"], "DONE")

    def test_expired_lease_is_reclaimed_and_exhausted_job_quarantines(self):
        first_build, _, first_digest = self._build(1)
        queue = self.queue_module.DocumentRenderQueue(os.environ["P121_TEST_PG_DSN"])
        first = queue.enqueue(
            build_job_id=first_build,
            security_clearance=self._clearance(first_digest),
            actor="p121.user",
        )
        queue.claim(worker_id="worker-a", lease_seconds=30)
        with self.psycopg.connect(os.environ["P121_TEST_PG_DSN"]) as conn:
            conn.execute(
                "UPDATE document_render_jobs SET lease_expires_at=now()-interval '1 second' "
                "WHERE render_job_id=%s",
                (first["render_job_id"],),
            )
            conn.commit()
        reclaimed = queue.claim(worker_id="worker-b", lease_seconds=30, max_claims=3)
        self.assertEqual(reclaimed["render_job_id"], first["render_job_id"])
        self.assertEqual(reclaimed["attempts"], 2)

        with self.psycopg.connect(os.environ["P121_TEST_PG_DSN"]) as conn:
            conn.execute(
                "UPDATE document_render_jobs SET attempts=3,lease_expires_at=now()-interval '1 second' "
                "WHERE render_job_id=%s",
                (first["render_job_id"],),
            )
            conn.commit()
        self.assertIsNone(queue.claim(worker_id="worker-c", lease_seconds=30, max_claims=3))
        self.assertEqual(queue.get(first["render_job_id"])["state"], "QUARANTINED")


if __name__ == "__main__":
    unittest.main()
