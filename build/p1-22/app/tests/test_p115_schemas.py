import json
from pathlib import Path
import unittest

from integrations.proposal_builder.schemas import QuoteContractError, QuoteExtractionResult


FIXTURE = Path(__file__).parent / "fixtures" / "quotes" / "builder-success.json"


class QuoteSchemaTests(unittest.TestCase):
    def test_normalizes_frozen_builder_wire_shape(self):
        result = QuoteExtractionResult.from_builder(json.loads(FIXTURE.read_text()))
        self.assertEqual(result.currency, "AED")
        self.assertEqual(len(result.items), 2)
        self.assertEqual(result.items[0].part_number, "FG-100F-BDL")
        self.assertEqual(str(result.items[0].quantity), "2")
        self.assertEqual(str(result.items[0].unit_price), "12500.0")

    def test_rejects_success_without_line_items(self):
        with self.assertRaisesRegex(QuoteContractError, "no line items"):
            QuoteExtractionResult.from_builder({"ok": True, "items": [], "currency": "AED"})

    def test_rejects_invalid_money_contract(self):
        payload = json.loads(FIXTURE.read_text())
        payload["items"][0]["total"] = "not-money"
        with self.assertRaisesRegex(QuoteContractError, "not numeric"):
            QuoteExtractionResult.from_builder(payload)


if __name__ == "__main__":
    unittest.main()
