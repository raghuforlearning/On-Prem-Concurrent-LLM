import os
from pathlib import Path
import sys
import unittest


APP_ROOT = Path(__file__).parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
os.environ.setdefault("PG_DSN", "postgresql://unused-for-pure-tests")


class ProposalReleasePureTests(unittest.TestCase):
    def test_api_exposes_release_package_and_human_submission_recording_only(self):
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")
        for route in (
            '@app.post("/proposals/{proposal_id}/release-package")',
            '@app.post("/proposal-release-packages/{release_package_id}/submit")',
            '@app.get("/proposal-release-packages/{release_package_id}")',
        ):
            self.assertIn(route, source)
        p122_region = source.split("# ---------- P1-22", 1)[1].split("# ---------- P1-17", 1)[0]
        for forbidden in ("smtp", "sendmail", "OllamaClient", "httpx.post"):
            self.assertNotIn(forbidden, p122_region.lower())
        self.assertIn("does not send externally", p122_region)

    def test_release_module_has_no_builder_or_email_send_dependency(self):
        source = (APP_ROOT / "proposals.py").read_text(encoding="utf-8").lower()
        release_region = source.split("def prepare_release_package", 1)[1]
        for forbidden in ("smtplib", "sendmail", "requests.post", "httpx.post", "create_build("):
            self.assertNotIn(forbidden, release_region)
        self.assertIn("proposal_release_packages", source)
        self.assertIn("proposal_submissions", source)


if __name__ == "__main__":
    unittest.main()
