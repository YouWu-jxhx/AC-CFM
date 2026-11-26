"""Run four serial cohorts on Windows, including one forced restart."""

import argparse
import csv
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from crash_resume import hashes, launch, terminate


def snapshot(folder):
    return {p.name: hashes(p) for p in folder.glob("scenario_*") if p.is_dir()}


def worker(matlab, root, group, mode, stop_after=None):
    name = f"group-{group}-{mode}.log"
    target = str(root).replace("'", "''")
    expression = (
        f"fid=fopen(fullfile('{target}','{name}.pid'),'w');"
        "fprintf(fid,'%d',feature('getpid'));fclose(fid);"
        f"addpath('benchmarks');long_batch('{target}',{group},'{mode}');"
    )
    start = last_change = time.monotonic()
    child = launch(matlab, root, name, expression)
    folder = root / f"group-{group}"
    pid = root / f"{name}.pid"
    previous = -1
    status = "failed"
    try:
        while child.poll() is None:
            count = sum(p.is_dir() for p in folder.glob("scenario_*"))
            if count != previous:
                last_change, previous = time.monotonic(), count
                if count and count % 25 == 0:
                    print(f"Group {group} {mode}: {count}/250 published", flush=True)
            if stop_after is not None and count >= stop_after:
                first = hashes(folder / "scenario_000001")
                terminate(child, pid, matlab)
                if hashes(folder / "scenario_000001") != first:
                    raise RuntimeError("First scene changed during forced termination")
                status = "interrupted"
                break
            if time.monotonic() - last_change > 180:
                terminate(child, pid, matlab)
                status = "no_progress_180s"
                break
            time.sleep(0.15)
        else:
            status = "completed" if child.returncode == 0 else "failed"
    finally:
        if child.poll() is None:
            terminate(child, pid, matlab)
    return {
        "group": group, "mode": mode, "status": status,
        "published": sum(p.is_dir() for p in folder.glob("scenario_*")),
        "process_wall_seconds": round(time.monotonic() - start, 3),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--matlab", required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This benchmark requires Windows.")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    first = worker(args.matlab, root, 1, "production", stop_after=125)
    committed = snapshot(root / "group-1")
    rows = [first]
    if first["status"] == "interrupted":
        resumed = worker(args.matlab, root, 1, "resume")
        after = snapshot(root / "group-1")
        unchanged = sum(after.get(name) == digest for name, digest in committed.items())
        resumed["preserved_scenarios"] = unchanged
        resumed["preserved_files"] = sum(len(digest) for name, digest in committed.items()
                                         if after.get(name) == digest)
        if unchanged != len(committed):
            resumed["status"] = "changed_committed_bytes"
        rows.append(resumed)
    for group in range(2, 5):
        rows.append(worker(args.matlab, root, group, "production"))
    fields = ["group", "mode", "status", "published", "process_wall_seconds",
              "preserved_scenarios", "preserved_files"]
    with (root / "processes.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        print(row, flush=True)
    if any(row["status"] not in ("completed", "interrupted") for row in rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
