import os
from pathlib import Path
import sys
import tempfile
import unittest


APP_ROOT = Path(__file__).parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
os.environ.setdefault("PG_DSN", "postgresql://unused-for-pure-tests")

from benchmarks import (  # noqa: E402
    BenchmarkCase,
    evaluate_case,
    load_dataset,
    summarize,
)


FIXTURE = APP_ROOT / "tests" / "fixtures" / "benchmarks" / "sample-dataset.json"


class BenchmarkPureTests(unittest.TestCase):
    def test_load_dataset_hashes_and_validates_sample(self):
        dataset = load_dataset(FIXTURE)
        self.assertEqual(dataset["dataset_key"], "p123-sample")
        self.assertEqual(len(dataset["cases"]), 4)
        self.assertEqual(len(dataset["dataset_hash"]), 64)
        self.assertEqual(
            {case["case_type"] for case in dataset["cases"]},
            {
                "requirement_extraction",
                "classification",
                "vendor_response_classification",
                "quote_extraction",
            },
        )

    def test_case_metrics_cover_extraction_classification_quote_and_invalid_output(self):
        dataset = load_dataset(FIXTURE)
        results = [
            evaluate_case(
                BenchmarkCase(
                    case_id=item["case_id"],
                    case_type=item["case_type"],
                    input=item["input"],
                    expected=item["expected"],
                    prediction=item["prediction"],
                )
            )
            for item in dataset["cases"]
        ]
        self.assertTrue(all(result.passed for result in results))
        report = summarize(dataset, results)
        self.assertEqual(report["status"], "INSUFFICIENT_DATA")
        self.assertFalse(report["signoff_ready"])
        bad = evaluate_case(
            BenchmarkCase(
                case_id="BAD-1",
                case_type="classification",
                input={},
                expected={"label": "QUOTE"},
                prediction={"label": "ACK"},
            )
        )
        self.assertFalse(bad.passed)
        self.assertIn("label", bad.errors[0])

    def test_dataset_validation_rejects_duplicate_case_ids(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            handle.write(
                '{"dataset_key":"bad","name":"bad","cases":['
                '{"case_id":"A","case_type":"classification","input":{},"expected":{}},'
                '{"case_id":"A","case_type":"classification","input":{},"expected":{}}]}'
            )
            path = handle.name
        try:
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_dataset(path)
        finally:
            Path(path).unlink(missing_ok=True)


class BenchmarkApiSurfaceTests(unittest.TestCase):
    def test_api_exposes_benchmark_run_and_report_routes_without_cloud_dependency(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('@app.post("/benchmarks/run")', source)
        self.assertIn('@app.get("/benchmarks/runs")', source)
        region = source.split("# ---------- P1-23", 1)[1].split("# ---------- P1-17", 1)[0]
        for forbidden in ("httpx", "OllamaClient", "openai", "requests"):
            self.assertNotIn(forbidden, region)


if __name__ == "__main__":
    unittest.main()
