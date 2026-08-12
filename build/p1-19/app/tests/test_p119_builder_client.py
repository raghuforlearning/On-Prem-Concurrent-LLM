import unittest

from integrations.proposal_builder.client import ProposalBuilderClient


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
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


if __name__ == "__main__":
    unittest.main()
