"""P1-16 deterministic quote validation.

This module deliberately has no LLM, HTTP, database or Proposal Builder
dependency.  It validates the structured commercial claims already accepted at
the Orchestrator boundary and never rewrites vendor-supplied figures.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable


ENGINE_VERSION = "p1-16-v1"
MONEY_QUANTUM = Decimal("0.01")
ALLOWED_TERMS = ("validity", "payment", "delivery")


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not number.is_finite():
        raise ValueError(f"{field} must be finite")
    return number


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


@dataclass(frozen=True)
class ValidationLine:
    line_no: int
    quantity: Decimal
    unit_price: Decimal
    stated_line_total: Decimal

    @classmethod
    def create(
        cls,
        line_no: int,
        quantity: Any,
        unit_price: Any,
        stated_line_total: Any,
    ) -> "ValidationLine":
        return cls(
            line_no=int(line_no),
            quantity=_decimal(quantity, "quantity"),
            unit_price=_decimal(unit_price, "unit_price"),
            stated_line_total=_decimal(stated_line_total, "stated_line_total"),
        )


@dataclass(frozen=True)
class CommercialClaims:
    stated_subtotal: Decimal | None = None
    vat_rate_percent: Decimal | None = None
    stated_vat: Decimal | None = None
    stated_total: Decimal | None = None
    validity_terms: str | None = None
    payment_terms: str | None = None
    delivery_terms: str | None = None

    @classmethod
    def create(
        cls,
        *,
        stated_subtotal: Any = None,
        vat_rate_percent: Any = None,
        stated_vat: Any = None,
        stated_total: Any = None,
        validity_terms: str | None = None,
        payment_terms: str | None = None,
        delivery_terms: str | None = None,
    ) -> "CommercialClaims":
        def optional_decimal(value: Any, field: str) -> Decimal | None:
            return None if value is None else _decimal(value, field)

        return cls(
            stated_subtotal=optional_decimal(stated_subtotal, "stated_subtotal"),
            vat_rate_percent=optional_decimal(vat_rate_percent, "vat_rate_percent"),
            stated_vat=optional_decimal(stated_vat, "stated_vat"),
            stated_total=optional_decimal(stated_total, "stated_total"),
            validity_terms=_text(validity_terms),
            payment_terms=_text(payment_terms),
            delivery_terms=_text(delivery_terms),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "stated_subtotal": str(self.stated_subtotal) if self.stated_subtotal is not None else None,
            "vat_rate_percent": (
                str(self.vat_rate_percent) if self.vat_rate_percent is not None else None
            ),
            "stated_vat": str(self.stated_vat) if self.stated_vat is not None else None,
            "stated_total": str(self.stated_total) if self.stated_total is not None else None,
            "validity_terms": self.validity_terms,
            "payment_terms": self.payment_terms,
            "delivery_terms": self.delivery_terms,
        }


@dataclass(frozen=True)
class ValidationPolicy:
    money_tolerance: Decimal = MONEY_QUANTUM
    require_currency_detected: bool = True
    require_stated_totals: bool = False
    require_vat: bool = False
    required_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        tolerance = _decimal(self.money_tolerance, "money_tolerance")
        if tolerance < 0:
            raise ValueError("money_tolerance cannot be negative")
        invalid = sorted(set(self.required_terms) - set(ALLOWED_TERMS))
        if invalid:
            raise ValueError(f"unsupported required terms: {', '.join(invalid)}")
        object.__setattr__(self, "money_tolerance", tolerance)
        object.__setattr__(self, "required_terms", tuple(dict.fromkeys(self.required_terms)))

    def as_dict(self) -> dict[str, Any]:
        return {
            "money_tolerance": str(self.money_tolerance),
            "require_currency_detected": self.require_currency_detected,
            "require_stated_totals": self.require_stated_totals,
            "require_vat": self.require_vat,
            "required_terms": list(self.required_terms),
        }


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    field: str
    message: str
    expected: str | None = None
    actual: str | None = None
    line_no: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "field": self.field,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
            "line_no": self.line_no,
        }


@dataclass(frozen=True)
class QuoteValidationResult:
    status: str
    currency: str
    computed_subtotal: Decimal
    computed_vat: Decimal
    computed_total: Decimal
    issues: tuple[ValidationIssue, ...]
    engine_version: str = ENGINE_VERSION

    @property
    def may_proceed(self) -> bool:
        return self.status == "VALIDATED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "may_proceed": self.may_proceed,
            "currency": self.currency,
            "computed_subtotal": str(self.computed_subtotal),
            "computed_vat": str(self.computed_vat),
            "computed_total": str(self.computed_total),
            "issues": [issue.as_dict() for issue in self.issues],
            "engine_version": self.engine_version,
        }


def validate_quote(
    lines: Iterable[ValidationLine],
    *,
    currency: str,
    currency_detected: bool,
    claims: CommercialClaims,
    policy: ValidationPolicy,
    quote_status: str = "PARSED",
    quote_is_current: bool = True,
    source_warning: str | None = None,
) -> QuoteValidationResult:
    """Return deterministic computed totals and discrepancies.

    Vendor-stated line and summary values are treated as claims.  A mismatch is
    recorded and blocks/reviews the quote; this function never changes a claim.
    """
    line_items = tuple(lines)
    issues: list[ValidationIssue] = []

    def issue(
        code: str,
        severity: str,
        field: str,
        message: str,
        *,
        expected: Any = None,
        actual: Any = None,
        line_no: int | None = None,
    ) -> None:
        issues.append(
            ValidationIssue(
                code=code,
                severity=severity,
                field=field,
                message=message,
                expected=str(expected) if expected is not None else None,
                actual=str(actual) if actual is not None else None,
                line_no=line_no,
            )
        )

    if quote_status != "PARSED":
        issue(
            "QUOTE_STATUS_NOT_PARSED",
            "BLOCKING",
            "quote_status",
            "Only a parsed quote can be validated",
            expected="PARSED",
            actual=quote_status,
        )
    if not quote_is_current:
        issue(
            "QUOTE_NOT_CURRENT",
            "BLOCKING",
            "is_current",
            "A superseded quote cannot proceed",
            expected=True,
            actual=False,
        )

    normalized_currency = (currency or "").strip().upper()
    if len(normalized_currency) != 3 or not normalized_currency.isalpha():
        issue(
            "CURRENCY_INVALID",
            "BLOCKING",
            "currency",
            "Quote currency must be an explicit three-letter ISO code",
            actual=normalized_currency or None,
        )
    elif policy.require_currency_detected and not currency_detected:
        issue(
            "CURRENCY_NOT_CONFIRMED",
            "REVIEW",
            "currency_detected",
            "Currency was assumed and requires human confirmation",
            expected=True,
            actual=False,
        )

    if not line_items:
        issue("NO_LINE_ITEMS", "BLOCKING", "lines", "Quote contains no line items")

    computed_lines: list[Decimal] = []
    for line in line_items:
        if line.quantity <= 0:
            issue(
                "QUANTITY_INVALID",
                "BLOCKING",
                "quantity",
                "Quantity must be positive",
                actual=line.quantity,
                line_no=line.line_no,
            )
        if line.unit_price < 0 or line.stated_line_total < 0:
            issue(
                "NEGATIVE_MONEY",
                "BLOCKING",
                "line_total",
                "Unit price and line total cannot be negative",
                actual=line.stated_line_total,
                line_no=line.line_no,
            )
        computed = _money(line.quantity * line.unit_price)
        computed_lines.append(computed)
        stated = _money(line.stated_line_total)
        if abs(computed - stated) > policy.money_tolerance:
            issue(
                "LINE_TOTAL_MISMATCH",
                "BLOCKING",
                "line_total",
                "Quantity multiplied by unit price does not match the stated line total",
                expected=computed,
                actual=stated,
                line_no=line.line_no,
            )

    computed_subtotal = _money(sum(computed_lines, Decimal("0")))
    if claims.stated_subtotal is not None:
        stated_subtotal = _money(claims.stated_subtotal)
        if abs(computed_subtotal - stated_subtotal) > policy.money_tolerance:
            issue(
                "SUBTOTAL_MISMATCH",
                "BLOCKING",
                "stated_subtotal",
                "Sum of computed line totals does not match the stated subtotal",
                expected=computed_subtotal,
                actual=stated_subtotal,
            )
    elif policy.require_stated_totals:
        issue(
            "STATED_SUBTOTAL_REQUIRED",
            "REVIEW",
            "stated_subtotal",
            "A stated subtotal is required by validation policy",
        )

    computed_vat = Decimal("0.00")
    rate = claims.vat_rate_percent
    if rate is None:
        if claims.stated_vat is not None:
            issue(
                "VAT_RATE_MISSING",
                "REVIEW",
                "vat_rate_percent",
                "Stated VAT cannot be verified without a VAT rate",
            )
        if policy.require_vat:
            issue(
                "VAT_RATE_REQUIRED",
                "REVIEW",
                "vat_rate_percent",
                "A VAT rate is required by validation policy",
            )
    elif rate < 0 or rate > 100:
        issue(
            "VAT_RATE_INVALID",
            "BLOCKING",
            "vat_rate_percent",
            "VAT rate must be between 0 and 100 percent",
            actual=rate,
        )
    else:
        computed_vat = _money(computed_subtotal * rate / Decimal("100"))
        if claims.stated_vat is not None:
            stated_vat = _money(claims.stated_vat)
            if abs(computed_vat - stated_vat) > policy.money_tolerance:
                issue(
                    "VAT_MISMATCH",
                    "BLOCKING",
                    "stated_vat",
                    "Computed VAT does not match stated VAT",
                    expected=computed_vat,
                    actual=stated_vat,
                )
        elif policy.require_vat:
            issue(
                "STATED_VAT_REQUIRED",
                "REVIEW",
                "stated_vat",
                "A stated VAT amount is required by validation policy",
            )

    computed_total = _money(computed_subtotal + computed_vat)
    if claims.stated_total is not None:
        stated_total = _money(claims.stated_total)
        if abs(computed_total - stated_total) > policy.money_tolerance:
            issue(
                "TOTAL_MISMATCH",
                "BLOCKING",
                "stated_total",
                "Computed subtotal plus VAT does not match the stated total",
                expected=computed_total,
                actual=stated_total,
            )
    elif policy.require_stated_totals:
        issue(
            "STATED_TOTAL_REQUIRED",
            "REVIEW",
            "stated_total",
            "A stated total is required by validation policy",
        )

    term_values = {
        "validity": claims.validity_terms,
        "payment": claims.payment_terms,
        "delivery": claims.delivery_terms,
    }
    for term in policy.required_terms:
        if not term_values[term]:
            issue(
                f"{term.upper()}_TERMS_REQUIRED",
                "REVIEW",
                f"{term}_terms",
                f"{term.title()} terms are required by validation policy",
            )

    if _text(source_warning):
        issue(
            "SOURCE_WARNING_REVIEW",
            "REVIEW",
            "source_warning",
            "Quote extraction returned a warning that requires human review",
            actual=_text(source_warning),
        )

    if any(item.severity == "BLOCKING" for item in issues):
        status = "BLOCKED"
    elif issues:
        status = "NEEDS_REVIEW"
    else:
        status = "VALIDATED"

    return QuoteValidationResult(
        status=status,
        currency=normalized_currency,
        computed_subtotal=computed_subtotal,
        computed_vat=computed_vat,
        computed_total=computed_total,
        issues=tuple(issues),
    )
