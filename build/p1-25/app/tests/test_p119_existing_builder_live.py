"""Opt-in live acceptance tests for the frozen Proposal Builder transport.

The test uses only the Builder's documented runtime URL and service credentials
from the environment.  TP acceptance additionally requires a hash-pinned,
pre-existing vendor PDF/DOCX from a controlled input archive.  The test is
skipped during normal offline regression runs.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse
import unittest

from integrations.proposal_builder.existing import ExistingProposalBuilderClient


_MAX_VENDOR_TP_BYTES = 50 * 1024 * 1024
_VENDOR_TP_CONTENT_PREFIXES = {
    ".docx": b"PK\x03\x04",
    ".pdf": b"%PDF-",
}


def _payload_sha256(payload):
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _configured_source_roots(environment):
    configured = environment.get("PROPOSAL_BUILDER_SOURCE_ARTIFACT_ROOTS", "")
    if configured.strip():
        raw_roots = [item.strip() for item in configured.split(",") if item.strip()]
    else:
        artifact_root = environment.get(
            "PROPOSAL_BUILDER_ARTIFACT_ROOT", "/srv/data/proposal_artifacts"
        )
        raw_roots = [
            "/srv/data/rfp_archive",
            "/srv/data/quote_archive",
            artifact_root,
        ]
    roots = tuple(Path(item).expanduser().resolve() for item in raw_roots)
    if not roots or any(not item.is_absolute() for item in roots):
        raise ValueError("Proposal Builder source artifact roots must be absolute paths")
    return roots


def _configured_vendor_tp_artifact(environment=None):
    """Return a pinned, pre-existing vendor TP for the opt-in live test.

    A generated CP is deliberately not accepted as a TP fixture.  The operator
    must stage an actual vendor-supplied PDF/DOCX in a controlled source archive
    and pin its hash before enabling the live Builder test.
    """

    environment = os.environ if environment is None else environment
    configured_path = environment.get("P119_TEST_VENDOR_TP_PATH", "").strip()
    expected_hash = environment.get("P119_TEST_VENDOR_TP_SHA256", "").strip().lower()
    if not configured_path or not expected_hash:
        raise ValueError(
            "P119_TEST_VENDOR_TP_PATH and P119_TEST_VENDOR_TP_SHA256 are required "
            "for the live TP acceptance test"
        )
    if len(expected_hash) != 64 or any(
        character not in "0123456789abcdef" for character in expected_hash
    ):
        raise ValueError("P119_TEST_VENDOR_TP_SHA256 must be a lowercase SHA-256 digest")

    path = Path(configured_path).expanduser()
    if not path.is_absolute():
        raise ValueError("P119_TEST_VENDOR_TP_PATH must be an absolute local path")
    path = path.resolve()
    if not path.is_file():
        raise ValueError("configured live vendor TP does not exist")
    if not any(path.is_relative_to(root) for root in _configured_source_roots(environment)):
        raise ValueError("configured live vendor TP is outside the controlled artifact roots")

    artifact_root = Path(
        environment.get("PROPOSAL_BUILDER_ARTIFACT_ROOT", "/srv/data/proposal_artifacts")
    ).expanduser().resolve()
    if path.is_relative_to(artifact_root):
        raise ValueError(
            "live vendor TP must come from an input archive, not generated proposal artifacts"
        )

    suffix = path.suffix.lower()
    expected_prefix = _VENDOR_TP_CONTENT_PREFIXES.get(suffix)
    if expected_prefix is None:
        raise ValueError("configured live vendor TP must be PDF or DOCX")
    content = path.read_bytes()
    if not content or len(content) > _MAX_VENDOR_TP_BYTES:
        raise ValueError("configured live vendor TP must be between 1 byte and 50 MiB")
    if not content.startswith(expected_prefix):
        raise ValueError("configured live vendor TP content does not match its extension")
    actual_hash = hashlib.sha256(content).hexdigest()
    if not hmac.compare_digest(actual_hash, expected_hash):
        raise ValueError("configured live vendor TP SHA-256 verification failed")
    return {
        "artifact_ref": path.as_uri(),
        "filename": path.name,
        "sha256": actual_hash,
    }


def _live_payload(proposal_type):
    proposal_numbers = {
        "CP": "NL-PP-AN-996-26",
        "TP": "NL-PP-AN-997-26",
        "AMC": "NL-PP-AN-998-26",
    }
    builder_context = {
        "proposal_number": proposal_numbers[proposal_type],
        "proposal_version": "V1.0",
        "proposal_date": "2026-08-18",
        "client_name": "NationLabs Internal UAT",
        "client_location": "Dubai, UAE",
        "solution": "OP Manager",
        "executive_summary": (
            "Synthetic internal acceptance document for the Orchestrator adapter."
        ),
        "include_assumptions": False,
        "include_scope_of_work": False,
        "additional_notes": "Not for customer release.",
    }
    if proposal_type == "TP":
        builder_context.update(
            {
                "client_name": "CUS999",
                "client_real_name": "NationLabs Internal UAT",
                "client_aliases": ["NationLabs Internal UAT"],
                "mask_client": True,
                "customer_commercials": {
                    "currency": "AED",
                    "subtotal": "100.00",
                    "vat_rate": "5.00",
                    "vat_amount": "5.00",
                    "grand_total": "105.00",
                    "terms": {
                        "payment": "100% advance",
                        "validity": "30 days",
                        "delivery": "2 weeks",
                    },
                    "line_items": [
                        {
                            "line_no": 1,
                            "part_number": "UAT-ONLY",
                            "description": "Synthetic Orchestrator adapter acceptance item",
                            "quantity": "1",
                            "unit_price": "100.00",
                            "line_total": "100.00",
                        }
                    ],
                    "authority": {
                        "kind": "APPROVED_COSTING_SHEET",
                        "source_sha256": "c" * 64,
                        "approved_by": "finance.uat",
                        "approved_at": "2026-08-18T10:00:00+04:00",
                    },
                },
                "rag_provenance": {
                    "status": "APPROVED",
                    "draft_id": 1,
                    "retrieval_id": 1,
                    "reviewed_by": "technical.uat",
                    "reviewed_at": "2026-08-18T10:00:00+04:00",
                },
            }
        )
    if proposal_type == "AMC":
        builder_context["amc"] = {
            "total_users": "25",
            "site_visit_frequency": "Quarterly",
            "sla_tier": "Standard",
            "payment_terms": "Annual advance",
            "contract_duration": "12 months",
            "po_reference": "UAT-ONLY",
            "include_data_handling": False,
            "pre_amc_activities": [],
            "amc_coverage": [],
            "support_hours": [],
        }
    return {
        "schema_version": "p1-19.proposal_payload.v1",
        "proposal_type": proposal_type,
        "template_version": "builder-uat-v1",
        "opportunity": {"opp_id": "OPP-P119-LIVE-UAT"},
        "commercial": {
            "native_currency": "AED",
            "aed_total": "105.00",
            "terms": {
                "payment": "100% advance",
                "validity": "30 days",
                "delivery": "2 weeks",
            },
            "line_items": [
                {
                    "line_no": 1,
                    "part_number": "UAT-ONLY",
                    "description": "Synthetic Orchestrator adapter acceptance item",
                    "quantity": "1.0000",
                    "native_unit_price": "100.00",
                    "native_line_total": "100.00",
                    "aed_unit_price": "100.00",
                    "aed_line_total": "100.00",
                }
            ],
        },
        "context": {"proposal_builder": builder_context},
    }


@unittest.skipUnless(
    os.environ.get("P119_TEST_EXISTING_BUILDER_LIVE") == "1",
    "set P119_TEST_EXISTING_BUILDER_LIVE=1 to call the live frozen Builder",
)
class ExistingProposalBuilderLiveTests(unittest.TestCase):
    def test_cp_tp_and_amc_generate_archived_docx_artifacts(self):
        vendor_tp_artifact = _configured_vendor_tp_artifact()
        client = ExistingProposalBuilderClient(
            os.environ["PROPOSAL_BUILDER_URL"],
            os.environ["PROPOSAL_BUILDER_USERNAME"],
            os.environ["PROPOSAL_BUILDER_PASSWORD"],
            artifact_root=os.environ["PROPOSAL_BUILDER_ARTIFACT_ROOT"],
            source_artifact_roots=_configured_source_roots(os.environ),
            timeout_s=float(os.environ.get("PROPOSAL_BUILDER_TIMEOUT_S", "120")),
        )
        try:
            for proposal_type in ("CP", "TP", "AMC"):
                with self.subTest(proposal_type=proposal_type):
                    payload = _live_payload(proposal_type)
                    if proposal_type == "TP":
                        payload["context"]["proposal_builder"][
                            "vendor_tp_artifact"
                        ] = vendor_tp_artifact
                    payload_hash = _payload_sha256(payload)
                    validation = client.validate_build(
                        proposal_type=proposal_type,
                        template_version=payload["template_version"],
                        payload=payload,
                        payload_hash=payload_hash,
                    )
                    self.assertTrue(validation["valid"], validation)

                    created = client.create_build(
                        proposal_type=proposal_type,
                        template_version=payload["template_version"],
                        payload=payload,
                        payload_hash=payload_hash,
                    )
                    stored = client.get_build(created["job_id"])
                    artifacts = client.get_artifacts(created["job_id"])
                    expected_state = "done"
                    failure_details = artifacts.get("validation", artifacts)
                    self.assertEqual(created["state"], expected_state, failure_details)
                    self.assertEqual(stored["state"], expected_state, failure_details)

                    docx_path = Path(unquote(urlparse(artifacts["docx_ref"]).path))
                    content = docx_path.read_bytes()
                    self.assertTrue(content.startswith(b"PK\x03\x04"))
                    self.assertEqual(hashlib.sha256(content).hexdigest(), artifacts["docx_sha256"])
                    self.assertTrue(artifacts["validation"]["passed"])
                    self.assertGreater(len(content), 100_000)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
