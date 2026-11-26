"""Generate or check the read-only observational copy of pinned AC-CFM."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor/AC-CFM"
LOCK = ROOT / "core/vendor-lock.json"
OBSERVED = ROOT / "core/accfm_observed.m"


def verified_source(vendor, lock):
    entries = lock["files"]
    expected = {entry["path"]: entry["sha256"] for entry in entries}
    paths = {path.relative_to(vendor).as_posix(): path
             for path in vendor.rglob("*") if path.is_file()}
    if len(entries) != len(expected) or expected.keys() != paths.keys():
        raise ValueError("Vendor file inventory differs from core/vendor-lock.json")
    original = None
    for name, path in paths.items():
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected[name]:
            raise ValueError(f"Vendor SHA-256 mismatch for {name}")
        if name == "accfm.m":
            original = content.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if original is None:
        raise ValueError("Missing original accfm.m")
    return original


def build_source(source):
    def replace(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError(f"Expected one upstream match for {old!r}")
        source = source.replace(old, new, 1)


    def before(anchor, code):
        replace(anchor, code + "\n" + anchor)


    def after(anchor, code):
        replace(anchor, anchor + "\n" + code)


    def observe(stage, network="network", detail="struct()", parent="Gnode_parent"):
        return f"observe(settings, '{stage}', {network}, i, k, {parent}, {detail});"


    replace("= accfm(network, initial_contingency, settings)", "= accfm_observed(network, initial_contingency, settings)")
    before("    % disable MATLAB warnings", "    observe(settings, 'after_initial', network, 0, 0, 'event', initial_contingency);")
    before("    % error if iteration limit reached", "    " + observe("island_enter"))
    before("            % apply recursion to every island", "            " + observe("island_split", "island", "struct('source', Gnode_parent)", "Gnode_name"))
    before("            network = trip_nodes(network, network.bus(:, BUS_I));\n            network.bus_tripped(:, i) = 1;\n            \n            if settings.verbose",
           "            " + observe("island_without_supply", detail=(
               "struct('load_mw', sum(network.bus(:, PD)), "
               "'no_active_capacity', ~any(network.gen(:, PMAX) > 0 & network.gen(:, GEN_STATUS) == 1), "
               "'no_grid_forming', ~isempty(settings.grid_forming) && isfield(network, 'gentype') && "
               "~any(ismember(network.gentype(network.gen(:, GEN_STATUS) == 1), settings.grid_forming)))")))
    before("                [network, Gnode_parent] = apply_vcls(network, settings, Gnode_parent, i, k);\n                conditions_changed = 1;",
           "                " + observe("missing_reference"))
    replace("network = distribute_slack(network, network_prev, settings);",
            "network = distribute_slack(network, network_prev, settings, i, k, Gnode_parent);")
    replace("function network = distribute_slack(network, network_prev, settings)",
            "function network = distribute_slack(network, network_prev, settings, i, k, Gnode_parent)")
    replace("                catch\n                    % sometimes", "                catch err\n                    " +
            observe("pf_exception", detail="struct('identifier', err.identifier, 'message', err.message)") +
            "\n                    % sometimes")
    before("                    [network, Gnode_parent] = apply_vcls(network, settings, Gnode_parent, i, k);",
           "                    " + observe("pf_recovery_required"))
    after("                sum_gmax = sum(network.gen(gens, PMAX));",
          "                " + observe("before_frequency", detail="struct('delta_pg_mw', dG, 'load_mw', sum_d, 'pg_mw', sum_g, 'pmax_mw', sum_gmax)"))
    before("                %% O/UXL", "                " + observe("before_limit_actions", detail=(
        "struct('branch_rows', network.branch_id(exceeded_lines), 'bus_rows', network.bus_id(exceeded_buses), "
        "'low_p_gen_rows', network.gen_id(exceeded_gens_p), 'xl_gen_rows', network.gen_id(exceeded_gens_q))")))
    before("            % cascade continues", "            " + observe("after_actions"))
    replace("            network.bus_tripped(:, i) = 1;\n            \n            if settings.verbose",
            "            network.bus_tripped(:, i) = 1;\n            " +
            observe("island_deenergized") + "\n\n            if settings.verbose")

    # Record each original graph edge at creation, so it keeps the model's
    # processing order and its island scope, including parallel edges.
    details = {
        "UFLS": "'bus_rows', ufls_bus_rows, 'load_before_mw', sum_d",
        "OFGS": "'gen_rows', network.gen_id(ind(1:gens_to_shed))",
        "XL": "'gen_rows', network.gen_id(exceeded_gens_q), 'load_before_mw', xl_load_before",
        "ULGT": "'gen_rows', network.gen_id(exceeded_gens_p)",
        "UVLS": "'bus_rows', network.bus_id([buses_uvls_apply(:); buses_uvls_exceeded(:)]), 'load_before_mw', load_initial",
        "OL": "'branch_rows', network.branch_id(exceeded_lines)",
        "SH": "'bus_rows', shunt_bus_rows",
        "VC": "'bus_rows', network.bus_id(ismember(network.bus(:, BUS_I), shed_bus_numbers)), 'load_before_mw', load_initial",
        "OPF": "'bus_rows', network.bus_id, 'reason', opf_trip_reason, 'load_before_mw', load_initial",
    }
    before("        network = trip_nodes(network, network.bus(:, BUS_I));\n        network.bus_tripped(:, i) = 1;",
           "        opf_trip_reason = 'recovery_attempts_exhausted';")
    before("            network = trip_nodes(network, network.bus(:, BUS_I));\n            network.bus_tripped(:, i) = 1;\n\n            Gnode_name",
           "            opf_trip_reason = 'verification_pf_failed';")
    before("            shunt_devices = length(find(network.bus(:, BS)));", "            shunt_bus_rows = network.bus_id(network.bus(:, BS) ~= 0);")
    before("                        network.bus(:, [PD QD]) = ls_factor * network.bus(:, [PD QD]);\n                        network.bus_ufls(:, i)",
           "                        ufls_bus_rows = network.bus_id(any(network.bus(:, [PD QD]) ~= 0, 2));")
    before("                    % O/UXL", "                    xl_load_before = sum(network.bus(:, PD));")
    before("        results_disp.gen(results_disp.gen(:, PMIN) < 0, :) = [];", """        shed_bus_numbers = [];
        if ~isempty(loads_shed)
            dispatchable = results_disp.gen(:, PMIN) < 0;
            changed = dispatchable & (abs(results_disp.gen(:, PG) - results_disp.gen(:, PMIN)) > 1e-6);
            shed_bus_numbers = results_disp.gen(changed, GEN_BUS);
        end""")
    expected_actions = dict.fromkeys(details, 1)
    expected_actions["OPF"] = 2
    seen_actions = dict.fromkeys(details, 0)
    pf_calls = 0
    output = []
    for line in source.splitlines():
        if " = runpf(network, settings.mpopt);" in line:
            pf_calls += 1
            lhs = line.split("=")[0].strip()
            label = "verification_pf" if lhs == "result" else "ac_pf"
            line = line.replace("runpf(network, settings.mpopt)", f"observed_pf(network, settings, i, k, Gnode_parent, '{label}')")
        output.append(line)
        for action, ids in details.items():
            if "addedge(" in line and "{'" + action + "'}" in line:
                seen_actions[action] += 1
                output.append(" " * (len(line) - len(line.lstrip())) + observe(
                    "action", detail=(f"struct('type', '{action}', 'target', Gnode_name, {ids}, "
                                      "'load_after_mw', sum(network.bus(:, PD)))")))
    if pf_calls != 6 or seen_actions != expected_actions:
        raise ValueError(f"Unexpected instrumentation counts: {pf_calls} PF calls, {seen_actions}")
    source = "\n".join(output) + "\n"

    replace("results_disp = runopf(network_disp, mpoption(settings.mpopt, 'opf.ac.solver', 'IPOPT'));",
            "results_disp = observed_opf(network_disp, mpoption(settings.mpopt, 'opf.ac.solver', 'IPOPT'), settings, network, i, k, Gnode_parent);")
    replace("results_disp = runopf(network_disp, settings.mpopt);",
            "results_disp = observed_opf(network_disp, settings.mpopt, settings, network, i, k, Gnode_parent);")

    source += """
