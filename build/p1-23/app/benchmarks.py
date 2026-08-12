"""P1-23 offline benchmark harness.

The harness evaluates labelled local datasets and persists benchmark reports.
It does not call cloud services and only invokes supplied local evaluators.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import json
import time

import psycopg

from db import PG_DSN, audit
from quote_comparison import canonical_json, payload_sha256


MIN_SIGNOFF_CASES = 30
REQUIRED_CASE_TYPES = {
    "requirement_extraction",
    "classification",
    "vendor_response_classification",
    "quote_extraction",
}


BENCHMARK_SCHEMA = """
CREATE TABLE IF NOT EXISTS evaluation_datasets (
    dataset_id      BIGSERIAL PRIMARY KEY,
    dataset_key     TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    dataset_hash    TEXT NOT NULL,
    case_count      INT NOT NULL,
    source_path     TEXT NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    evaluation_run_id BIGSERIAL PRIMARY KEY,
    dataset_id        BIGINT NOT NULL REFERENCES evaluation_datasets(dataset_id),
    evaluator_name    TEXT NOT NULL,
    status            TEXT NOT NULL,
    report_json       JSONB NOT NULL,
    metrics_json      JSONB NOT NULL,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status IN ('PASSED','FAILED','INSUFFICIENT_DATA'))
);
CREATE INDEX IF NOT EXISTS idx_evaluation_runs_dataset
    ON evaluation_runs (dataset_id, evaluation_run_id DESC);

