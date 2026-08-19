from io import BytesIO
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from docx import Document

from document_worker import (
    DocumentWorkerContractError,
    DocumentWorkerSupervisor,
    RenderJob,
)


def _docx(path: Path, text: str = "Builder-produced proposal") -> str:
    document = Document()
    document.add_paragraph(text)
    document.save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload(path: Path, digest: str, job_id: str = "p121-job") -> dict:
    return {
        "job_id": job_id,
        "source_ref": path.as_uri(),
        "source_sha256": digest,
        "security_clearance": {
            "status": "CLEARED",
            "artifact_sha256": digest,
            "scanner": "orchestrator-generated-artifact-policy-v1",
            "scanned_at": "2026-08-19T12:00:00+04:00",
        },
    }


class SuccessfulExecution:
    def __init__(self, tracker=None):
        self.tracker = tracker

    def run(self, manifest_path, result_path, timeout_s):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        output = Path(manifest["output_directory"])
        if self.tracker:
            with self.tracker["lock"]:
                self.tracker["active"] += 1
                self.tracker["maximum"] = max(self.tracker["maximum"], self.tracker["active"])
            time.sleep(0.04)
        docx = output / "rendered.docx"
        pdf = output / "rendered.pdf"
        docx.write_bytes(Path(manifest["source_path"]).read_bytes())
        pdf.write_bytes(b"%PDF-1.7\n% worker test\n")
        if self.tracker:
            with self.tracker["lock"]:
                self.tracker["active"] -= 1
        result = {
            "status": "DONE",
            "artifacts": [
                {"kind": "docx", "path": str(docx), "sha256": hashlib.sha256(docx.read_bytes()).hexdigest()},
                {"kind": "pdf", "path": str(pdf), "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()},
            ],
        }
        result_path.write_text(json.dumps(result), encoding="utf-8")
        return result


class FailingExecution:
    def __init__(self):
        self.calls = 0

    def run(self, manifest_path, result_path, timeout_s):
        self.calls += 1
        raise TimeoutError("synthetic Office modal hang")


class DocumentWorkerTests(unittest.TestCase):
    def test_contract_requires_controlled_hash_verified_macro_free_docx_and_clearance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "proposal.docx"
            digest = _docx(source)
            job = RenderJob.from_payload(_payload(source, digest), source_roots=[str(root)], output_root=str(root / "out"))
            self.assertEqual(job.source_sha256, digest)
            self.assertEqual(len(job.request_hash), 64)

            bad = _payload(source, digest)
            bad["security_clearance"]["status"] = "PENDING"
            with self.assertRaisesRegex(DocumentWorkerContractError, "CLEARED"):
                RenderJob.from_payload(bad, source_roots=[str(root)], output_root=str(root / "out"))
            with self.assertRaisesRegex(DocumentWorkerContractError, "absolute controlled"):
                RenderJob.from_payload(_payload(source, digest), source_roots=["relative"], output_root=str(root / "out"))
            with self.assertRaisesRegex(DocumentWorkerContractError, "output_root must be absolute"):
                RenderJob.from_payload(_payload(source, digest), source_roots=[str(root)], output_root="relative")

            outside = root.parent / f"{root.name}-outside.docx"
            try:
                outside_digest = _docx(outside)
                with self.assertRaisesRegex(DocumentWorkerContractError, "outside controlled"):
                    RenderJob.from_payload(_payload(outside, outside_digest), source_roots=[str(root)], output_root=str(root / "out"))
            finally:
                outside.unlink(missing_ok=True)

    def test_same_input_is_idempotent_and_changed_source_changes_request_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "proposal.docx"
            first_hash = _docx(source, "first")
            first = RenderJob.from_payload(_payload(source, first_hash), source_roots=[str(root)], output_root=str(root / "out"))
            repeated = RenderJob.from_payload(_payload(source, first_hash), source_roots=[str(root)], output_root=str(root / "out"))
            self.assertEqual(first.request_hash, repeated.request_hash)
            second_hash = _docx(source, "second")
            second = RenderJob.from_payload(_payload(source, second_hash), source_roots=[str(root)], output_root=str(root / "out"))
            self.assertNotEqual(first.request_hash, second.request_hash)

    def test_supervisor_verifies_docx_and_pdf_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "proposal.docx"
            digest = _docx(source)
            job = RenderJob.from_payload(_payload(source, digest), source_roots=[str(root)], output_root=str(root / "out"))
            result = DocumentWorkerSupervisor(SuccessfulExecution(), timeout_s=1).process(job)
            self.assertEqual(result["status"], "DONE")
            self.assertEqual(result["attempts"], 1)
            self.assertEqual({item["kind"] for item in result["artifacts"]}, {"docx", "pdf"})

    def test_two_concurrent_jobs_are_serialized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracker = {"lock": threading.Lock(), "active": 0, "maximum": 0}
            supervisor = DocumentWorkerSupervisor(SuccessfulExecution(tracker), timeout_s=1)
            jobs = []
            for number in (1, 2):
                source = root / f"proposal-{number}.docx"
                digest = _docx(source, str(number))
                jobs.append(RenderJob.from_payload(_payload(source, digest, f"job-{number}"), source_roots=[str(root)], output_root=str(root / "out")))
            threads = [threading.Thread(target=supervisor.process, args=(job,)) for job in jobs]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(tracker["maximum"], 1)

    def test_watchdog_failure_retries_once_then_quarantines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "proposal.docx"
            digest = _docx(source)
            job = RenderJob.from_payload(_payload(source, digest), source_roots=[str(root)], output_root=str(root / "out"))
            execution = FailingExecution()
            result = DocumentWorkerSupervisor(execution, timeout_s=0.01).process(job)
            self.assertEqual(execution.calls, 2)
            self.assertEqual(result["status"], "QUARANTINED")
            self.assertTrue((Path(result["quarantine_path"]) / "failure.json").is_file())


if __name__ == "__main__":
    unittest.main()