function result = observed_pf(network, settings, i, k, parent, stage)
    observe(settings, [stage '_input'], network, i, k, parent, struct());
    try
        result = runpf(network, settings.mpopt);
    catch err
        observe(settings, [stage '_exception'], network, i, k, parent, ...
            struct('identifier', err.identifier, 'message', err.message, 'success', false));
        rethrow(err);
    end
    observe(settings, stage, result, i, k, parent, struct('success', logical(result.success)));
end

function result = observed_opf(network_disp, options, settings, island, i, k, parent)
    observe(settings, 'before_recovery_opf', island, i, k, parent, ...
        struct('solver', options.opf.ac.solver), network_disp);
    try
        result = runopf(network_disp, options);
    catch err
        observe(settings, 'recovery_opf_exception', island, i, k, parent, ...
            struct('identifier', err.identifier, 'message', err.message, 'success', false));
        rethrow(err);
    end
    if ~isfield(settings, 'observer')
        return
    end
    define_constants;
    detail = struct('success', logical(result.success), 'solver', options.opf.ac.solver, ...
        'objective', result.f);
    if isfield(result, 'raw') && isfield(result.raw, 'info')
        detail.exit_code = result.raw.info;
    end
    if isfield(result, 'raw') && isfield(result.raw, 'output')
        for field = {'iterations', 'message', 'alg'}
            key = field{1};
            if isfield(result.raw.output, key)
                detail.(key) = result.raw.output.(key);
            end
        end
    end
    loads = isload(network_disp.gen);
    detail.dispatchable_demand_mw = -sum(network_disp.gen(loads, PMIN));
    detail.dispatchable_served_mw = -sum(result.gen(loads, PG));
    detail.dispatchable_shed_mw = detail.dispatchable_demand_mw - detail.dispatchable_served_mw;
    observe(settings, 'recovery_opf_result', island, i, k, parent, detail, result);
