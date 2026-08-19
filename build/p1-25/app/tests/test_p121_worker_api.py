from pathlib import Path
import unittest


APP_ROOT = Path(__file__).resolve().parents[1]


class DocumentWorkerApiSurfaceTests(unittest.TestCase):
    def test_durable_queue_and_worker_only_api_are_exposed(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")
        for route in (
            '@app.post("/proposal-build-jobs/{build_job_id}/render")',
            '@app.post("/internal/document-worker/jobs/claim")',
            '@app.post("/internal/document-worker/jobs/{render_job_id}/start")',
            '@app.post("/internal/document-worker/jobs/{render_job_id}/heartbeat")',
            '@app.get("/internal/document-worker/jobs/{render_job_id}/source")',
            '@app.get("/internal/document-worker/jobs/{render_job_id}/source-manifest")',
            '@app.post("/internal/document-worker/jobs/{render_job_id}/artifacts")',
            '@app.post("/internal/document-worker/jobs/{render_job_id}/complete")',
        ):
            self.assertIn(route, source)
        self.assertIn("DOCUMENT_WORKER_TOKEN", source)
        self.assertIn("hmac.compare_digest", source)

    def test_worker_boundary_has_no_cloud_or_proposal_generation_logic(self):
        worker_source = (APP_ROOT / "document_worker.py").read_text(encoding="utf-8").casefold()
        queue_source = (APP_ROOT / "document_render_queue.py").read_text(encoding="utf-8").casefold()
        service_source = (
            APP_ROOT / "windows-document-worker" / "worker_service.py"
        ).read_text(encoding="utf-8").casefold()
        combined = worker_source + queue_source + service_source
        for forbidden in (
            "openai",
            "anthropic",
            "azure",
            "generate-tp",
            "generate-cp",
            "margin calculation",
        ):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
