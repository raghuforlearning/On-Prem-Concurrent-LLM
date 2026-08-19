from hashlib import sha256
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = APP_ROOT / "windows-document-worker" / "worker_service.py"
SPEC = importlib.util.spec_from_file_location("p121_worker_service", WORKER_PATH)
worker_service = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = worker_service
SPEC.loader.exec_module(worker_service)


class FakeResponse:
    def __init__(self, *, value=None, content=b""):
        self.value = value
        self.content = content

    def raise_for_status(self):
        return None

    def json(self):
        return self.value


class FakeClient:
    def __init__(self, *, source=b"source"):
        self.source = source
        self.posts = []

    def get(self, path, params=None):
        if path.endswith("source-manifest"):
            return FakeResponse(
                value={
                    "job_id": "p121-1",
                    "request_hash": "r" * 64,
                    "source_sha256": sha256(self.source).hexdigest(),
                    "security_clearance": {
                        "status": "CLEARED",
                        "artifact_sha256": sha256(self.source).hexdigest(),
                        "scanner": "test",
                        "scanned_at": "2026-08-19T12:00:00+04:00",
                    },
                }
            )
        return FakeResponse(content=self.source)

    def post(self, path, json=None, data=None, files=None):
        self.posts.append({"path": path, "json": json, "data": data, "files": files})
        if path.endswith("/claim"):
            return FakeResponse(value=None)
        if path.endswith("/artifacts"):
            return FakeResponse(
                value={
                    "kind": data["artifact_kind"],
                    "sha256": data["artifact_sha256"],
                    "ref": f"file:///controlled/rendered.{data['artifact_kind']}",
                }
            )
        return FakeResponse(value={"state": "DONE"})


class WindowsWorkerServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name).resolve()
        self.settings = worker_service.WorkerSettings(
            orchestrator_url="http://orchestrator.internal:8080",
            token="test-token",
            worker_id="worker-test",
            inbox_root=root / "inbox",
            output_root=root / "output",
            render_script=WORKER_PATH.with_name("Invoke-DocumentRender.ps1"),
            lease_seconds=60,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_environment_requires_absolute_controlled_paths(self):
        environment = {
            "ORCHESTRATOR_URL": "http://orchestrator.internal:8080",
            "DOCUMENT_WORKER_TOKEN": "token",
            "DOCUMENT_WORKER_INBOX_ROOT": "relative-inbox",
            "DOCUMENT_WORKER_OUTPUT_ROOT": str(self.settings.output_root),
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "absolute"):
                worker_service.WorkerSettings.from_environment()

    def test_download_verifies_sha_and_writes_only_to_inbox(self):
        client = FakeClient(source=b"hash-cleared-builder-docx")
        service = worker_service.WindowsDocumentWorkerService(self.settings, client=client)
        source, manifest = service._download_source(7)
        self.assertEqual(source.read_bytes(), b"hash-cleared-builder-docx")
        self.assertTrue(source.is_relative_to(self.settings.inbox_root))
        self.assertEqual(manifest["source_sha256"], sha256(source.read_bytes()).hexdigest())

    def test_download_rejects_hash_mismatch(self):
        client = FakeClient(source=b"expected")
        original_get = client.get

        def mismatched(path, params=None):
            response = original_get(path, params)
            if path.endswith("/source"):
                response.content = b"changed"
            return response

        client.get = mismatched
        service = worker_service.WindowsDocumentWorkerService(self.settings, client=client)
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            service._download_source(8)

    def test_done_artifacts_are_returned_to_orchestrator(self):
        client = FakeClient()
        service = worker_service.WindowsDocumentWorkerService(self.settings, client=client)
        self.settings.output_root.mkdir(parents=True)
        items = []
        for kind, content in (("docx", b"docx-result"), ("pdf", b"pdf-result")):
            path = self.settings.output_root / f"rendered.{kind}"
            path.write_bytes(content)
            items.append({"kind": kind, "path": str(path), "sha256": sha256(content).hexdigest()})
        result = service._upload_artifacts(9, {"status": "DONE", "artifacts": items})
        self.assertEqual({item["kind"] for item in result["artifacts"]}, {"docx", "pdf"})
        uploads = [item for item in client.posts if item["path"].endswith("/artifacts")]
        self.assertEqual(len(uploads), 2)

    def test_once_with_empty_queue_returns_without_rendering(self):
        client = FakeClient()
        service = worker_service.WindowsDocumentWorkerService(self.settings, client=client)
        self.assertIsNone(service.process_one())


if __name__ == "__main__":
    unittest.main()
