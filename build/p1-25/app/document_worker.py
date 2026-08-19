"""P1-21 isolated Windows document-rendering worker boundary.

The worker is deliberately downstream of the frozen Proposal Builder.  It may
open a Builder-produced DOCX in Word, update fields, save the rendered DOCX and
export PDF.  It does not own templates, BOQ placement, commercials or proposal
content and therefore cannot be used to repair a non-conforming Builder output.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any, Protocol
from urllib.parse import unquote, urlparse
import zipfile


class DocumentWorkerContractError(ValueError):
    """A render request failed the immutable worker contract."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _local_path(reference: str) -> Path:
    parsed = urlparse(reference)
    if parsed.scheme not in ("", "file"):
        raise DocumentWorkerContractError("document worker accepts local file references only")
    raw = unquote(parsed.path) if parsed.scheme == "file" else reference
    if parsed.scheme == "file" and parsed.netloc:
        raw = f"//{parsed.netloc}{raw}"
    if len(raw) >= 3 and raw[0] == "/" and raw[2] == ":":
        raw = raw[1:]
    return Path(raw).expanduser().resolve()


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


@dataclass(frozen=True)
class RenderJob:
    job_id: str
    source_path: Path
    source_sha256: str
    output_root: Path
    request_hash: str
    clearance: dict[str, Any]

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        source_roots: list[str] | tuple[str, ...],
        output_root: str,
    ) -> "RenderJob":
        job_id = str(payload.get("job_id") or "").strip()
        reference = str(payload.get("source_ref") or "").strip()
        expected_hash = str(payload.get("source_sha256") or "").strip().lower()
        clearance = payload.get("security_clearance")
        if not job_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in job_id):
            raise DocumentWorkerContractError("job_id must contain only letters, numbers, hyphen or underscore")
        if len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
            raise DocumentWorkerContractError("source_sha256 must be a lowercase SHA-256 digest")
        if not isinstance(clearance, dict) or clearance.get("status") != "CLEARED":
            raise DocumentWorkerContractError("security clearance must be explicitly CLEARED")
        if not hmac.compare_digest(str(clearance.get("artifact_sha256") or "").lower(), expected_hash):
            raise DocumentWorkerContractError("security clearance hash does not match source_sha256")
        if not str(clearance.get("scanner") or "").strip() or not str(clearance.get("scanned_at") or "").strip():
            raise DocumentWorkerContractError("security clearance requires scanner and scanned_at provenance")

        raw_roots = tuple(Path(item).expanduser() for item in source_roots)
        if not raw_roots or any(not item.is_absolute() for item in raw_roots):
            raise DocumentWorkerContractError("at least one absolute controlled source root is required")
        roots = tuple(item.resolve() for item in raw_roots)
        source = _local_path(reference)
        if not _inside(source, roots):
            raise DocumentWorkerContractError("source document is outside controlled artifact roots")
        if not source.is_file() or source.suffix.casefold() != ".docx":
            raise DocumentWorkerContractError("source must be an existing DOCX")
        actual_hash = _sha256_file(source)
        if not hmac.compare_digest(actual_hash, expected_hash):
            raise DocumentWorkerContractError("source document SHA-256 verification failed")
        try:
            with zipfile.ZipFile(source) as archive:
                names = {name.casefold() for name in archive.namelist()}
        except (OSError, zipfile.BadZipFile) as exc:
            raise DocumentWorkerContractError("source is not a valid DOCX package") from exc
        if "[content_types].xml" not in names or "word/document.xml" not in names:
            raise DocumentWorkerContractError("source is not a valid Word document package")
        if any(name.endswith("vbaproject.bin") for name in names):
            raise DocumentWorkerContractError("macro-bearing documents are not accepted by the worker")

        raw_output_root = Path(output_root).expanduser()
        if not raw_output_root.is_absolute():
            raise DocumentWorkerContractError("output_root must be absolute")
        out_root = raw_output_root.resolve()
        request_body = {
            "job_id": job_id,
            "source_sha256": expected_hash,
            "renderer": "word-com-v1",
        }
        return cls(
            job_id=job_id,
            source_path=source,
            source_sha256=expected_hash,
            output_root=out_root,
            request_hash=sha256(_canonical_json(request_body).encode("utf-8")).hexdigest(),
            clearance=clearance,
        )

    def manifest(self) -> dict[str, Any]:
        job_root = (self.output_root / self.request_hash).resolve()
        if not _inside(job_root, (self.output_root,)):
            raise DocumentWorkerContractError("computed worker output escaped output_root")
        return {
            "job_id": self.job_id,
            "request_hash": self.request_hash,
            "source_path": str(self.source_path),
            "source_sha256": self.source_sha256,
            "output_directory": str(job_root),
            "security_clearance": self.clearance,
        }


class RenderExecution(Protocol):
    def run(self, manifest_path: Path, result_path: Path, timeout_s: float) -> dict[str, Any]:
        ...