end

function observe(settings, stage, network, i, k, parent, detail, dispatch)
    if ~isfield(settings, 'observer')
        return
    end
    entry = struct('stage', stage, 'generation', i, 'local_depth', k, ...
        'graph_parent', parent, 'detail', detail);
    state = struct('bus_rows', network.bus_id, 'gen_rows', network.gen_id, ...
        'branch_rows', network.branch_id);
    if settings.record_states
        state.bus = network.bus;
        state.gen = network.gen;
        state.branch = network.branch;
    end
    if nargin == 8
        % load2disp appends artificial generators in external bus order.
        extra = size(dispatch.gen,1) - numel(network.gen_id);
        state.opf_network = struct('baseMVA', dispatch.baseMVA, 'bus', dispatch.bus, ...
            'gen', dispatch.gen, 'branch', dispatch.branch, 'gencost', dispatch.gencost, ...
            'gen_rows', [network.gen_id; zeros(extra,1)]);
    end
    settings.observer(entry, state);
end
"""
    return source


def update_observed(target, expected, *, check):
    if check:
        if not target.is_file() or target.read_bytes() != expected:
            raise ValueError("Observer differs from generated output. Run python core/build_observed.py")
    else:
        target.write_bytes(expected)


def main():
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate without writing the observer")
    parser.add_argument("--version", action="version", version=lock["generator_version"])
    args = parser.parse_args()
    try:
        source = verified_source(VENDOR, lock)
        update_observed(OBSERVED, build_source(source).encode("utf-8"), check=args.check)
    except (OSError, ValueError) as err:
        parser.exit(1, f"{err}\n")
    if args.check:
        print("Vendor and generated observer match")


if __name__ == "__main__":
    main()
