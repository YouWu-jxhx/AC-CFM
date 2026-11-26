function record = simulate(prepared, scenario)
    [~,~,~,NONE,BUS_I,BUS_TYPE,PD,QD] = idx_bus;
    [GEN_BUS,PG,QG,~,~,~,~,GEN_STATUS] = idx_gen;
    [F_BUS,T_BUS,~,~,~,~,~,~,~,~,BR_STATUS,PF,QF,PT,QT] = idx_brch;
    pre = prepared.pre;
    s = prepared.settings;
    clock = tic;
    priorRng = rng;
    priorWarning = warning;
    rngCleanup = onCleanup(@() rng(priorRng)); %#ok<NASGU>
    warningCleanup = onCleanup(@() warning(priorWarning)); %#ok<NASGU>
    recorded = cell(0,1);
    states = cell(0,1);
    s.record_states = prepared.config.record_states;
    s.observer = @collect;
    row = struct('scenario_id',scenario.id,'seed',scenario.seed,'status',"error", ...
        'ls_total',NaN,'lost_mw',NaN,'initial_bus_lost_mw',NaN, ...
        'ls_ufls',NaN,'ls_uvls',NaN,'ls_vcls',NaN,'ls_opf',NaN,'ls_other',NaN, ...
        'n_off',NaN,'n_secondary',NaN,'n_ol',NaN,'pf_count',NaN,'elapsed_sec',NaN, ...
        'has_opf_trip',false,'has_solver_failure',false,'error_id',"",'error_message',"");
    r = [];
    ledger = [];
    initial = [];
    failure = [];
    try
        f = scenario.fault;
        assert(isstruct(f) && isscalar(f) && ...
            isequal(sort(fieldnames(f)), {'branch_rows';'bus_numbers';'gen_rows'}), ...
            'ACCFMLab:Fault', 'Build faults with accfmlab.fault.');
        branchRows = checked_ids(f.branch_rows, 'branch', size(pre.branch,1));
        genRows = checked_ids(f.gen_rows, 'generator', size(pre.gen,1));
        busNumbers = checked_ids(f.bus_numbers, 'bus', Inf);
        [present,busRows] = ismember(busNumbers,pre.bus(:,BUS_I));
        assert(all(present) && all(pre.branch(branchRows,BR_STATUS)>0) && ...
            all(pre.gen(genRows,GEN_STATUS)>0) && all(pre.bus(busRows,BUS_TYPE)~=NONE), ...
            'ACCFMLab:FaultOffline', 'An initial element is absent or out of service.');

        % Apply the external bus event defined in the guide. Native AC-CFM
        % handling is retained for direct branch and generator contingencies.
        input = pre;
        input.bus(busRows,BUS_TYPE) = NONE;
        input.bus(busRows,[PD QD]) = 0;
        adjacent = ismember(input.branch(:,F_BUS),busNumbers) | ismember(input.branch(:,T_BUS),busNumbers);
        localGen = ismember(input.gen(:,GEN_BUS),busNumbers);
        input.branch(adjacent,[BR_STATUS PF QF PT QT]) = 0;
        input.gen(localGen,[PG QG GEN_STATUS]) = 0;
        initial = struct('bus_rows',busRows,'bus_numbers',busNumbers, ...
            'branch_rows',union(branchRows,find(adjacent & pre.branch(:,BR_STATUS)>0)), ...
            'gen_rows',union(genRows,find(localGen & pre.gen(:,GEN_STATUS)>0)), ...
            'native_branches',branchRows,'native_gens',genRows);
        originalMW = sum(pre.bus(:,PD));
        modelMW = sum(input.bus(:,PD));
        assert(modelMW>0, 'ACCFMLab:ZeroModelLoad', ...
            'The externally applied event removes all active demand; AC-CFM requires a positive denominator.');
        rng(scenario.seed,'twister');
        r = accfm_observed(input,struct('branches',branchRows,'gens',genRows),s);

        assert(isequal(r.branch_id,(1:size(pre.branch,1)).') && ...
            isequal(r.gen_id,(1:size(pre.gen,1)).') && isequal(r.bus_id,(1:size(pre.bus,1)).') && ...
            isequal(r.branch(:,[F_BUS T_BUS]),pre.branch(:,[F_BUS T_BUS])) && ...
            isequal(r.bus(:,BUS_I),pre.bus(:,BUS_I)) && isequal(r.gen(:,GEN_BUS),pre.gen(:,GEN_BUS)), ...
            'ACCFMLab:ElementMap','Terminal matrices changed element row identities.');
        ledger = struct();
        ledger.branch = classify(pre.branch(:,BR_STATUS)>0, r.branch(:,BR_STATUS)>0, ...
            initial.branch_rows, r.branch_tripped, true);
        ledger.gen = classify(pre.gen(:,GEN_STATUS)>0, r.gen(:,GEN_STATUS)>0, ...
            initial.gen_rows, r.gen_tripped, true);
        ledger.bus = classify(pre.bus(:,BUS_TYPE)~=NONE, r.bus(:,BUS_TYPE)~=NONE, ...
            initial.bus_rows, r.bus_tripped, false);
        ledger.before_mw = originalMW;
        ledger.model_input_mw = modelMW;
        ledger.served_mw = sum(r.bus(:,PD));
        ledger.initial_bus_lost_mw = originalMW-modelMW;
        share = [r.ls_ufls r.ls_uvls r.ls_vcls r.ls_opf r.ls_tripped];
        ledger.model_loss_mw = share*modelMW;
        ledger.breakdown_mw = [ledger.initial_bus_lost_mw ledger.model_loss_mw];
        ledger.closure_mw = originalMW-ledger.served_mw-sum(ledger.breakdown_mw);
        ledger.graph_mw_delta = [sum(r.G.Edges.LS(strcmp(r.G.Edges.Type,'UFLS'))) ...
            sum(r.G.Edges.LS(strcmp(r.G.Edges.Type,'UVLS'))) ...
            sum(r.G.Edges.LS(strcmp(r.G.Edges.Type,'VC'))) ...
            sum(r.G.Edges.LS(strcmp(r.G.Edges.Type,'OPF')))] - ledger.model_loss_mw(1:4);
        row.status = "completed_model";
        row.lost_mw = originalMW-ledger.served_mw;
        row.ls_total = row.lost_mw/originalMW;
        row.initial_bus_lost_mw = ledger.initial_bus_lost_mw;
        row.ls_ufls = ledger.model_loss_mw(1)/originalMW;
        row.ls_uvls = ledger.model_loss_mw(2)/originalMW;
        row.ls_vcls = ledger.model_loss_mw(3)/originalMW;
        row.ls_opf = ledger.model_loss_mw(4)/originalMW;
        row.ls_other = ledger.model_loss_mw(5)/originalMW;
        row.n_off = numel(ledger.branch.final_off_rows);
        row.n_secondary = numel(setdiff(ledger.branch.final_off_rows,initial.branch_rows));
        row.n_ol = nnz(any(r.branch_tripped~=0,2));
        row.pf_count = r.pf_count;
        row.has_opf_trip = any(strcmp(r.G.Edges.Type,'OPF'));
        if row.has_opf_trip
            row.status = "model_opf_trip";
        end
        values = [ledger.breakdown_mw ledger.closure_mw ledger.graph_mw_delta r.load(end)];
        if any(~isfinite(values)) || any(ledger.breakdown_mw < -1e-6) || ...
                abs(ledger.closure_mw)>1e-6 || max(abs(ledger.graph_mw_delta))>1e-6 || ...
                abs(r.ls_total-(1-ledger.served_mw/modelMW))>1e-9 || ...
                abs(r.load(end)-ledger.served_mw)>1e-6 || row.ls_total < -1e-8 || row.ls_total > 1+1e-8
            row.status = "review_ledger";
        end
    catch err
        row.error_id = string(err.identifier);
        row.error_message = string(err.message);
        failure = struct('identifier',err.identifier,'message',err.message,'stack',err.stack);
        if strcmp(err.message,'Iteration limit reached')
            row.status = "iteration_limit";
        elseif ~isempty(recorded)
            last = recorded{end}.stage;
            if endsWith(last,'_pf_input') || strcmp(last,'before_recovery_opf')
                row.status = "solver_error";
            end
        end
    end
    for n = 1:numel(recorded)
        entry = recorded{n};
        if strcmp(entry.stage,'pf_exception') || ...
                (isfield(entry.detail,'success') && ~entry.detail.success)
            row.has_solver_failure = true;
        end
    end
    row.has_solver_failure = row.has_solver_failure || row.status=="solver_error";
    row.elapsed_sec = toc(clock);
    record = struct('summary',row,'scenario',scenario,'initial',initial, ...
        'ledger',ledger,'result',r,'events',{recorded},'states',{states},'failure',failure, ...
        'record_states',s.record_states,'finished_utc', ...
        char(datetime('now','TimeZone','UTC','Format',"uuuu-MM-dd'T'HH:mm:ss.SSS'Z'")));

    function collect(entry,state)
        entry.sequence = numel(recorded)+1;
        entry.bus_rows = state.bus_rows;
        entry.gen_rows = state.gen_rows;
        entry.branch_rows = state.branch_rows;
        recorded{end+1,1} = entry;
        if s.record_states
            states{end+1,1} = rmfield(state,{'bus_rows','gen_rows','branch_rows'});
        end
    end
end

function ids = checked_ids(ids, label, upper)
    assert(isnumeric(ids) && isreal(ids) && (isvector(ids) || isempty(ids)), ...
        'ACCFMLab:FaultID','Use a vector of %s IDs.',label);
    ids = double(ids(:));
    assert(all(isfinite(ids) & ids>=1 & ids<=upper & ids==fix(ids)) && ...
        numel(unique(ids))==numel(ids),'ACCFMLab:FaultID','Invalid or duplicate %s ID.',label);
end

function map = classify(wasOnline, isOnline, initial, flags, flagsAreExplicit)
    finalOff = find(wasOnline & ~isOnline);
    assert(all(ismember(initial,finalOff)) && ~any(~wasOnline & isOnline), ...
        'ACCFMLab:StatusLedger','Unexpected reactivation or missing initial outage.');
    flagged = find(any(flags~=0,2));
    explicit = intersect(setdiff(finalOff,initial),flagged);
    if ~flagsAreExplicit
        explicit = zeros(0,1);
    end
    map = struct('initial_rows',initial,'final_off_rows',finalOff, ...
        'flagged_rows',flagged,'explicit_trip_rows',explicit, ...
        'indirect_rows',setdiff(finalOff,union(initial,explicit)));
end
