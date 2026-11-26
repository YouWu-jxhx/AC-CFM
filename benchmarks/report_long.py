"""Export measured IEEE 118 campaign metrics and independently validate each record."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from read_run import SCENARIO_FILES, read_scenario, validate_folder

INVALID_RECORD = (AssertionError, ValueError, KeyError, IndexError, OSError)


def vector(value):
    return value if isinstance(value, list) else [value]


def save_table(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def run(source, output, campaign):
    groups = re.compile(r"group-(\d+)" if campaign == "production" else r"group-(\d+)-pilot(?:-traced)?")
    design, rows, batch_files = [], [], []
    exposures = set()
    for folder in sorted(source.iterdir()):
        match = groups.fullmatch(folder.name)
        if not match or not (folder / "plan.json").is_file():
            continue
        group = int(match.group(1))
        plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
        env = plan["environment"]
        design.append({
            "experiment": folder.name, "group": group, "sampling_seed": 20261126 + group,
            "planned": len(plan["manifest"]), "load_scale": plan["config"]["load_scale"],
            "record_states": plan["config"]["record_states"], "operating_point": plan["config"]["operating_point"],
            "plan_sha256": plan["plan_sha256"], "case_sha256": env["case_sha256"],
            "matlab": env["matlab"], "matpower": env["matpower"], "solver": env["solver"],
            "pf_core": env["pf_core"], "observer_generator_version": env["observer_generator_version"],
            "solver_inventory": env["solver_inventory"],
            "source_sha256": env["platform_source_sha256"], "settings": plan["settings"],
            "operating_point_audit": plan["operating_point_audit"],
        })
        for item in plan["manifest"]:
            fault = item["fault"]
            outage = {key: " ".join(map(str, vector(fault[key]))) for key in
                      ("branch_rows", "gen_rows", "bus_numbers")}
            tag = (plan["config"]["load_scale"], *outage.values())
            if campaign == "production" and tag in exposures:
                raise ValueError(f"Duplicate physical experiment {tag}")
            exposures.add(tag)
            scenario = folder / f"scenario_{item['id']:06d}"
            row = {
                "experiment": folder.name, "group": group, "load_scale": plan["config"]["load_scale"],
                "record_states": int(plan["config"]["record_states"]), "id": item["id"],
                "model_seed": item["seed"], **outage,
            }
            error = ""
            if not scenario.is_dir():
                metadata, events = {"summary": {}, "error_category": ""}, []
                validation = "unpublished"
            else:
                try:
                    metadata, events, _, _ = validate_folder(scenario, require_plan=True)
                    validation = "passed"
                except INVALID_RECORD as exc:
                    validation = "rejected"
                    error = f"{type(exc).__name__}: {exc}".replace("\n", " ")
                    try:
                        metadata, events, _, _ = read_scenario(scenario)
                    except INVALID_RECORD:
                        metadata, events = {"summary": {}, "error_category": ""}, []
            summary = metadata["summary"]
            count = Counter(event["stage"] for event in events)
            failures = Counter(event["stage"] for event in events if event["detail"].get("success") is False)
            row.update({
                "validation": validation, "validation_error": error,
                "status": summary.get("status", ""), "error_category": metadata["error_category"],
                "error_id": summary.get("error_id", ""), "elapsed_seconds": summary.get("elapsed_sec"),
                "lost_mw": summary.get("lost_mw"), "native_pf_count": summary.get("pf_count"),
                "pf_calls": count["ac_pf_input"] + count["verification_pf_input"],
                "opf_calls": count["before_recovery_opf"], "events": len(events),
                "generation": max((e["generation"] for e in events), default=0),
                "pf_failed_returns": failures["ac_pf"] + failures["verification_pf"],
                "opf_failed_returns": failures["recovery_opf_result"],
                "solver_exceptions": sum(failures[name] for name in
                                         ("ac_pf_exception", "verification_pf_exception", "recovery_opf_exception")),
                "solver_issue": summary.get("has_solver_failure", ""), "opf_trip": summary.get("has_opf_trip", ""),
            })
            for filename in (*SCENARIO_FILES, "checksums.json"):
                path = scenario / filename
                row[f"{filename.replace('.', '_')}_bytes"] = path.stat().st_size if path.is_file() else 0
            row["scenario_bytes"] = sum(row[k] for k in row if k.endswith("_bytes"))
            rows.append(row)
        stage = folder / ".staging"
        batch_files.append({
            "experiment": folder.name,
            "plan_and_index_bytes": sum(p.stat().st_size for p in folder.iterdir() if p.is_file()),
            "staging_bytes": sum(p.stat().st_size for p in stage.rglob("*") if p.is_file()),
        })
    if not rows:
        raise ValueError("No frozen plans found")
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{campaign}-design.json").write_text(json.dumps(design, indent=2) + "\n", encoding="utf-8")
    save_table(output / f"{campaign}-scenarios.csv", rows)
    save_table(output / f"{campaign}-disk.csv", batch_files)
    for kind in ("batch", "profile"):
        metrics = []
        for path in sorted(source.glob(f"*-{kind}.csv")):
            with path.open(newline="") as stream:
                metrics.extend({"measurement": path.stem, **record} for record in csv.DictReader(stream))
        if metrics:
            save_table(output / f"{campaign}-{kind}.csv", metrics)
    print(campaign, "physical experiments", len(exposures), "validation", Counter(r["validation"] for r in rows))
    print("outcomes", Counter(r["status"] for r in rows))
    return any(row["validation"] != "passed" for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--campaign", choices=("pilot", "production"), default="production")
    args = parser.parse_args()
    sys.exit(run(args.source, args.output, args.campaign))


if __name__ == "__main__":
    main()
