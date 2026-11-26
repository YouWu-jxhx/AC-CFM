"""Regenerate the observational copy from the pinned AC-CFM source."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "vendor/AC-CFM/accfm.m").read_text(encoding="utf-8")


def replace(old, new):
    global source
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
    "UFLS": "'bus_rows', ufls_bus_rows",
    "OFGS": "'gen_rows', network.gen_id(ind(1:gens_to_shed))",
    "XL": "'gen_rows', network.gen_id(exceeded_gens_q)",
    "ULGT": "'gen_rows', network.gen_id(exceeded_gens_p)",
    "UVLS": "'bus_rows', network.bus_id([buses_uvls_apply(:); buses_uvls_exceeded(:)])",
    "OL": "'branch_rows', network.branch_id(exceeded_lines)",
    "SH": "'bus_rows', shunt_bus_rows",
    "VC": "'bus_rows', network.bus_id(ismember(network.bus(:, BUS_I), shed_bus_numbers))",
    "OPF": "'bus_rows', network.bus_id, 'reason', opf_trip_reason",
}
before("        network = trip_nodes(network, network.bus(:, BUS_I));\n        network.bus_tripped(:, i) = 1;",
       "        opf_trip_reason = 'recovery_attempts_exhausted';")
before("            network = trip_nodes(network, network.bus(:, BUS_I));\n            network.bus_tripped(:, i) = 1;\n\n            Gnode_name",
       "            opf_trip_reason = 'verification_pf_failed';")
before("            shunt_devices = length(find(network.bus(:, BS)));", "            shunt_bus_rows = network.bus_id(network.bus(:, BS) ~= 0);")
before("                        network.bus(:, [PD QD]) = ls_factor * network.bus(:, [PD QD]);\n                        network.bus_ufls(:, i)",
       "                        ufls_bus_rows = network.bus_id(any(network.bus(:, [PD QD]) ~= 0, 2));")
before("        results_disp.gen(results_disp.gen(:, PMIN) < 0, :) = [];", "        shed_bus_numbers = results_disp.gen(loads_shed, GEN_BUS);")
output = []
for line in source.splitlines():
    if " = runpf(network, settings.mpopt);" in line:
        lhs = line.split("=")[0].strip()
        label = "verification_pf" if lhs == "result" else "ac_pf"
        line = line.replace("runpf(network, settings.mpopt)", f"observed_pf(network, settings, i, k, Gnode_parent, '{label}')")
    output.append(line)
    for action, ids in details.items():
        if "addedge(" in line and "{'" + action + "'}" in line:
            output.append(" " * (len(line) - len(line.lstrip())) + observe(
                "action", detail=f"struct('type', '{action}', 'target', Gnode_name, {ids})"))
source = "\n".join(output) + "\n"

before("    % use a faster OPF solver if available", "    " + observe("before_recovery_opf"))
after("    opf_success = results_disp.success;", "    " + observe(
    "recovery_opf_result", detail="struct('success', logical(opf_success))"))

source += """
function result = observed_pf(network, settings, i, k, parent, stage)
    observe(settings, [stage '_input'], network, i, k, parent, struct());
    result = runpf(network, settings.mpopt);
    observe(settings, stage, result, i, k, parent, struct('success', logical(result.success)));
end

function observe(settings, stage, network, i, k, parent, detail)
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
    settings.observer(entry, state);
end
"""
(ROOT / "core/accfm_observed.m").write_text(source, encoding="utf-8", newline="\n")
