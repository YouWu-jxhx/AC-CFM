function extended(output)
% Exercise the exposed reusable configuration paths on the pinned 118 case.
    define = accfmlab.config();
    a95 = define;
    a95.load_scale = 0.95;
    a105 = define;
    a105.load_scale = 1.05;
    lower = accfmlab.prepare(a95);
    upper = accfmlab.prepare(a105);
    assert(abs(lower.audit.load_mw-4029.9)<1e-8 && lower.audit.n0_graph_edges==1);
    assert(abs(upper.audit.load_mw-4454.1)<1e-8 && upper.audit.n0_graph_edges==1);
    fprintf('PASS load multipliers 0.95 and 1.05 through platform preflight\n');

    define.output_dir = fullfile(output,'events');
    faults = [accfmlab.fault([],[],65), accfmlab.fault([],[],2), accfmlab.fault([],1)];
    manifest = accfmlab.scenarios(faults,118701);
    summary = accfmlab.batch(define,manifest);
    assert(all(summary.status=="completed_model" | summary.status=="model_opf_trip"));
    assert(abs(summary.lost_mw(1)-3030.18)<0.01 && abs(summary.initial_bus_lost_mw(1))<1e-8);
    assert(abs(summary.initial_bus_lost_mw(2)-20)<1e-8);
    bus = load(fullfile(define.output_dir,'scenario_000002','record.mat'),'record');
    gen = load(fullfile(define.output_dir,'scenario_000003','record.mat'),'record');
    assert(isequal(bus.record.initial.bus_numbers,2) && ~isempty(bus.record.initial.branch_rows));
    assert(isequal(gen.record.ledger.gen.initial_rows,1) && ...
           ismember(1,gen.record.ledger.gen.final_off_rows));
    assert(abs(bus.record.ledger.closure_mw)<1e-6 && abs(gen.record.ledger.closure_mw)<1e-6);
    fprintf('PASS BUS_I 65 and 2 outages, direct BUS_I 2 loss of 20 MW, generator row 1 outage\n');
    fprintf('ACCFMLAB_EXTENDED_PASSED %s\n',output);
end
