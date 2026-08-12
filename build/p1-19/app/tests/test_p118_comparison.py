from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import unittest


APP_ROOT = Path(__file__).parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
os.environ.setdefault("PG_DSN", "postgresql://unused-for-pure-tests")

from quote_comparison import (  # noqa: E402
    RecordedRate,
    build_comparison_result,
    canonical_json,
    payload_sha256,
)


def _candidate(quote_id, vendor, currency, total, rate):
    subtotal = Decimal(str(total)) / Decimal("1.05")
    vat = Decimal(str(total)) - subtotal
    return {
        "quote_id": quote_id,
        "quote_group_id": f"group-{quote_id}",
        "quote_version_no": 1,
        "validation_id": quote_id + 100,
        "vendor_id": quote_id + 10,
        "vendor_name": vendor,
        "currency": currency,
        "native_subtotal": subtotal,
        "native_vat": vat,
        "native_total": total,
        "rate": rate,
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
                "unit_price": total,
                "line_total": total,
            }
        ],
    }


class DeterministicComparisonTests(unittest.TestCase):
    def test_three_vendor_result_is_order_independent_and_byte_stable(self):
        candidates = [
            _candidate(3, "Vendor C", "EUR", "8000", RecordedRate(9, "EUR", Decimal("4.1"), "2026-08-12", "finance-3")),
            _candidate(1, "Vendor A", "AED", "29925", RecordedRate.aed()),
            _candidate(2, "Vendor B", "USD", "7500", RecordedRate(8, "USD", Decimal("3.6725"), "2026-08-12", "finance-2")),
        ]
        first = build_comparison_result(candidates)
        second = build_comparison_result(reversed(candidates))
        self.assertEqual(canonical_json(first), canonical_json(second))
        self.assertEqual(payload_sha256(first), payload_sha256(second))
        self.assertEqual([row["vendor_name"] for row in first["quotes"]], ["Vendor A", "Vendor B", "Vendor C"])
        usd = first["quotes"][1]
        self.assertEqual(usd["native_total"], "7500.00")
        self.assertEqual(usd["aed_total"], "27543.75")
        self.assertEqual(usd["exchange_rate"]["source_reference"], "finance-2")

    def test_non_aed_quote_requires_matching_positive_recorded_rate(self):
        candidate = _candidate(2, "Vendor B", "USD", "100", RecordedRate.aed())
        with self.assertRaisesRegex(ValueError, "matching recorded exchange rate"):
            build_comparison_result([candidate, _candidate(1, "Vendor A", "AED", "100", RecordedRate.aed())])

    def test_comparison_module_has_no_llm_or_exchange_rate_network_dependency(self):
        source = (APP_ROOT / "quote_comparison.py").read_text(encoding="utf-8")
        for forbidden in ("import httpx", "import requests", "Ollama", "generate_grounded"):
            self.assertNotIn(forbidden, source)
        self.assertIn("canonical_json", source)
        self.assertIn("exchange_rates", source)


class ComparisonApiTests(unittest.TestCase):
    def test_api_exposes_record_compare_select_and_read_without_ai_calls(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")
        for route in (
            '@app.post("/exchange-rates")',
            '@app.post("/opportunities/{opp_id}/quote-comparisons")',
            '@app.get("/opportunities/{opp_id}/quote-comparisons")',
            '@app.post("/quote-comparisons/{comparison_run_id}/select")',
            '@app.get("/opportunities/{opp_id}/quote-selection")',
        ):
            self.assertIn(route, source)
        comparison_region = source.split("# ---------- P1-18", 1)[1].split("# ---------- P1-17", 1)[0]
        self.assertNotIn("OllamaClient", comparison_region)
        self.assertNotIn("httpx", comparison_region)


if __name__ == "__main__":
    unittest.main()
