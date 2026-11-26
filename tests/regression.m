function output = regression(output)
% Regress the platform against both the original implementation and fixed results.
    if nargin<1
        output = fullfile(pwd,'runs',['regression-' char(datetime('now','Format','yyyyMMdd-HHmmss-SSS'))]);
    end
    assert(~isfolder(output),'ACCFMLab:TestOutput','Choose a new directory for regression output.');
    cfg = accfmlab.config();
    cfg.output_dir = fullfile(output,'plain');
    faults = [accfmlab.fault(),accfmlab.fault(1),accfmlab.fault(9),accfmlab.fault([1 9])];
    manifest = accfmlab.scenarios(faults,cfg.seed);
    baseline = accfmlab.batch(cfg,manifest);
    assert(all(baseline.status=="completed_model"));
    assert(max(abs(baseline.ls_total-[0;0;0.554525932526224;0.554525948698150]))<1e-7);
    assert(isequal(baseline.n_off,[0;1;43;44]));
    assert(isequal(baseline.n_secondary,[0;0;42;42]));
    assert(isequal(baseline.n_ol,[0;0;33;33]));
    assert(isequal(baseline.pf_count,[1;2;58;58]));
    fprintf('PASS fixed 118 pilot outputs and N-0\n');

    traceCfg = cfg;
    traceCfg.output_dir = fullfile(output,'traced');
    traceCfg.record_states = true;
    traced = accfmlab.batch(traceCfg,manifest);
    assert(isequaln(traced(:,setdiff(traced.Properties.VariableNames,{'elapsed_sec'})), ...
        baseline(:,setdiff(baseline.Properties.VariableNames,{'elapsed_sec'}))));
    s = load(fullfile(cfg.output_dir,'plan.mat'),'prepared');
    p = s.prepared;
    originalRng = rng;
    originalWarnings = warning;
    resetRng = onCleanup(@() rng(originalRng)); %#ok<NASGU>
    resetWarnings = onCleanup(@() warning(originalWarnings)); %#ok<NASGU>
    for n = 1:numel(manifest)
        control = read_record(cfg.output_dir,n);
        treatment = read_record(traceCfg.output_dir,n);
        assert(isequaln(control.events,treatment.events) && isempty(control.states));
        assert(numel(treatment.events)==numel(treatment.states));
        rng(manifest(n).seed,'twister');
        stock = accfm(p.pre,struct('branches',faults(n).branch_rows),p.settings);
        for field = {'bus','gen','branch','branch_tripped','gen_tripped','bus_tripped', ...
                'bus_ufls','bus_uvls','load','ls_total','ls_ufls','ls_uvls','ls_vcls','ls_opf','ls_tripped','pf_count'}
            name = field{1};
            assert(isequaln(control.result.(name),stock.(name),treatment.result.(name)),name);
        end
        assert(isequaln(stock.G.Edges,treatment.result.G.Edges) && ...
            isequaln(stock.G.Nodes,treatment.result.G.Nodes));
        assert(abs(treatment.ledger.closure_mw)<1e-6);
        if n>=3
            stages = cellfun(@(x) x.stage,treatment.events,'UniformOutput',false);
            assert(any(strcmp(stages,'island_split')) && any(strcmp(stages,'before_frequency')) && ...
                any(strcmp(stages,'before_limit_actions')) && any(strcmp(stages,'action')));
        end
    end
    representative = read_record(traceCfg.output_dir,3);
    assert(nnz(cellfun(@(x) strcmp(x.stage,'before_limit_actions'),representative.events))==15);
    assert(nnz(cellfun(@(x) strcmp(x.stage,'island_deenergized'),representative.events))>0);
    assert(representative.summary.has_solver_failure && ~representative.summary.has_opf_trip);
    fprintf('PASS exact upstream/trace-off/trace-on equivalence across all four cases\n');

    % Simulate an interrupted run: leave committed predecessors in place.
    kept = read_record(cfg.output_dir,3);
    missing = fullfile(cfg.output_dir,'scenario_000004');
    assert(movefile(missing,fullfile(output,'held-scenario-000004')));
    resumed = accfmlab.batch(cfg,manifest);
    assert(isequaln(kept,read_record(cfg.output_dir,3)));
    assert(isequaln(resumed(:,setdiff(resumed.Properties.VariableNames,{'elapsed_sec'})), ...
        baseline(:,setdiff(baseline.Properties.VariableNames,{'elapsed_sec'}))));
    changed = manifest;
    changed(3).seed = changed(3).seed+1;
    assert_error(@() accfmlab.batch(cfg,changed),'ACCFMLab:ResumeMismatch');
    fprintf('PASS resume fills missing scenario and rejects a changed manifest\n');

    isolationCfg = cfg;
    isolationCfg.output_dir = fullfile(output,'isolation');
    isolated = accfmlab.batch(isolationCfg,accfmlab.scenarios( ...
        [accfmlab.fault(),accfmlab.fault([1 1]),accfmlab.fault(1)],cfg.seed));
    assert(isequal(isolated.status,["completed_model";"error";"completed_model"]));
    assert(isolated.error_id(2)=="ACCFMLab:FaultID");
    cfg.output_dir = fullfile(output,'recursion-limit');
    cfg.protection.max_recursion_depth = 1;
    cfg.fault = accfmlab.fault(9);
    limited = accfmlab.run(cfg);
    assert(limited.summary.status=="iteration_limit" && ~isempty(limited.events));
    assert(isempty(limited.result) && ~isempty(limited.failure));
    fprintf('PASS scenario failure isolation and recursion-limit record through single entry\n');

    cfg = accfmlab.config();
    cfg.operating_point = 'pf';
    mpc = p.pre; %#ok<NASGU>
    cfg.case_file = fullfile(output,'fixed-dispatch.mat');
    save(cfg.case_file,'mpc','-v7');
    cfg.output_dir = fullfile(output,'fixed-dispatch');
    fixed = accfmlab.run(cfg);
    assert(fixed.summary.status=="completed_model" && abs(fixed.summary.ls_total)<1e-9);
    fprintf('PASS supplied MAT case and PF-only operating point\n');
    fprintf('ACCFMLAB_REGRESSION_PASSED %s\n',output);
end

function record = read_record(root,id)
    data = load(fullfile(root,sprintf('scenario_%06d',id),'record.mat'),'record');
    record = data.record;
end

function assert_error(action,identifier)
    try
        action();
    catch err
        assert(strcmp(err.identifier,identifier),'Unexpected error: %s',err.message);
        return
    end
    error('Expected %s.',identifier);
end
