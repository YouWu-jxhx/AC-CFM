"""Read one scenario directory created by the MATLAB platform."""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.io import loadmat


def ids(value):
    """MATLAB JSON encodes a scalar vector as a number."""
    return np.asarray(value, dtype=int).reshape(-1)


def read_scenario(folder):
    folder = Path(folder)
    metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    if metadata["schema_version"] != 1:
        raise ValueError("Unsupported result schema")
    events = [
        json.loads(line)
        for line in (folder / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    matrices = loadmat(folder / "numeric.mat")
    edges = []
    if metadata["result_available"]:
        with (folder / "edges.csv").open(newline="", encoding="utf-8-sig") as stream:
            edges = list(csv.DictReader(stream))
    return metadata, events, matrices, edges


def validate(metadata, events, data, edges):
    if [event["sequence"] for event in events] != list(range(1, len(events) + 1)):
        raise ValueError("Broken event sequence")
    columns = metadata["columns_1based"]
    if metadata["record_states"]:
        for kind in ("bus", "gen", "branch"):
            states = data[f"state_{kind}"].ravel()
            if len(states) != len(events):
                raise ValueError(f"{kind} state count differs from the event count")
            for event, local in zip(events, states):
                rows = ids(event[f"{kind}_rows"])
                if len(rows) != len(local) or (len(rows) and
                        (min(rows) < 1 or max(rows) > len(data[f"pre_{kind}"]))):
                    raise ValueError(f"Invalid {kind} state row map")
                if kind == "bus" and len(rows):
                    c = columns["bus_number"] - 1
                    np.testing.assert_array_equal(local[:, c], data["pre_bus"][rows - 1, c])
    if not metadata["result_available"]:
        return

    for kind, map_columns in (
        ("bus", [columns["bus_number"]]),
        ("gen", [columns["gen_bus"]]),
        ("branch", [columns["branch_from"], columns["branch_to"]]),
    ):
        c = ids(map_columns) - 1
        positions = np.arange(len(data[f"pre_{kind}"]))
        np.testing.assert_array_equal(data[f"{kind}_id"].ravel(), positions + 1)
        np.testing.assert_array_equal(data[kind][:, c], data[f"pre_{kind}"][:, c])
    ol_rows = {
        (int(row + 1), int(generation + 1))
        for row, generation in zip(*np.nonzero(data["branch_tripped"]))
    }
    event_ol_rows = {
        (row, event["generation"])
        for event in events
        if event["stage"] == "action" and event["detail"]["type"] == "OL"
        for row in ids(event["detail"]["branch_rows"])
    }
    if ol_rows != event_ol_rows:
        raise ValueError("OL journal disagrees with the native matrix")
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
    pd = columns["bus_pd"] - 1
    before = data["pre_bus"][:, pd].sum()
    served = data["bus"][:, pd].sum()
    ledger = metadata["ledger"]
    np.testing.assert_allclose(
        [before, served, before - served],
        [ledger["before_mw"], ledger["served_mw"], sum(ledger["breakdown_mw"])],
        atol=1e-6, rtol=0,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path, nargs="+")
    for folder in parser.parse_args().scenario:
        metadata, events, matrices, edges = read_scenario(folder)
        validate(metadata, events, matrices, edges)
        print(f"{folder.name}: {metadata['summary']['status']}, "
              f"{len(events)} events, {len(edges)} graph edges, "
              f"lost MW={metadata['summary']['lost_mw']}")


if __name__ == "__main__":
    main()
