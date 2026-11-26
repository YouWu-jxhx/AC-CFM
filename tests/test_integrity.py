"""Byte-level tests for the schema 2 commit and plan references."""

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from read_run import SCENARIO_FILES, sha256, verify_integrity


class CommitIntegrity(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.folder = root / "scenario_000001"
        self.folder.mkdir()
        scenario = {"id": 1, "seed": 7, "fault": {"branch_rows": 2}}
        self.mat = root / "plan.mat"
        self.mat.write_bytes(b"frozen test plan")
        self.plan = root / "plan.json"
        self.write_json(self.plan, {
            "plan_sha256": sha256(self.mat),
            "manifest": scenario,
            "environment": {"case_sha256": "fixture case"},
        })
        metadata = {
            "schema_version": 2,
            "case_sha256": "fixture case",
            "scenario": scenario,
            "plan": {
                "mat": "../plan.mat",
                "json": "../plan.json",
                "sha256": sha256(self.mat),
                "json_sha256": sha256(self.plan),
            },
        }
        for name in SCENARIO_FILES:
            (self.folder / name).write_bytes(b"disposable example")
        self.write_json(self.folder / "metadata.json", metadata)
        manifest = {
            "version": 1,
            "scenario_id": 1,
            "plan_sha256": sha256(self.mat),
            "files": [
                {"name": name, "bytes": (self.folder / name).stat().st_size,
                 "sha256": sha256(self.folder / name)}
                for name in SCENARIO_FILES
            ],
        }
        self.write_json(self.folder / "checksums.json", manifest)

    @staticmethod
    def write_json(path, body):
        path.write_text(json.dumps(body), encoding="utf-8")

    def test_linked_plan(self):
        verify_integrity(self.folder, require_plan=True)

    def test_detached_plan(self):
        self.plan.unlink()
        self.mat.unlink()
        verify_integrity(self.folder)
        with self.assertRaisesRegex(ValueError, "referenced plan"):
            verify_integrity(self.folder, require_plan=True)

    def test_same_size_corruption(self):
        path = self.folder / "events.jsonl"
        contents = path.read_bytes()
        path.write_bytes(b"x" + contents[1:])
        with self.assertRaisesRegex(ValueError, "events.jsonl"):
            verify_integrity(self.folder)

    def test_missing_file(self):
        (self.folder / "nodes.csv").unlink()
        with self.assertRaisesRegex(ValueError, "nodes.csv"):
            verify_integrity(self.folder)

    def test_missing_manifest(self):
        (self.folder / "checksums.json").unlink()
        with self.assertRaisesRegex(ValueError, "checksum manifest"):
            verify_integrity(self.folder)

    def test_modified_plan(self):
        self.plan.write_bytes(self.plan.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "referenced plan"):
            verify_integrity(self.folder)


if __name__ == "__main__":
    unittest.main()
