import ast
from decimal import Decimal
from pathlib import Path
import unittest

from quote_validation import (
    CommercialClaims,
    ValidationLine,
    ValidationPolicy,
    validate_quote,
)


def valid_lines():
    return (
        ValidationLine.create(1, 2, "12500.00", "25000.00"),
        ValidationLine.create(2, 1, "3500.00", "3500.00"),
    )


def strict_claims():
    return CommercialClaims.create(
        stated_subtotal="28500.00",
        vat_rate_percent="5",
        stated_vat="1425.00",
        stated_total="29925.00",
        validity_terms="30 days",
        payment_terms="30 days from invoice",
        delivery_terms="2-4 weeks",
    )


def strict_policy():
    return ValidationPolicy(
        require_currency_detected=True,
        require_stated_totals=True,
        require_vat=True,
        required_terms=("validity", "payment", "delivery"),
    )


class DeterministicQuoteValidationTests(unittest.TestCase):
    def test_valid_quote_proceeds_with_exact_computed_totals(self):
        result = validate_quote(
            valid_lines(),
            currency="aed",
            currency_detected=True,
            claims=strict_claims(),
            policy=strict_policy(),
        )
        self.assertEqual(result.status, "VALIDATED")
        self.assertTrue(result.may_proceed)
        self.assertEqual(result.currency, "AED")
        self.assertEqual(result.computed_subtotal, Decimal("28500.00"))
        self.assertEqual(result.computed_vat, Decimal("1425.00"))
        self.assertEqual(result.computed_total, Decimal("29925.00"))
        self.assertEqual(result.issues, ())

    def test_seeded_arithmetic_error_is_blocked_every_run(self):
        bad_lines = (
            ValidationLine.create(1, 2, "12500.00", "25001.00"),
            ValidationLine.create(2, 1, "3500.00", "3500.00"),
        )
        outcomes = [
            validate_quote(
                bad_lines,
                currency="AED",
                currency_detected=True,
                claims=strict_claims(),
                policy=strict_policy(),
            )
            for _ in range(20)
        ]
        self.assertTrue(all(result.status == "BLOCKED" for result in outcomes))
        self.assertTrue(all(not result.may_proceed for result in outcomes))
        self.assertTrue(
            all("LINE_TOTAL_MISMATCH" in {i.code for i in result.issues} for result in outcomes)
        )
        self.assertEqual({result.computed_total for result in outcomes}, {Decimal("29925.00")})

    def test_subtotal_vat_and_total_claims_are_independently_checked(self):
        claims = CommercialClaims.create(
            stated_subtotal="28501.00",
            vat_rate_percent="5",
            stated_vat="1400.00",
            stated_total="29900.00",
            validity_terms="30 days",
            payment_terms="advance",
            delivery_terms="stock",
        )
        result = validate_quote(
            valid_lines(),
            currency="AED",
            currency_detected=True,
            claims=claims,
            policy=strict_policy(),
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(
            {issue.code for issue in result.issues},
            {"SUBTOTAL_MISMATCH", "VAT_MISMATCH", "TOTAL_MISMATCH"},
        )

    def test_assumed_currency_and_required_terms_need_human_review(self):
        claims = CommercialClaims.create(
            stated_subtotal="28500",
            vat_rate_percent="5",
            stated_vat="1425",
            stated_total="29925",
        )
        result = validate_quote(
            valid_lines(),
            currency="AED",
            currency_detected=False,
            claims=claims,
            policy=strict_policy(),
        )
        self.assertEqual(result.status, "NEEDS_REVIEW")
        self.assertFalse(result.may_proceed)
        self.assertEqual(
            {issue.code for issue in result.issues},
            {
                "CURRENCY_NOT_CONFIRMED",
                "VALIDITY_TERMS_REQUIRED",
                "PAYMENT_TERMS_REQUIRED",
                "DELIVERY_TERMS_REQUIRED",
            },
        )

    def test_validation_engine_has_only_standard_library_imports(self):
        module_path = Path(__file__).parents[1] / "quote_validation.py"
        tree = ast.parse(module_path.read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertEqual(imports, {"dataclasses", "decimal", "typing"})


if __name__ == "__main__":
    unittest.main()
