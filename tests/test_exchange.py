"""Corruption checks for the archived exchange and a new traced exchange if supplied."""

import copy
import os
import shutil
from tempfile import TemporaryDirectory
from pathlib import Path
import sys
import unittest

import numpy as np
from scipy.io import savemat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
from read_run import read_scenario, validate, validate_folder


class ExchangeValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.historical = ROOT / "evidence" / "verified-row9"
        cls.reference = read_scenario(cls.historical)
        configured = os.environ.get("ACCFM_TEST_SCENARIO")
        cls.new_scenario = Path(configured) if configured else None

    def check_corruption(self, corrupt):
        dataset = copy.deepcopy(self.reference)
        corrupt(*dataset)
        with self.assertRaises((AssertionError, ValueError)):
            validate(*dataset)

    def test_historical_exchange(self):
        validate_folder(self.historical)

    def test_snapshot_differs_from_matlab_record(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "scenario"
            shutil.copytree(self.historical, folder)
            metadata, events, data, edges = read_scenario(folder)
            # An electrical value can disagree while preserving topology and row identity.
            data["state_bus"].flat[0][0, 7] += 0.02
            validate(metadata, events, data, edges)
            savemat(folder / "numeric.mat", {k: v for k, v in data.items() if not k.startswith("__")})
            with self.assertRaises(AssertionError):
                validate_folder(folder)

    def test_local_generator_identity(self):
        def corrupt(meta, events, data, edges):
            data["state_gen"].flat[0][0, 0] += 1
        self.check_corruption(corrupt)

    def test_parallel_line_identity(self):
        def corrupt(meta, events, data, edges):
            data["state_branch"].flat[0][0, 3] += 1
        self.check_corruption(corrupt)

    def test_out_of_range_and_duplicate_rows(self):
        for rows in ([1, 1], [0], [0.3], [10**4]):
            with self.subTest(rows=rows):
                def corrupt(meta, events, data, edges):
                    events[0]["branch_rows"] = rows
                self.check_corruption(corrupt)

    def test_overload_matrix(self):
        def corrupt(meta, events, data, edges):
            data["branch_tripped"][0, 0] = 1
        self.check_corruption(corrupt)

    def test_ledger_preserving_total(self):
        def corrupt(meta, events, data, edges):
            meta["ledger"]["breakdown_mw"][1] -= 1
            meta["ledger"]["breakdown_mw"][5] += 1
        self.check_corruption(corrupt)

    def test_graph_edge_type(self):
        def corrupt(meta, events, data, edges):
            edges[0]["action"] = "unknown"
        self.check_corruption(corrupt)

    def test_new_recovery_opf_mapping_and_diagnostics(self):
        if self.new_scenario is None:
            self.skipTest("Set ACCFM_TEST_SCENARIO to a fresh traced recovery scenario")
        metadata, events, data, edges = validate_folder(self.new_scenario)
        results = [event for event in events if event["stage"] == "recovery_opf_result"]
        self.assertTrue(results and any(e["detail"]["success"] for e in results))
        corrupted = copy.deepcopy(events)
        next(event for event in corrupted if event["stage"] == "recovery_opf_result"
             )["detail"]["dispatchable_shed_mw"] += 1
        with self.assertRaises(AssertionError):
            validate(metadata, corrupted, data, edges)
        self.assertGreater(np.count_nonzero(data["gen_tripped"]), 0)
        data["gen_tripped"][0, -1] = 1
        with self.assertRaises(ValueError):
            validate(metadata, events, data, edges)


if __name__ == "__main__":
    unittest.main()
