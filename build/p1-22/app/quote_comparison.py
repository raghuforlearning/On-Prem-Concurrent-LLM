"""P1-18 deterministic multi-vendor quote comparison and human selection."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from typing import Any, Iterable


MONEY_QUANTUM = Decimal("0.01")
RATE_QUANTUM = Decimal("0.00000001")
SATISFIED_DEAL_REG_STATES = {"NOT_REQUIRED", "APPROVED", "APPROVED_WITH_CONDITIONS"}


COMPARISON_SCHEMA = """
CREATE TABLE IF NOT EXISTS exchange_rates (
    rate_id             BIGSERIAL PRIMARY KEY,
    currency            CHAR(3) NOT NULL,
    aed_per_unit        NUMERIC(20,8) NOT NULL,
    rate_date           DATE NOT NULL,
    source_reference    TEXT NOT NULL,
    recorded_by         TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (currency<>'AED'),
    CHECK (aed_per_unit>0),
    UNIQUE (currency,rate_date,source_reference,aed_per_unit)
);

CREATE TABLE IF NOT EXISTS quote_comparison_runs (
    comparison_run_id   BIGSERIAL PRIMARY KEY,
    opp_id              TEXT NOT NULL REFERENCES opportunities(opp_id),
    input_hash          TEXT NOT NULL,
    result_hash         TEXT NOT NULL,
    result_json         JSONB NOT NULL,
    created_by          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quote_comparison_opp
    ON quote_comparison_runs (opp_id,comparison_run_id DESC);

CREATE TABLE IF NOT EXISTS quote_comparison_inputs (
    comparison_run_id   BIGINT NOT NULL REFERENCES quote_comparison_runs(comparison_run_id),
    quote_id            BIGINT NOT NULL REFERENCES quotes(quote_id),
    quote_version_no    INT NOT NULL,
    validation_id       BIGINT NOT NULL REFERENCES quote_validation_results(validation_id),
    exchange_rate_id    BIGINT REFERENCES exchange_rates(rate_id),
    PRIMARY KEY (comparison_run_id,quote_id)
);

CREATE TABLE IF NOT EXISTS quote_selections (
    selection_id        BIGSERIAL PRIMARY KEY,
    comparison_run_id   BIGINT NOT NULL UNIQUE REFERENCES quote_comparison_runs(comparison_run_id),
    opp_id              TEXT NOT NULL REFERENCES opportunities(opp_id),
    quote_id            BIGINT NOT NULL REFERENCES quotes(quote_id),
    quote_version_no    INT NOT NULL,
    commercial_snapshot JSONB NOT NULL,
    snapshot_sha256     TEXT NOT NULL,
    deal_reg_status     TEXT NOT NULL,
    proposal_eligible   BOOLEAN NOT NULL,
    status              TEXT NOT NULL DEFAULT 'ACTIVE',
    selected_by         TEXT NOT NULL,
    selection_reason    TEXT NOT NULL,
    selected_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at       TIMESTAMPTZ,
    CHECK (status IN ('ACTIVE','SUPERSEDED'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_quote_selection_active
    ON quote_selections (opp_id) WHERE status='ACTIVE';

CREATE TABLE IF NOT EXISTS quote_selection_decisions (
    selection_id        BIGINT NOT NULL REFERENCES quote_selections(selection_id),
    quote_id            BIGINT NOT NULL REFERENCES quotes(quote_id),
    decision            TEXT NOT NULL,
    PRIMARY KEY (selection_id,quote_id),
    CHECK (decision IN ('SELECTED','NOT_SELECTED'))
);
"""


def _decimal(value: Any, field: str) -> Decimal:
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a decimal number") from exc
    if not converted.is_finite():
        raise ValueError(f"{field} must be finite")
    return converted


def _money(value: Any) -> Decimal:
    return _decimal(value, "money").quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _money_text(value: Any) -> str:
    return format(_money(value), ".2f")


def canonical_json(payload: Any) -> str:
    """Stable serialization used for deterministic results and frozen hashes."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RecordedRate:
    rate_id: int | None
    currency: str
    aed_per_unit: Decimal
    rate_date: str | None
    source_reference: str

    @classmethod
    def aed(cls) -> "RecordedRate":
        return cls(None, "AED", Decimal("1"), None, "AED_NATIVE")

    def as_dict(self) -> dict[str, Any]:
        return {
            "rate_id": self.rate_id,
            "currency": self.currency,
            "aed_per_unit": format(self.aed_per_unit, ".8f"),
            "rate_date": self.rate_date,
            "source_reference": self.source_reference,
        }


def build_comparison_result(candidates: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Build a byte-stable AED matrix without consulting an LLM or rate API."""
    rows = []
    seen_quotes = set()
    for candidate in candidates:
        quote_id = int(candidate["quote_id"])
        if quote_id in seen_quotes:
            raise ValueError(f"duplicate quote {quote_id}")
        seen_quotes.add(quote_id)
        currency = str(candidate["currency"]).strip().upper()
        rate = candidate["rate"]
        if not isinstance(rate, RecordedRate) or rate.currency != currency:
            raise ValueError(f"quote {quote_id} has no matching recorded exchange rate")
        if rate.aed_per_unit <= 0:
            raise ValueError("exchange rate must be positive")

        native_subtotal = _money(candidate["native_subtotal"])
        native_vat = _money(candidate["native_vat"])
        native_total = _money(candidate["native_total"])
        line_items = []
        for line in candidate.get("line_items", []):
            line_items.append(
                {
                    "line_no": int(line["line_no"]),
                    "part_number": line.get("part_number"),
                    "description": str(line["description"]),
                    "quantity": str(line["quantity"]),
                    "native_unit_price": _money_text(line["unit_price"]),
                    "native_line_total": _money_text(line["line_total"]),
                    "aed_unit_price": _money_text(_money(line["unit_price"]) * rate.aed_per_unit),
                    "aed_line_total": _money_text(_money(line["line_total"]) * rate.aed_per_unit),
                }
            )
        line_items.sort(key=lambda item: item["line_no"])
        rows.append(
            {
                "quote_id": quote_id,
                "quote_group_id": str(candidate["quote_group_id"]),
                "quote_version_no": int(candidate["quote_version_no"]),
                "validation_id": int(candidate["validation_id"]),
                "vendor_id": int(candidate["vendor_id"]),
                "vendor_name": str(candidate["vendor_name"]),
                "native_currency": currency,
                "native_subtotal": _money_text(native_subtotal),
                "native_vat": _money_text(native_vat),
                "native_total": _money_text(native_total),
                "exchange_rate": rate.as_dict(),
                "aed_subtotal": _money_text(native_subtotal * rate.aed_per_unit),
                "aed_vat": _money_text(native_vat * rate.aed_per_unit),
                "aed_total": _money_text(native_total * rate.aed_per_unit),
                "terms": candidate.get("terms") or {},
                "deal_registration": candidate["deal_registration"],
                "line_items": line_items,
            }
        )
    if len(rows) < 2:
        raise ValueError("comparison requires at least two validated current quotes")
    rows.sort(key=lambda item: (item["vendor_name"].casefold(), item["quote_id"]))
    return {"base_currency": "AED", "quotes": rows}


class QuoteComparisonRepository:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def init_schema(self) -> None:
        import psycopg

        with psycopg.connect(self.dsn) as conn:
            conn.execute(COMPARISON_SCHEMA)
            conn.commit()

    def record_exchange_rate(
        self,
        *,
        currency: str,
        aed_per_unit: Any,
        rate_date: date,
        source_reference: str,
        actor: str,
    ) -> dict[str, Any]:
        import psycopg
        from db import audit

        normalized = currency.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha() or normalized == "AED":
            raise ValueError("currency must be a non-AED three-letter code")
        rate = _decimal(aed_per_unit, "aed_per_unit").quantize(RATE_QUANTUM)
        if rate <= 0:
            raise ValueError("aed_per_unit must be positive")
        if not source_reference.strip() or not actor.strip():
            raise ValueError("source_reference and actor are required")
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "INSERT INTO exchange_rates "
                "(currency,aed_per_unit,rate_date,source_reference,recorded_by) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (currency,rate_date,source_reference,aed_per_unit) DO UPDATE "
                "SET source_reference=EXCLUDED.source_reference RETURNING rate_id,created_at",
                (normalized, rate, rate_date, source_reference.strip(), actor.strip()),
            ).fetchone()
            audit(
                conn,
                actor,
                "quote_comparison",
                "exchange_rate_recorded",
                new=canonical_json(
                    {
                        "rate_id": row[0],
                        "currency": normalized,
                        "aed_per_unit": format(rate, ".8f"),
                        "rate_date": str(rate_date),
                        "source_reference": source_reference.strip(),
                    }
                ),
            )
            conn.commit()
        return {
            "rate_id": row[0],
            "currency": normalized,
            "aed_per_unit": format(rate, ".8f"),
            "rate_date": str(rate_date),
            "source_reference": source_reference.strip(),
            "recorded_by": actor.strip(),
            "created_at": str(row[1]),
        }

    @staticmethod
    def _deal_registration(conn: Any, opp_id: str, vendor_id: int, capable: bool) -> dict[str, Any]:
        if not capable:
            status = "NOT_REQUIRED"
        else:
            row = conn.execute(
                "SELECT status,reg_reference,validity FROM deal_registrations "
                "WHERE opp_id=%s AND vendor_id=%s",
                (opp_id, vendor_id),
            ).fetchone()
            if not row:
                status, reference, validity = "REQUIRED", None, None
            else:
                status, reference, validity = row
                status = "PENDING" if status == "REQUESTED" else str(status).upper()
                if validity is not None and validity <= date.today() and status in SATISFIED_DEAL_REG_STATES:
                    status = "EXPIRED"
                return {
                    "required": True,
                    "status": status,
                    "reference": reference,
                    "validity": str(validity) if validity else None,
                    "proposal_gate_satisfied": status in SATISFIED_DEAL_REG_STATES,
                }
        return {
            "required": capable,
            "status": status,
            "reference": None,
            "validity": None,
            "proposal_gate_satisfied": status in SATISFIED_DEAL_REG_STATES,
        }

    def create_comparison(
        self,
        *,
        opp_id: str,
        quote_ids: Iterable[int],
        exchange_rate_ids: dict[int, int],
        actor: str,
    ) -> dict[str, Any]:
        import psycopg
        from db import audit

        normalized_ids = sorted(set(int(value) for value in quote_ids))
        if len(normalized_ids) < 2:
            raise ValueError("comparison requires at least two distinct quotes")
        if not actor.strip():
            raise ValueError("actor is required")
        candidates = []
        inputs = []
        with psycopg.connect(self.dsn) as conn:
            for quote_id in normalized_ids:
                row = conn.execute(
                    "SELECT q.quote_id,q.quote_group_id,q.version_no,q.vendor_id,v.vendor_name,"
                    "q.currency,q.status,q.is_current,q.validation_status,v.deal_reg_capable,"
                    "vr.validation_id,vr.computed_subtotal,vr.computed_vat,vr.computed_total,"
                    "vr.claims_snapshot "
                    "FROM quotes q JOIN vendors v ON v.vendor_id=q.vendor_id "
                    "JOIN LATERAL (SELECT validation_id,computed_subtotal,computed_vat,"
                    "computed_total,claims_snapshot FROM quote_validation_results "
                    "WHERE quote_id=q.quote_id AND status='VALIDATED' "
                    "ORDER BY validation_id DESC LIMIT 1) vr ON true "
                    "WHERE q.quote_id=%s AND q.opp_id=%s",
                    (quote_id, opp_id),
                ).fetchone()
                if not row:
                    raise ValueError(f"quote {quote_id} is not a validated quote for {opp_id}")
                if row[6] != "PARSED" or not row[7] or row[8] != "VALIDATED":
                    raise PermissionError(f"quote {quote_id} must be current, parsed and validated")
                currency = row[5].strip().upper()
                rate_id = exchange_rate_ids.get(quote_id)
                if currency == "AED":
                    if rate_id is not None:
                        raise ValueError(f"AED quote {quote_id} must not specify an exchange rate")
                    rate = RecordedRate.aed()
                else:
                    if rate_id is None:
                        raise ValueError(f"quote {quote_id} in {currency} requires a recorded rate")
                    rate_row = conn.execute(
                        "SELECT rate_id,currency,aed_per_unit,rate_date,source_reference "
                        "FROM exchange_rates WHERE rate_id=%s",
                        (rate_id,),
                    ).fetchone()
                    if not rate_row or rate_row[1].strip().upper() != currency:
                        raise ValueError(f"recorded rate {rate_id} does not match {currency}")
                    rate = RecordedRate(
                        rate_row[0],
                        rate_row[1].strip().upper(),
                        Decimal(rate_row[2]),
                        str(rate_row[3]),
                        rate_row[4],
                    )
                line_rows = conn.execute(
                    "SELECT line_no,part_number,description,quantity,unit_price,line_total "
                    "FROM quote_line_items WHERE quote_id=%s ORDER BY line_no",
                    (quote_id,),
                ).fetchall()
                claims = row[14] or {}
                candidates.append(
                    {
                        "quote_id": row[0],
                        "quote_group_id": row[1],
                        "quote_version_no": row[2],
                        "vendor_id": row[3],
                        "vendor_name": row[4],
                        "currency": currency,
                        "validation_id": row[10],
                        "native_subtotal": row[11],
                        "native_vat": row[12],
                        "native_total": row[13],
                        "rate": rate,
                        "terms": {
                            "validity": claims.get("validity_terms"),
                            "payment": claims.get("payment_terms"),
                            "delivery": claims.get("delivery_terms"),
                        },
                        "deal_registration": self._deal_registration(
                            conn, opp_id, row[3], row[9]
                        ),
                        "line_items": [
                            {
                                "line_no": item[0],
                                "part_number": item[1],
                                "description": item[2],
                                "quantity": item[3],
                                "unit_price": item[4],
                                "line_total": item[5],
                            }
                            for item in line_rows
                        ],
                    }
                )
                inputs.append((quote_id, row[2], row[10], rate.rate_id))
            result = build_comparison_result(candidates)
            input_payload = [
                {
                    "quote_id": item[0],
                    "quote_version_no": item[1],
                    "validation_id": item[2],
                    "exchange_rate_id": item[3],
                }
                for item in inputs
            ]
            input_hash = payload_sha256(input_payload)
            result_hash = payload_sha256(result)
            run_id = conn.execute(
                "INSERT INTO quote_comparison_runs "
                "(opp_id,input_hash,result_hash,result_json,created_by) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING comparison_run_id,created_at",
                (opp_id, input_hash, result_hash, canonical_json(result), actor.strip()),
            ).fetchone()
            for quote_id, version_no, validation_id, rate_id in inputs:
                conn.execute(
                    "INSERT INTO quote_comparison_inputs "
                    "(comparison_run_id,quote_id,quote_version_no,validation_id,exchange_rate_id) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (run_id[0], quote_id, version_no, validation_id, rate_id),
                )
            audit(
                conn,
                actor,
                "quote_comparison",
                "quote_comparison_created",
                opp_id,
                new=canonical_json(
                    {
                        "comparison_run_id": run_id[0],
                        "input_hash": input_hash,
                        "result_hash": result_hash,
                        "quote_ids": normalized_ids,
                    }
                ),
            )
            conn.commit()
        return {
            "comparison_run_id": run_id[0],
            "opp_id": opp_id,
            "input_hash": input_hash,
            "result_hash": result_hash,
            "result": result,
            "created_by": actor.strip(),
            "created_at": str(run_id[1]),
        }

    def select_quote(
        self,
        *,
        comparison_run_id: int,
        quote_id: int,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        import psycopg
        from db import audit

        if not actor.strip() or not reason.strip():
            raise ValueError("actor and selection reason are required")
        with psycopg.connect(self.dsn) as conn:
            run = conn.execute(
                "SELECT opp_id,result_json FROM quote_comparison_runs "
                "WHERE comparison_run_id=%s FOR UPDATE",
                (comparison_run_id,),
            ).fetchone()
            if not run:
                raise ValueError(f"unknown comparison run {comparison_run_id}")
            prior_for_run = conn.execute(
                "SELECT selection_id,quote_id,status,selected_by,selected_at FROM quote_selections "
                "WHERE comparison_run_id=%s",
                (comparison_run_id,),
            ).fetchone()
            if prior_for_run:
                if prior_for_run[1] != quote_id:
                    raise PermissionError("a frozen comparison run selection cannot be changed")
                return {
                    "selection_id": prior_for_run[0],
                    "comparison_run_id": comparison_run_id,
                    "opp_id": run[0],
                    "quote_id": prior_for_run[1],
                    "status": prior_for_run[2],
                    "selected_by": prior_for_run[3],
                    "selected_at": str(prior_for_run[4]),
                    "existing": True,
                }
            result = run[1]
            matching = [item for item in result["quotes"] if int(item["quote_id"]) == quote_id]
            if not matching:
                raise ValueError("selected quote is not part of the comparison run")
            snapshot = matching[0]
            current = conn.execute(
                "SELECT version_no,is_current,status,validation_status FROM quotes "
                "WHERE quote_id=%s FOR UPDATE",
                (quote_id,),
            ).fetchone()
            if not current or current[0] != snapshot["quote_version_no"]:
                raise ValueError("selected quote version no longer matches the comparison snapshot")
            if not current[1] or current[2] != "PARSED" or current[3] != "VALIDATED":
                raise PermissionError("only a current validated quote can be selected")
            conn.execute(
                "UPDATE quote_selections SET status='SUPERSEDED',superseded_at=now() "
                "WHERE opp_id=%s AND status='ACTIVE'",
                (run[0],),
            )
            dr_status = snapshot["deal_registration"]["status"]
            eligible = bool(snapshot["deal_registration"]["proposal_gate_satisfied"])
            frozen_json = canonical_json(snapshot)
            selection = conn.execute(
                "INSERT INTO quote_selections "
                "(comparison_run_id,opp_id,quote_id,quote_version_no,commercial_snapshot,"
                "snapshot_sha256,deal_reg_status,proposal_eligible,selected_by,selection_reason) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "RETURNING selection_id,selected_at",
                (
                    comparison_run_id,
                    run[0],
                    quote_id,
                    snapshot["quote_version_no"],
                    frozen_json,
                    payload_sha256(snapshot),
                    dr_status,
                    eligible,
                    actor.strip(),
                    reason.strip(),
                ),
            ).fetchone()
            for candidate in result["quotes"]:
                conn.execute(
                    "INSERT INTO quote_selection_decisions (selection_id,quote_id,decision) "
                    "VALUES (%s,%s,%s)",
                    (
                        selection[0],
                        candidate["quote_id"],
                        "SELECTED" if candidate["quote_id"] == quote_id else "NOT_SELECTED",
                    ),
                )
            audit(
                conn,
                actor,
                "quote_comparison",
                "quote_selected_human",
                run[0],
                new=canonical_json(
                    {
                        "selection_id": selection[0],
                        "comparison_run_id": comparison_run_id,
                        "quote_id": quote_id,
                        "quote_version_no": snapshot["quote_version_no"],
                        "snapshot_sha256": payload_sha256(snapshot),
                        "deal_reg_status": dr_status,
                        "proposal_eligible": eligible,
                    }
                ),
                reason=reason.strip(),
            )
            conn.commit()
        return {
            "selection_id": selection[0],
            "comparison_run_id": comparison_run_id,
            "opp_id": run[0],
            "quote_id": quote_id,
            "quote_version_no": snapshot["quote_version_no"],
            "snapshot_sha256": payload_sha256(snapshot),
            "deal_reg_status": dr_status,
            "proposal_eligible": eligible,
            "status": "ACTIVE",
            "selected_by": actor.strip(),
            "selection_reason": reason.strip(),
            "selected_at": str(selection[1]),
            "existing": False,
        }

    def list_comparisons(self, opp_id: str) -> list[dict[str, Any]]:
        import psycopg

        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute(
                "SELECT comparison_run_id,input_hash,result_hash,result_json,created_by,created_at "
                "FROM quote_comparison_runs WHERE opp_id=%s ORDER BY comparison_run_id DESC",
                (opp_id,),
            ).fetchall()
        return [
            {
                "comparison_run_id": row[0],
                "opp_id": opp_id,
                "input_hash": row[1],
                "result_hash": row[2],
                "result": row[3],
                "created_by": row[4],
                "created_at": str(row[5]),
            }
            for row in rows
        ]

    def active_selection(self, opp_id: str) -> dict[str, Any] | None:
        import psycopg

        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(
                "SELECT selection_id,comparison_run_id,quote_id,quote_version_no,"
                "commercial_snapshot,snapshot_sha256,deal_reg_status,proposal_eligible,status,"
                "selected_by,selection_reason,selected_at FROM quote_selections "
                "WHERE opp_id=%s AND status='ACTIVE'",
                (opp_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "selection_id": row[0],
            "comparison_run_id": row[1],
            "opp_id": opp_id,
            "quote_id": row[2],
            "quote_version_no": row[3],
            "commercial_snapshot": row[4],
            "snapshot_sha256": row[5],
            "deal_reg_status": row[6],
            "proposal_eligible": row[7],
            "status": row[8],
            "selected_by": row[9],
            "selection_reason": row[10],
            "selected_at": str(row[11]),
        }


def init_quote_comparison(dsn: str) -> None:
    QuoteComparisonRepository(dsn).init_schema()
