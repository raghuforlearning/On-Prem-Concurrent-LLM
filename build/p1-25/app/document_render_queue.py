"""P1-21 durable PostgreSQL queue for the isolated Windows render worker."""
from __future__ import annotations

from hashlib import sha256
import hmac
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urlparse

import psycopg

from db import PG_DSN, audit


RENDER_QUEUE_SCHEMA = """
CREATE TABLE IF NOT EXISTS document_render_jobs (
    render_job_id       BIGSERIAL PRIMARY KEY,
    build_job_id        BIGINT NOT NULL REFERENCES document_build_jobs(build_job_id),
    source_artifact_id  BIGINT NOT NULL REFERENCES proposal_artifacts(artifact_id),
    request_hash        TEXT NOT NULL UNIQUE,
    renderer_profile    TEXT NOT NULL DEFAULT 'word-com-v1',
    security_clearance  JSONB NOT NULL,
    state               TEXT NOT NULL DEFAULT 'QUEUED',
    worker_id           TEXT,
    attempts            INT NOT NULL DEFAULT 0,
    lease_expires_at    TIMESTAMPTZ,
    heartbeat_at        TIMESTAMPTZ,
    result_json         JSONB,
    last_error          TEXT,
    created_by          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ,
    CHECK (attempts >= 0),
    CHECK (state IN ('QUEUED','LEASED','RUNNING','DONE','QUARANTINED'))
);
CREATE INDEX IF NOT EXISTS idx_document_render_jobs_claim
    ON document_render_jobs (state, lease_expires_at, render_job_id);
CREATE INDEX IF NOT EXISTS idx_document_render_jobs_build
    ON document_render_jobs (build_job_id, render_job_id DESC);
CREATE TABLE IF NOT EXISTS document_render_artifacts (
    render_artifact_id  BIGSERIAL PRIMARY KEY,
    render_job_id       BIGINT NOT NULL REFERENCES document_render_jobs(render_job_id),
    artifact_kind       TEXT NOT NULL,
    artifact_ref        TEXT NOT NULL,
    artifact_sha256     TEXT NOT NULL,
    size_bytes          BIGINT NOT NULL,
    metadata_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (render_job_id, artifact_kind),
    CHECK (artifact_kind IN ('docx','pdf')),
    CHECK (size_bytes > 0)
);
"""

