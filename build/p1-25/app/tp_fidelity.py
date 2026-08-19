"""Deterministic P1-20 structural fidelity checks for generated TP DOCX files.

This module validates Proposal Builder output.  It does not generate or edit
Word documents and therefore keeps the frozen Builder as the sole document
owner.  Visual raster comparison remains a document-worker responsibility.
"""
from __future__ import annotations

from io import BytesIO
import re
from typing import Any
import zipfile

from docx import Document


PROFILE_VERSION = "p1-20.tp-golden.v1"
GOLDEN_INLINE_SHAPES = 16
_REQUIRED_HEADINGS = ("proposed boq", "commercials", "acceptance")
_FORBIDDEN_CUSTOMER_LABELS = (
    "vendor cost",
    "buy price",
    "purchase cost",
    "internal cost",
    "gross margin",
    "margin %",
    "markup %",
)


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").replace("\ufffd", " ").split()).casefold()


def _heading_name(value: str) -> str:
    value = re.sub(r"^\s*\d+(?:\.\d+)*\s*[.)-]?\s*", "", value)
    return _normalized(value)


def _check(name: str, passed: bool, details: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "details": details}


def validate_tp_fidelity(
    content: bytes,
    *,
    request_payload: dict[str, Any],
    frozen_payload: dict[str, Any],
) -> dict[str, Any]:
    """Return a fail-closed, JSON-serializable validation report."""
    checks: list[dict[str, Any]] = []
    try:
        document = Document(BytesIO(content))
        with zipfile.ZipFile(BytesIO(content)) as archive:
            names = archive.namelist()
            media_parts = [name for name in names if name.startswith("word/media/")]
            drawing_elements = sum(
                archive.read(name).count(b"<w:drawing")
                for name in names
                if name.startswith("word/") and name.endswith(".xml")
            )
    except Exception as exc:
        return {
            "passed": False,
            "profile": PROFILE_VERSION,
            "checks": [_check("valid_docx_package", False, str(exc))],
            "metrics": {},
        }

    checks.append(_check("valid_docx_package", True, "DOCX opened successfully"))
    headings = [
        _heading_name(paragraph.text)
        for paragraph in document.paragraphs
        if paragraph.text.strip() and paragraph.style.name.casefold().startswith("heading")
    ]
    positions: list[int] = []
    for expected in _REQUIRED_HEADINGS:
        matches = [index for index, heading in enumerate(headings) if heading == expected]
        positions.append(matches[0] if len(matches) == 1 else -1)
    ordered = all(position >= 0 for position in positions) and positions == sorted(positions)
    adjacent = ordered and positions[1] == positions[0] + 1 and positions[2] == positions[1] + 1
    checks.append(
        _check(
            "tp_section_order",
            ordered and adjacent,
            {
                "required": list(_REQUIRED_HEADINGS),
                "positions": positions,
                "headings": headings,
                "commercials_immediately_after_boq": adjacent,
            },
        )
    )

    table_headers = []
    for table in document.tables:
        if table.rows:
            table_headers.append([_normalized(cell.text) for cell in table.rows[0].cells])
    boq_table = any(
        all(label in headers for label in ("s.no", "part number", "description", "qty"))
        for headers in table_headers
    )
    commercial_table = any(
        all(
            any(required in header for header in headers)
            for required in ("part number", "description", "qty", "unit price", "total")
        )
        for headers in table_headers
    )
    checks.append(
        _check(
            "boq_and_commercial_tables",
            boq_table and commercial_table,
            {"boq_table": boq_table, "commercial_table": commercial_table},
        )
    )

    all_text = "\n".join(
        [paragraph.text for paragraph in document.paragraphs]
        + [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    )
    normalized_text = _normalized(all_text)
    missing_facts: list[str] = []
    for item in request_payload.get("boq") or []:
        for field in ("pn", "desc", "qty", "up", "total"):
            value = _normalized(item.get(field))
            if value and value not in normalized_text:
                missing_facts.append(f"boq[{item.get('sno')}].{field}={item.get(field)}")
    expected_value = str(request_payload.get("expectedValue") or "").rstrip("0").rstrip(".")
    if expected_value and expected_value not in normalized_text:
        missing_facts.append(f"expectedValue={request_payload.get('expectedValue')}")
    terms = request_payload.get("terms") if isinstance(request_payload.get("terms"), dict) else {}
    for field in ("payment", "currency", "validity", "delivery"):
        value = _normalized(terms.get(field))
        if value and value not in normalized_text:
            missing_facts.append(f"terms.{field}={terms.get(field)}")
    checks.append(
        _check(
            "approved_commercial_facts_present",
            not missing_facts,
            {"missing": missing_facts},
        )
    )

    leaked_labels = [label for label in _FORBIDDEN_CUSTOMER_LABELS if label in normalized_text]
    checks.append(
        _check(
            "no_internal_commercial_labels",
            not leaked_labels,
            {"forbidden_labels_found": leaked_labels},
        )
    )

    context = frozen_payload.get("context")
    builder_context = context.get("proposal_builder", context) if isinstance(context, dict) else {}
    rag = builder_context.get("rag_provenance") if isinstance(builder_context, dict) else None
    rag_valid = bool(
        isinstance(rag, dict)
        and _normalized(rag.get("status")) == "approved"
        and rag.get("draft_id")
        and rag.get("retrieval_id")
        and str(rag.get("reviewed_by") or "").strip()
        and str(rag.get("reviewed_at") or "").strip()
    )
    checks.append(
        _check(
            "approved_rag_provenance",
            rag_valid,
            "approved draft/retrieval/reviewer provenance is required",
        )
    )

    inline_shapes = len(document.inline_shapes)
    checks.append(
        _check(
            "golden_inline_shape_floor",
            inline_shapes >= GOLDEN_INLINE_SHAPES,
            {"actual": inline_shapes, "required_minimum": GOLDEN_INLINE_SHAPES},
        )
    )

    metrics = {
        "paragraphs": len(document.paragraphs),
        "tables": len(document.tables),
        "inline_shapes": inline_shapes,
        "media_parts": len(media_parts),
        "drawing_elements": drawing_elements,
        "sections": len(document.sections),
    }
    return {
        "passed": all(check["passed"] for check in checks),
        "profile": PROFILE_VERSION,
        "checks": checks,
        "metrics": metrics,
        "visual_review_required": True,
    }
