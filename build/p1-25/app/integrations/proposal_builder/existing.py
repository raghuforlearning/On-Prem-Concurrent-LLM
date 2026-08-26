"""Adapter for the frozen Builder's existing synchronous generation API.

The frozen NationLabs Proposal Builder currently exposes authenticated
``POST /api/generate`` and returns the generated DOCX as the response body.
This module translates the Orchestrator's approved frozen proposal payload to
that public contract and archives the returned artifact without copying any
document-generation logic into the Orchestrator.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any
from urllib.parse import unquote, urlparse

from .client import (
    BuilderAuthError,
    BuilderQuoteRejected,
    BuilderUnavailableError,
    ProposalBuilderClient,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PROPOSAL_NUMBER_RE = re.compile(r"^NL-PP-AN-\d{3}-\d{2}$")
_PROPOSAL_VERSION_RE = re.compile(r"^V\d+(?:\.\d+)?$")
_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_SOURCE_CONTENT_TYPES = {
    ".docx": _DOCX_CONTENT_TYPE,
    ".pdf": "application/pdf",
}
_MAX_SOURCE_BYTES = 50 * 1024 * 1024
_INTERNAL_COMMERCIAL_KEYS = {
    "cost",
    "cost_price",
    "vendor_cost",
    "buy_price",
    "margin",
    "margin_pct",
    "markup",
    "markup_pct",
}


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _boolean(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = _text(value).lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value {value!r}")


def _number(value: Any, field: str) -> float:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be a non-negative finite number")
    return float(number)


def _decimal(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be a non-negative finite number")
    return number


def _approved_tp_commercials(context: dict[str, Any]) -> dict[str, Any]:
    """Validate the customer-facing snapshot supplied by the costing workflow."""
    snapshot = context.get("customer_commercials")
    if not isinstance(snapshot, dict):
        raise ValueError(
            "TP generation requires context.proposal_builder.customer_commercials "
            "from an approved costing sheet"
        )
    forbidden = sorted(_INTERNAL_COMMERCIAL_KEYS.intersection(snapshot))
    if forbidden:
        raise ValueError(
            "customer_commercials must not expose internal fields: " + ", ".join(forbidden)
        )
    authority = snapshot.get("authority")
    if not isinstance(authority, dict):
        raise ValueError("customer_commercials.authority is required")
    if _text(authority.get("kind")).upper() != "APPROVED_COSTING_SHEET":
        raise ValueError("customer_commercials authority must be APPROVED_COSTING_SHEET")
    source_hash = _text(authority.get("source_sha256")).lower()
    if not _SHA256_RE.fullmatch(source_hash):
        raise ValueError("approved costing sheet source_sha256 is required")
    for field in ("approved_by", "approved_at"):
        if not _text(authority.get(field)):
            raise ValueError(f"approved costing sheet {field} is required")

    currency = _text(snapshot.get("currency")).upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("customer_commercials.currency must be a three-letter code")
    lines = snapshot.get("line_items")
    if not isinstance(lines, list) or not lines:
        raise ValueError("customer_commercials requires at least one selling-price line item")
    normalized_lines: list[dict[str, Any]] = []
    computed_subtotal = Decimal("0")
    for index, line in enumerate(lines, 1):
        if not isinstance(line, dict):
            raise ValueError(f"customer commercial line item {index} must be an object")
        forbidden_line = sorted(_INTERNAL_COMMERCIAL_KEYS.intersection(line))
        if forbidden_line:
            raise ValueError(
                f"customer commercial line item {index} exposes internal fields: "
                + ", ".join(forbidden_line)
            )
        description = _text(line.get("description"))
        quantity = _decimal(line.get("quantity"), f"customer_commercials.line_items[{index}].quantity")
        unit_price = _decimal(line.get("unit_price"), f"customer_commercials.line_items[{index}].unit_price")
        line_total = _decimal(line.get("line_total"), f"customer_commercials.line_items[{index}].line_total")
        if not description or quantity <= 0:
            raise ValueError(f"customer commercial line item {index} requires description and quantity")
        if (quantity * unit_price).quantize(Decimal("0.01")) != line_total.quantize(Decimal("0.01")):
            raise ValueError(f"customer commercial line item {index} total does not equal quantity x unit price")
        computed_subtotal += line_total
        normalized_lines.append(
            {
                "line_no": int(line.get("line_no") or index),
                "part_number": _text(line.get("part_number")),
                "description": description,
                "quantity": str(quantity),
                "native_unit_price": format(unit_price, "f"),
                "native_line_total": format(line_total, "f"),
            }
        )
    subtotal = _decimal(snapshot.get("subtotal"), "customer_commercials.subtotal")
    vat_rate = _decimal(snapshot.get("vat_rate"), "customer_commercials.vat_rate")
    vat_amount = _decimal(snapshot.get("vat_amount"), "customer_commercials.vat_amount")
    grand_total = _decimal(snapshot.get("grand_total"), "customer_commercials.grand_total")
    if computed_subtotal.quantize(Decimal("0.01")) != subtotal.quantize(Decimal("0.01")):
        raise ValueError("customer commercial subtotal does not equal the sum of line totals")
    if (subtotal + vat_amount).quantize(Decimal("0.01")) != grand_total.quantize(Decimal("0.01")):
        raise ValueError("customer commercial grand total does not equal subtotal plus VAT")
    computed_vat = (subtotal * vat_rate / Decimal("100")).quantize(Decimal("0.01"))
    if computed_vat != vat_amount.quantize(Decimal("0.01")):
        raise ValueError("customer commercial VAT amount does not match subtotal x VAT rate")
    terms = snapshot.get("terms") if isinstance(snapshot.get("terms"), dict) else {}
    missing_terms = [
        field for field in ("payment", "validity", "delivery") if not _text(terms.get(field))
    ]
    if missing_terms:
        raise ValueError(
            "approved customer commercial terms missing: " + ", ".join(missing_terms)
        )
    return {
        "native_currency": currency,
        "aed_total": format(grand_total, "f"),
        "terms": terms,
        "line_items": normalized_lines,
        "authority": authority,
    }


def _require_approved_rag_provenance(context: dict[str, Any]) -> None:
    provenance = context.get("rag_provenance")
    if not isinstance(provenance, dict):
        raise ValueError("TP generation requires approved RAG provenance")
    missing = [
        field
        for field in ("draft_id", "retrieval_id", "reviewed_by", "reviewed_at")
        if not provenance.get(field)
    ]
    if _text(provenance.get("status")).upper() != "APPROVED" or missing:
        detail = ", ".join(missing) if missing else "status"
        raise ValueError(f"TP generation requires approved RAG provenance: {detail}")


def _approved_tp_identity(context: dict[str, Any]) -> dict[str, Any]:
    """Return the explicit customer-masking contract for a TP build.

    The frozen Builder already accepts these fields.  Keeping them in the
    frozen Orchestrator payload makes the masking decision auditable and lets
    the returned-document gate independently prove that no real-name alias
    survived.
    """
    client_code = _text(context.get("client_name") or context.get("client"))
    if not client_code:
        raise ValueError("TP generation requires a masked client code")
    if not _boolean(context.get("mask_client"), False):
        raise ValueError("TP generation requires mask_client=true")

    raw_aliases = context.get("client_aliases")
    if isinstance(raw_aliases, str):
        aliases = [item.strip() for item in raw_aliases.splitlines() if item.strip()]
    elif isinstance(raw_aliases, (list, tuple)):
        aliases = [_text(item) for item in raw_aliases if _text(item)]
    else:
        aliases = []
    real_name = _text(context.get("client_real_name"))
    if real_name:
        aliases.insert(0, real_name)

    unique_aliases: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        key = alias.casefold()
        if key == client_code.casefold() or key in seen:
            continue
        seen.add(key)
        unique_aliases.append(alias)
    if not unique_aliases:
        raise ValueError("TP generation requires at least one real client alias for masking")
    return {
        "client_code": client_code,
        "client_real_name": real_name or unique_aliases[0],
        "client_aliases": unique_aliases,
    }


def _safe_filename(content_disposition: str, fallback: str) -> str:
    encoded = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, re.I)
    quoted = re.search(r'filename="([^"]+)"', content_disposition, re.I)
    candidate = unquote(encoded.group(1)) if encoded else (quoted.group(1) if quoted else fallback)
    candidate = Path(candidate).name
    candidate = re.sub(r"[^A-Za-z0-9 ._&+()-]", "_", candidate).strip(" .")
    if not candidate.lower().endswith(".docx"):
        candidate = f"{candidate or 'proposal'}.docx"
    return candidate


class ExistingProposalBuilderClient(ProposalBuilderClient):
    """Bridge the P1-19 job protocol to the existing synchronous Builder API."""

    transport = "existing_sync"
    _archive_lock = Lock()

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        artifact_root: str,
        source_artifact_roots: list[str] | tuple[str, ...] | None = None,
        timeout_s: float = 120.0,
        session: Any = None,
    ):
        super().__init__(
            base_url,
            username,
            password,
            timeout_s=timeout_s,
            session=session,
        )
        root = Path(artifact_root or "").expanduser()
        if not root.is_absolute():
            raise ValueError("PROPOSAL_BUILDER_ARTIFACT_ROOT must be an absolute path")
        self.artifact_root = root
        roots = source_artifact_roots or (
            "/srv/data/rfp_archive",
            "/srv/data/quote_archive",
            str(root),
        )
        self.source_artifact_roots = tuple(Path(item).expanduser().resolve() for item in roots)
        if not self.source_artifact_roots or any(
            not item.is_absolute() for item in self.source_artifact_roots
        ):
            raise ValueError("Proposal Builder source artifact roots must be absolute paths")

    @staticmethod
    def _builder_context(payload: dict[str, Any]) -> dict[str, Any]:
        context = payload.get("context")
        if not isinstance(context, dict):
            raise ValueError("proposal context must be an object")
        builder = context.get("proposal_builder", context)
        if not isinstance(builder, dict):
            raise ValueError("context.proposal_builder must be an object")
        return builder

    @classmethod
    def _builder_payload(
        cls,
        *,
        proposal_type: str,
        template_version: str,
        payload: dict[str, Any],
        payload_hash: str,
    ) -> dict[str, Any]:
        normalized_type = _text(proposal_type).upper()
        if normalized_type not in {"CP", "TP", "AMC"}:
            raise ValueError("proposal_type must be CP, TP or AMC")
        if _text(payload.get("proposal_type")).upper() != normalized_type:
            raise ValueError("proposal_type does not match the frozen payload")
        if _text(payload.get("template_version")) != _text(template_version):
            raise ValueError("template_version does not match the frozen payload")
        normalized_hash = _text(payload_hash).lower()
        if not _SHA256_RE.fullmatch(normalized_hash):
            raise ValueError("payload_hash must be a SHA-256 digest")
        if _payload_sha256(payload) != normalized_hash:
            raise ValueError("payload_hash does not match the frozen payload")

        context = cls._builder_context(payload)
        commercial = payload.get("commercial")
        if not isinstance(commercial, dict):
            raise ValueError("frozen payload has no commercial snapshot")
        if normalized_type == "TP":
            commercial = _approved_tp_commercials(context)
            _require_approved_rag_provenance(context)
            tp_identity = _approved_tp_identity(context)
        else:
            tp_identity = None

        proposal_number = _text(
            context.get("proposal_number") or context.get("prop_num") or context.get("propNum")
        )
        if not _PROPOSAL_NUMBER_RE.fullmatch(proposal_number):
            raise ValueError("context.proposal_builder.proposal_number must match NL-PP-AN-xxx-yy")
        proposal_version = _text(
            context.get("proposal_version") or context.get("version")
        )
        if not proposal_version and _PROPOSAL_VERSION_RE.fullmatch(_text(template_version)):
            proposal_version = _text(template_version)
        if not _PROPOSAL_VERSION_RE.fullmatch(proposal_version):
            raise ValueError("context.proposal_builder.proposal_version must match V1 or V1.0")

        proposal_date = _text(context.get("proposal_date") or context.get("date"))
        client = _text(context.get("client_name") or context.get("client"))
        solution = _text(context.get("solution"))
        missing = [
            name
            for name, value in (
                ("proposal_date", proposal_date),
                ("client_name", client),
                ("solution", solution),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "context.proposal_builder missing required fields: " + ", ".join(missing)
            )

        line_items = commercial.get("line_items")
        if not isinstance(line_items, list) or not line_items:
            raise ValueError("commercial snapshot requires at least one accepted line item")
        boq: list[dict[str, Any]] = []
        for index, line in enumerate(line_items, 1):
            if not isinstance(line, dict):
                raise ValueError(f"commercial line item {index} must be an object")
            description = _text(line.get("description"))
            quantity = _text(line.get("quantity"))
            unit_price = _text(line.get("native_unit_price"))
            line_total = _text(line.get("native_line_total"))
            if not description or not quantity or not unit_price or not line_total:
                raise ValueError(
                    f"commercial line item {index} is missing description, quantity or native pricing"
                )
            boq.append(
                {
                    "sno": int(line.get("line_no") or index),
                    "pn": _text(line.get("part_number")),
                    "desc": description,
                    "qty": quantity,
                    "up": unit_price,
                    "total": line_total,
                }
            )

        accepted_terms = commercial.get("terms")
        terms = accepted_terms if isinstance(accepted_terms, dict) else {}
        delivery = _text(terms.get("delivery"))
        if normalized_type in {"CP", "TP"} and not delivery:
            raise ValueError("accepted commercial terms require delivery for CP/TP generation")
        currency = _text(commercial.get("native_currency")).upper()
        if len(currency) != 3:
            raise ValueError("accepted commercial snapshot requires a three-letter native currency")

        request: dict[str, Any] = {
            "type": normalized_type,
            "propNum": proposal_number,
            "version": proposal_version,
            "date": proposal_date,
            "client": client,
            "clientLoc": _text(context.get("client_location") or context.get("clientLoc")),
            "solution": solution,
            "summary": _text(context.get("executive_summary") or context.get("summary")),
            "boq": boq,
            "terms": {
                "payment": _text(terms.get("payment")),
                "currency": currency,
                "validity": _text(terms.get("validity")),
                "delivery": delivery,
                "warranty": _text(context.get("warranty")),
                "outOfScope": _text(context.get("out_of_scope") or context.get("outOfScope")),
            },
            "expectedValue": _number(commercial.get("aed_total"), "commercial.aed_total"),
            "includeAssumptions": _boolean(context.get("include_assumptions"), True),
        }
        if tp_identity is not None:
            # The existing Builder multipart endpoint expects aliases as a
            # newline-delimited field and parses maskClient from the string
            # value emitted by _multipart_fields().
            request.update(
                {
                    "client": tp_identity["client_code"],
                    "clientRealName": tp_identity["client_real_name"],
                    "clientAliases": "\n".join(tp_identity["client_aliases"]),
                    "maskClient": True,
                }
            )

        if normalized_type in {"CP", "TP"}:
            request["showPartNumber"] = _text(context.get("show_part_number")) or "auto"
            request["notes"] = _text(context.get("additional_notes") or context.get("notes"))
        custom_assumptions = context.get("custom_assumptions")
        if isinstance(custom_assumptions, list):
            request["customAssumptions"] = [_text(item) for item in custom_assumptions if _text(item)]
        custom_exclusions = context.get("custom_exclusions")
        if isinstance(custom_exclusions, list):
            request["customExclusions"] = [_text(item) for item in custom_exclusions if _text(item)]

        if normalized_type == "TP":
            request["includeScopeOfWork"] = _boolean(context.get("include_scope_of_work"), False)

        if normalized_type == "AMC":
            amc = context.get("amc")
            if not isinstance(amc, dict):
                raise ValueError("context.proposal_builder.amc is required for AMC generation")
            request.update(
                {
                    "amcTrack": "nl-owned",
                    "totalUsers": _text(amc.get("total_users")),
                    "siteVisitFrequency": _text(amc.get("site_visit_frequency")),
                    "slaTier": _text(amc.get("sla_tier")),
                    "paymentTerms": _text(amc.get("payment_terms")),
                    "contractDuration": _text(amc.get("contract_duration")),
                    "poReference": _text(amc.get("po_reference")),
                    "includeDataHandling": _boolean(amc.get("include_data_handling"), False),
                    "preAmcActivities": amc.get("pre_amc_activities") or [],
                    "amcCoverage": amc.get("amc_coverage") or [],
                    "supportHours": amc.get("support_hours") or [],
                    "commercials": [
                        {"description": item["desc"], "amount": _number(item["total"], "boq.total")}
                        for item in boq
                    ],
                }
            )
            if request["slaTier"] == "Custom":
                request["customSlaRows"] = amc.get("custom_sla_rows") or []
                request["customSlaCoverage"] = _text(amc.get("custom_sla_coverage"))
        return request

    def _source_artifact(
        self,
        payload: dict[str, Any],
        proposal_type: str,
    ) -> dict[str, Any] | None:
        if _text(proposal_type).upper() != "TP":
            return None
        context = self._builder_context(payload)
        source = context.get("vendor_tp_artifact")
        if not isinstance(source, dict):
            raise ValueError(
                "context.proposal_builder.vendor_tp_artifact is required for TP generation"
            )
        artifact_ref = _text(source.get("artifact_ref") or source.get("ref"))
        expected_hash = _text(source.get("sha256")).lower()
        if not artifact_ref or not _SHA256_RE.fullmatch(expected_hash):
            raise ValueError("vendor TP artifact_ref and SHA-256 are required")
        parsed = urlparse(artifact_ref)
        if parsed.scheme not in {"", "file"} or parsed.netloc not in {"", "localhost"}:
            raise ValueError("vendor TP artifact_ref must be a local file reference")
        raw_path = unquote(parsed.path) if parsed.scheme == "file" else artifact_ref
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", raw_path):
            raw_path = raw_path[1:]
        path = Path(raw_path).resolve()
        if not any(path.is_relative_to(root) for root in self.source_artifact_roots):
            raise ValueError("vendor TP artifact is outside the controlled artifact roots")
        if not path.is_file():
            raise ValueError("vendor TP artifact does not exist")
        suffix = path.suffix.lower()
        if suffix not in _SOURCE_CONTENT_TYPES:
            raise ValueError("vendor TP artifact must be PDF or DOCX")
        size = path.stat().st_size
        if size <= 0 or size > _MAX_SOURCE_BYTES:
            raise ValueError("vendor TP artifact must be between 1 byte and 50 MiB")
        content = path.read_bytes()
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError("vendor TP artifact SHA-256 verification failed")
        filename = Path(_text(source.get("filename")) or path.name).name
        if Path(filename).suffix.lower() != suffix:
            raise ValueError("vendor TP filename extension must match the verified artifact")
        return {
            "path": path,
            "filename": filename,
            "sha256": actual_hash,
            "content": content,
            "content_type": _SOURCE_CONTENT_TYPES[suffix],
        }

    @staticmethod
    def _multipart_fields(request_payload: dict[str, Any]) -> dict[str, str]:
        fields: dict[str, str] = {}
        for key, value in request_payload.items():
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                fields[key] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            elif isinstance(value, bool):
                fields[key] = "true" if value else "false"
            else:
                fields[key] = str(value)
        return fields

    @staticmethod
    def _job_id(proposal_type: str, payload_hash: str) -> str:
        return f"existing-{_text(proposal_type).lower()}-{_text(payload_hash).lower()[:24]}"

    def _job_paths(self, job_id: str) -> tuple[Path, Path, Path]:
        if not re.fullmatch(r"existing-(?:cp|tp|amc)-[0-9a-f]{24}", job_id):
            raise ValueError("invalid existing Builder job id")
        directory = self.artifact_root / job_id
        return directory, directory / "proposal.docx", directory / "metadata.json"

    def _load_metadata(self, job_id: str) -> dict[str, Any] | None:
        _, docx_path, metadata_path = self._job_paths(job_id)
        if not metadata_path.exists():
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BuilderUnavailableError(f"stored Builder metadata is unreadable: {exc}") from exc
        if not isinstance(metadata, dict) or metadata.get("job_id") != job_id:
            raise BuilderUnavailableError("stored Builder metadata failed identity validation")
        if not docx_path.is_file():
            raise BuilderUnavailableError("stored Builder DOCX is missing")
        actual_hash = hashlib.sha256(docx_path.read_bytes()).hexdigest()
        if actual_hash != metadata.get("docx_sha256"):
            raise BuilderUnavailableError("stored Builder DOCX hash verification failed")
        return metadata

    def health(self) -> dict[str, Any]:
        result = super().health()
        result.update(
            {
                "build_transport": self.transport,
                "build_endpoint": "/api/generate",
                "tp_build_endpoint": "/api/generate-tp-vendor",
                "artifact_kinds": ["docx"],
            }
        )
        return result

    def validate_build(
        self,
        *,
        proposal_type: str,
        template_version: str,
        payload: dict[str, Any],
        payload_hash: str,
    ) -> dict[str, Any]:
        try:
            self._builder_payload(
                proposal_type=proposal_type,
                template_version=template_version,
                payload=payload,
                payload_hash=payload_hash,
            )
            self._source_artifact(payload, proposal_type)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "transport": self.transport}
        return {"valid": True, "errors": [], "transport": self.transport}

    @staticmethod
    def _error_payload(response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def create_build(
        self,
        *,
        proposal_type: str,
        template_version: str,
        payload: dict[str, Any],
        payload_hash: str,
    ) -> dict[str, Any]:
        request_payload = self._builder_payload(
            proposal_type=proposal_type,
            template_version=template_version,
            payload=payload,
            payload_hash=payload_hash,
        )
        source_artifact = self._source_artifact(payload, proposal_type)
        job_id = self._job_id(proposal_type, payload_hash)
        with self._archive_lock:
            existing = self._load_metadata(job_id)
            if existing:
                if existing.get("payload_sha256") != payload_hash.lower():
                    raise BuilderUnavailableError("stored Builder job payload hash does not match")
                return {"job_id": job_id, "state": existing["state"], "existing": True}

            if not self._authenticated:
                self._login()
            try:
                if source_artifact:
                    response = self.session.post(
                        f"{self.base_url}/api/generate-tp-vendor",
                        data=self._multipart_fields(request_payload),
                        files={
                            "file": (
                                source_artifact["filename"],
                                source_artifact["content"],
                                source_artifact["content_type"],
                            )
                        },
                        timeout=self.timeout_s,
                    )
                else:
                    response = self.session.post(
                        f"{self.base_url}/api/generate",
                        json=request_payload,
                        timeout=self.timeout_s,
                    )
            except Exception as exc:
                raise BuilderUnavailableError(f"Proposal Builder generation failed: {exc}") from exc
            if response.status_code in (401, 403):
                self._authenticated = False
                details = self._error_payload(response)
                raise BuilderAuthError(
                    details.get("error") or "Proposal Builder session was rejected",
                    http_status=response.status_code,
                    details=details,
                )
            if response.status_code >= 400:
                details = self._error_payload(response)
                raise BuilderQuoteRejected(
                    details.get("error") or details.get("message") or "Proposal Builder rejected the build",
                    rejection_code=str(details.get("code") or "BUILDER_BUILD_REJECTED"),
                    http_status=response.status_code,
                    details=details,
                )

            content = bytes(getattr(response, "content", b"") or b"")
            if not content.startswith(b"PK\x03\x04"):
                raise BuilderUnavailableError("Proposal Builder response is not a valid DOCX package")
            headers = getattr(response, "headers", {}) or {}
            content_type = _text(headers.get("content-type") or headers.get("Content-Type"))
            if content_type and _DOCX_CONTENT_TYPE not in content_type:
                raise BuilderUnavailableError(
                    f"Proposal Builder returned unexpected content type {content_type}"
                )
            content_disposition = _text(
                headers.get("content-disposition") or headers.get("Content-Disposition")
            )
            filename = _safe_filename(
                content_disposition,
                f"{request_payload['propNum']}_{request_payload['version']}_{proposal_type}.docx",
            )
            docx_hash = hashlib.sha256(content).hexdigest()
            if _text(proposal_type).upper() == "TP":
                from tp_fidelity import validate_tp_fidelity

                fidelity_validation = validate_tp_fidelity(
                    content,
                    request_payload=request_payload,
                    frozen_payload=payload,
                    source_content=source_artifact["content"] if source_artifact else None,
                    source_filename=source_artifact["filename"] if source_artifact else None,
                )
            else:
                fidelity_validation = {
                    "passed": True,
                    "checks": [
                        {"name": "frozen_builder_generation", "passed": True},
                        {"name": "docx_package_signature", "passed": True},
                        {"name": "frozen_payload_hash", "passed": True},
                    ],
                }
            directory, docx_path, metadata_path = self._job_paths(job_id)
            directory.mkdir(parents=True, exist_ok=True)
            temp_docx = directory / f"proposal.{os.getpid()}.tmp"
            temp_metadata = directory / f"metadata.{os.getpid()}.tmp"
            metadata = {
                "job_id": job_id,
                "state": "done" if fidelity_validation["passed"] else "quarantined",
                "transport": self.transport,
                "proposal_type": _text(proposal_type).upper(),
                "template_version": template_version,
                "payload_sha256": payload_hash.lower(),
                "docx_filename": filename,
                "docx_sha256": docx_hash,
                "docx_bytes": len(content),
                "content_type": content_type or _DOCX_CONTENT_TYPE,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_artifact": (
                    {
                        "filename": source_artifact["filename"],
                        "sha256": source_artifact["sha256"],
                    }
                    if source_artifact
                    else None
                ),
                "validation": fidelity_validation,
            }
            try:
                temp_docx.write_bytes(content)
                os.replace(temp_docx, docx_path)
                temp_metadata.write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                os.replace(temp_metadata, metadata_path)
            finally:
                temp_docx.unlink(missing_ok=True)
                temp_metadata.unlink(missing_ok=True)
            return {"job_id": job_id, "state": metadata["state"], "existing": False}

    def get_build(self, builder_job_id: str) -> dict[str, Any]:
        metadata = self._load_metadata(builder_job_id)
        if metadata is None:
            raise BuilderQuoteRejected(
                "unknown existing Builder job",
                rejection_code="BUILD_NOT_FOUND",
                http_status=404,
            )
        return {
            "job_id": builder_job_id,
            "state": metadata["state"],
            "transport": metadata["transport"],
        }

    def get_artifacts(self, builder_job_id: str) -> dict[str, Any]:
        metadata = self._load_metadata(builder_job_id)
        if metadata is None:
            raise BuilderQuoteRejected(
                "unknown existing Builder job",
                rejection_code="BUILD_NOT_FOUND",
                http_status=404,
            )
        _, docx_path, _ = self._job_paths(builder_job_id)
        return {
            "docx_ref": docx_path.as_uri(),
            "docx_sha256": metadata["docx_sha256"],
            "validation": metadata["validation"],
            "metadata": {
                "docx": {
                    "filename": metadata["docx_filename"],
                    "bytes": metadata["docx_bytes"],
                    "content_type": metadata["content_type"],
                    "payload_sha256": metadata["payload_sha256"],
                    "transport": metadata["transport"],
                }
            },
        }
