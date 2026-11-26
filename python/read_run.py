"""Read and independently check AC-CFM scenario exports."""

import argparse
import csv
import json
from collections import Counter
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
    edges = csv_rows(folder / "edges.csv") if metadata["result_available"] else []
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
    if pending is not None and any(event["stage"] == "recovery_opf_result" and
                                   "opf_network_index" not in event for event in events):
        raise ValueError("Recovery OPF result is missing its snapshot")


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


def check_actions(events, data, extended):
    names = ACTION_COLUMNS if extended else ("branch_tripped",)
    for name in names:
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
    if not events or events[0]["stage"] != "after_initial":
        raise ValueError("Missing initial event")
    np.testing.assert_array_equal(ids(events[0]["detail"]["branches"]), branches)
    np.testing.assert_array_equal(ids(events[0]["detail"]["gens"]), gens)
    if metadata["record_states"]:
        for kind, col, off_value in (
            ("bus", "bus_type", 4), ("branch", "branch_status", 0), ("gen", "gen_status", 0),
        ):
            initial_matrix = data[f"state_{kind}"].flat[0]
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


def validate(metadata, events, data, edges):
    check_events(metadata, events, data)
    extended = metadata.get("observations_version", 1) >= 2
    if extended:
        check_opf(events, data, metadata["columns_1based"])
    if not metadata["result_available"]:
        return
    for kind, columns in IDENTITY.items():
        pre = data[f"pre_{kind}"]
        expected = np.arange(1, len(pre) + 1)
        np.testing.assert_array_equal(data[f"{kind}_id"].ravel(), expected)
        check_identity(data[kind], pre, expected, columns)
    check_initial(metadata, events, data)
    check_actions(events, data, extended)
    check_graph(events, edges)
    check_ledger(metadata, events, data, edges)
    check_outages(metadata, data)


def validate_folder(folder):
    folder = Path(folder)
    metadata, events, data, edges = read_scenario(folder)
    validate(metadata, events, data, edges)
    saved = loadmat(folder / "record.mat", variable_names=["record"], simplify_cells=True)["record"]
    if (saved["scenario"]["id"], saved["scenario"]["seed"]) != (
        metadata["scenario"]["id"], metadata["scenario"]["seed"]
    ):
        raise ValueError("record.mat scenario disagrees with metadata")
    for key in ("bus_numbers", "branch_rows", "gen_rows"):
        np.testing.assert_array_equal(ids(saved["scenario"]["fault"][key]),
                                      ids(metadata["scenario"]["fault"][key]))
    if metadata["result_available"]:
        nodes = csv_rows(folder / "nodes.csv")
        names = {node["Name"] for node in nodes}
        endpoints = {edge[key] for edge in edges for key in ("source", "target")}
        if len(names) != len(nodes) or names != endpoints:
            raise ValueError("Graph nodes and edge endpoints disagree")
        for key in ("bus", "gen", "branch", *ACTION_COLUMNS):
            np.testing.assert_array_equal(saved["result"][key], data[key].squeeze())
    return metadata, events, data, edges


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path, nargs="+")
    for folder in parser.parse_args().scenario:
        metadata, events, _, edges = validate_folder(folder)
        print(f"{folder.name}: {metadata['summary']['status']}, "
              f"{len(events)} events, {len(edges)} graph edges, "
              f"lost MW={metadata['summary']['lost_mw']}")


if __name__ == "__main__":
    main()
