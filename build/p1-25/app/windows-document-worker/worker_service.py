"""P1-21 Windows worker loop for the Orchestrator's durable render queue.

This process downloads only a leased, hash-cleared Builder DOCX, invokes the
isolated Word supervisor, renews its lease while Word runs, and reports a
terminal result. It contains no proposal generation or template logic.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import socket
import sys
import threading
import time
from typing import Any

import httpx

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from document_worker import DocumentWorkerSupervisor, PowerShellWordExecution, RenderJob


MAX_SOURCE_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class WorkerSettings:
    orchestrator_url: str
    token: str
    worker_id: str
    inbox_root: Path
    output_root: Path
    render_script: Path
    lease_seconds: int = 120
    render_timeout_s: float = 600.0
    poll_seconds: float = 2.0
    ca_bundle: str | None = None

    @classmethod
    def from_environment(cls) -> "WorkerSettings":
        url = os.environ.get("ORCHESTRATOR_URL", "").strip().rstrip("/")
        token = os.environ.get("DOCUMENT_WORKER_TOKEN", "").strip()
        if not url or not token:
            raise ValueError("ORCHESTRATOR_URL and DOCUMENT_WORKER_TOKEN are required")
        if not url.startswith(("http://", "https://")):
            raise ValueError("ORCHESTRATOR_URL must be an internal HTTP(S) URL")
        inbox = Path(os.environ.get("DOCUMENT_WORKER_INBOX_ROOT", "")).expanduser()
        output = Path(os.environ.get("DOCUMENT_WORKER_OUTPUT_ROOT", "")).expanduser()
        script = Path(
            os.environ.get(
                "DOCUMENT_WORKER_RENDER_SCRIPT",
                str(Path(__file__).with_name("Invoke-DocumentRender.ps1")),
            )
        ).expanduser()
        if not inbox.is_absolute() or not output.is_absolute() or not script.is_absolute():
            raise ValueError("worker inbox, output and render-script paths must be absolute")
        lease = int(os.environ.get("DOCUMENT_WORKER_LEASE_SECONDS", "120"))
        timeout = float(os.environ.get("DOCUMENT_WORKER_RENDER_TIMEOUT_S", "600"))
        poll = float(os.environ.get("DOCUMENT_WORKER_POLL_SECONDS", "2"))
        if not 30 <= lease <= 900 or timeout <= 0 or poll <= 0:
            raise ValueError("worker lease, timeout or poll configuration is invalid")
        return cls(
            orchestrator_url=url,
            token=token,
            worker_id=os.environ.get("DOCUMENT_WORKER_ID", socket.gethostname()).strip(),
            inbox_root=inbox.resolve(),
            output_root=output.resolve(),
            render_script=script.resolve(),
            lease_seconds=lease,
            render_timeout_s=timeout,
            poll_seconds=poll,
            ca_bundle=os.environ.get("DOCUMENT_WORKER_CA_BUNDLE") or None,
        )


class WindowsDocumentWorkerService:
    def __init__(self, settings: WorkerSettings, client: Any = None):
        self.settings = settings
        if not settings.worker_id:
            raise ValueError("DOCUMENT_WORKER_ID is required")
        if client is None:
            verify: bool | str = settings.ca_bundle if settings.ca_bundle else True
            client = httpx.Client(
                base_url=settings.orchestrator_url,
                headers={"X-Document-Worker-Token": settings.token},
                timeout=30.0,
                verify=verify,
            )
        self.client = client

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        response = self.client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    def _get(self, path: str, **params: Any) -> Any:
        response = self.client.get(path, params=params)
        response.raise_for_status()
        return response

    def claim(self) -> dict[str, Any] | None:
        value = self._post(
            "/internal/document-worker/jobs/claim",
            {
                "worker_id": self.settings.worker_id,
                "lease_seconds": self.settings.lease_seconds,
                "max_claims": 3,
            },
        )
        return value if isinstance(value, dict) else None

    def _download_source(self, render_job_id: int) -> tuple[Path, dict[str, Any]]:
        manifest_response = self._get(
            f"/internal/document-worker/jobs/{render_job_id}/source-manifest",
            worker_id=self.settings.worker_id,
        )
        manifest = manifest_response.json()
        response = self._get(
            f"/internal/document-worker/jobs/{render_job_id}/source",
            worker_id=self.settings.worker_id,
        )
        content = response.content
        if not content or len(content) > MAX_SOURCE_BYTES:
            raise ValueError("render source must be between 1 byte and 50 MiB")
        digest = sha256(content).hexdigest()
        if digest != str(manifest.get("source_sha256") or "").lower():
            raise ValueError("downloaded render source SHA-256 mismatch")
        inbox = (self.settings.inbox_root / str(render_job_id)).resolve()
        if not (inbox == self.settings.inbox_root or inbox.is_relative_to(self.settings.inbox_root)):
            raise ValueError("computed worker inbox escaped its controlled root")
        inbox.mkdir(parents=True, exist_ok=True)
        temporary = inbox / "source.docx.tmp"
        source = inbox / "source.docx"
        temporary.write_bytes(content)
        temporary.replace(source)
        return source, manifest

    def _heartbeat_loop(self, render_job_id: int, stop: threading.Event, errors: list[str]) -> None:
        interval = max(10.0, self.settings.lease_seconds / 3)
        while not stop.wait(interval):
            try:
                self._post(
                    f"/internal/document-worker/jobs/{render_job_id}/heartbeat",
                    {"worker_id": self.settings.worker_id, "lease_seconds": self.settings.lease_seconds},
                )
            except Exception as exc:
                errors.append(str(exc)[:500])
                return

    def _upload_artifacts(self, render_job_id: int, result: dict[str, Any]) -> dict[str, Any]:
        if str(result.get("status") or "").upper() != "DONE":
            return result
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, list):
            raise ValueError("DONE renderer result has no artifact list")
        uploaded: list[dict[str, Any]] = []
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip().lower()
            if kind not in {"docx", "pdf"}:
                continue
            path = Path(str(item.get("path") or "")).resolve()
            digest = str(item.get("sha256") or "").strip().lower()
            if not path.is_file() or len(digest) != 64:
                raise ValueError(f"renderer {kind} artifact is missing or unhashed")
            media_type = (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                if kind == "docx"
                else "application/pdf"
            )
            with path.open("rb") as stream:
                response = self.client.post(
                    f"/internal/document-worker/jobs/{render_job_id}/artifacts",
                    data={
                        "worker_id": self.settings.worker_id,
                        "artifact_kind": kind,
                        "artifact_sha256": digest,
                    },
                    files={"file": (path.name, stream, media_type)},
                )
            response.raise_for_status()
            uploaded.append(response.json())
        if {str(item.get("kind") or "") for item in uploaded} != {"docx", "pdf"}:
            raise ValueError("worker did not return both rendered DOCX and PDF")
        return {**result, "artifacts": uploaded}

    def process_one(self) -> dict[str, Any] | None:
        claimed = self.claim()
        if not claimed:
            return None
        render_job_id = int(claimed["render_job_id"])
        try:
            source, manifest = self._download_source(render_job_id)
            self._post(
                f"/internal/document-worker/jobs/{render_job_id}/start",
                {"worker_id": self.settings.worker_id, "lease_seconds": self.settings.lease_seconds},
            )
            payload = {
                "job_id": str(manifest["job_id"]),
                "source_ref": source.as_uri(),
                "source_sha256": manifest["source_sha256"],
                "security_clearance": manifest["security_clearance"],
            }
            job = RenderJob.from_payload(
                payload,
                source_roots=[str(self.settings.inbox_root)],
                output_root=str(self.settings.output_root),
            )
            stop = threading.Event()
            heartbeat_errors: list[str] = []
            heartbeat = threading.Thread(
                target=self._heartbeat_loop,
                args=(render_job_id, stop, heartbeat_errors),
                daemon=True,
            )
            heartbeat.start()
            try:
                supervisor = DocumentWorkerSupervisor(
                    PowerShellWordExecution(self.settings.render_script),
                    timeout_s=self.settings.render_timeout_s,
                    max_attempts=2,
                )
                result = supervisor.process(job)
                result = self._upload_artifacts(render_job_id, result)
            finally:
                stop.set()
                heartbeat.join(timeout=5)
            result["queue_request_hash"] = manifest["request_hash"]
            if heartbeat_errors:
                result = {
                    "status": "QUARANTINED",
                    "error": "lease heartbeat failed",
                    "heartbeat_errors": heartbeat_errors,
                    "render_result": result,
                }
        except Exception as exc:
            result = {"status": "QUARANTINED", "error": str(exc)[:1000]}
        return self._post(
            f"/internal/document-worker/jobs/{render_job_id}/complete",
            {"worker_id": self.settings.worker_id, "result": result},
        )

    def run(self, *, once: bool = False) -> None:
        while True:
            handled = self.process_one()
            if once:
                return
            if handled is None:
                time.sleep(self.settings.poll_seconds)

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close:
            close()


def main() -> int:
    parser = argparse.ArgumentParser(description="NationLabs P1-21 Windows document worker")
    parser.add_argument("--once", action="store_true", help="claim at most one job and exit")
    args = parser.parse_args()
    service = WindowsDocumentWorkerService(WorkerSettings.from_environment())
    try:
        service.run(once=args.once)
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
