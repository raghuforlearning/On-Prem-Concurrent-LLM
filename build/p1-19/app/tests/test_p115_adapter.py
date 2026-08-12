import json
from pathlib import Path
import unittest

from integrations.proposal_builder.client import (
    BuilderAuthError,
    BuilderQuoteRejected,
    ProposalBuilderClient,
)


FIXTURE = Path(__file__).parent / "fixtures" / "quotes" / "builder-success.json"


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


class ProposalBuilderAdapterTests(unittest.TestCase):
    def test_health_uses_existing_public_env_endpoint(self):
        session = FakeSession([FakeResponse(200, {"env": "UAT"})])
        client = ProposalBuilderClient("http://builder", "svc", "secret", session=session)
        self.assertEqual(client.health(), {"status": "ok", "environment": "UAT"})
        self.assertTrue(session.calls[0][1].endswith("/api/env"))

    def test_login_then_extract_uses_public_quote_endpoint(self):
        success = json.loads(FIXTURE.read_text())
        session = FakeSession([FakeResponse(200, {"ok": True}), FakeResponse(200, success)])
        client = ProposalBuilderClient("http://builder", "svc", "secret", session=session)
        result = client.extract_quote(b"quote", "vendor.pdf", "application/pdf")
        self.assertEqual(len(result.items), 2)
        self.assertTrue(session.calls[0][1].endswith("/api/login"))
        self.assertTrue(session.calls[1][1].endswith("/api/extract-quote"))
        self.assertIn("file", session.calls[1][2]["files"])

    def test_builder_rejection_is_typed_for_review_queue(self):
        session = FakeSession([
            FakeResponse(200, {"ok": True}),
            FakeResponse(422, {"code": "QUOTE_NOT_RECONCILED", "error": "totals disagree"}),
        ])
        client = ProposalBuilderClient("http://builder", "svc", "secret", session=session)
        with self.assertRaises(BuilderQuoteRejected) as raised:
            client.extract_quote(b"quote", "bad.pdf", "application/pdf")
        self.assertEqual(raised.exception.code, "QUOTE_NOT_RECONCILED")
        self.assertEqual(raised.exception.http_status, 422)

    def test_missing_credentials_is_explicit_auth_failure(self):
        client = ProposalBuilderClient("http://builder", "", "", session=FakeSession([]))
        with self.assertRaises(BuilderAuthError):
            client.extract_quote(b"quote", "vendor.pdf")


if __name__ == "__main__":
    unittest.main()