_QUEUE_LOCK_ID = 1212101
_TERMINAL_STATES = {"DONE", "QUARANTINED"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _actor(value: str, field: str = "actor") -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError(f"{field} is required")
    return cleaned


def _clearance(value: Any, artifact_sha256: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("status") != "CLEARED":
        raise PermissionError("document render requires explicit CLEARED security evidence")
    evidence_hash = str(value.get("artifact_sha256") or "").strip().lower()
    if not hmac.compare_digest(evidence_hash, artifact_sha256.lower()):
        raise PermissionError("security clearance hash does not match the Builder DOCX")
    if not str(value.get("scanner") or "").strip() or not str(value.get("scanned_at") or "").strip():
        raise PermissionError("security clearance requires scanner and scanned_at provenance")
    return value


def init_document_render_queue(dsn: str = PG_DSN) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(RENDER_QUEUE_SCHEMA)
        conn.commit()


class DocumentRenderQueue:
    def __init__(self, dsn: str = PG_DSN):
        self.dsn = dsn

    @staticmethod
    def _job(row: Any) -> dict[str, Any]:
        return {
            "render_job_id": row[0],
            "build_job_id": row[1],
            "source_artifact_id": row[2],
            "request_hash": row[3],
            "renderer_profile": row[4],
            "security_clearance": row[5],
            "state": row[6],
            "worker_id": row[7],
            "attempts": row[8],
            "lease_expires_at": str(row[9]) if row[9] else None,
            "heartbeat_at": str(row[10]) if row[10] else None,
            "result": row[11],
            "last_error": row[12],
            "created_at": str(row[13]),
            "updated_at": str(row[14]),
            "completed_at": str(row[15]) if row[15] else None,
        }

    @staticmethod
    def _select_columns() -> str:
        return (
            "render_job_id,build_job_id,source_artifact_id,request_hash,renderer_profile,"
            "security_clearance,state,worker_id,attempts,lease_expires_at,heartbeat_at,"
            "result_json,last_error,created_at,updated_at,completed_at"
        )

    def enqueue(
        self,
        *,
        build_job_id: int,
        security_clearance: dict[str, Any],
        actor: str,
        renderer_profile: str = "word-com-v1",
    ) -> dict[str, Any]:
        actor = _actor(actor)
        renderer_profile = _actor(renderer_profile, "renderer_profile")
        with psycopg.connect(self.dsn) as conn:
            source = conn.execute(
                "SELECT a.artifact_id,a.artifact_ref,a.artifact_sha256,j.state,p.opp_id "
                "FROM proposal_artifacts a "
                "JOIN document_build_jobs j ON j.build_job_id=a.build_job_id "
                "JOIN proposal_versions pv ON pv.proposal_version_id=j.proposal_version_id "
                "JOIN proposals p ON p.proposal_id=pv.proposal_id "
                "WHERE a.build_job_id=%s AND a.artifact_kind='docx'",
                (build_job_id,),
            ).fetchone()
            if not source:
                raise ValueError("render queue requires a Builder DOCX artifact")
            if source[3] not in {"DONE", "QUARANTINED"}:
                raise PermissionError("render queue requires a terminal Builder job")
            clearance = _clearance(security_clearance, source[2])
            request_hash = sha256(
                _canonical_json(
                    {
                        "source_artifact_id": source[0],
                        "source_sha256": source[2],
                        "renderer_profile": renderer_profile,
                    }
                ).encode("utf-8")
            ).hexdigest()
            existing = conn.execute(
                f"SELECT {self._select_columns()} FROM document_render_jobs WHERE request_hash=%s",
                (request_hash,),
            ).fetchone()
            if existing:
                result = self._job(existing)
                result["existing"] = True
                return result
            row = conn.execute(
                "INSERT INTO document_render_jobs "
                "(build_job_id,source_artifact_id,request_hash,renderer_profile,"
                "security_clearance,state,created_by) "
                "VALUES (%s,%s,%s,%s,%s,'QUEUED',%s) RETURNING "
                + self._select_columns(),
                (
                    build_job_id,
                    source[0],
                    request_hash,
                    renderer_profile,
                    _canonical_json(clearance),
                    actor,
                ),
            ).fetchone()
            audit(
                conn,
                actor,
                "document_worker",
                "document_render_queued",
                source[4],
                new=_canonical_json(
                    {
                        "render_job_id": row[0],
                        "build_job_id": build_job_id,
                        "source_artifact_id": source[0],
                        "request_hash": request_hash,
                    }
                ),
            )
            conn.commit()
        result = self._job(row)
        result["existing"] = False
        return result

    def claim(self, *, worker_id: str, lease_seconds: int = 120, max_claims: int = 3) -> dict[str, Any] | None:
        worker_id = _actor(worker_id, "worker_id")
        if not 30 <= lease_seconds <= 900:
            raise ValueError("lease_seconds must be between 30 and 900")
        if not 1 <= max_claims <= 10:
            raise ValueError("max_claims must be between 1 and 10")
        with psycopg.connect(self.dsn) as conn:
            locked = conn.execute("SELECT pg_try_advisory_xact_lock(%s)", (_QUEUE_LOCK_ID,)).fetchone()[0]
            if not locked:
                return None
            active = conn.execute(
                "SELECT 1 FROM document_render_jobs WHERE state IN ('LEASED','RUNNING') "
                "AND lease_expires_at > now() LIMIT 1"
            ).fetchone()
            if active:
                return None
            exhausted = conn.execute(
                "UPDATE document_render_jobs SET state='QUARANTINED',"
                "last_error='worker lease expired after maximum claims',updated_at=now(),"
                "completed_at=now(),lease_expires_at=NULL "
                "WHERE state IN ('LEASED','RUNNING') AND lease_expires_at <= now() "
                "AND attempts >= %s RETURNING render_job_id,build_job_id,attempts",
                (max_claims,),
            ).fetchall()
            for exhausted_job in exhausted:
                context = conn.execute(
                    "SELECT p.opp_id FROM document_build_jobs j "
                    "JOIN proposal_versions pv ON pv.proposal_version_id=j.proposal_version_id "
                    "JOIN proposals p ON p.proposal_id=pv.proposal_id WHERE j.build_job_id=%s",
                    (exhausted_job[1],),
                ).fetchone()
                audit(
                    conn,
                    "document-worker-recovery",
                    "document_worker",
                    "document_render_quarantined",
                    context[0] if context else None,
                    new=_canonical_json(
                        {
                            "render_job_id": exhausted_job[0],
                            "attempts": exhausted_job[2],
                            "reason": "maximum expired claims",
                        }
                    ),
                    reason="worker lease expired after maximum claims",
                )
            candidate = conn.execute(
                "SELECT r.render_job_id,p.opp_id FROM document_render_jobs r "
                "JOIN document_build_jobs j ON j.build_job_id=r.build_job_id "
                "JOIN proposal_versions pv ON pv.proposal_version_id=j.proposal_version_id "
                "JOIN proposals p ON p.proposal_id=pv.proposal_id "
                "WHERE (r.state='QUEUED' OR (r.state IN ('LEASED','RUNNING') "
                "AND r.lease_expires_at <= now())) AND r.attempts < %s "
                "ORDER BY r.render_job_id FOR UPDATE OF r SKIP LOCKED LIMIT 1",
                (max_claims,),
            ).fetchone()
            if not candidate:
                conn.commit()
                return None
            row = conn.execute(
                "UPDATE document_render_jobs SET state='LEASED',worker_id=%s,"
                "attempts=attempts+1,lease_expires_at=now()+make_interval(secs => %s),"
                "heartbeat_at=now(),updated_at=now(),last_error=NULL "
                "WHERE render_job_id=%s RETURNING " + self._select_columns(),
                (worker_id, lease_seconds, candidate[0]),
            ).fetchone()
            action = "document_render_reclaimed" if row[8] > 1 else "document_render_claimed"
            audit(
                conn,
                f"worker:{worker_id}",
                "document_worker",
                action,
                candidate[1],
                new=_canonical_json(
                    {"render_job_id": row[0], "attempt": row[8], "lease_seconds": lease_seconds}
                ),
            )
            conn.commit()
        result = self._job(row)
        result["expired_jobs_quarantined"] = [item[0] for item in exhausted]
        return result

    def record_artifact(
        self,
        *,
        render_job_id: int,
        worker_id: str,
        artifact_kind: str,
        artifact_path: str | Path,
        artifact_sha256: str,
        size_bytes: int,
        allowed_root: str | Path,
    ) -> dict[str, Any]:
        """Register a worker upload only while its lease is active."""
        worker_id = _actor(worker_id, "worker_id")
        kind = str(artifact_kind or "").strip().lower()
        digest = str(artifact_sha256 or "").strip().lower()
        if kind not in {"docx", "pdf"}:
            raise ValueError("render artifact kind must be docx or pdf")
        if not _SHA256_RE.fullmatch(digest) or size_bytes <= 0:
            raise ValueError("render artifact requires a SHA-256 digest and positive size")
        root = Path(allowed_root).expanduser().resolve()
        path = Path(artifact_path).expanduser().resolve()
        expected_suffix = f".{kind}"
        if not (path == root or path.is_relative_to(root)) or path.suffix.casefold() != expected_suffix:
            raise PermissionError("render artifact is outside its controlled root or has the wrong type")
        if not path.is_file() or path.stat().st_size != size_bytes:
            raise ValueError("render artifact file or size is invalid")
        if not hmac.compare_digest(_sha256_file(path), digest):
            raise PermissionError("render artifact SHA-256 verification failed")
        with psycopg.connect(self.dsn) as conn:
            context = conn.execute(
                "SELECT p.opp_id FROM document_render_jobs r "
                "JOIN document_build_jobs j ON j.build_job_id=r.build_job_id "
                "JOIN proposal_versions pv ON pv.proposal_version_id=j.proposal_version_id "
                "JOIN proposals p ON p.proposal_id=pv.proposal_id "
                "WHERE r.render_job_id=%s AND r.worker_id=%s "
                "AND r.state='RUNNING' AND r.lease_expires_at > now()",
                (render_job_id, worker_id),
            ).fetchone()
            if not context:
                raise PermissionError("render artifact upload requires an active running lease")
            row = conn.execute(
                "INSERT INTO document_render_artifacts "
                "(render_job_id,artifact_kind,artifact_ref,artifact_sha256,size_bytes,metadata_json) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (render_job_id,artifact_kind) DO UPDATE SET "
                "artifact_ref=EXCLUDED.artifact_ref,artifact_sha256=EXCLUDED.artifact_sha256,"
                "size_bytes=EXCLUDED.size_bytes,metadata_json=EXCLUDED.metadata_json,recorded_at=now() "
                "RETURNING render_artifact_id,artifact_kind,artifact_ref,artifact_sha256,size_bytes,recorded_at",
                (
                    render_job_id,
                    kind,
                    path.as_uri(),
                    digest,
                    size_bytes,
                    _canonical_json({"worker_id": worker_id}),
                ),
            ).fetchone()
            audit(
                conn,
                f"worker:{worker_id}",
                "document_worker",
                "document_render_artifact_recorded",
                context[0],
                new=_canonical_json(
                    {
                        "render_job_id": render_job_id,
                        "artifact_kind": kind,
                        "artifact_sha256": digest,
                        "size_bytes": size_bytes,
                    }
                ),
            )
            conn.commit()
        return {
            "render_artifact_id": row[0],
            "kind": row[1],
            "ref": row[2],
            "sha256": row[3],
            "size_bytes": row[4],
            "recorded_at": str(row[5]),
        }

    def artifacts(self, render_job_id: int) -> list[dict[str, Any]]:
        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute(
                "SELECT render_artifact_id,artifact_kind,artifact_ref,artifact_sha256,size_bytes,recorded_at "
                "FROM document_render_artifacts WHERE render_job_id=%s ORDER BY artifact_kind",
                (render_job_id,),
            ).fetchall()
        return [
            {
                "render_artifact_id": row[0],
                "kind": row[1],
                "ref": row[2],
                "sha256": row[3],
                "size_bytes": row[4],
                "recorded_at": str(row[5]),
            }
            for row in rows
        ]

    def start(self, *, render_job_id: int, worker_id: str, lease_seconds: int = 120) -> dict[str, Any]:
        return self._renew(
            render_job_id=render_job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            require_state="LEASED",
            next_state="RUNNING",
        )

    def heartbeat(self, *, render_job_id: int, worker_id: str, lease_seconds: int = 120) -> dict[str, Any]:
        return self._renew(
            render_job_id=render_job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            require_state="RUNNING",
            next_state="RUNNING",
        )

    def _renew(
        self,
        *,
        render_job_id: int,
        worker_id: str,
        lease_seconds: int,
        require_state: str,
        next_state: str,
    ) -> dict[str, Any]:
        worker_id = _actor(worker_id, "worker_id")
        if not 30 <= lease_seconds <= 900:
            raise ValueError("lease_seconds must be between 30 and 900")
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "UPDATE document_render_jobs SET state=%s,heartbeat_at=now(),"
                "lease_expires_at=now()+make_interval(secs => %s),updated_at=now() "
                "WHERE render_job_id=%s AND state=%s AND worker_id=%s "
                "AND lease_expires_at > now() RETURNING " + self._select_columns(),
                (next_state, lease_seconds, render_job_id, require_state, worker_id),
            ).fetchone()
            if not row:
                raise PermissionError("render lease is missing, expired or owned by another worker")
            conn.commit()
        return self._job(row)

    def complete(
        self,
        *,
        render_job_id: int,
        worker_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        worker_id = _actor(worker_id, "worker_id")
        if not isinstance(result, dict):
            raise ValueError("result must be an object")
        outcome = str(result.get("status") or "").strip().upper()
        if outcome not in _TERMINAL_STATES:
            raise ValueError("result status must be DONE or QUARANTINED")
        if outcome == "DONE":
            artifacts = self.artifacts(render_job_id)
            kinds = {item["kind"] for item in artifacts if _SHA256_RE.fullmatch(item["sha256"])}
            if not {"docx", "pdf"}.issubset(kinds):
                raise ValueError("DONE render result requires uploaded, verified DOCX and PDF artifacts")
            result = {**result, "artifacts": artifacts}
        error = None if outcome == "DONE" else str(result.get("error") or result.get("events") or "render quarantined")[:1000]
        with psycopg.connect(self.dsn) as conn:
            context = conn.execute(
                "SELECT p.opp_id FROM document_render_jobs r "
                "JOIN document_build_jobs j ON j.build_job_id=r.build_job_id "
                "JOIN proposal_versions pv ON pv.proposal_version_id=j.proposal_version_id "
                "JOIN proposals p ON p.proposal_id=pv.proposal_id "
                "WHERE r.render_job_id=%s",
                (render_job_id,),
            ).fetchone()
            if not context:
                raise ValueError(f"unknown render job {render_job_id}")
            row = conn.execute(
                "UPDATE document_render_jobs SET state=%s,result_json=%s,last_error=%s,"
                "lease_expires_at=NULL,heartbeat_at=now(),updated_at=now(),completed_at=now() "
                "WHERE render_job_id=%s AND state IN ('LEASED','RUNNING') AND worker_id=%s "
                "RETURNING " + self._select_columns(),
                (outcome, _canonical_json(result), error, render_job_id, worker_id),
            ).fetchone()
            if not row:
                raise PermissionError("render job is terminal or owned by another worker")
            audit(
                conn,
                f"worker:{worker_id}",
                "document_worker",
                "document_render_completed" if outcome == "DONE" else "document_render_quarantined",
                context[0],
                new=_canonical_json(
                    {"render_job_id": render_job_id, "state": outcome, "attempts": row[8]}
                ),
                reason=error,
            )
            conn.commit()
        return self._job(row)

    def get(self, render_job_id: int) -> dict[str, Any]:
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                f"SELECT {self._select_columns()} FROM document_render_jobs WHERE render_job_id=%s",
                (render_job_id,),
            ).fetchone()
        if not row:
            raise ValueError(f"unknown render job {render_job_id}")
        return self._job(row)

    def source_manifest(self, *, render_job_id: int, worker_id: str) -> dict[str, Any]:
        worker_id = _actor(worker_id, "worker_id")
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT a.artifact_ref,a.artifact_sha256,r.security_clearance,r.request_hash "
                "FROM document_render_jobs r "
                "JOIN proposal_artifacts a ON a.artifact_id=r.source_artifact_id "
                "WHERE r.render_job_id=%s AND r.worker_id=%s "
                "AND r.state IN ('LEASED','RUNNING') AND r.lease_expires_at > now()",
                (render_job_id, worker_id),
            ).fetchone()
        if not row:
            raise PermissionError("render source requires an active worker lease")
        return {
            "render_job_id": render_job_id,
            "job_id": f"p121-{render_job_id}",
            "source_ref": row[0],
            "source_sha256": row[1],
            "security_clearance": row[2],
            "request_hash": row[3],
        }

    def source_file(
        self,
        *,
        render_job_id: int,
        worker_id: str,
        allowed_roots: list[str] | tuple[str, ...],
    ) -> dict[str, Any]:
        manifest = self.source_manifest(render_job_id=render_job_id, worker_id=worker_id)
        parsed = urlparse(manifest["source_ref"])
        if parsed.scheme not in ("", "file"):
            raise PermissionError("render source is not a local Orchestrator artifact")
        raw = unquote(parsed.path) if parsed.scheme == "file" else manifest["source_ref"]
        if parsed.scheme == "file" and parsed.netloc:
            raw = f"//{parsed.netloc}{raw}"
        path = Path(raw).expanduser().resolve()
        roots = tuple(Path(item).expanduser().resolve() for item in allowed_roots)
        if not roots or not any(path == root or path.is_relative_to(root) for root in roots):
            raise PermissionError("render source is outside Orchestrator artifact roots")
        if not path.is_file() or path.suffix.casefold() != ".docx":
            raise ValueError("render source DOCX is missing")
        digest = _sha256_file(path)
        if not hmac.compare_digest(digest, manifest["source_sha256"]):
            raise PermissionError("render source changed after queueing")
        return {**manifest, "path": path}
