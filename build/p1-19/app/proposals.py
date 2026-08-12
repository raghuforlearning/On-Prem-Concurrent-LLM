"""P1-19 Proposal Builder handoff orchestration.

This module owns the Orchestrator-side proposal payload freeze, gating, build
job tracking and artifact provenance.  The frozen Proposal Builder remains an
external service consumed through the adapter contract only.
"""
from __future__ import annotations

from typing import Any, Protocol

import psycopg

from db import PG_DSN, audit
from quote_comparison import canonical_json, payload_sha256


KNOWN_PROPOSAL_TYPES = {"CP", "TP", "AMC"}
REQUIRED_APPROVAL_KINDS = ("PROPOSAL_VALUE", "COSTING_OVERRIDE", "END_USER_DISCLOSURE")
BUILDER_TERMINAL_STATES = {"DONE", "FAILED", "QUARANTINED"}


PROPOSAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    proposal_id       BIGSERIAL PRIMARY KEY,
    opp_id            TEXT NOT NULL REFERENCES opportunities(opp_id),
    proposal_type     TEXT NOT NULL,
    selection_id      BIGINT NOT NULL REFERENCES quote_selections(selection_id),
    status            TEXT NOT NULL DEFAULT 'ASSEMBLED',
    created_by        TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (proposal_type IN ('CP','TP','AMC')),
    CHECK (status IN (
        'ASSEMBLED',
        'BUILD_PENDING',
        'BUILD_SUBMITTED',
        'BUILD_RUNNING',
        'PENDING_HUMAN_REVIEW',
        'FAILED',
        'QUARANTINED'
    ))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_proposal_selection_type
    ON proposals (opp_id, proposal_type, selection_id);

CREATE TABLE IF NOT EXISTS proposal_versions (
    proposal_version_id BIGSERIAL PRIMARY KEY,
    proposal_id         BIGINT NOT NULL REFERENCES proposals(proposal_id),
    version_no          INT NOT NULL,
    template_version    TEXT NOT NULL,
    payload_json        JSONB NOT NULL,
    payload_sha256      TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'FROZEN',
    frozen_by           TEXT NOT NULL,
    frozen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('FROZEN','SUPERSEDED')),
    UNIQUE (proposal_id, version_no),
    UNIQUE (proposal_id, payload_sha256)
);

CREATE TABLE IF NOT EXISTS document_build_jobs (
    build_job_id        BIGSERIAL PRIMARY KEY,
    proposal_version_id BIGINT NOT NULL REFERENCES proposal_versions(proposal_version_id),
    request_hash        TEXT NOT NULL UNIQUE,
    builder_job_id      TEXT,
    state               TEXT NOT NULL DEFAULT 'PENDING',
    attempts            INT NOT NULL DEFAULT 0,
    last_error          TEXT,
    submitted_at        TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ,
    CHECK (attempts >= 0),
    CHECK (state IN (
        'PENDING',
        'SUBMITTED',
        'RUNNING',
        'DONE',
        'FAILED',
        'QUARANTINED',
        'PENDING_HUMAN_REVIEW'
    ))
);
CREATE INDEX IF NOT EXISTS idx_document_build_jobs_version
    ON document_build_jobs (proposal_version_id, build_job_id DESC);

CREATE TABLE IF NOT EXISTS proposal_artifacts (
    artifact_id       BIGSERIAL PRIMARY KEY,
    build_job_id      BIGINT NOT NULL REFERENCES document_build_jobs(build_job_id),
    artifact_kind     TEXT NOT NULL,
    artifact_ref      TEXT NOT NULL,
    artifact_sha256   TEXT NOT NULL,
    metadata_json     JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (build_job_id, artifact_kind)
);

