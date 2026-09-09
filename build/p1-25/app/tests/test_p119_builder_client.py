import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from integrations.proposal_builder.client import ProposalBuilderClient
from integrations.proposal_builder.client import BuilderUnavailableError
from integrations.proposal_builder.existing import ExistingProposalBuilderClient


class FakeResponse:
    def __init__(self, status_code, payload=None, *, content=b"", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("response is not JSON")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    def close(self):
        pass


class ProposalBuilderBuildContractTests(unittest.TestCase):
    def test_validate_and_create_use_documented_v1_build_contract(self):
        session = FakeSession(
            [
                FakeResponse(200, {"valid": True, "errors": []}),
                FakeResponse(200, {"job_id": "builder-job-1"}),
            ]
        )
        client = ProposalBuilderClient("http://builder", "", "", session=session)
        payload = {"commercial": {"aed_total": "100.00"}}
        valid = client.validate_build(
            proposal_type="CP",
            template_version="cp-v1",
            payload=payload,
            payload_hash="hash-1",
        )
        created = client.create_build(
            proposal_type="CP",
            template_version="cp-v1",
            payload=payload,
            payload_hash="hash-1",
        )
        self.assertTrue(valid["valid"])
        self.assertEqual(created["job_id"], "builder-job-1")
        self.assertTrue(session.calls[0][1].endswith("/api/v1/builds/validate"))
        self.assertTrue(session.calls[1][1].endswith("/api/v1/builds"))
        self.assertEqual(session.calls[1][2]["json"]["type"], "cp")
        self.assertEqual(session.calls[1][2]["json"]["payload_hash"], "hash-1")

    def test_build_contract_does_not_require_legacy_quote_login(self):
        session = FakeSession([FakeResponse(200, {"job_id": "builder-job-1"})])
        client = ProposalBuilderClient("http://builder", "svc", "secret", session=session)
        client.create_build(
            proposal_type="CP",
            template_version="cp-v1",
            payload={"commercial": {}},
            payload_hash="hash-1",
        )
        self.assertEqual(len(session.calls), 1)
        self.assertTrue(session.calls[0][1].endswith("/api/v1/builds"))

    def test_get_build_and_artifacts_use_documented_v1_paths(self):
        session = FakeSession(
            [
                FakeResponse(200, {"state": "done"}),
                FakeResponse(
                    200,
                    {
                        "docx_ref": "artifact://cp.docx",
                        "docx_sha256": "a" * 64,
                        "pdf_ref": "artifact://cp.pdf",
                        "pdf_sha256": "b" * 64,
                        "metadata": {"commercial_payload_hash": "hash-1"},
                    },
                ),
            ]
        )
        client = ProposalBuilderClient("http://builder", "", "", session=session)
        self.assertEqual(client.get_build("job-1")["state"], "done")
        self.assertEqual(client.get_artifacts("job-1")["docx_ref"], "artifact://cp.docx")
        self.assertTrue(session.calls[0][1].endswith("/api/v1/builds/job-1"))
        self.assertTrue(session.calls[1][1].endswith("/api/v1/builds/job-1/artifacts"))


def _frozen_payload(proposal_type="CP"):
    context = {
        "proposal_builder": {
            "proposal_number": "NL-PP-AN-999-26",
            "proposal_version": "V1.0",
            "proposal_date": "2026-08-17",
            "client_name": "NationLabs UAT",
            "client_location": "Internal",
            "solution": "Adapter Contract Test",
            "executive_summary": "Synthetic internal UAT document.",
            "include_assumptions": False,
        }
    }
    if proposal_type in {"CP", "TP"}:
        context["proposal_builder"]["customer_commercials"] = {
            "currency": "AED",
            "subtotal": "150.00",
            "vat_rate": "5.00",
            "vat_amount": "7.50",
            "grand_total": "157.50",
            "terms": {
                "payment": "30 days",
                "validity": "30 days",
                "delivery": "2 weeks",
            },
            "line_items": [
                {
                    "line_no": 1,
                    "part_number": "TEST-1",
                    "description": "Synthetic customer line",
                    "quantity": "2",
                    "unit_price": "75.00",
                    "line_total": "150.00",
                }
            ],
            "authority": {
                "kind": "APPROVED_COSTING_SHEET",
                "source_sha256": "c" * 64,
                "approved_by": "finance.test",
                "approved_at": "2026-08-18T10:00:00+04:00",
            },
        }
    if proposal_type == "TP":
        context["proposal_builder"].update(
            {
                "client_name": "CUS999",
                "client_real_name": "NationLabs UAT",
                "client_aliases": ["NationLabs UAT"],
                "mask_client": True,
                "rag_provenance": {
                    "status": "APPROVED",
                    "draft_id": 1,
                    "retrieval_id": 1,
                    "reviewed_by": "technical.test",
                    "reviewed_at": "2026-08-18T10:00:00+04:00",
                },
            }
        )
    if proposal_type == "AMC":
        context["proposal_builder"]["amc"] = {
            "total_users": "25",
            "site_visit_frequency": "Quarterly",
            "sla_tier": "Standard",
            "payment_terms": "Annual advance",
            "contract_duration": "12 months",
            "po_reference": "UAT-PO",
            "include_data_handling": False,
            "pre_amc_activities": [],
            "amc_coverage": ["Remote support"],
            "support_hours": ["Business hours"],
        }
    return {
        "schema_version": "p1-19.proposal_payload.v1",
        "proposal_type": proposal_type,
        "template_version": "template-v1",
        "opportunity": {"opp_id": "OPP-UAT"},
        "commercial": {
            "native_currency": "USD",
            "aed_total": "385.65",
            "terms": {
                "payment": "30 days",
                "validity": "30 days",
                "delivery": "2 weeks",
            },
            "line_items": [
                {
                    "line_no": 1,
                    "part_number": "TEST-1",
                    "description": "Synthetic line",
                    "quantity": "2.0000",
                    "native_unit_price": "50.00",
                    "native_line_total": "100.00",
                    "aed_unit_price": "183.50",
                    "aed_line_total": "367.00",
                }
            ],
        },
        "context": context,
    }


def _hash(payload):
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ExistingProposalBuilderContractTests(unittest.TestCase):
    def test_maps_cp_tp_and_amc_without_changing_accepted_money(self):
        for proposal_type in ("CP", "TP", "AMC"):
            with self.subTest(proposal_type=proposal_type):
                payload = _frozen_payload(proposal_type)
                mapped = ExistingProposalBuilderClient._builder_payload(
                    proposal_type=proposal_type,
                    template_version="template-v1",
                    payload=payload,
                    payload_hash=_hash(payload),
                )
                self.assertEqual(mapped["type"], proposal_type)
                if proposal_type in {"CP", "TP"}:
                    self.assertEqual(mapped["terms"]["currency"], "AED")
                    self.assertEqual(mapped["boq"][0]["up"], "75.00")
                    self.assertEqual(mapped["boq"][0]["total"], "150.00")
                    self.assertEqual(mapped["expectedValue"], 157.5)
                else:
                    self.assertEqual(mapped["terms"]["currency"], "USD")
                    self.assertEqual(mapped["boq"][0]["up"], "50.00")
                    self.assertEqual(mapped["boq"][0]["total"], "100.00")
                    self.assertEqual(mapped["expectedValue"], 385.65)
        self.assertEqual(mapped["amcTrack"], "nl-owned")
        self.assertEqual(mapped["commercials"][0]["amount"], 100.0)

    def test_sync_build_archives_docx_and_is_idempotent(self):
        payload = _frozen_payload("CP")
        payload_hash = _hash(payload)
        docx = b"PK\x03\x04synthetic-docx"
        session = FakeSession(
            [
                FakeResponse(200, {"ok": True}),
                FakeResponse(
                    200,
                    content=docx,
                    headers={
                        "content-type": (
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document"
                        ),
                        "content-disposition": 'attachment; filename="NL-PP-AN-999-26_V1.0_UAT_CP_Test.docx"',
                    },
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            client = ExistingProposalBuilderClient(
                "http://builder",
                "svc",
                "secret",
                artifact_root=directory,
                session=session,
            )
            self.assertTrue(
                client.validate_build(
                    proposal_type="CP",
                    template_version="template-v1",
                    payload=payload,
                    payload_hash=payload_hash,
                )["valid"]
            )
            created = client.create_build(
                proposal_type="CP",
                template_version="template-v1",
                payload=payload,
                payload_hash=payload_hash,
            )
            repeated = client.create_build(
                proposal_type="CP",
                template_version="template-v1",
                payload=payload,
                payload_hash=payload_hash,
            )
            self.assertFalse(created["existing"])
            self.assertTrue(repeated["existing"])
            self.assertEqual(created["job_id"], repeated["job_id"])
            self.assertEqual(len(session.calls), 2)
            self.assertTrue(session.calls[1][1].endswith("/api/generate"))
            self.assertEqual(session.calls[1][2]["json"]["boq"][0]["total"], "150.00")
            self.assertEqual(client.get_build(created["job_id"])["state"], "done")
            artifacts = client.get_artifacts(created["job_id"])
            self.assertEqual(artifacts["docx_sha256"], hashlib.sha256(docx).hexdigest())
            self.assertTrue(artifacts["validation"]["passed"])
            self.assertEqual(len(list(Path(directory).rglob("proposal.docx"))), 1)

    def test_tp_uses_verified_vendor_artifact_multipart_contract(self):
        docx = b"PK\x03\x04synthetic-builder-result"
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "vendor-technical-proposal.docx"
            source_content = b"PK\x03\x04synthetic-vendor-tp"
            source_path.write_bytes(source_content)
            payload = _frozen_payload("TP")
            payload["context"]["proposal_builder"]["vendor_tp_artifact"] = {
                "artifact_ref": source_path.as_uri(),
                "filename": source_path.name,
                "sha256": hashlib.sha256(source_content).hexdigest(),
            }
            session = FakeSession(
                [
                    FakeResponse(200, {"ok": True}),
                    FakeResponse(
                        200,
                        content=docx,
                        headers={
                            "content-type": (
                                "application/vnd.openxmlformats-officedocument."
                                "wordprocessingml.document"
                            )
                        },
                    ),
                ]
            )
            client = ExistingProposalBuilderClient(
                "http://builder",
                "svc",
                "secret",
                artifact_root=directory,
                source_artifact_roots=[directory],
                session=session,
            )
            payload_hash = _hash(payload)
            self.assertTrue(
                client.validate_build(
                    proposal_type="TP",
                    template_version="template-v1",
                    payload=payload,
                    payload_hash=payload_hash,
                )["valid"]
            )
            created = client.create_build(
                proposal_type="TP",
                template_version="template-v1",
                payload=payload,
                payload_hash=payload_hash,
            )
            self.assertEqual(created["state"], "quarantined")
            method, url, kwargs = session.calls[1]
            self.assertEqual(method, "POST")
            self.assertTrue(url.endswith("/api/generate-tp-vendor"))
            self.assertEqual(kwargs["files"]["file"][0], source_path.name)
            self.assertEqual(kwargs["files"]["file"][1], source_content)
            self.assertEqual(json.loads(kwargs["data"]["boq"])[0]["total"], "150.00")
            self.assertEqual(kwargs["data"]["client"], "CUS999")
            self.assertEqual(kwargs["data"]["clientRealName"], "NationLabs UAT")
            self.assertEqual(kwargs["data"]["clientAliases"], "NationLabs UAT")
            self.assertEqual(kwargs["data"]["maskClient"], "true")

    def test_tp_source_artifact_must_be_inside_controlled_roots(self):
        with tempfile.TemporaryDirectory() as artifacts, tempfile.TemporaryDirectory() as outside:
            source_path = Path(outside) / "vendor-tp.pdf"
            source_content = b"%PDF-1.4 synthetic"
            source_path.write_bytes(source_content)
            payload = _frozen_payload("TP")
            payload["context"]["proposal_builder"]["vendor_tp_artifact"] = {
                "artifact_ref": source_path.as_uri(),
                "sha256": hashlib.sha256(source_content).hexdigest(),
            }
            client = ExistingProposalBuilderClient(
                "http://builder",
                "svc",
                "secret",
                artifact_root=artifacts,
                source_artifact_roots=[artifacts],
                session=FakeSession([]),
            )
            validation = client.validate_build(
                proposal_type="TP",
                template_version="template-v1",
                payload=payload,
                payload_hash=_hash(payload),
            )
            self.assertFalse(validation["valid"])
            self.assertIn("controlled artifact roots", validation["errors"][0])

    def test_validation_fails_closed_on_hash_or_context_mismatch(self):
        payload = _frozen_payload("CP")
        with tempfile.TemporaryDirectory() as directory:
            client = ExistingProposalBuilderClient(
                "http://builder",
                "svc",
                "secret",
                artifact_root=directory,
                session=FakeSession([]),
            )
            result = client.validate_build(
                proposal_type="CP",
                template_version="template-v1",
                payload=payload,
                payload_hash="0" * 64,
            )
            self.assertFalse(result["valid"])
            self.assertIn("does not match", result["errors"][0])

    def test_cp_without_approved_customer_commercials_is_rejected(self):
        payload = _frozen_payload("CP")
        del payload["context"]["proposal_builder"]["customer_commercials"]
        with tempfile.TemporaryDirectory() as directory:
            client = ExistingProposalBuilderClient(
                "http://builder",
                "svc",
                "secret",
                artifact_root=directory,
                session=FakeSession([]),
            )
            result = client.validate_build(
                proposal_type="CP",
                template_version="template-v1",
                payload=payload,
                payload_hash=_hash(payload),
            )
            self.assertFalse(result["valid"])
            self.assertIn("approved costing sheet", result["errors"][0])

    def test_sync_build_rejects_non_docx_response(self):
        payload = _frozen_payload("CP")
        session = FakeSession(
            [
                FakeResponse(200, {"ok": True}),
                FakeResponse(200, content=b"not-a-docx", headers={"content-type": "text/plain"}),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            client = ExistingProposalBuilderClient(
                "http://builder",
                "svc",
                "secret",
                artifact_root=directory,
                session=session,
            )
            with self.assertRaisesRegex(BuilderUnavailableError, "valid DOCX"):
                client.create_build(
                    proposal_type="CP",
                    template_version="template-v1",
                    payload=payload,
                    payload_hash=_hash(payload),
                )
            self.assertEqual(list(Path(directory).rglob("proposal.docx")), [])


if __name__ == "__main__":
    unittest.main()
