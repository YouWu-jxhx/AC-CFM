"""Deterministic journal replay checks without a MATLAB license."""

import copy
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from read_run import replay_observations


def event(stage, parent, detail, generation=1):
    return {"stage": stage, "detail": detail, "graph_parent": parent,
            "generation": generation, "bus_rows": [1, 2], "gen_rows": [1, 2],
            "branch_rows": [1, 2]}


def node(name, load):
    return event("graph_node", name, {"type": name if name in ("root", "event") else "",
                                      "load_mw": load, "generators": 2, "lines": 2})


def edge(source, target, action, weight, base, loss):
    return dict(zip(("source", "target", "action", "weight", "base", "loss_mw"),
                    (source, target, action, str(weight), str(base), "" if loss is None else str(loss))))


def fixture(step=0.05):
    metadata = {"result_available": True, "record_states": False, "uvls_per_step": step,
                "uvls_max_steps": 2}
    load_first = 50 * (1 - step)
    load_second = 50 * (1 - 2 * step)
    events = [node("root", 50), node("event", 50), event("after_initial", "event", {}, 0),
              node("a", load_first),
              event("action", "event", {"type": "UVLS", "target": "a", "bus_rows": [1, 2],
                                       "stepped_bus_rows": [1, 2], "load_before_mw": 50,
                                       "load_after_mw": load_first}),
              event("action", "event", {"type": "OL", "target": "a", "branch_rows": 2}),
              node("b", load_second),
              event("action", "a", {"type": "UVLS", "target": "b", "bus_rows": [1, 2],
                                   "stepped_bus_rows": [1, 2], "load_before_mw": load_first,
                                   "load_after_mw": load_second}, 2)]
    data = {"bus_uvls": np.array([[step, step / (1-step), 0]] * 2),
            "bus_ufls": np.zeros((2, 3))}
    edges = [edge("root", "event", "EV", 1, 1, None),
             edge("event", "a", "UVLS", 2, 2, 50 - load_first),
             edge("event", "a", "OL", 1, 2, None),
             edge("a", "b", "UVLS", 2, 2, load_first - load_second)]
    names = ["root", "event", "a", "b"]
    nodes = [{"Name": name, "Buses": "2", "Type": name if k < 2 else "", "Load": str(load),
              "Generators": "2", "Lines": "2"}
             for k, (name, load) in enumerate(zip(names, (50, 50, load_first, load_second)))]
    return metadata, events, data, edges, nodes


def opf_snapshot(data, demand, served):
    gen = np.zeros((2, 10))
    gen[:, 0] = [11, 22]
    gen[:, 1], gen[:, 9] = -np.asarray(served), -np.asarray(demand)
    result = np.empty((1, 1), dtype=[("gen", object), ("bus", object)])
    result["gen"][0, 0] = gen
    result["bus"][0, 0] = np.array([[11], [22]])
    data["opf_networks"] = np.empty((1, 1), dtype=object)
    data["opf_networks"][0, 0] = result
    observed = event("recovery_opf_result", "b", {"success": True}, 2)
    observed["opf_network_index"] = 1
    return observed


