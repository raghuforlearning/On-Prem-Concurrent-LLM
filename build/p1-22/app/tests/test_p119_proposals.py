from decimal import Decimal
import os
from pathlib import Path
import sys
import unittest


APP_ROOT = Path(__file__).parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
os.environ.setdefault("PG_DSN", "postgresql://unused-for-pure-tests")

from proposals import _artifact_rows, _builder_state  # noqa: E402
from quote_comparison import RecordedRate, build_comparison_result, payload_sha256  # noqa: E402


def _candidate(quote_id, vendor, total):
    return {
        "quote_id": quote_id,
        "quote_group_id": f"group-{quote_id}",
        "quote_version_no": 1,
        "validation_id": quote_id + 100,
        "vendor_id": quote_id + 10,
        "vendor_name": vendor,
        "currency": "AED",
        "native_subtotal": Decimal(str(total)),
        "native_vat": Decimal(str(total)) * Decimal("0.05"),
        "native_total": Decimal(str(total)) * Decimal("1.05"),
        "rate": RecordedRate.aed(),
        "terms": {"validity": "30 days", "payment": "30 days", "delivery": "2 weeks"},
        "deal_registration": {
            "required": False,
            "status": "NOT_REQUIRED",
            "reference": None,
            "validity": None,
            "proposal_gate_satisfied": True,
        },
        "line_items": [
            {
                "line_no": 1,
                "part_number": f"SKU-{quote_id}",
                "description": "Firewall",
                "quantity": Decimal("1.0000"),
                "unit_price": Decimal(str(total)),
                "line_total": Decimal(str(total)),
            }
        ],
    }


class ProposalHandoffPureTests(unittest.TestCase):
    def test_selected_commercial_payload_hash_remains_deterministic(self):
        comparison = build_comparison_result(
            [_candidate(2, "Vendor B", "20000"), _candidate(1, "Vendor A", "10000")]
        )
        selected = comparison["quotes"][0]
        self.assertEqual(selected["vendor_name"], "Vendor A")
        self.assertEqual(payload_sha256(selected), payload_sha256(dict(reversed(list(selected.items())))))
        self.assertEqual(selected["aed_total"], "10500.00")

    def test_builder_state_mapping_keeps_quarantine_and_human_review_path(self):
        self.assertEqual(_builder_state("queued"), "SUBMITTED")
        self.assertEqual(_builder_state("validating"), "RUNNING")
        self.assertEqual(_builder_state("done"), "DONE")
        self.assertEqual(_builder_state("quarantined"), "QUARANTINED")

    def test_artifact_rows_require_builder_supplied_sha256(self):
        rows = _artifact_rows(
            {
                "docx_ref": "artifact://cp.docx",
                "docx_sha256": "a" * 64,
                "pdf_ref": "artifact://cp.pdf",
                "pdf_sha256": "b" * 64,
                "metadata": {"docx": {"template": "cp-v1"}},
            }
        )
        self.assertEqual([row["kind"] for row in rows], ["docx", "pdf"])
        self.assertEqual(rows[0]["metadata"], {"template": "cp-v1"})
        with self.assertRaisesRegex(ValueError, "sha256"):
            _artifact_rows({"docx_ref": "artifact://missing-hash.docx"})


class ProposalApiSurfaceTests(unittest.TestCase):
    def test_api_exposes_p119_handoff_routes_without_builder_implementation(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")
        for route in (
            '@app.post("/proposals/{proposal_type}/assemble")',
            '@app.post("/proposals/{proposal_id}/build")',
            '@app.post("/proposal-build-jobs/{build_job_id}/refresh")',
            '@app.get("/proposals/{proposal_id}/artifacts")',
        ):
            self.assertIn(route, source)
        p119_region = source.split("# ---------- P1-19", 1)[1].split("# ---------- P1-17", 1)[0]
        self.assertNotIn("OllamaClient", p119_region)

    def test_orchestrator_does_not_copy_document_generation_logic(self):
        source = (APP_ROOT / "proposals.py").read_text(encoding="utf-8")
        for forbidden in ("win32com", "Document(", "openpyxl", "mailmerge", "docx.Document"):
            self.assertNotIn(forbidden, source)
        self.assertIn("ProposalBuilderBuildAdapter", source)
        self.assertIn("payload_sha256", source)


if __name__ == "__main__":
    unittest.main()
