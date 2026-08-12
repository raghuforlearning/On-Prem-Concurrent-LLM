import os
from pathlib import Path
import unittest


FIXTURE = Path(__file__).parent / "fixtures" / "benchmarks" / "sample-dataset.json"


@unittest.skipUnless(
    os.environ.get("P123_TEST_PG_DSN"),
    "set P123_TEST_PG_DSN to a disposable PostgreSQL Orchestrator test database",
)
class LivePostgresBenchmarkHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PG_DSN"] = os.environ["P123_TEST_PG_DSN"]
        import psycopg
        import benchmarks
        import db

        cls.psycopg = psycopg
        cls.benchmarks = benchmarks
        db.init_schema()
        with psycopg.connect(os.environ["P123_TEST_PG_DSN"]) as conn:
            if conn.execute("SELECT to_regclass('audit_log')").fetchone()[0] is None:
                raise unittest.SkipTest("test database must contain the P1-02 audit_log schema")
        benchmarks.init_benchmarks(os.environ["P123_TEST_PG_DSN"])

    def tearDown(self):
        with self.psycopg.connect(os.environ["P123_TEST_PG_DSN"]) as conn:
            run_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT evaluation_run_id FROM evaluation_runs r "
                    "JOIN evaluation_datasets d ON d.dataset_id=r.dataset_id "
                    "WHERE d.dataset_key='p123-sample'"
                ).fetchall()
            ]
            if run_ids:
                conn.execute("DELETE FROM evaluation_case_results WHERE evaluation_run_id=ANY(%s)", (run_ids,))
                conn.execute("DELETE FROM evaluation_runs WHERE evaluation_run_id=ANY(%s)", (run_ids,))
            conn.execute("DELETE FROM evaluation_datasets WHERE dataset_key='p123-sample'")
            conn.commit()

    def test_benchmark_run_persists_report_case_results_and_audit(self):
        repo = self.benchmarks.BenchmarkRepository(os.environ["P123_TEST_PG_DSN"])
        report = repo.run_dataset(
            dataset_path=str(FIXTURE),
            evaluator_name="fixture_predictions",
            actor="p123.evaluator",
        )
        self.assertEqual(report["status"], "INSUFFICIENT_DATA")
        self.assertEqual(report["case_count"], 4)
        self.assertFalse(report["signoff_ready"])
        self.assertEqual(len(report["case_results"]), 4)
        latest = repo.latest_runs()
        self.assertEqual(latest[0]["evaluation_run_id"], report["evaluation_run_id"])
        self.assertEqual(latest[0]["report"]["dataset_key"], "p123-sample")
        with self.psycopg.connect(os.environ["P123_TEST_PG_DSN"]) as conn:
            case_count = conn.execute(
                "SELECT count(*) FROM evaluation_case_results WHERE evaluation_run_id=%s",
                (report["evaluation_run_id"],),
            ).fetchone()[0]
            action = conn.execute(
                "SELECT action FROM audit_log WHERE component='evaluation' ORDER BY seq DESC LIMIT 1"
            ).fetchone()[0]
        self.assertEqual(case_count, 4)
        self.assertEqual(action, "benchmark_run_completed")


if __name__ == "__main__":
    unittest.main()
