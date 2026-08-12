"""P1-25 local security hardening controls.

The module implements Orchestrator-owned checks that are air-gap compatible:
file signature screening, quarantine/security events, prompt-injection
regression evaluation, RBAC policy checks and restore/audit verification
evidence. External scanners such as ClamAV can be wired later without changing
the fail-closed decision shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import hashlib
import json
import re
import zipfile

import psycopg

from db import PG_DSN, audit
from quote_comparison import canonical_json, payload_sha256


MAX_SCAN_BYTES = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".csv", ".txt", ".png", ".jpg", ".jpeg"}
MAGIC_PREFIXES = {
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".docx": (b"PK\x03\x04",),
    ".xlsx": (b"PK\x03\x04",),
}
DANGEROUS_PDF_MARKERS = (b"/JavaScript", b"/JS", b"/OpenAction", b"/AA")
PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore (all )?(previous|prior|system|developer) instructions", re.I),
    re.compile(r"reveal (the )?(system prompt|developer message|credentials|secrets)", re.I),
    re.compile(r"credentials|secrets", re.I),
    re.compile(r"disable (guardrails|policy|security)", re.I),
    re.compile(r"send (this|data|quote|proposal).*(outside|external|internet|gmail|whatsapp)", re.I),
)


SECURITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS security_events (
    security_event_id BIGSERIAL PRIMARY KEY,
    kind              TEXT NOT NULL,
    severity          TEXT NOT NULL,
    actor             TEXT NOT NULL,
    subject_ref       TEXT,
    decision          TEXT NOT NULL,
    detail_json       JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_security_events_kind
    ON security_events (kind, security_event_id DESC);

CREATE TABLE IF NOT EXISTS rbac_roles (
    role_name         TEXT PRIMARY KEY,
    permissions_json  JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS restore_verifications (
    restore_verification_id BIGSERIAL PRIMARY KEY,
    restore_scope           TEXT NOT NULL,
    evidence_ref            TEXT NOT NULL,
    evidence_sha256         TEXT NOT NULL,
    audit_chain_verified    BOOLEAN NOT NULL,
    backup_age_hours        NUMERIC(10,2),
    status                  TEXT NOT NULL,
    verified_by             TEXT NOT NULL,
    notes                   TEXT,
    verified_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('PASSED','FAILED','NEEDS_REVIEW'))
);
"""


DEFAULT_ROLE_PERMISSIONS = {
    "presales_member": [
        "opportunity:create",
        "quote:ingest",
        "proposal:assemble",
        "proposal:submit_record",
    ],
    "presales_lead": [
        "opportunity:create",
        "quote:ingest",
        "proposal:assemble",
        "proposal:release_prepare",
        "proposal:submit_record",
    ],
    "finance": ["approval:decide", "quote:validate", "proposal:release_prepare"],
    "technical_reviewer": ["knowledge:approve", "proposal:release_prepare"],
    "admin": ["*"],
    "auditor": ["audit:read", "security:read", "benchmark:read"],
}


@dataclass(frozen=True)
class SecurityDecision:
    decision: str
    severity: str
    issues: list[dict[str, Any]]
    sha256: str | None = None
    size_bytes: int | None = None
    detected_type: str | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == "ALLOW"

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "severity": self.severity,
            "issues": self.issues,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "detected_type": self.detected_type,
        }


def init_security(dsn: str = PG_DSN) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(SECURITY_SCHEMA)
        for role, permissions in DEFAULT_ROLE_PERMISSIONS.items():
            conn.execute(
                "INSERT INTO rbac_roles (role_name,permissions_json) VALUES (%s,%s) "
                "ON CONFLICT (role_name) DO UPDATE SET permissions_json=EXCLUDED.permissions_json",
                (role, canonical_json(permissions)),
            )
        conn.commit()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _zip_contains_macros(content: bytes) -> bool:
    from io import BytesIO

    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            names = {name.lower() for name in archive.namelist()}
    except zipfile.BadZipFile:
        return False
    return any(name.endswith("vbaproject.bin") for name in names)


def scan_file_content(
    *,
    filename: str,
    content: bytes,
    claimed_content_type: str | None = None,
) -> SecurityDecision:
    suffix = Path(filename or "").suffix.lower()
    issues: list[dict[str, Any]] = []
    if suffix not in ALLOWED_EXTENSIONS:
        issues.append({"code": "EXTENSION_NOT_ALLOWED", "message": f"{suffix or '<none>'} is not allowed"})
    if not content:
        issues.append({"code": "EMPTY_FILE", "message": "file is empty"})
    if len(content) > MAX_SCAN_BYTES:
        issues.append({"code": "FILE_TOO_LARGE", "message": f"file exceeds {MAX_SCAN_BYTES} bytes"})
    magic = MAGIC_PREFIXES.get(suffix)
    if magic and not any(content.startswith(prefix) for prefix in magic):
        issues.append({"code": "MAGIC_MISMATCH", "message": f"{suffix} signature did not match"})
    if suffix == ".pdf" and any(marker in content for marker in DANGEROUS_PDF_MARKERS):
        issues.append({"code": "PDF_ACTIVE_CONTENT", "message": "PDF active content marker found"})
    if suffix in {".docx", ".xlsx"} and _zip_contains_macros(content):
        issues.append({"code": "OFFICE_MACRO_FOUND", "message": "Office macro project found"})
    decision = "ALLOW" if not issues else "QUARANTINE"
    severity = "INFO" if not issues else "HIGH"
    return SecurityDecision(
        decision=decision,
        severity=severity,
        issues=issues,
        sha256=sha256_bytes(content),
        size_bytes=len(content),
        detected_type=claimed_content_type,
    )


