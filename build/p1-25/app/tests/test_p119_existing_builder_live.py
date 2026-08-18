"""Opt-in live acceptance tests for the frozen Proposal Builder transport.

The test uses only the Builder's documented runtime URL and service credentials
from the environment.  It is skipped during normal offline regression runs.
"""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse
import unittest

from integrations.proposal_builder.existing import ExistingProposalBuilderClient


def _payload_sha256(payload):
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
        client = ExistingProposalBuilderClient(
            os.environ["PROPOSAL_BUILDER_URL"],
            os.environ["PROPOSAL_BUILDER_USERNAME"],
            os.environ["PROPOSAL_BUILDER_PASSWORD"],
            artifact_root=os.environ["PROPOSAL_BUILDER_ARTIFACT_ROOT"],
            timeout_s=float(os.environ.get("PROPOSAL_BUILDER_TIMEOUT_S", "120")),
        )
        try:
            generated_cp = None
            for proposal_type in ("CP", "TP", "AMC"):
                with self.subTest(proposal_type=proposal_type):
                    payload = _live_payload(proposal_type)
                    if proposal_type == "TP":
                        self.assertIsNotNone(generated_cp)
                        payload["context"]["proposal_builder"]["vendor_tp_artifact"] = {
                            "artifact_ref": generated_cp["docx_ref"],
                            "filename": "synthetic-vendor-technical-proposal.docx",
                            "sha256": generated_cp["docx_sha256"],
                        }
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
                    self.assertEqual(created["state"], "done")
                    self.assertEqual(client.get_build(created["job_id"])["state"], "done")

                    artifacts = client.get_artifacts(created["job_id"])
                    docx_path = Path(unquote(urlparse(artifacts["docx_ref"]).path))
                    content = docx_path.read_bytes()
                    self.assertTrue(content.startswith(b"PK\x03\x04"))
                    self.assertEqual(hashlib.sha256(content).hexdigest(), artifacts["docx_sha256"])
                    self.assertTrue(artifacts["validation"]["passed"])
                    self.assertGreater(len(content), 100_000)
                    if proposal_type == "CP":
                        generated_cp = artifacts
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