CREATE TABLE IF NOT EXISTS evaluation_case_results (
    case_result_id     BIGSERIAL PRIMARY KEY,
    evaluation_run_id  BIGINT NOT NULL REFERENCES evaluation_runs(evaluation_run_id),
    case_id            TEXT NOT NULL,
    case_type          TEXT NOT NULL,
    passed             BOOLEAN NOT NULL,
    metrics_json       JSONB NOT NULL,
    errors             TEXT[] NOT NULL DEFAULT '{}',
    latency_ms         INT NOT NULL,
    UNIQUE (evaluation_run_id, case_id)
);
"""


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    case_type: str
    input: dict[str, Any]
    expected: dict[str, Any]
    prediction: dict[str, Any] | None


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    case_type: str
    passed: bool
    metrics: dict[str, Any]
    errors: list[str]
    latency_ms: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "case_type": self.case_type,
            "passed": self.passed,
            "metrics": self.metrics,
            "errors": self.errors,
            "latency_ms": self.latency_ms,
        }


Evaluator = Callable[[BenchmarkCase], dict[str, Any]]


def init_benchmarks(dsn: str = PG_DSN) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute(BENCHMARK_SCHEMA)
        conn.commit()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"benchmark dataset is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("benchmark dataset must be a JSON object")
    return payload


def load_dataset(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    payload = _load_json(source)
    key = str(payload.get("dataset_key") or "").strip()
    name = str(payload.get("name") or "").strip()
    cases = payload.get("cases")
    if not key or not name:
        raise ValueError("dataset_key and name are required")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty array")
    normalized_cases = []
    seen = set()
    for index, item in enumerate(cases, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"case {index} must be an object")
        case_id = str(item.get("case_id") or "").strip()
        case_type = str(item.get("case_type") or "").strip()
        expected = item.get("expected")
        if not case_id or not case_type:
            raise ValueError(f"case {index} requires case_id and case_type")
        if case_id in seen:
            raise ValueError(f"duplicate case_id {case_id}")
        if not isinstance(item.get("input"), dict) or not isinstance(expected, dict):
            raise ValueError(f"case {case_id} requires object input and expected")
        prediction = item.get("prediction")
        if prediction is not None and not isinstance(prediction, dict):
            raise ValueError(f"case {case_id} prediction must be an object when supplied")
        seen.add(case_id)
        normalized_cases.append(
            {
                "case_id": case_id,
                "case_type": case_type,
                "input": item["input"],
                "expected": expected,
                "prediction": prediction,
            }
        )
    normalized = {
        "dataset_key": key,
        "name": name,
        "source_path": str(source),
        "cases": normalized_cases,
    }
    normalized["dataset_hash"] = payload_sha256(
        {"dataset_key": key, "name": name, "cases": normalized_cases}
    )
    return normalized


def _nested_get(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _normalize_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip().casefold()
    return str(value).strip().casefold()


def _field_accuracy(expected: dict[str, Any], prediction: dict[str, Any]) -> tuple[float, list[str]]:
    fields = expected.get("fields")
    if not isinstance(fields, dict) or not fields:
        fields = expected
    total = len(fields)
    correct = 0
    errors: list[str] = []
    for path, expected_value in fields.items():
        actual = _nested_get(prediction, str(path))
        if _normalize_scalar(actual) == _normalize_scalar(expected_value):
            correct += 1
        else:
            errors.append(f"{path}: expected {expected_value!r}, got {actual!r}")
    return (correct / total if total else 0.0), errors


def _label_accuracy(expected: dict[str, Any], prediction: dict[str, Any]) -> tuple[float, list[str]]:
    expected_label = expected.get("label")
    actual_label = prediction.get("label")
    if expected_label is None:
        return _field_accuracy(expected, prediction)
    if _normalize_scalar(expected_label) == _normalize_scalar(actual_label):
        return 1.0, []
    return 0.0, [f"label: expected {expected_label!r}, got {actual_label!r}"]


def _quote_accuracy(expected: dict[str, Any], prediction: dict[str, Any]) -> tuple[float, list[str]]:
    expected_lines = expected.get("line_items")
    actual_lines = prediction.get("line_items")
    if not isinstance(expected_lines, list) or not isinstance(actual_lines, list):
        return _field_accuracy(expected, prediction)
    errors: list[str] = []
    if len(expected_lines) != len(actual_lines):
        errors.append(f"line count: expected {len(expected_lines)}, got {len(actual_lines)}")
    total = max(len(expected_lines), 1)
    correct = 0
    for idx, expected_line in enumerate(expected_lines):
        actual_line = actual_lines[idx] if idx < len(actual_lines) else {}
        if canonical_json(expected_line) == canonical_json(actual_line):
            correct += 1
        else:
            errors.append(f"line {idx + 1}: expected {expected_line!r}, got {actual_line!r}")
    return correct / total, errors


def evaluate_case(
    case: BenchmarkCase,
    *,
    evaluator: Evaluator | None = None,
) -> CaseResult:
    start = time.perf_counter()
    prediction = evaluator(case) if evaluator else case.prediction
    latency_ms = int((time.perf_counter() - start) * 1000)
    if prediction is None:
        return CaseResult(
            case.case_id,
            case.case_type,
            False,
            {"structured_output_valid": False, "accuracy": 0.0},
            ["no prediction supplied"],
            latency_ms,
        )
    if not isinstance(prediction, dict):
        return CaseResult(
            case.case_id,
            case.case_type,
            False,
            {"structured_output_valid": False, "accuracy": 0.0},
            ["prediction is not an object"],
            latency_ms,
        )
    if case.case_type == "quote_extraction":
        accuracy, errors = _quote_accuracy(case.expected, prediction)
    elif case.case_type in {"classification", "vendor_response_classification"}:
        accuracy, errors = _label_accuracy(case.expected, prediction)
    else:
        accuracy, errors = _field_accuracy(case.expected, prediction)
    passed = not errors
    return CaseResult(
        case.case_id,
        case.case_type,
        passed,
        {"structured_output_valid": True, "accuracy": round(accuracy, 4)},
        errors,
        latency_ms,
    )


def summarize(dataset: dict[str, Any], results: list[CaseResult]) -> dict[str, Any]:
    by_type: dict[str, dict[str, Any]] = {}
    for result in results:
        bucket = by_type.setdefault(
            result.case_type,
            {
                "cases": 0,
                "passed": 0,
                "accuracy_sum": 0.0,
                "latencies_ms": [],
            },
        )
        bucket["cases"] += 1
        bucket["passed"] += 1 if result.passed else 0
        bucket["accuracy_sum"] += float(result.metrics.get("accuracy", 0.0))
        bucket["latencies_ms"].append(result.latency_ms)
    metrics = {}
    for case_type, bucket in by_type.items():
        latencies = sorted(bucket["latencies_ms"])
        p95_idx = min(len(latencies) - 1, int(round(0.95 * (len(latencies) - 1))))
        metrics[case_type] = {
            "cases": bucket["cases"],
            "passed": bucket["passed"],
            "pass_rate": round(bucket["passed"] / bucket["cases"], 4),
            "mean_accuracy": round(bucket["accuracy_sum"] / bucket["cases"], 4),
            "latency_p95_ms": latencies[p95_idx] if latencies else 0,
        }
    case_types = {result.case_type for result in results}
    signoff_ready = (
        len(results) >= MIN_SIGNOFF_CASES
        and REQUIRED_CASE_TYPES.issubset(case_types)
        and all(result.passed for result in results)
    )
    status = "PASSED" if signoff_ready else "INSUFFICIENT_DATA"
    if len(results) >= MIN_SIGNOFF_CASES and not all(result.passed for result in results):
        status = "FAILED"
    return {
        "dataset_key": dataset["dataset_key"],
        "dataset_hash": dataset["dataset_hash"],
        "case_count": len(results),
        "required_case_types": sorted(REQUIRED_CASE_TYPES),
        "present_case_types": sorted(case_types),
        "minimum_signoff_cases": MIN_SIGNOFF_CASES,
        "signoff_ready": signoff_ready,
        "status": status,
        "metrics": metrics,
        "failures": [result.as_dict() for result in results if not result.passed],
    }


class BenchmarkRepository:
    def __init__(self, dsn: str = PG_DSN):
        self.dsn = dsn

    def run_dataset(
        self,
        *,
        dataset_path: str,
        evaluator_name: str = "fixture_predictions",
        actor: str = "api.user",
        evaluator: Evaluator | None = None,
    ) -> dict[str, Any]:
        dataset = load_dataset(dataset_path)
        cases = [
            BenchmarkCase(
                case_id=item["case_id"],
                case_type=item["case_type"],
                input=item["input"],
                expected=item["expected"],
                prediction=item["prediction"],
            )
            for item in dataset["cases"]
        ]
        results = [evaluate_case(case, evaluator=evaluator) for case in cases]
        report = summarize(dataset, results)
        with psycopg.connect(self.dsn) as conn:
            dataset_id = conn.execute(
                "INSERT INTO evaluation_datasets "
                "(dataset_key,name,dataset_hash,case_count,source_path) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (dataset_key) DO UPDATE SET "
                "name=EXCLUDED.name,dataset_hash=EXCLUDED.dataset_hash,"
                "case_count=EXCLUDED.case_count,source_path=EXCLUDED.source_path,"
                "loaded_at=now() "
                "RETURNING dataset_id",
                (
                    dataset["dataset_key"],
                    dataset["name"],
                    dataset["dataset_hash"],
                    len(cases),
                    dataset["source_path"],
                ),
            ).fetchone()[0]
            run_id = conn.execute(
                "INSERT INTO evaluation_runs "
                "(dataset_id,evaluator_name,status,report_json,metrics_json) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING evaluation_run_id,started_at,completed_at",
                (
                    dataset_id,
                    evaluator_name,
                    report["status"],
                    canonical_json(report),
                    canonical_json(report["metrics"]),
                ),
            ).fetchone()
            for result in results:
                conn.execute(
                    "INSERT INTO evaluation_case_results "
                    "(evaluation_run_id,case_id,case_type,passed,metrics_json,errors,latency_ms) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        run_id[0],
                        result.case_id,
                        result.case_type,
                        result.passed,
                        canonical_json(result.metrics),
                        result.errors,
                        result.latency_ms,
                    ),
                )
            audit(
                conn,
                actor,
                "evaluation",
                "benchmark_run_completed",
                new=canonical_json(
                    {
                        "evaluation_run_id": run_id[0],
                        "dataset_key": dataset["dataset_key"],
                        "dataset_hash": dataset["dataset_hash"],
                        "status": report["status"],
                        "case_count": len(cases),
                    }
                ),
            )
            conn.commit()
        response = dict(report)
        response.update(
            {
                "evaluation_run_id": run_id[0],
                "dataset_id": dataset_id,
                "evaluator_name": evaluator_name,
                "started_at": str(run_id[1]),
                "completed_at": str(run_id[2]),
                "case_results": [result.as_dict() for result in results],
            }
        )
        return response

    def latest_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with psycopg.connect(self.dsn) as conn:
            rows = conn.execute(
                "SELECT r.evaluation_run_id,d.dataset_key,d.name,r.evaluator_name,"
                "r.status,d.case_count,r.completed_at,r.report_json "
                "FROM evaluation_runs r JOIN evaluation_datasets d ON d.dataset_id=r.dataset_id "
                "ORDER BY r.evaluation_run_id DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [
            {
                "evaluation_run_id": row[0],
                "dataset_key": row[1],
                "name": row[2],
                "evaluator_name": row[3],
                "status": row[4],
                "case_count": row[5],
                "completed_at": str(row[6]),
                "report": row[7],
            }
            for row in rows
        ]