def evaluate_prompt_injection(text: str) -> SecurityDecision:
    issues = [
        {"code": "PROMPT_INJECTION_PATTERN", "message": pattern.pattern}
        for pattern in PROMPT_INJECTION_PATTERNS
        if pattern.search(text or "")
    ]
    return SecurityDecision(
        decision="ALLOW" if not issues else "FLAG",
        severity="INFO" if not issues else "HIGH",
        issues=issues,
        sha256=sha256_bytes((text or "").encode("utf-8")),
        size_bytes=len((text or "").encode("utf-8")),
        detected_type="text/plain",
    )


class SecurityRepository:
    def __init__(self, dsn: str = PG_DSN):
        self.dsn = dsn

    def record_event(
        self,
        *,
        kind: str,
        decision: SecurityDecision,
        actor: str,
        subject_ref: str | None = None,
    ) -> dict[str, Any]:
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "INSERT INTO security_events "
                "(kind,severity,actor,subject_ref,decision,detail_json) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING security_event_id,created_at",
                (
                    kind,
                    decision.severity,
                    actor,
                    subject_ref,
                    decision.decision,
                    canonical_json(decision.as_dict()),
                ),
            ).fetchone()
            audit(
                conn,
                actor,
                "security",
                f"{kind.lower()}_{decision.decision.lower()}",
                new=canonical_json(
                    {
                        "security_event_id": row[0],
                        "kind": kind,
                        "decision": decision.decision,
                        "subject_ref": subject_ref,
                        "detail_sha256": payload_sha256(decision.as_dict()),
                    }
                ),
            )
            conn.commit()
        payload = decision.as_dict()
        payload.update({"security_event_id": row[0], "kind": kind, "created_at": str(row[1])})
        return payload

    def role_has_permission(self, role_name: str, permission: str) -> bool:
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT permissions_json FROM rbac_roles WHERE role_name=%s",
                (role_name,),
            ).fetchone()
        if not row:
            return False
        permissions = row[0]
        return "*" in permissions or permission in permissions

    def require_permission(self, *, role_name: str, permission: str) -> dict[str, Any]:
        allowed = self.role_has_permission(role_name, permission)
        if not allowed:
            raise PermissionError(f"role {role_name} lacks {permission}")
        return {"role": role_name, "permission": permission, "allowed": True}

    def record_restore_verification(
        self,
        *,
        restore_scope: str,
        evidence_ref: str,
        evidence_sha256: str,
        audit_chain_verified: bool,
        verified_by: str,
        backup_age_hours: float | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        status = "PASSED" if audit_chain_verified else "FAILED"
        if not restore_scope.strip() or not evidence_ref.strip() or not evidence_sha256.strip():
            raise ValueError("restore_scope, evidence_ref and evidence_sha256 are required")
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "INSERT INTO restore_verifications "
                "(restore_scope,evidence_ref,evidence_sha256,audit_chain_verified,"
                "backup_age_hours,status,verified_by,notes) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING restore_verification_id,verified_at",
                (
                    restore_scope.strip(),
                    evidence_ref.strip(),
                    evidence_sha256.strip().lower(),
                    audit_chain_verified,
                    backup_age_hours,
                    status,
                    verified_by.strip(),
                    notes or None,
                ),
            ).fetchone()
            audit(
                conn,
                verified_by,
                "security",
                "restore_verification_recorded",
                new=canonical_json(
                    {
                        "restore_verification_id": row[0],
                        "restore_scope": restore_scope.strip(),
                        "status": status,
                        "audit_chain_verified": audit_chain_verified,
                    }
                ),
                reason=notes or None,
            )
            conn.commit()
        return {
            "restore_verification_id": row[0],
            "restore_scope": restore_scope.strip(),
            "evidence_ref": evidence_ref.strip(),
            "evidence_sha256": evidence_sha256.strip().lower(),
            "audit_chain_verified": audit_chain_verified,
            "backup_age_hours": backup_age_hours,
            "status": status,
            "verified_by": verified_by.strip(),
            "notes": notes or None,
            "verified_at": str(row[1]),
        }

    def latest_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute(
                "SELECT security_event_id,kind,severity,actor,subject_ref,decision,detail_json,created_at "
                "FROM security_events ORDER BY security_event_id DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [
            {
                "security_event_id": row[0],
                "kind": row[1],
                "severity": row[2],
                "actor": row[3],
                "subject_ref": row[4],
                "decision": row[5],
                "detail": row[6],
                "created_at": str(row[7]),
            }
            for row in rows
        ]