class ObservationReplay(unittest.TestCase):
    def test_valid_parallel_edges_and_two_uvls_steps(self):
        metadata, events, data, edges, nodes = fixture()
        replay_observations(metadata, events, data, list(reversed(edges)), nodes)

    def test_missing_extra_and_bad_uvls_ratio(self):
        for place, value in (((0, 0), 0), ((1, 2), 0.05), ((0, 1), 0.06)):
            with self.subTest(place=place, value=value):
                metadata, events, data, edges, nodes = fixture()
                data["bus_uvls"][place] = value
                with self.assertRaisesRegex(AssertionError, "bus_uvls"):
                    replay_observations(metadata, events, data, edges, nodes)

    def test_zero_step_is_a_legal_zero(self):
        replay_observations(*fixture(step=0))

    def test_vcls_replaces_uvls_with_nonzero_and_exact_zero(self):
        metadata, events, data, edges, nodes = fixture()
        events.extend([opf_snapshot(data, [27, 18], [27, 10]),
                       event("vcls_write", "b", {"bus_rows": [1, 2], "prior_pd_mw": [27, 18]}, 2),
                       event("verification_pf", "b", {"success": False}, 2),
                       event("graph_node", "off", {"type": "failure", "load_mw": 0,
                                                   "generators": 0, "lines": 0}, 2),
                       event("action", "b", {"type": "OPF", "target": "off",
                                             "load_before_mw": 45}, 2)])
        nodes.append({"Name": "off", "Type": "failure", "Load": "0", "Buses": "2",
                      "Generators": "0", "Lines": "0"})
        edges.append(edge("b", "off", "OPF", 1, 45, 45))
        data["bus_uvls"][:, 1] = [0, 1 - 10/18]
        replay_observations(metadata, events, data, edges, nodes)
        data["bus_uvls"][1, 1] = 0
        with self.assertRaisesRegex(AssertionError, "bus_uvls"):
            replay_observations(metadata, events, data, edges, nodes)

    def test_matlab_half_away_rounding_prevents_vcls_write(self):
        metadata, events, data, edges, nodes = fixture()
        events.extend([opf_snapshot(data, [30, 20], [29.5, 19.6]),
                       event("verification_pf_input", "b", {}, 2)])
        replay_observations(metadata, events, data, edges, nodes)
        events[-1] = event("vcls_write", "b", {"bus_rows": [1, 2], "prior_pd_mw": [30, 20]}, 2)
        with self.assertRaisesRegex(ValueError, "rounded OPF trigger"):
            replay_observations(metadata, events, data, edges, nodes)

    def test_small_vcls_flag_is_required_when_another_load_triggers(self):
        metadata, events, data, edges, nodes = fixture()
        served = np.nextafter(27.0, 0.0)
        events.extend([opf_snapshot(data, [27, 18], [served, 10]),
                       event("vcls_write", "b", {"bus_rows": [1, 2], "prior_pd_mw": [27, 18]}, 2)])
        data["bus_uvls"][:, 1] = [1 - served/27, 1 - 10/18]
        replay_observations(metadata, events, data, edges, nodes)
        data["bus_uvls"][0, 1] = 0
        with self.assertRaisesRegex(AssertionError, "bus_uvls"):
            replay_observations(metadata, events, data, edges, nodes)

    def test_compensating_edge_damage(self):
        metadata, events, data, edges, nodes = fixture()
        edges[1]["loss_mw"] = str(float(edges[1]["loss_mw"]) + 0.25)
        edges[3]["loss_mw"] = str(float(edges[3]["loss_mw"]) - 0.25)
        with self.assertRaises(AssertionError):
            replay_observations(metadata, events, data, edges, nodes)

    def test_single_edge_values(self):
        for field in ("weight", "base", "loss_mw"):
            metadata, events, data, edges, nodes = fixture()
            edges[1][field] = "100"
            with self.subTest(field=field), self.assertRaises(AssertionError):
                replay_observations(metadata, events, data, edges, nodes)

    def test_node_attributes(self):
        for field in ("Load", "Buses", "Generators", "Lines", "Type"):
            metadata, events, data, edges, nodes = fixture()
            nodes[0][field] = "100"
            with self.subTest(field=field), self.assertRaises((AssertionError, ValueError)):
                replay_observations(metadata, events, data, edges, nodes)

    def test_extra_deleted_and_replaced_edges(self):
        metadata, events, data, edges, nodes = fixture()
        replacement = dict(edges[2], action="XL")
        for changed in [edges + [copy.copy(edges[2])], edges[:-1], edges[:2] + [replacement] + edges[3:]]:
            with self.assertRaises((AssertionError, ValueError)):
                replay_observations(metadata, events, data, changed, nodes)


if __name__ == "__main__":
    unittest.main()
