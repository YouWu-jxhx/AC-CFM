"""Read and independently check AC-CFM scenario exports."""

import argparse
import csv
import hashlib
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.io import loadmat

# Immutable MATPOWER case columns, including identity beyond bus membership.
IDENTITY = {
    "bus": [0],
    "gen": [0, 6, 8, 9],
    "branch": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12],
}
ACTION_COLUMNS = {
    "branch_tripped": ("branch", {"OL"}),
    "gen_tripped": ("gen", {"OFGS", "ULGT"}),
    "bus_tripped": ("bus", {"OPF", "island_deenergized"}),
    "bus_ufls": ("bus", {"UFLS"}),
    "bus_uvls": ("bus", {"UVLS", "VC"}),
}
LOSS_ACTIONS = ("UFLS", "UVLS", "VC", "OPF")
SCENARIO_FILES = ("record.mat", "metadata.json", "events.jsonl", "numeric.mat", "nodes.csv", "edges.csv")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_integrity(folder, require_plan=False):
    """Verify the committed bytes and, when present, the referenced plan."""
    manifest_path = folder / "checksums.json"
    if not manifest_path.is_file():
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        if metadata["schema_version"] == 1 and not require_plan and "plan" not in metadata:
            return
        raise ValueError("Missing scenario checksum manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest["files"]
    if manifest["version"] != 1 or tuple(item["name"] for item in files) != SCENARIO_FILES:
        raise ValueError("Invalid scenario checksum manifest")
    for item in files:
        path = folder / item["name"]
        if (not path.is_file() or path.stat().st_size != item["bytes"]
                or sha256(path) != item["sha256"]):
            raise ValueError(f"Missing or changed committed file {item['name']}")
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    ref = metadata["plan"]
    if (manifest["scenario_id"] != metadata["scenario"]["id"]
            or manifest["plan_sha256"] != ref["sha256"]
            or ref["mat"] != "../plan.mat" or ref["json"] != "../plan.json"):
        raise ValueError("Scenario checksum manifest disagrees with plan reference")
    mat_plan, json_plan = folder.parent / "plan.mat", folder.parent / "plan.json"
    if require_plan or mat_plan.exists() or json_plan.exists():
        if (not mat_plan.is_file() or not json_plan.is_file()
                or sha256(mat_plan) != ref["sha256"] or sha256(json_plan) != ref["json_sha256"]):
            raise ValueError("Missing or changed referenced plan")
        plan = json.loads(json_plan.read_text(encoding="utf-8"))
        scenarios = plan["manifest"] if isinstance(plan["manifest"], list) else [plan["manifest"]]
        matches = [scenario for scenario in scenarios if scenario["id"] == manifest["scenario_id"]]
        if (matches != [metadata["scenario"]] or plan["plan_sha256"] != ref["sha256"]
                or plan["environment"]["case_sha256"] != metadata["case_sha256"]):
            raise ValueError("Scenario metadata disagrees with referenced experiment")
        if metadata.get("observations_version", 1) >= 3:
            for field in ("uvls_per_step", "uvls_max_steps"):
                if plan["settings"][field] != metadata[field]:
                    raise ValueError(f"Scenario {field} disagrees with the frozen plan")


def ids(value):
    """MATLAB JSON encodes a scalar vector as a number."""
    values = np.asarray(value).reshape(-1)
    if not np.issubdtype(values.dtype, np.number) or not np.all(
        np.isfinite(values) & (np.floor(values) == values)
    ):
        raise ValueError("Expected integer MATLAB row indices")
    return values.astype(int)


def csv_rows(path):
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def read_scenario(folder):
    folder = Path(folder)
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    if metadata["schema_version"] not in (1, 2):
        raise ValueError("Unsupported result schema")
    events = [
        json.loads(line)
        for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    matrices = loadmat(folder / "numeric.mat")
    graph_path = folder / "edges.csv"
    edges = csv_rows(graph_path) if metadata["result_available"] or graph_path.is_file() else []
    return metadata, events, matrices, edges


def check_identity(local, pre, rows, columns):
    if len(local) != len(rows):
        raise ValueError("State matrix length differs from the row map")
    if rows.size:
        np.testing.assert_array_equal(local[:, columns], pre[rows - 1][:, columns])


def check_events(metadata, events, data):
    if [event["sequence"] for event in events] != list(range(1, len(events) + 1)):
        raise ValueError("Broken event sequence")
    for kind, columns in IDENTITY.items():
        pre = data[f"pre_{kind}"]
        states = data[f"state_{kind}"].ravel() if metadata["record_states"] else None
        if states is not None and len(states) != len(events):
            raise ValueError(f"{kind} state count differs from the event count")
        for n, event in enumerate(events):
            rows = ids(event[f"{kind}_rows"])
            if len(np.unique(rows)) != len(rows) or np.any((rows < 1) | (rows > len(pre))):
                raise ValueError(f"Invalid {kind} row map at event {n + 1}")
            if states is not None:
                check_identity(states[n], pre, rows, columns)
            detail = event["detail"]
            # Initial native indices are stored as branches/gens, rather than action row keys.
            if (event["stage"] in ("action", "before_limit_actions")
                    and f"{kind}_rows" in detail
                    and not np.all(np.isin(ids(detail[f"{kind}_rows"]), rows))):
                raise ValueError(f"{kind} action row outside island at event {n + 1}")


def check_opf(events, data, columns):
    snapshots = data["opf_networks"].ravel()
    references = [event for event in events if "opf_network_index" in event]
    if [event["opf_network_index"] for event in references] != list(range(1, len(snapshots) + 1)):
        raise ValueError("Broken recovery OPF snapshot references")
    pending = None
    for event, cell in zip(references, snapshots):
        stage = event["stage"]
        network = cell[0, 0]
        gen_rows = network["gen_rows"].ravel()
        rows = ids(event["gen_rows"])
        np.testing.assert_array_equal(gen_rows[:len(rows)], rows)
        np.testing.assert_array_equal(gen_rows[len(rows):], 0)
        for kind, identity in (("bus", [0]), ("branch", [0, 1, 2, 3, 4])):
            check_identity(network[kind], data[f"pre_{kind}"], ids(event[f"{kind}_rows"]), identity)
        check_identity(network["gen"][:len(rows)], data["pre_gen"], rows, [0])
        synthetic = network["gen"][len(rows):, 0]
        if len(network["gen"]) != len(gen_rows) or not np.all(np.isin(synthetic, network["bus"][:, 0])):
            raise ValueError("Invalid dispatchable-load generator mapping")
        key = (event["generation"], event["local_depth"], event["graph_parent"])
        if stage == "before_recovery_opf":
            if pending is not None:
                raise ValueError("Missing recovery OPF result")
            pending = (key, network["gen"], gen_rows)
        elif stage == "recovery_opf_result" and pending is not None and pending[0] == key:
            detail = event["detail"]
            pmin = columns["gen_pmin"] - 1
            pg = columns["gen_pq"][0] - 1
            np.testing.assert_array_equal(gen_rows, pending[2])
            np.testing.assert_array_equal(network["gen"][:, 0], pending[1][:, 0])
            loads = gen_rows == 0
            demand = -pending[1][loads, pmin].sum()
            served = -network["gen"][loads, pg].sum()
            np.testing.assert_allclose(
                [demand, served, demand - served],
                [detail["dispatchable_demand_mw"], detail["dispatchable_served_mw"],
                 detail["dispatchable_shed_mw"]],
                atol=1e-6, rtol=0,
            )
            pending = None
        else:
            raise ValueError("Unpaired recovery OPF snapshot")
    for n, event in enumerate(events):
        stage = event["stage"]
        if stage == "before_recovery_opf":
            if n + 1 >= len(events) or events[n + 1]["stage"] not in (
                "recovery_opf_result", "recovery_opf_exception",
            ):
                raise ValueError("Recovery OPF attempt is missing a result or exception")
        if stage in ("before_recovery_opf", "recovery_opf_result") and "opf_network_index" not in event:
            raise ValueError("Recovery OPF event is missing its snapshot")
        if stage == "recovery_opf_result" and event["detail"]["success"]:
            start = n + 1
            if start < len(events) and events[start]["stage"] == "vcls_write":
                start += 1
            if start + 1 >= len(events) or events[start]["stage"] != "verification_pf_input" or (
                    events[start + 1]["stage"] not in ("verification_pf", "verification_pf_exception")):
                raise ValueError("Successful recovery OPF is missing its verification PF")
            for related in events[n + 1:start + 2]:
                if any(related[key] != event[key] for key in ("generation", "local_depth", "graph_parent")):
                    raise ValueError("Recovery OPF verification changed island scope")
        if stage == "before_recovery_opf":
            following = events[n + 1]
            if any(following[key] != event[key] for key in ("generation", "local_depth", "graph_parent")):
                raise ValueError("Recovery OPF outcome changed island scope")


def check_graph(events, edges):
    graph_actions = Counter((row["source"], row["target"], row["action"]) for row in edges)
    for event in events:
        if event["stage"] == "action":
            edge = (event["graph_parent"], event["detail"]["target"], event["detail"]["type"])
        elif event["stage"] == "island_split":
            edge = (event["detail"]["source"], event["graph_parent"], "ISL")
        elif event["stage"] == "after_initial":
            edge = ("root", "event", "EV")
        else:
            continue
        graph_actions[edge] -= 1
    if any(graph_actions.values()):
        raise ValueError("Journal edges disagree with graph CSV")


def check_actions(events, data, extended, replay=False):
    names = ACTION_COLUMNS if extended else ("branch_tripped",)
    for name in names:
        if replay and name in ("bus_uvls", "bus_ufls"):
            continue
        kind, actions = ACTION_COLUMNS[name]
        actual = {(row + 1, generation + 1) for row, generation in zip(*np.nonzero(data[name]))}
        expected = set()
        vcls_flags = set()
        for event in events:
            stage, detail = event["stage"], event["detail"]
            action = detail["type"] if stage == "action" else stage
            key = f"{kind}_rows"
            if action in actions:
                # UFLS writes its fraction for every bus in the island, including zero demand.
                rows = event[key] if action in ("UFLS", "island_deenergized") else detail[key]
                expected.update((row, event["generation"]) for row in ids(rows))
            if name == "bus_uvls" and stage == "recovery_opf_result" and detail["success"]:
                # The native VCLS writeback updates the UVLS matrix for every dispatchable
                # load when any load triggers the rounded application threshold.
                network = data["opf_networks"].flat[event["opf_network_index"] - 1][0, 0]
                gen = network["gen"][network["gen_rows"].ravel() == 0]
                rounded = np.copysign(np.floor(np.abs(gen[:, [1, 9]]) + 0.5), gen[:, [1, 9]])
                if np.any(rounded[:, 0] > rounded[:, 1]):
                    bus_rows = ids(event["bus_rows"])
                    local = np.isin(network["bus"][:, 0], gen[:, 0])
                    vcls_flags.update((row, event["generation"]) for row in bus_rows[local])
        if name == "bus_uvls":
            # Upstream also uses bus_uvls for VCLS; a failed verification PF can leave these
            # flags behind, and very small dispatch changes can round to zero.
            if actual - expected - vcls_flags:
                raise ValueError(f"Journal disagrees with {name}")
        elif actual != expected:
            raise ValueError(f"Journal disagrees with {name}")
        if name.endswith("_tripped") and np.any((data[name] != 0) & (data[name] != 1)):
            raise ValueError(f"Unexpected native flag value in {name}")


def check_ledger(metadata, events, data, edges):
    columns = metadata["columns_1based"]
    pd = columns["bus_pd"] - 1
    before = data["pre_bus"][:, pd].sum()
    served = data["bus"][:, pd].sum()
    ledger = metadata["ledger"]
    initial = metadata["initial"]
    bus_rows = ids(initial["bus_rows"])
    initial_loss = data["pre_bus"][bus_rows - 1, pd].sum()
    graph_losses = [
        sum(float(edge["loss_mw"]) for edge in edges if edge["action"] == action)
        for action in LOSS_ACTIONS
    ]
    residual = before - initial_loss - served - sum(graph_losses)
    expected = [initial_loss, *graph_losses, residual]
    np.testing.assert_allclose(
        [before, before - initial_loss, served, before - served, served],
        [ledger["before_mw"], ledger["model_input_mw"], ledger["served_mw"],
         metadata["summary"]["lost_mw"], data["load"].flat[-1]], atol=1e-6, rtol=0,
    )
    np.testing.assert_allclose(ledger["breakdown_mw"], expected, atol=1e-6, rtol=0)
    np.testing.assert_allclose(ledger["model_loss_mw"], expected[1:], atol=1e-6, rtol=0)
    np.testing.assert_allclose(
        [metadata["summary"][name] for name in (
            "ls_ufls", "ls_uvls", "ls_vcls", "ls_opf", "ls_other", "ls_total", "initial_bus_lost_mw"
        )],
        [*(value / before for value in expected[1:]), (before - served) / before, initial_loss],
        atol=1e-6, rtol=0,
    )
    np.testing.assert_allclose(
        [ledger["initial_bus_lost_mw"], ledger["closure_mw"], *ledger["graph_mw_delta"]],
        [initial_loss, 0, 0, 0, 0, 0], atol=1e-6, rtol=0,
    )
    if metadata.get("observations_version", 1) >= 2:
        observed = Counter()
        for event in events:
            detail = event["detail"]
            if event["stage"] == "action" and "load_before_mw" in detail:
                observed[detail["type"]] += detail["load_before_mw"] - detail["load_after_mw"]
            elif event["stage"] == "island_without_supply":
                observed["other"] += detail["load_mw"]
        np.testing.assert_allclose(
            [observed[action] for action in LOSS_ACTIONS] + [observed["XL"] + observed["other"]],
            expected[1:], atol=1e-6, rtol=0,
        )


def check_initial(metadata, events, data):
    fault = metadata["scenario"]["fault"]
    initial = metadata["initial"]
    requested_bus = ids(fault["bus_numbers"])
    branches = ids(fault["branch_rows"])
    gens = ids(fault["gen_rows"])
    columns = metadata["columns_1based"]
    bus_rows = np.flatnonzero(np.isin(data["pre_bus"][:, 0], requested_bus)) + 1
    np.testing.assert_array_equal(np.sort(ids(initial["bus_rows"])), bus_rows)
    np.testing.assert_array_equal(np.sort(data["pre_bus"][bus_rows - 1, 0]), np.sort(requested_bus))
    for kind, native_key, requested, identity, status in (
        ("branch", "native_branches", branches, [0, 1], columns["branch_status"]),
        ("gen", "native_gens", gens, [0], columns["gen_status"]),
    ):
        pre = data[f"pre_{kind}"]
        adjacent = np.isin(pre[:, identity], requested_bus).any(axis=1)
        inferred = np.union1d(requested, np.flatnonzero(adjacent & (pre[:, status - 1] > 0)) + 1)
        np.testing.assert_array_equal(np.sort(ids(initial[native_key])), np.sort(requested))
        np.testing.assert_array_equal(np.sort(ids(initial[f"{kind}_rows"])), inferred)
    initial_events = [n for n, event in enumerate(events) if event["stage"] == "after_initial"]
    if len(initial_events) != 1:
        raise ValueError("Missing or duplicate initial event")
    snapshot = initial_events[0]
    np.testing.assert_array_equal(ids(events[snapshot]["detail"]["branches"]), branches)
    np.testing.assert_array_equal(ids(events[snapshot]["detail"]["gens"]), gens)
    if metadata["record_states"]:
        for kind, col, off_value in (
            ("bus", "bus_type", 4), ("branch", "branch_status", 0), ("gen", "gen_status", 0),
        ):
            initial_matrix = data[f"state_{kind}"].flat[snapshot]
            rows = ids(initial[f"{kind}_rows"])
            np.testing.assert_array_equal(initial_matrix[rows - 1, columns[col] - 1], off_value)


def check_outages(metadata, data):
    columns = metadata["columns_1based"]
    for kind, col in (("bus", "bus_type"), ("gen", "gen_status"), ("branch", "branch_status")):
        c = columns[col] - 1
        pre, final = data[f"pre_{kind}"][:, c], data[kind][:, c]
        before = pre != 4 if kind == "bus" else pre > 0
        after = final != 4 if kind == "bus" else final > 0
        ledger = metadata["ledger"][kind]
        initial = ids(metadata["initial"][f"{kind}_rows"])
        off = np.flatnonzero(before & ~after) + 1
        flagged = np.flatnonzero(np.any(data[f"{kind}_tripped"] != 0, axis=1)) + 1
        explicit = [] if kind == "bus" else np.intersect1d(np.setdiff1d(off, initial), flagged)
        indirect = np.setdiff1d(off, np.union1d(initial, explicit))
        if np.any(after & ~before) or not np.all(np.isin(initial, off)):
            raise ValueError(f"Unexpected {kind} reactivation or initial outage")
        for key, expected in (
            ("initial_rows", initial), ("final_off_rows", off), ("flagged_rows", flagged),
            ("explicit_trip_rows", explicit), ("indirect_rows", indirect),
        ):
            np.testing.assert_array_equal(np.sort(ids(ledger[key])), np.sort(expected))


def recovery_write(events, index, data, metadata):
    """Validate the upstream rounded trigger and derive all VCLS replacements."""
    event = events[index]
    snapshot = data["opf_networks"].flat[event["opf_network_index"] - 1][0, 0]
    gen = snapshot["gen"]
    loads = gen[gen[:, 9] < 0]
    values = loads[:, [1, 9]]
    frac, integral = np.modf(np.abs(values))
    rounded = np.copysign(integral + (frac >= 0.5), values)
    triggered = np.any(rounded[:, 0] > rounded[:, 1])
    following = events[index + 1]
    if triggered != (following["stage"] == "vcls_write"):
        raise ValueError("VCLS writeback disagrees with rounded OPF trigger")
    if not triggered:
        return None, None, 0.0
    detail = following["detail"]
    rows = ids(detail["bus_rows"])
    local = np.isin(snapshot["bus"][:, 0], loads[:, 0])
    np.testing.assert_array_equal(rows, ids(event["bus_rows"])[local])
    demand = np.asarray(detail["prior_pd_mw"], dtype=float).reshape(-1)
    np.testing.assert_allclose(demand, -loads[:, 9], rtol=0, atol=1e-6)
    if metadata["record_states"]:
        columns = metadata["columns_1based"]
        state = data["state_bus"].flat[index + 1]
        np.testing.assert_allclose(demand, state[local, columns["bus_pd"] - 1], rtol=0, atol=1e-6)
    return rows, 1 + loads[:, 1] / demand, 1 - loads[:, 1].sum() / loads[:, 9].sum()


def replay_observations(metadata, events, data, edges, nodes=None):
    """Rebuild native action matrices and graph updates from observed inputs."""
    terminal = metadata["result_available"]
    uvls = np.zeros_like(data["bus_uvls"]) if terminal else None
    ufls = np.zeros_like(data["bus_ufls"]) if terminal else None
    expected_nodes = {}
    expected_edges = {}
    vc_fraction = 0.0
    for index, event in enumerate(events):
        stage, detail = event["stage"], event["detail"]
        parent, generation = event["graph_parent"], event["generation"]
        if stage == "recovery_opf_result" and detail["success"]:
            rows, values, vc_fraction = recovery_write(events, index, data, metadata)
            if terminal and rows is not None:
                uvls[rows - 1, generation - 1] = values  # includes zero replacements
        if not terminal:
            continue
        if stage == "graph_node":
            if parent in expected_nodes:
                raise ValueError("Repeated graph node creation")
            values = [len(ids(event["bus_rows"])), detail["type"], detail["load_mw"],
                      detail["generators"], detail["lines"]]
            if metadata["record_states"] and detail["type"] != "failure":
                columns = metadata["columns_1based"]
                np.testing.assert_allclose(values[2], data["state_bus"].flat[index][
                    :, columns["bus_pd"] - 1].sum(), rtol=0, atol=1e-6)
                for offset, kind in ((3, "gen"), (4, "branch")):
                    local = data[f"state_{kind}"].flat[index]
                    status = columns[f"{kind}_status"] - 1
                    actual = np.count_nonzero(local[:, status] == 1) if len(local) else 0
                    if actual != values[offset]:
                        raise ValueError("Graph node count disagrees with state")
            expected_nodes[parent] = values
        elif stage == "after_actions":
            expected_nodes[parent][2] = detail["load_mw"]
        elif stage == "graph_success":
            expected_nodes[parent][1] = "success"
        elif stage == "island_without_supply":
            expected_nodes[parent][1:] = ["failure", 0, 0, 0]
            # Native AC-CFM updates the LS column of outgoing edges of this node.
            for key, records in expected_edges.items():
                if key[0] == parent:
                    for record in records:
                        record[2] = detail["load_mw"]
        elif stage in ("after_initial", "island_split"):
            source = "root" if stage == "after_initial" else detail["source"]
            action = "EV" if stage == "after_initial" else "ISL"
            expected_edges.setdefault((source, parent, action), []).append([1, 1, np.nan])
        elif stage == "action":
            action = detail["type"]
            loss = np.nan
            if action == "UFLS":
                weight, base = detail["fraction"], 1
                ufls[ids(event["bus_rows"]) - 1, generation - 1] = weight
                loss = weight * detail["load_before_mw"]
            elif action == "UVLS":
                rows = ids(detail["bus_rows"]) - 1
                stepped = ids(detail["stepped_bus_rows"]) - 1
                if not np.all(np.isin(stepped, rows)):
                    raise ValueError("UVLS step rows fall outside the action")
                dropped = np.setdiff1d(rows, stepped)
                steps = np.count_nonzero(uvls, axis=1)
                maximum, step = metadata["uvls_max_steps"], metadata["uvls_per_step"]
                if np.any(steps[stepped] >= maximum) or np.any(steps[dropped] < maximum):
                    raise ValueError("UVLS write disagrees with preceding nonzero history")
                uvls[stepped, generation - 1] = step / (1 - step * steps[stepped])
                uvls[dropped, generation - 1] = 1
                weight, base = len(rows), len(ids(event["bus_rows"]))
                loss = detail["load_before_mw"] - detail["load_after_mw"]
            elif action in ("VC", "OPF"):
                weight, base = vc_fraction if action == "VC" else 1, detail["load_before_mw"]
                loss = weight * base
            elif action == "SH":
                weight = base = len(ids(detail["bus_rows"]))
            elif action == "OFGS":
                weight, base = 1, len(ids(event["gen_rows"]))  # scalar length(gens_to_shed)
            else:
                kind = {"XL": "gen", "ULGT": "gen", "OL": "branch"}[action]
                key = f"{kind}_rows"
                weight, base = len(ids(detail[key])), len(ids(event[key]))
            expected_edges.setdefault((parent, detail["target"], action), []).append([weight, base, loss])

    if not terminal:
        return
    for name, expected in (("bus_uvls", uvls), ("bus_ufls", ufls)):
        np.testing.assert_array_equal(data[name] != 0, expected != 0, err_msg=name)
        np.testing.assert_allclose(data[name], expected, rtol=0, atol=1e-14, err_msg=name)
    actual_edges = {}
    for edge in edges:
        key = tuple(edge[field] for field in ("source", "target", "action"))
        actual_edges.setdefault(key, []).append([float(edge[x]) if edge[x] else np.nan
                                                  for x in ("weight", "base", "loss_mw")])
    if actual_edges.keys() != expected_edges.keys():
        raise ValueError("Graph edge keys disagree with replay")
    for key, expected in expected_edges.items():
        def ordered(records):
            return sorted(records, key=lambda row: tuple(-np.inf if np.isnan(x) else x for x in row))
        actual = np.array(ordered(actual_edges[key]))
        expected = np.array(ordered(expected))
        np.testing.assert_array_equal(actual.shape, expected.shape, err_msg=str(key))
        np.testing.assert_allclose(actual[:, 0], expected[:, 0], rtol=0, atol=1e-14, err_msg=str(key))
        np.testing.assert_allclose(actual[:, 1:], expected[:, 1:], rtol=0, atol=1e-6, err_msg=str(key))
    if nodes is not None:
        if len(nodes) != len(expected_nodes) or {row["Name"] for row in nodes} != expected_nodes.keys():
            raise ValueError("Graph node keys disagree with replay")
        for row in nodes:
            buses, kind, load, gens, lines = expected_nodes[row["Name"]]
            if row["Type"] != kind or [int(row[x]) for x in ("Buses", "Generators", "Lines")] != [buses, gens, lines]:
                raise ValueError(f"Node attributes disagree for {row['Name']}")
            np.testing.assert_allclose(float(row["Load"]), load, rtol=0, atol=1e-6)


def check_status(metadata, events):
    summary = metadata["summary"]
    category = metadata["error_category"]
    available = metadata["result_available"]
    expected = {
        "completed_model": (True, ""), "model_opf_trip": (True, ""),
        "review_ledger": (True, "ledger"), "iteration_limit": (False, "recursion_limit"),
        "error": (False, "input"), "solver_error": (False, "solver_exception"),
    }
    if expected.get(summary["status"]) != (available, category):
        raise ValueError("Scenario outcome disagrees with error category or terminal availability")
    solver_events = {"ac_pf", "verification_pf", "recovery_opf_result", "ac_pf_exception",
                     "verification_pf_exception", "recovery_opf_exception"}
    failed = any(event["stage"] in solver_events and not event["detail"]["success"] for event in events)
    if failed != summary["has_solver_failure"]:
        raise ValueError("Solver failure summary disagrees with journal")
    opf_trip = available and any(event["stage"] == "action" and event["detail"]["type"] == "OPF"
                                 for event in events)
    if opf_trip != summary["has_opf_trip"] or (
        available and summary["status"] != "review_ledger"
        and opf_trip != (summary["status"] == "model_opf_trip")
    ):
        raise ValueError("OPF trip status disagrees with journal")
    if category == "solver_exception" and (
        not events or not events[-1]["stage"].endswith("_exception")
        or events[-1]["detail"]["identifier"] != summary["error_id"]
    ):
        raise ValueError("Solver exception outcome is missing the corresponding call failure")


def validate(metadata, events, data, edges, nodes=None):
    check_events(metadata, events, data)
    extended = metadata.get("observations_version", 1) >= 2
    if extended:
        check_opf(events, data, metadata["columns_1based"])
    replay = metadata.get("observations_version", 1) >= 3
    if replay:
        check_status(metadata, events)
        replay_observations(metadata, events, data, edges, nodes)
        if not metadata["result_available"] and (edges or nodes):
            raise ValueError("A scenario without a result must not export a graph")
    if not metadata["result_available"]:
        return
    for kind, columns in IDENTITY.items():
        pre = data[f"pre_{kind}"]
        expected = np.arange(1, len(pre) + 1)
        np.testing.assert_array_equal(data[f"{kind}_id"].ravel(), expected)
        check_identity(data[kind], pre, expected, columns)
    check_initial(metadata, events, data)
    check_actions(events, data, extended, replay)
    if not replay:
        check_graph(events, edges)
    check_ledger(metadata, events, data, edges)
    check_outages(metadata, data)


def mat_cells(value):
    return [value] if isinstance(value, dict) else list(value)


def compare_numeric(saved, exported):
    left, right = np.asarray(saved), np.asarray(exported)
    if left.size or right.size:
        np.testing.assert_array_equal(left.squeeze(), right.squeeze())


def compare_detail(saved, json_detail, field):
    if isinstance(json_detail, dict):
        if not isinstance(saved, dict) or saved.keys() != json_detail.keys():
            raise ValueError(f"Structure differs between record.mat and JSON in {field}")
        for key, value in json_detail.items():
            compare_detail(saved[key], value, f"{field}.{key}")
    elif isinstance(json_detail, str):
        if json_detail == "" and np.asarray(saved).size == 0:
            return
        if not isinstance(saved, str) or saved != json_detail:
            raise ValueError(f"Text differs between record.mat and JSON in {field}")
    elif json_detail == [] and np.asarray(saved).size == 0:
        return
    else:
        expected = np.asarray(json_detail, dtype=float)
        actual = np.asarray(saved, dtype=float)
        np.testing.assert_allclose(actual.squeeze(), expected.squeeze(),
                                   rtol=1e-15, atol=0, err_msg=field)


def check_record_exports(record, metadata, events, data):
    if bool(record["record_states"]) != metadata["record_states"] or (
        isinstance(record["result"], dict) != metadata["result_available"]
    ):
        raise ValueError("Record availability flags disagree with metadata")
    for field, value in metadata["summary"].items():
        if not isinstance(value, str):
            compare_numeric(record["summary"][field], np.nan if value is None else value)
    saved_events = mat_cells(record["events"])
    if len(saved_events) != len(events):
        raise ValueError("record.mat and JSONL event counts disagree")
    for source, exported in zip(saved_events, events):
        for field in ("sequence", "stage", "generation", "local_depth", "graph_parent"):
            if source[field] != exported[field]:
                raise ValueError(f"record.mat and JSONL disagree on {field}")
        for kind in IDENTITY:
            field = f"{kind}_rows"
            np.testing.assert_array_equal(ids(source[field]), ids(exported[field]))
        if metadata.get("observations_version", 1) >= 3:
            compare_detail(source["detail"], exported["detail"], f"event {exported['sequence']}")
            if source.get("opf_network_index") != exported.get("opf_network_index"):
                raise ValueError("record.mat and JSONL disagree on OPF snapshot index")
        elif exported["stage"] == "action":
            for field in ("type", "target"):
                if source["detail"][field] != exported["detail"][field]:
                    raise ValueError(f"record.mat and JSONL disagree on action {field}")
    saved_states = mat_cells(record["states"])
    if len(saved_states) != (len(events) if metadata["record_states"] else 0):
        raise ValueError("Unexpected record.mat snapshot count")
    if saved_states:
        for kind in IDENTITY:
            for state, export in zip(saved_states, data[f"state_{kind}"].ravel()):
                compare_numeric(state[kind], export)
    if "opf_networks" in data:
        saved_opf = mat_cells(record["opf_networks"])
        exported_opf = data["opf_networks"].ravel()
        if len(saved_opf) != len(exported_opf):
            raise ValueError("record.mat and numeric.mat OPF snapshot counts disagree")
        for snapshot, export in zip(saved_opf, exported_opf):
            for field in snapshot:
                compare_numeric(snapshot[field], export[0, 0][field])


@lru_cache(maxsize=4)
def read_prepared_plan(path, digest):
    # The caller checked the digest. It also keys the cache when a path is reused.
    return loadmat(path, variable_names=["prepared"], simplify_cells=True)["prepared"]


def validate_folder(folder, require_plan=False):
    folder = Path(folder)
    verify_integrity(folder, require_plan)
    metadata, events, data, edges = read_scenario(folder)
    has_result = metadata["result_available"]
    nodes_path = folder / "nodes.csv"
    nodes = csv_rows(nodes_path) if has_result or nodes_path.is_file() else []
    validate(metadata, events, data, edges, nodes)
    if metadata.get("observations_version", 1) >= 3:
        plan_path = folder.parent / "plan.mat"
        if plan_path.is_file():
            prepared = read_prepared_plan(plan_path, metadata["plan"]["sha256"])
            for kind in IDENTITY:
                compare_numeric(prepared["pre"][kind], data[f"pre_{kind}"])
            compare_numeric(prepared["pre"]["baseMVA"], metadata["base_mva"])
            for field in ("record_states", "load_scale"):
                compare_numeric(prepared["config"][field], metadata[field])
    saved = loadmat(folder / "record.mat", variable_names=["record"], simplify_cells=True)["record"]
    if (saved["scenario"]["id"], saved["scenario"]["seed"]) != (
        metadata["scenario"]["id"], metadata["scenario"]["seed"]
    ):
        raise ValueError("record.mat scenario disagrees with metadata")
    check_record_exports(saved, metadata, events, data)
    if metadata.get("observations_version", 1) >= 3:
        compare_detail(saved["error_category"], metadata["error_category"], "error_category")
        if has_result:
            compare_detail(saved["ledger"], metadata["ledger"], "ledger")
    error_category = metadata.get("error_category", "")
    if error_category != "input":
        for key in ("bus_numbers", "branch_rows", "gen_rows"):
            np.testing.assert_array_equal(ids(saved["scenario"]["fault"][key]),
                                          ids(metadata["scenario"]["fault"][key]))
    if has_result:
        names = {node["Name"] for node in nodes}
        endpoints = {edge[key] for edge in edges for key in ("source", "target")}
        if len(names) != len(nodes) or names != endpoints:
            raise ValueError("Graph nodes and edge endpoints disagree")
        for key in ("bus", "gen", "branch", *ACTION_COLUMNS):
            compare_numeric(saved["result"][key], data[key])
    return metadata, events, data, edges


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path, nargs="+")
    parser.add_argument("--require-plan", action="store_true", help="Require the two referenced plan files")
    args = parser.parse_args()
    for folder in args.scenario:
        metadata, events, _, edges = validate_folder(folder, args.require_plan)
        print(f"{folder.name}: {metadata['summary']['status']}, "
              f"{len(events)} events, {len(edges)} graph edges, "
              f"lost MW={metadata['summary']['lost_mw']}")


if __name__ == "__main__":
    main()
