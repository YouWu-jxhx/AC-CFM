"""Verify the pinned original, generator, and read-only check mode."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from build_observed import LOCK, OBSERVED, VENDOR, build_source, update_observed, verified_source


class ObserverGeneration(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads(LOCK.read_text(encoding="utf-8"))

    def test_generated_matches_checked_in(self):
        expected = build_source(verified_source(VENDOR, self.lock)).encode("utf-8")
        self.assertEqual(OBSERVED.read_bytes(), expected)
        subprocess.run([sys.executable, ROOT / "core/build_observed.py", "--check"],
                       check=True, capture_output=True)

    def test_modified_vendor_supporting_file_is_rejected(self):
        with TemporaryDirectory() as tmp:
            vendor = Path(tmp) / "vendor"
            shutil.copytree(VENDOR, vendor)
            with (vendor / "get_default_settings.m").open("ab") as stream:
                stream.write(b"% synthetic modification")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                verified_source(vendor, self.lock)

    def test_extra_and_missing_vendor_files_are_rejected(self):
        with TemporaryDirectory() as tmp:
            vendor = Path(tmp) / "vendor"
            shutil.copytree(VENDOR, vendor)
            (vendor / "README.md").rename(vendor / "unexpected.md")
            with self.assertRaisesRegex(ValueError, "file inventory"):
                verified_source(vendor, self.lock)

    def test_drift_check_never_writes(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "accfm_observed.m"
            target.write_bytes(b"drift")
            with self.assertRaisesRegex(ValueError, "differs"):
                update_observed(target, b"expected", check=True)
            self.assertEqual(target.read_bytes(), b"drift")

    def test_unexpected_pf_call_count(self):
        source = verified_source(VENDOR, self.lock)
        with self.assertRaisesRegex(ValueError, "instrumentation counts"):
            build_source(source.replace(" = runpf(network, settings.mpopt);",
                                        " = runpf(other_network, settings.mpopt);", 1))


if __name__ == "__main__":
    unittest.main()
