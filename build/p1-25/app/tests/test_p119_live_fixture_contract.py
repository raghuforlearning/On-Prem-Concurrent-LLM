"""Offline tests for the P1-19/P1-20 live vendor-TP fixture contract."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tests.test_p119_existing_builder_live import _configured_vendor_tp_artifact


class ExistingBuilderLiveFixtureContractTests(unittest.TestCase):
    def _environment(self, source_root, output_root, source_path, sha256):
        return {
            "PROPOSAL_BUILDER_SOURCE_ARTIFACT_ROOTS": str(source_root),
            "PROPOSAL_BUILDER_ARTIFACT_ROOT": str(output_root),
            "P119_TEST_VENDOR_TP_PATH": str(source_path),
            "P119_TEST_VENDOR_TP_SHA256": sha256,
        }

    def test_requires_path_and_pinned_sha256(self):
        with self.assertRaisesRegex(ValueError, "PATH and P119_TEST_VENDOR_TP_SHA256"):
            _configured_vendor_tp_artifact({})

    def test_accepts_hash_pinned_docx_from_controlled_input_archive(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "quote_archive"
            output_root = root / "proposal_artifacts"
            source_root.mkdir()
            output_root.mkdir()
            source = source_root / "vendor-technical-proposal.docx"
            content = b"PK\x03\x04" + (b"vendor-tp" * 20)
            source.write_bytes(content)
            expected_hash = hashlib.sha256(content).hexdigest()

            artifact = _configured_vendor_tp_artifact(
                self._environment(source_root, output_root, source, expected_hash)
            )

            self.assertEqual(artifact["filename"], source.name)
            self.assertEqual(artifact["sha256"], expected_hash)
            self.assertEqual(artifact["artifact_ref"], source.resolve().as_uri())

    def test_rejects_generated_proposal_artifact_as_vendor_tp(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "quote_archive"
            output_root = root / "proposal_artifacts"
            source_root.mkdir()
            output_root.mkdir()
            generated_cp = output_root / "generated-cp.docx"
            content = b"PK\x03\x04generated-cp"
            generated_cp.write_bytes(content)

            environment = self._environment(
                source_root, output_root, generated_cp, hashlib.sha256(content).hexdigest()
            )
            environment["PROPOSAL_BUILDER_SOURCE_ARTIFACT_ROOTS"] = (
                f"{source_root},{output_root}"
            )
            with self.assertRaisesRegex(ValueError, "not generated proposal artifacts"):
                _configured_vendor_tp_artifact(environment)

    def test_rejects_hash_mismatch_and_extension_spoofing(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "quote_archive"
            output_root = root / "proposal_artifacts"
            source_root.mkdir()
            output_root.mkdir()
            source = source_root / "vendor-tp.pdf"
            content = b"%PDF-1.7 vendor technical proposal"
            source.write_bytes(content)
            environment = self._environment(source_root, output_root, source, "0" * 64)
            with self.assertRaisesRegex(ValueError, "SHA-256 verification failed"):
                _configured_vendor_tp_artifact(environment)

            source.write_bytes(b"PK\x03\x04not-a-pdf")
            environment["P119_TEST_VENDOR_TP_SHA256"] = hashlib.sha256(
                source.read_bytes()
            ).hexdigest()
            with self.assertRaisesRegex(ValueError, "does not match its extension"):
                _configured_vendor_tp_artifact(environment)


if __name__ == "__main__":
    unittest.main()
