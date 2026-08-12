"""Typed contract for deterministic quote results from Proposal Builder.

The frozen builder currently returns compact keys (``pn``, ``desc``, ``qty``,
``up``, ``total``).  This module is the only place in the Orchestrator that
knows that wire shape.  Domain and persistence code receive normalized names.
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


class QuoteContractError(ValueError):
    """Proposal Builder returned a response outside the agreed contract."""


def _decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise QuoteContractError(f"line item {field_name} is missing or not numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise QuoteContractError(f"line item {field_name} is not numeric") from exc
    if not number.is_finite():
        raise QuoteContractError(f"line item {field_name} must be finite")
    return number


@dataclass(frozen=True)
class QuoteLine:
    line_no: int
    part_number: str
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_builder(cls, line_no: int, payload: Any) -> "QuoteLine":
        if not isinstance(payload, dict):
            raise QuoteContractError(f"line item {line_no} is not an object")
        description = str(payload.get("desc") or "").strip()
        if not description:
            raise QuoteContractError(f"line item {line_no} has no description")
        quantity = _decimal(payload.get("qty"), "quantity")
        unit_price = _decimal(payload.get("up"), "unit price")
        line_total = _decimal(payload.get("total"), "total")
        if quantity <= 0:
            raise QuoteContractError(f"line item {line_no} quantity must be positive")
        if unit_price < 0 or line_total < 0:
            raise QuoteContractError(f"line item {line_no} prices cannot be negative")
        return cls(
            line_no=line_no,
            part_number=str(payload.get("pn") or "").strip(),
            description=description,
            quantity=quantity,
            unit_price=unit_price,
            line_total=line_total,
            raw=dict(payload),
        )


@dataclass(frozen=True)
class QuoteExtractionResult:
    items: tuple[QuoteLine, ...]
    currency: str
    currency_detected: bool
    warning: str | None
    notice: str | None
    source: str | None
    via: str | None
    raw_payload: dict[str, Any] = field(repr=False)

    @classmethod
    def from_builder(cls, payload: Any) -> "QuoteExtractionResult":
        if not isinstance(payload, dict):
            raise QuoteContractError("Proposal Builder response is not an object")
        if payload.get("ok") is not True:
            raise QuoteContractError("Proposal Builder success response does not set ok=true")
        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise QuoteContractError("Proposal Builder success response has no line items")
        currency = str(payload.get("currency") or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise QuoteContractError("Proposal Builder returned an invalid ISO currency")
        items = tuple(QuoteLine.from_builder(i, item) for i, item in enumerate(raw_items, 1))
        return cls(
            items=items,
            currency=currency,
            currency_detected=payload.get("currencyDetected") is not False,
            warning=str(payload["warning"]) if payload.get("warning") else None,
            notice=str(payload["notice"]) if payload.get("notice") else None,
            source=str(payload["source"]) if payload.get("source") else None,
            via=str(payload["via"]) if payload.get("via") else None,
            raw_payload=dict(payload),
        )