class PowerShellWordExecution:
    """Launch the Windows-only renderer in an isolated hidden process."""

    def __init__(self, script_path: str | Path):
        self.script_path = Path(script_path).resolve()

    def run(self, manifest_path: Path, result_path: Path, timeout_s: float) -> dict[str, Any]:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        word_pid_path = result_path.with_suffix(".word-pid")
        progress_path = result_path.with_suffix(".progress.log")
        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.script_path),
                "-JobManifestPath",
                str(manifest_path),
                "-ResultPath",
                str(result_path),
                "-WordPidPath",
                str(word_pid_path),
                "-ProgressPath",
                str(progress_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )
        deadline = time.monotonic() + timeout_s
        while process.poll() is None and not result_path.is_file() and time.monotonic() < deadline:
            time.sleep(0.2)
        timed_out = process.poll() is None and not result_path.is_file()
        if process.poll() is None and result_path.is_file():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        if process.poll() is None:
            if word_pid_path.is_file():
                word_pid = word_pid_path.read_text(encoding="utf-8-sig").strip()
                if word_pid.isdigit():
                    subprocess.run(
                        ["taskkill.exe", "/PID", word_pid, "/T", "/F"],
                        capture_output=True,
                        text=True,
                        creationflags=creationflags,
                        timeout=10,
                    )
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                creationflags=creationflags,
                timeout=10,
            )
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("Word renderer could not be terminated cleanly") from exc
        if timed_out:
            progress = "none"
            if progress_path.is_file():
                lines = progress_path.read_text(encoding="utf-8-sig").splitlines()
                progress = lines[-1] if lines else "none"
            raise TimeoutError(
                f"Word render exceeded {timeout_s:g} seconds; last_progress={progress}"
            )
        if process.returncode != 0 and not result_path.is_file():
            detail = (stderr or stdout or "Word renderer failed").strip()[-2000:]
            raise RuntimeError(detail)
        if not result_path.is_file():
            raise RuntimeError("Word renderer did not produce a result manifest")
        # Windows PowerShell 5.1 writes a UTF-8 BOM for ``-Encoding utf8``.
        result = json.loads(result_path.read_text(encoding="utf-8-sig"))
        if not isinstance(result, dict):
            raise RuntimeError("Word renderer returned an invalid result")
        return result


class DocumentWorkerSupervisor:
    """Serialize Office jobs, retry once, and quarantine every terminal failure."""

    _office_lock = threading.Lock()

    def __init__(self, execution: RenderExecution, *, timeout_s: float = 600.0, max_attempts: int = 2):
        if timeout_s <= 0 or max_attempts not in (1, 2):
            raise ValueError("timeout_s must be positive and max_attempts must be 1 or 2")
        self.execution = execution
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts

    @staticmethod
    def _verify_success(job: RenderJob, result: dict[str, Any]) -> dict[str, Any]:
        if result.get("status") != "DONE":
            raise RuntimeError(str(result.get("error") or "renderer did not report DONE"))
        artifacts = result.get("artifacts")
        if not isinstance(artifacts, list):
            raise RuntimeError("renderer result is missing artifacts")
        by_kind = {str(item.get("kind") or "").lower(): item for item in artifacts if isinstance(item, dict)}
        if not {"docx", "pdf"}.issubset(by_kind):
            raise RuntimeError("renderer must return DOCX and PDF artifacts")
        job_root = (job.output_root / job.request_hash).resolve()
        for kind in ("docx", "pdf"):
            artifact = by_kind[kind]
            path = Path(str(artifact.get("path") or "")).resolve()
            claimed_hash = str(artifact.get("sha256") or "").lower()
            if not _inside(path, (job_root,)) or not path.is_file():
                raise RuntimeError(f"renderer {kind} artifact is outside the job output directory")
            if not hmac.compare_digest(_sha256_file(path), claimed_hash):
                raise RuntimeError(f"renderer {kind} artifact SHA-256 verification failed")
        return result

    def process(self, job: RenderJob) -> dict[str, Any]:
        manifest = job.manifest()
        job_root = Path(manifest["output_directory"])
        job_root.mkdir(parents=True, exist_ok=True)
        manifest_path = job_root / "job.json"
        manifest_path.write_text(_canonical_json(manifest), encoding="utf-8")
        events: list[dict[str, Any]] = []
        with self._office_lock:
            for attempt in range(1, self.max_attempts + 1):
                result_path = job_root / f"result-attempt-{attempt}.json"
                started = time.monotonic()
                try:
                    result = self.execution.run(manifest_path, result_path, self.timeout_s)
                    verified = self._verify_success(job, result)
                    return {
                        **verified,
                        "job_id": job.job_id,
                        "request_hash": job.request_hash,
                        "attempts": attempt,
                        "events": events,
                    }
                except Exception as exc:
                    events.append(
                        {
                            "attempt": attempt,
                            "elapsed_s": round(time.monotonic() - started, 3),
                            "error": str(exc)[:1000],
                        }
                    )
            quarantine = job.output_root / "quarantine" / job.request_hash
            quarantine.mkdir(parents=True, exist_ok=True)
            shutil.copy2(manifest_path, quarantine / "job.json")
            failure = {
                "status": "QUARANTINED",
                "job_id": job.job_id,
                "request_hash": job.request_hash,
                "attempts": self.max_attempts,
                "events": events,
                "quarantine_path": str(quarantine),
            }
            (quarantine / "failure.json").write_text(_canonical_json(failure), encoding="utf-8")
            return failure