CREATE TABLE IF NOT EXISTS document_validation_results (
    validation_result_id BIGSERIAL PRIMARY KEY,
    build_job_id         BIGINT NOT NULL REFERENCES document_build_jobs(build_job_id),
    passed               BOOLEAN NOT NULL,
    checks_json          JSONB NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_document_validation_results_job
    ON document_validation_results (build_job_id, validation_result_id DESC);
"""


class ProposalBuilderBuildAdapter(Protocol):
    def validate_build(
        self,
        *,
        proposal_type: str,
        template_version: str,
        payload: dict[str, Any],
        payload_hash: str,
    ) -> dict[str, Any]:
        ...

    def create_build(
        self,
        *,
        proposal_type: str,
        template_version: str,
        payload: dict[str, Any],
        payload_hash: str,
    ) -> dict[str, Any]:
        ...

    def get_build(self, builder_job_id: str) -> dict[str, Any]:
        ...

    def get_artifacts(self, builder_job_id: str) -> dict[str, Any]:
        ...


def init_proposals(dsn: str = PG_DSN) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(PROPOSAL_SCHEMA)
        conn.commit()


def _json(value: Any) -> str:
    return canonical_json(value)


def _normalize_type(proposal_type: str) -> str:
    normalized = (proposal_type or "").strip().upper()
    if normalized not in KNOWN_PROPOSAL_TYPES:
        raise ValueError("proposal_type must be one of CP, TP or AMC")
    return normalized


def _clean_actor(actor: str) -> str:
    value = (actor or "").strip()
    if not value:
        raise ValueError("actor is required")
    return value


def _builder_state(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    mapping = {
        "QUEUED": "SUBMITTED",
        "PENDING": "SUBMITTED",
        "SUBMITTED": "SUBMITTED",
        "RUNNING": "RUNNING",
        "VALIDATING": "RUNNING",
        "DONE": "DONE",
        "COMPLETED": "DONE",
        "SUCCESS": "DONE",
        "FAILED": "FAILED",
        "ERROR": "FAILED",
        "QUARANTINED": "QUARANTINED",
    }
    return mapping.get(normalized, "RUNNING")


def _artifact_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = payload.get("artifacts")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if artifacts is None:
        artifacts = []
        for kind in ("docx", "pdf", "validation_report"):
            ref = payload.get(f"{kind}_ref")
            sha = payload.get(f"{kind}_sha256")
            if ref or sha:
                artifacts.append(
                    {
                        "kind": kind,
                        "ref": ref,
                        "sha256": sha,
                        "metadata": metadata.get(kind, {}),
                    }
                )
    if isinstance(artifacts, dict):
        artifacts = [
            {"kind": key, **(value if isinstance(value, dict) else {"ref": value})}
            for key, value in artifacts.items()
        ]
    rows: list[dict[str, Any]] = []
    for item in artifacts or []:
        if not isinstance(item, dict):
            raise ValueError("builder artifacts must be objects")
        kind = str(item.get("kind") or item.get("artifact_kind") or "").strip().lower()
        ref = str(item.get("ref") or item.get("artifact_ref") or item.get("uri") or "").strip()
        sha = str(item.get("sha256") or item.get("artifact_sha256") or "").strip().lower()
        if not kind or not ref or not sha:
            raise ValueError("builder artifact kind, ref and sha256 are required")
        rows.append(
            {
                "kind": kind,
                "ref": ref,
                "sha256": sha,
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            }
        )
    return rows


class ProposalRepository:
    def __init__(self, dsn: str = PG_DSN):
        self.dsn = dsn

    @staticmethod
    def _active_selection(conn: Any, opp_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT selection_id,comparison_run_id,quote_id,quote_version_no,"
            "commercial_snapshot,snapshot_sha256,deal_reg_status,proposal_eligible,"
            "selected_by,selected_at FROM quote_selections "
            "WHERE opp_id=%s AND status='ACTIVE'",
            (opp_id,),
        ).fetchone()
        if not row:
            raise PermissionError("proposal requires an accepted quote selection")
        return {
            "selection_id": row[0],
            "comparison_run_id": row[1],
            "quote_id": row[2],
            "quote_version_no": row[3],
            "commercial_snapshot": row[4],
            "snapshot_sha256": row[5],
            "deal_reg_status": row[6],
            "proposal_eligible": row[7],
            "selected_by": row[8],
            "selected_at": str(row[9]),
        }

    @staticmethod
    def _approved_required_approvals(conn: Any, opp_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT id,kind,amount_aed,routed_to_role,rule_id,status,decided_by,decided_at "
            "FROM approvals WHERE opp_id=%s AND kind=ANY(%s) ORDER BY id",
            (opp_id, list(REQUIRED_APPROVAL_KINDS)),
        ).fetchall()
        if any(row[5] == "REJECTED" for row in rows):
            raise PermissionError("proposal is blocked by a rejected approval")
        if any(row[5] == "PENDING" for row in rows):
            raise PermissionError("proposal requires all routed approvals to be decided")
        approved_value = [row for row in rows if row[1] == "PROPOSAL_VALUE" and row[5] == "APPROVED"]
        if not approved_value:
            raise PermissionError("proposal requires an approved PROPOSAL_VALUE approval")
        return [
            {
                "approval_id": row[0],
                "kind": row[1],
                "amount_aed": str(row[2]) if row[2] is not None else None,
                "routed_to_role": row[3],
                "rule_id": row[4],
                "status": row[5],
                "decided_by": row[6],
                "decided_at": str(row[7]) if row[7] else None,
            }
            for row in rows
            if row[5] == "APPROVED"
        ]

    @staticmethod
    def _costing_validation(conn: Any, quote_id: int, validation_id: int) -> dict[str, Any]:
        row = conn.execute(
            "SELECT q.validation_status,q.status,q.is_current,vr.validation_id,vr.status,"
            "vr.computed_subtotal,vr.computed_vat,vr.computed_total,vr.created_at "
            "FROM quotes q JOIN quote_validation_results vr ON vr.quote_id=q.quote_id "
            "WHERE q.quote_id=%s AND vr.validation_id=%s",
            (quote_id, validation_id),
        ).fetchone()
        if not row:
            raise PermissionError("proposal requires the selected quote validation record")
        if row[0] != "VALIDATED" or row[1] != "PARSED" or not row[2] or row[4] != "VALIDATED":
            raise PermissionError("proposal requires current validated costing")
        return {
            "validation_id": row[3],
            "status": row[4],
            "computed_subtotal": str(row[5]),
            "computed_vat": str(row[6]),
            "computed_total": str(row[7]),
            "validated_at": str(row[8]),
        }

    @staticmethod
    def _build_payload(
        *,
        opp_id: str,
        proposal_type: str,
        template_version: str,
        selection: dict[str, Any],
        approvals: list[dict[str, Any]],
        validation: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        commercial = selection["commercial_snapshot"]
        return {
            "schema_version": "p1-19.proposal_payload.v1",
            "proposal_type": proposal_type,
            "template_version": template_version,
            "opportunity": {"opp_id": opp_id},
            "accepted_quote": {
                "selection_id": selection["selection_id"],
                "comparison_run_id": selection["comparison_run_id"],
                "quote_id": selection["quote_id"],
                "quote_version_no": selection["quote_version_no"],
                "commercial_snapshot_sha256": selection["snapshot_sha256"],
                "selected_by": selection["selected_by"],
                "selected_at": selection["selected_at"],
            },
            "commercial": commercial,
            "costing_validation": validation,
            "approvals": approvals,
            "deal_registration": commercial.get("deal_registration", {}),
            "context": context,
        }

    def assemble(
        self,
        *,
        opp_id: str,
        proposal_type: str,
        template_version: str,
        actor: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        proposal_type = _normalize_type(proposal_type)
        actor = _clean_actor(actor)
        template_version = (template_version or "").strip()
        if not template_version:
            raise ValueError("template_version is required")
        if context is not None and not isinstance(context, dict):
            raise ValueError("context must be an object")
        with psycopg.connect(self.dsn) as conn:
            selection = self._active_selection(conn, opp_id)
            if not selection["proposal_eligible"]:
                raise PermissionError("Deal Registration gate is not satisfied for proposal generation")
            commercial = selection["commercial_snapshot"]
            if payload_sha256(commercial) != selection["snapshot_sha256"]:
                raise PermissionError("accepted commercial snapshot hash no longer matches")
            validation_id = int(commercial.get("validation_id") or 0)
            validation = self._costing_validation(conn, selection["quote_id"], validation_id)
            approvals = self._approved_required_approvals(conn, opp_id)
            payload = self._build_payload(
                opp_id=opp_id,
                proposal_type=proposal_type,
                template_version=template_version,
                selection=selection,
                approvals=approvals,
                validation=validation,
                context=context or {},
            )
            payload_hash = payload_sha256(payload)
            proposal_row = conn.execute(
                "INSERT INTO proposals (opp_id,proposal_type,selection_id,status,created_by) "
                "VALUES (%s,%s,%s,'ASSEMBLED',%s) "
                "ON CONFLICT (opp_id,proposal_type,selection_id) DO UPDATE "
                "SET updated_at=now() RETURNING proposal_id,status,created_at",
                (opp_id, proposal_type, selection["selection_id"], actor),
            ).fetchone()
            existing_version = conn.execute(
                "SELECT proposal_version_id,version_no,status,frozen_at FROM proposal_versions "
                "WHERE proposal_id=%s AND payload_sha256=%s",
                (proposal_row[0], payload_hash),
            ).fetchone()
            existing = existing_version is not None
            if existing_version:
                version_row = existing_version
            else:
                version_no = conn.execute(
                    "SELECT coalesce(max(version_no),0)+1 FROM proposal_versions WHERE proposal_id=%s",
                    (proposal_row[0],),
                ).fetchone()[0]
                conn.execute(
                    "UPDATE proposal_versions SET status='SUPERSEDED' WHERE proposal_id=%s AND status='FROZEN'",
                    (proposal_row[0],),
                )
                version_row = conn.execute(
                    "INSERT INTO proposal_versions "
                    "(proposal_id,version_no,template_version,payload_json,payload_sha256,status,frozen_by) "
                    "VALUES (%s,%s,%s,%s,%s,'FROZEN',%s) "
                    "RETURNING proposal_version_id,version_no,status,frozen_at",
                    (
                        proposal_row[0],
                        version_no,
                        template_version,
                        _json(payload),
                        payload_hash,
                        actor,
                    ),
                ).fetchone()
                audit(
                    conn,
                    actor,
                    "proposal",
                    "proposal_payload_frozen",
                    opp_id,
                    new=_json(
                        {
                            "proposal_id": proposal_row[0],
                            "proposal_version_id": version_row[0],
                            "proposal_type": proposal_type,
                            "selection_id": selection["selection_id"],
                            "payload_sha256": payload_hash,
                        }
                    ),
                )
            conn.commit()
        return {
            "proposal_id": proposal_row[0],
            "proposal_version_id": version_row[0],
            "opp_id": opp_id,
            "proposal_type": proposal_type,
            "template_version": template_version,
            "version_no": version_row[1],
            "status": proposal_row[1],
            "payload_sha256": payload_hash,
            "payload": payload,
            "existing": existing,
            "created_at": str(proposal_row[2]),
            "frozen_at": str(version_row[3]),
        }

    def _load_version(self, conn: Any, proposal_id: int) -> dict[str, Any]:
        row = conn.execute(
            "SELECT p.proposal_id,p.opp_id,p.proposal_type,p.status,pv.proposal_version_id,"
            "pv.version_no,pv.template_version,pv.payload_json,pv.payload_sha256 "
            "FROM proposals p JOIN proposal_versions pv ON pv.proposal_id=p.proposal_id "
            "WHERE p.proposal_id=%s AND pv.status='FROZEN' "
            "ORDER BY pv.version_no DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"proposal {proposal_id} has no frozen version")
        return {
            "proposal_id": row[0],
            "opp_id": row[1],
            "proposal_type": row[2],
            "proposal_status": row[3],
            "proposal_version_id": row[4],
            "version_no": row[5],
            "template_version": row[6],
            "payload": row[7],
            "payload_sha256": row[8],
        }

    def submit_build(
        self,
        *,
        proposal_id: int,
        adapter: ProposalBuilderBuildAdapter,
        actor: str,
    ) -> dict[str, Any]:
        actor = _clean_actor(actor)
        with psycopg.connect(self.dsn) as conn:
            version = self._load_version(conn, proposal_id)
            request_hash = payload_sha256(
                {
                    "proposal_type": version["proposal_type"],
                    "template_version": version["template_version"],
                    "payload_sha256": version["payload_sha256"],
                }
            )
            existing = conn.execute(
                "SELECT build_job_id,builder_job_id,state,attempts,last_error,submitted_at,completed_at "
                "FROM document_build_jobs WHERE request_hash=%s",
                (request_hash,),
            ).fetchone()
            if existing and existing[2] in {"SUBMITTED", "RUNNING", "DONE", "PENDING_HUMAN_REVIEW"}:
                return self._job_dict(existing, version, request_hash, existing=True)
            if existing:
                build_job_id = existing[0]
            else:
                build_job_id = conn.execute(
                    "INSERT INTO document_build_jobs "
                    "(proposal_version_id,request_hash,state,attempts) VALUES (%s,%s,'PENDING',0) "
                    "RETURNING build_job_id",
                    (version["proposal_version_id"], request_hash),
                ).fetchone()[0]
                audit(
                    conn,
                    actor,
                    "proposal",
                    "proposal_build_job_created",
                    version["opp_id"],
                    new=_json(
                        {
                            "proposal_id": proposal_id,
                            "proposal_version_id": version["proposal_version_id"],
                            "build_job_id": build_job_id,
                            "request_hash": request_hash,
                        }
                    ),
                )
            conn.commit()

        try:
            validation = adapter.validate_build(
                proposal_type=version["proposal_type"],
                template_version=version["template_version"],
                payload=version["payload"],
                payload_hash=version["payload_sha256"],
            )
            if validation.get("valid") is not True:
                raise ValueError(f"builder validation failed: {validation.get('errors') or validation}")
            created = adapter.create_build(
                proposal_type=version["proposal_type"],
                template_version=version["template_version"],
                payload=version["payload"],
                payload_hash=version["payload_sha256"],
            )
            builder_job_id = str(created.get("job_id") or "").strip()
            if not builder_job_id:
                raise ValueError("builder create_build response did not include job_id")
        except Exception as exc:
            message = str(exc)[:1000]
            with psycopg.connect(self.dsn) as conn:
                row = conn.execute(
                    "UPDATE document_build_jobs SET state='FAILED',attempts=attempts+1,"
                    "last_error=%s,updated_at=now() WHERE build_job_id=%s "
                    "RETURNING build_job_id,builder_job_id,state,attempts,last_error,submitted_at,completed_at",
                    (message, build_job_id),
                ).fetchone()
                conn.execute(
                    "UPDATE proposals SET status='FAILED',updated_at=now() WHERE proposal_id=%s",
                    (proposal_id,),
                )
                audit(
                    conn,
                    actor,
                    "proposal",
                    "proposal_build_submission_failed",
                    version["opp_id"],
                    new=f"build_job={build_job_id};error={message}",
                )
                conn.commit()
            return self._job_dict(row, version, request_hash, existing=False)

        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "UPDATE document_build_jobs SET builder_job_id=%s,state='SUBMITTED',"
                "attempts=attempts+1,last_error=NULL,submitted_at=coalesce(submitted_at,now()),"
                "updated_at=now() WHERE build_job_id=%s "
                "RETURNING build_job_id,builder_job_id,state,attempts,last_error,submitted_at,completed_at",
                (builder_job_id, build_job_id),
            ).fetchone()
            conn.execute(
                "UPDATE proposals SET status='BUILD_SUBMITTED',updated_at=now() WHERE proposal_id=%s",
                (proposal_id,),
            )
            audit(
                conn,
                actor,
                "proposal",
                "proposal_build_submitted",
                version["opp_id"],
                new=_json(
                    {
                        "proposal_id": proposal_id,
                        "proposal_version_id": version["proposal_version_id"],
                        "build_job_id": build_job_id,
                        "builder_job_id": builder_job_id,
                        "payload_sha256": version["payload_sha256"],
                    }
                ),
            )
            conn.commit()
        return self._job_dict(row, version, request_hash, existing=False)

    @staticmethod
    def _job_dict(
        row: Any,
        version: dict[str, Any],
        request_hash: str,
        *,
        existing: bool,
    ) -> dict[str, Any]:
        return {
            "build_job_id": row[0],
            "proposal_id": version["proposal_id"],
            "proposal_version_id": version["proposal_version_id"],
            "request_hash": request_hash,
            "builder_job_id": row[1],
            "state": row[2],
            "attempts": row[3],
            "last_error": row[4],
            "submitted_at": str(row[5]) if row[5] else None,
            "completed_at": str(row[6]) if row[6] else None,
            "existing": existing,
        }

    def refresh_build(
        self,
        *,
        build_job_id: int,
        adapter: ProposalBuilderBuildAdapter,
        actor: str,
    ) -> dict[str, Any]:
        actor = _clean_actor(actor)
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT j.build_job_id,j.builder_job_id,j.state,j.attempts,j.last_error,"
                "j.submitted_at,j.completed_at,p.proposal_id,p.opp_id,p.proposal_type,"
                "pv.proposal_version_id,pv.version_no,pv.template_version,pv.payload_json,"
                "pv.payload_sha256,j.request_hash "
                "FROM document_build_jobs j "
                "JOIN proposal_versions pv ON pv.proposal_version_id=j.proposal_version_id "
                "JOIN proposals p ON p.proposal_id=pv.proposal_id "
                "WHERE j.build_job_id=%s",
                (build_job_id,),
            ).fetchone()
        if not row:
            raise ValueError(f"unknown build job {build_job_id}")
        if not row[1]:
            raise PermissionError("build job has not been submitted to Proposal Builder")
        version = {
            "proposal_id": row[7],
            "opp_id": row[8],
            "proposal_type": row[9],
            "proposal_version_id": row[10],
            "version_no": row[11],
            "template_version": row[12],
            "payload": row[13],
            "payload_sha256": row[14],
        }
        request_hash = row[15]
        job_state = adapter.get_build(str(row[1]))
        mapped_state = _builder_state(str(job_state.get("state") or job_state.get("status") or ""))
        artifacts_saved = 0
        validation_saved = False
        try:
            artifact_payload = adapter.get_artifacts(str(row[1])) if mapped_state == "DONE" else {}
            artifacts = _artifact_rows(artifact_payload)
            validation = artifact_payload.get("validation") if isinstance(artifact_payload, dict) else None
            with psycopg.connect(self.dsn) as conn:
                for item in artifacts:
                    conn.execute(
                        "INSERT INTO proposal_artifacts "
                        "(build_job_id,artifact_kind,artifact_ref,artifact_sha256,metadata_json) "
                        "VALUES (%s,%s,%s,%s,%s) "
                        "ON CONFLICT (build_job_id,artifact_kind) DO UPDATE SET "
                        "artifact_ref=EXCLUDED.artifact_ref,artifact_sha256=EXCLUDED.artifact_sha256,"
                        "metadata_json=EXCLUDED.metadata_json",
                        (
                            build_job_id,
                            item["kind"],
                            item["ref"],
                            item["sha256"],
                            _json(item["metadata"]),
                        ),
                    )
                    artifacts_saved += 1
                if isinstance(validation, dict):
                    checks = validation.get("checks") if isinstance(validation.get("checks"), list) else validation
                    passed = bool(validation.get("passed") is True or validation.get("valid") is True)
                    conn.execute(
                        "INSERT INTO document_validation_results "
                        "(build_job_id,passed,checks_json) VALUES (%s,%s,%s)",
                        (build_job_id, passed, _json(checks)),
                    )
                    validation_saved = True
                proposal_status = {
                    "SUBMITTED": "BUILD_SUBMITTED",
                    "RUNNING": "BUILD_RUNNING",
                    "DONE": "PENDING_HUMAN_REVIEW",
                    "FAILED": "FAILED",
                    "QUARANTINED": "QUARANTINED",
                }[mapped_state]
                completed_sql = "now()" if mapped_state in BUILDER_TERMINAL_STATES else "completed_at"
                row = conn.execute(
                    f"UPDATE document_build_jobs SET state=%s,last_error=%s,updated_at=now(),"
                    f"completed_at={completed_sql} WHERE build_job_id=%s "
                    "RETURNING build_job_id,builder_job_id,state,attempts,last_error,submitted_at,completed_at",
                    (
                        mapped_state,
                        job_state.get("error") or job_state.get("detail"),
                        build_job_id,
                    ),
                ).fetchone()
                conn.execute(
                    "UPDATE proposals SET status=%s,updated_at=now() WHERE proposal_id=%s",
                    (proposal_status, version["proposal_id"]),
                )
                audit(
                    conn,
                    actor,
                    "proposal",
                    "proposal_build_refreshed",
                    version["opp_id"],
                    new=_json(
                        {
                            "build_job_id": build_job_id,
                            "builder_job_id": row[1],
                            "state": mapped_state,
                            "artifacts_saved": artifacts_saved,
                            "payload_sha256": version["payload_sha256"],
                        }
                    ),
                )
                conn.commit()
        except Exception as exc:
            message = str(exc)[:1000]
            with psycopg.connect(self.dsn) as conn:
                row = conn.execute(
                    "UPDATE document_build_jobs SET state='QUARANTINED',last_error=%s,"
                    "updated_at=now(),completed_at=now() WHERE build_job_id=%s "
                    "RETURNING build_job_id,builder_job_id,state,attempts,last_error,submitted_at,completed_at",
                    (message, build_job_id),
                ).fetchone()
                conn.execute(
                    "UPDATE proposals SET status='QUARANTINED',updated_at=now() WHERE proposal_id=%s",
                    (version["proposal_id"],),
                )
                audit(
                    conn,
                    actor,
                    "proposal",
                    "proposal_build_quarantined",
                    version["opp_id"],
                    new=f"build_job={build_job_id};error={message}",
                )
                conn.commit()
        result = self._job_dict(row, version, request_hash, existing=False)
        result["artifacts_saved"] = artifacts_saved
        result["validation_saved"] = validation_saved
        return result

    def artifacts(self, proposal_id: int) -> dict[str, Any]:
        with psycopg.connect(self.dsn) as conn:
            proposal = conn.execute(
                "SELECT proposal_id,opp_id,proposal_type,status FROM proposals WHERE proposal_id=%s",
                (proposal_id,),
            ).fetchone()
            if not proposal:
                raise ValueError(f"unknown proposal {proposal_id}")
            rows = conn.execute(
                "SELECT a.artifact_id,a.build_job_id,a.artifact_kind,a.artifact_ref,"
                "a.artifact_sha256,a.metadata_json,a.recorded_at,j.state "
                "FROM proposal_artifacts a JOIN document_build_jobs j ON j.build_job_id=a.build_job_id "
                "JOIN proposal_versions pv ON pv.proposal_version_id=j.proposal_version_id "
                "WHERE pv.proposal_id=%s ORDER BY a.artifact_kind",
                (proposal_id,),
            ).fetchall()
        return {
            "proposal_id": proposal[0],
            "opp_id": proposal[1],
            "proposal_type": proposal[2],
            "status": proposal[3],
            "artifacts": [
                {
                    "artifact_id": row[0],
                    "build_job_id": row[1],
                    "kind": row[2],
                    "ref": row[3],
                    "sha256": row[4],
                    "metadata": row[5],
                    "recorded_at": str(row[6]),
                    "job_state": row[7],
                }
                for row in rows
            ],
        }
