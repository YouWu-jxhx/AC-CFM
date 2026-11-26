function protections()
% Isolate protection branches with explicit deterministic solver returns.
    environment = accfmlab.setup();
    oldRng = rng; oldWarnings = warning; oldPath = path;
    restored = onCleanup(@() restore(oldRng,oldWarnings,oldPath)); %#ok<NASGU>
    real_small_network();
    real_action_cases();
    real_verification_limit();
    controlled_cases();
    fprintf('ACCFMLAB_PROTECTIONS_PASSED %s\n',environment.matlab);
end

function controlled_cases()
    [PQ,~,~,NONE,BUS_I,BUS_TYPE,PD,~,~,BS,~,VM,~,~,~,~,VMIN] = idx_bus;
    [GEN_BUS,PG,QG,~,~,~,~,GEN_STATUS,~,PMIN] = idx_gen;
    [F_BUS,T_BUS,~,~,~,RATE_A,~,~,~,~,BR_STATUS,PF,QF,PT,QT] = idx_brch;
    s = get_default_settings();
    s.grid_forming = {};
    s.mpopt = mpoption(s.mpopt,'exp.use_legacy_core',1,'opf.ac.solver','MIPS');
    s.record_states = true;
    s.observer = @collect;

    base = fixture();
    cases = {'UFLS','OFGS','XL','ULGT','UVLS','OL','VC','SH','OPF','verify_failure','retry_pmin'};
    rows = {2,2,2,2,2,2,2,2,[1;2],[1;2],zeros(0,1)};
    addpath(fullfile(fileparts(mfilename('fullpath')),'fixtures','protection'),'-begin');
    setappdata(0,'accfmlab_test_pf',@pf);
    setappdata(0,'accfmlab_test_opf',@opf);
    for n = 1:numel(cases)
        kind = cases{n};
        input = base;
        settings = s;
        if strcmp(kind,'UFLS')
            settings.dP_limit = 0;
        elseif strcmp(kind,'ULGT')
            input.gen(2,[PG PMIN]) = [0 5];
        elseif strcmp(kind,'OFGS')
            input.gen(:,PG) = [20;20];
        elseif strcmp(kind,'SH')
            input.bus(2,BS) = 10;
        elseif strcmp(kind,'retry_pmin')
            input.gen(2,[PG PMIN]) = [5 5];
        end
        records = {};
        states = {};
        pfCalls = 0; opfCalls = 0;
        rng(70,'twister');
        result = accfm_observed(input,struct(),settings);
        rngObserved = rng;
        observedCalls = [pfCalls opfCalls];
        pfCalls = 0; opfCalls = 0;
        rng(70,'twister');
        original = accfm(input,struct(),rmfield(settings,{'observer','record_states'}));
        assert(isequal(rngObserved,rng) && isequal(observedCalls,[pfCalls opfCalls]),kind);
        for field = {'bus','gen','branch','ls_total','ls_ufls','ls_uvls','ls_vcls','ls_opf', ...
                'ls_tripped','pf_count','bus_tripped','bus_ufls','bus_uvls','gen_tripped','branch_tripped'}
            key = field{1};
            assert(isequaln(result.(key),original.(key)),[kind ' ' key]);
        end
        assert(isequaln(result.G.Edges,original.G.Edges) && isequaln(result.G.Nodes,original.G.Nodes));
        action = kind;
        if strcmp(kind,'verify_failure')
            action = 'OPF';
        elseif strcmp(kind,'retry_pmin')
            action = 'VC';
        end
        event = find(cellfun(@(e) strcmp(e.stage,'action') && strcmp(e.detail.type,action),records));
        assert(isscalar(event),kind);
        e = records{event};
        state = states{event};
        assert(any(strcmp(result.G.Edges.Type,action) & ...
            strcmp(result.G.Edges.EndNodes(:,1),e.graph_parent) & ...
            strcmp(result.G.Edges.EndNodes(:,2),e.detail.target)),kind);
        assert(e.generation==1,kind);
        assert(isequal(state.bus(:,BUS_I),input.bus(state.bus_rows,BUS_I)));
        assert(isequal(state.gen(:,GEN_BUS),input.gen(state.gen_rows,GEN_BUS)));
        assert(isequal(state.branch(:,[F_BUS T_BUS]),input.branch(state.branch_rows,[F_BUS T_BUS])));
        before = find(cellfun(@(x) strcmp(x.stage,'before_frequency'),records),1);
        limits = find(cellfun(@(x) strcmp(x.stage,'before_limit_actions'),records),1);
        loss = 0;
        switch kind
            case 'UFLS'
                assert(records{before}.detail.delta_pg_mw==20);
                assert(abs(state.bus(2,PD)-36.3636)<1e-8 && result.bus_ufls(2,1)>0);
                loss = 3.6364;
            case 'OFGS'
                assert(records{before}.detail.delta_pg_mw==-20);
                assert(states{before}.gen(2,GEN_STATUS)==1 && state.gen(2,GEN_STATUS)==0);
                assert(result.gen_tripped(2,1)==1);
            case 'XL'
                assert(states{limits}.gen(2,QG)==70 && state.gen(2,QG)==50);
                assert(state.bus(2,BUS_TYPE)==PQ && state.gen(2,GEN_STATUS)==1);
            case 'ULGT'
                assert(states{limits}.gen(2,PG)<states{limits}.gen(2,PMIN));
                assert(state.gen(2,GEN_STATUS)==0 && result.gen_tripped(2,1)==1);
            case 'UVLS'
                assert(states{limits}.bus(2,VM)<states{limits}.bus(2,VMIN));
                assert(state.bus(2,PD)==38 && result.bus_uvls(2,1)==0.05);
                loss = 2;
            case 'OL'
                assert(states{limits}.branch(2,PF)>states{limits}.branch(2,RATE_A));
                assert(state.branch(2,BR_STATUS)==0 && result.branch_tripped(2,1)==1);
            otherwise
                stages = cellfun(@(x) x.stage,records,'UniformOutput',false);
                inputs = find(strcmp(stages,'before_recovery_opf'));
                outputs = find(strcmp(stages,'recovery_opf_result'));
                assert(isequal(outputs,inputs+1) && all(inputs<event));
                assert(all(states{inputs(1)}.opf_network.branch(:,RATE_A)==0));
                assert(isequal(states{inputs(1)}.opf_network.gen_rows,[1;2;0]));
                assert(states{inputs(1)}.opf_network.gen(3,PMIN)==-40);
                assert(isscalar(find(strcmp(stages,'pf_recovery_required'),1)));
                if strcmp(kind,'SH')
                    assert(numel(inputs)==2 && ~records{outputs(1)}.detail.success);
                    assert(states{inputs(1)}.opf_network.bus(2,BS)==10);
                    assert(states{inputs(2)}.opf_network.bus(2,BS)==0 && state.bus(2,BS)==0);
                elseif strcmp(kind,'VC')
                    assert(records{outputs(1)}.detail.success && records{outputs(1)}.detail.objective==15);
                    assert(records{outputs(1)}.detail.dispatchable_shed_mw==15 && state.bus(2,PD)==25);
                    loss = 15;
                elseif strcmp(kind,'retry_pmin')
                    assert(numel(inputs)==2 && ~records{outputs(1)}.detail.success && ...
                        records{outputs(2)}.detail.success && isempty(e.detail.bus_rows));
                    assert(states{inputs(1)}.opf_network.gen(2,PMIN)==5);
                    assert(states{inputs(2)}.opf_network.gen(2,PMIN)==0);
                    assert(states{inputs(2)}.opf_network.gen(3,PMIN)==-40);
                else
                    assert(all(state.bus(:,BUS_TYPE)==NONE) && all(result.bus_tripped(:,1)==1));
                    loss = 40;
                end
                verify = find(strcmp(stages,'verification_pf'),1);
                if strcmp(kind,'OPF')
                    assert(isempty(verify) && strcmp(e.detail.reason,'recovery_attempts_exhausted'));
                    assert(all(cellfun(@(x) ~x.detail.success,records(outputs))));
                else
                    assert(~isempty(verify) && records{verify}.detail.success==~strcmp(kind,'verify_failure'));
                    if strcmp(kind,'verify_failure')
                        assert(strcmp(e.detail.reason,'verification_pf_failed'));
                    end
                end
        end
        keys = intersect(fieldnames(e.detail),{'bus_rows','gen_rows','branch_rows'});
        assert(isscalar(keys) && isequal(e.detail.(keys{1}),rows{n}),kind);
        parts = [result.ls_ufls result.ls_uvls result.ls_vcls result.ls_opf result.ls_tripped]*40;
        expected = zeros(1,5);
        if loss>0
            expected(strcmp({'UFLS','UVLS','VC','OPF','other'},action)) = loss;
        end
        assert(max(abs(parts-expected))<1e-7 && abs(40-sum(result.bus(:,PD))-loss)<1e-7,kind);
        fprintf('PASS isolated %s with controlled solver returns\n',kind);
    end

    % A nontrivial graph uses different node labels, while physical outputs
    % and the caller's RNG advancement remain determined by the model.
    kind = 'OL'; records = {}; states = {}; pfCalls = 0; opfCalls = 0;
    rng(71,'twister');
    first = accfm_observed(base,struct(),s);
    pfCalls = 0; opfCalls = 0;
    rng(72,'twister');
    second = accfm_observed(base,struct(),s);
    assert(~isequal(first.G.Nodes.Name,second.G.Nodes.Name));
    assert(isequaln(first.bus,second.bus) && isequaln(first.gen,second.gen) && ...
        isequaln(first.branch,second.branch) && isequal(first.branch_tripped,second.branch_tripped));
    function collect(entry,state)
        records{end+1} = entry;
        states{end+1} = state;
    end

    function net = pf(net, ~)
        pfCalls = pfCalls+1;
        net.success = true;
        if pfCalls==1
            switch kind
                case 'UFLS'
                    net.gen(2,PG) = net.gen(2,PG)+20;
                case 'OFGS'
                    net.gen(2,PG) = 0;
                case 'XL'
                    net.gen(2,QG) = 70;
                case 'UVLS'
                    net.bus(2,VM) = 0.85;
                case 'OL'
                    net.branch(2,[PF PT]) = [120 -120];
                case {'VC','SH','OPF','verify_failure','retry_pmin'}
                    net.success = false;
            end
        else
            net.bus(:,VM) = 1;
            net.branch(:,[PF QF PT QT]) = 0;
            if strcmp(kind,'verify_failure') && pfCalls==2
                net.success = false;
            end
        end
    end

    function net = opf(net, ~)
        opfCalls = opfCalls+1;
        net.success = ~strcmp(kind,'OPF') && ~(strcmp(kind,'SH') && net.bus(2,BS)~=0) && ...
            ~(strcmp(kind,'retry_pmin') && any(net.gen(:,PMIN)>0));
        net.f = 0;
        net.raw.output.iterations = 1;
        if net.success && any(strcmp(kind,{'VC','verify_failure'}))
            net.gen(isload(net.gen),PG) = -25;
            net.f = 15;
        end
    end
end

function real_small_network()
    define_constants;
    s = get_default_settings();
    s.grid_forming = {};
    s.mpopt = mpoption(s.mpopt,'exp.use_legacy_core',1,'opf.ac.solver','MIPS');
    base = fixture();
    base.bus(2,[BUS_TYPE QD]) = [PQ 20];
    base.gen(2,GEN_STATUS) = 0;
    [balanced,ok] = runpf(base,s.mpopt);
    assert(ok && abs(sum(balanced.gen(:,PG))-40)<1e-6);
    fault = struct('branches',1);
    for seed = [70 71]
        input = balanced;
        input.branch(2,RATE_A) = 25;
        assert(hypot(input.branch(2,PF),input.branch(2,QF))<25);
        rng(seed,'twister');
        result = accfm_observed(input,fault,s);
        assert(result.branch_tripped(2,1)==1 && result.branch_tripped(1,1)==0);
        assert(all(result.branch(:,BR_STATUS)==0) && sum(result.bus(:,PD))==0);
        assert(result.ls_tripped==1 && nnz(strcmp(result.G.Edges.Type,'OL'))==1);
        if seed==70
            first = result;
        else
            assert(~isequal(first.G.Nodes.Name,result.G.Nodes.Name));
            assert(isequaln(first.bus,result.bus) && isequaln(first.gen,result.gen) && ...
                isequaln(first.branch,result.branch) && first.pf_count==result.pf_count);
        end
    end
    input = balanced;
    input.bus(2,VMIN) = 0.965;
    assert(input.bus(2,VM)>input.bus(2,VMIN));
    result = accfm_observed(input,fault,s);
    assert(result.bus_uvls(2,1)>0 && nnz(strcmp(result.G.Edges.Type,'UVLS'))>=1);
    assert(abs(40-sum(result.bus(:,PD))-40*result.ls_uvls)<1e-7);
    fprintf('PASS real two-bus NR overload, undervoltage and seed equivalence\n');
end

function real_action_cases()
% Synthetic post-event island states with genuine NR/MIPS solver calls.
    [PQ,~,~,NONE,BUS_I,BUS_TYPE,PD,QD,GS,BS,~,~,~,~,~,~,VMIN] = idx_bus;
    [GEN_BUS,PG,QG,QMAX,~,~,~,GEN_STATUS,PMAX,PMIN] = idx_gen;
    [F_BUS,T_BUS,~,~,~,RATE_A] = idx_brch;
    s = get_default_settings();
    s.grid_forming = {};
    s.mpopt = mpoption(s.mpopt,'exp.use_legacy_core',1,'opf.ac.solver','MIPS');
    s.observer = @collect;
    s.record_states = true;
    cases = {'UFLS','OFGS','XL','ULGT','VC','SH','OPF'};
    for n = 1:numel(cases)
        kind = cases{n};
        input = fixture();
        if ismember(kind,{'VC','SH','OPF'})
            input.bus(:,BUS_TYPE) = PQ;
            input.bus(:,VMIN) = 0.2;
            input.gen(2,GEN_STATUS) = 0;
            input.success = true;  % inherited successful pre-event solve
        end
        switch kind
            case 'UFLS'
                input.bus(2,BUS_TYPE) = PQ;
                input.gen(2,GEN_STATUS) = 0;
                input.gen(1,PG) = 30;
            case 'OFGS'
                input.gen(1,PG) = 80;
            case 'XL'
                input.bus(2,QD) = 20;
                input.gen(2,QMAX) = 2;
            case 'ULGT'
                input.gen(2,PMIN) = 5;
            case 'VC'
                input.gen(1,PMAX) = 25;
            case 'SH'
                input.bus(2,BS) = -5000;
            case 'OPF'
                input.gen(1,PMAX) = 25;
                input.bus(2,GS) = 1000;
        end
        records = {};
        states = {};
        rng(73,'twister');
        result = accfm_observed(input,struct(),s);
        rng(73,'twister');
        stock = accfm(input,struct(),rmfield(s,{'observer','record_states'}));
        assert(isequaln(result.bus,stock.bus) && isequaln(result.gen,stock.gen) && ...
            isequaln(result.branch,stock.branch) && result.pf_count==stock.pf_count && ...
            isequaln(result.G.Edges,stock.G.Edges) && isequaln(result.G.Nodes,stock.G.Nodes),kind);
        selected = find(cellfun(@(e) strcmp(e.stage,'action') && strcmp(e.detail.type,kind),records));
        assert(isscalar(selected),kind);
        event = records{selected};
        state = states{selected};
        assert(event.generation==1 && any(strcmp(result.G.Edges.Type,kind) & ...
            strcmp(result.G.Edges.EndNodes(:,1),event.graph_parent) & ...
            strcmp(result.G.Edges.EndNodes(:,2),event.detail.target)),kind);
        assert(isequal(state.bus(:,BUS_I),input.bus(state.bus_rows,BUS_I)));
        assert(isequal(state.gen(:,GEN_BUS),input.gen(state.gen_rows,GEN_BUS)));
        assert(isequal(state.branch(:,[F_BUS T_BUS]),input.branch(state.branch_rows,[F_BUS T_BUS])));
        stages = cellfun(@(e) e.stage,records,'UniformOutput',false);
        freq = find(strcmp(stages,'before_frequency'),1);
        limits = find(strcmp(stages,'before_limit_actions'),1);
        attempts = find(strcmp(stages,'before_recovery_opf'));
        outcomes = find(strcmp(stages,'recovery_opf_result'));
        if ~isempty(attempts)
            assert(isequal(outcomes,attempts+1));
            assert(all(states{attempts(1)}.opf_network.branch(:,RATE_A)==0));
            assert(isequal(states{attempts(1)}.opf_network.gen_rows,[1;2;0]));
            assert(strcmp(records{outcomes(end)}.detail.solver,'MIPS'));
        end
        loss = zeros(1,5);
        switch kind
            case 'UFLS'
                assert(abs(records{freq}.detail.delta_pg_mw-10)<1e-7 && event.detail.bus_rows==2);
                assert(abs(state.bus(2,PD)-31.3636)<1e-7);
                loss(1) = 8.6364;
            case 'OFGS'
                assert(records{freq}.detail.delta_pg_mw < -39 && event.detail.gen_rows==2);
                assert(state.gen(2,GEN_STATUS)==0 && result.gen_tripped(2,1)==1);
            case 'XL'
                assert(states{limits}.gen(2,QG)>20 && event.detail.gen_rows==2);
                assert(state.gen(2,QG)==2 && state.bus(2,BUS_TYPE)==PQ);
            case 'ULGT'
                assert(states{limits}.gen(2,PG)==0 && event.detail.gen_rows==2);
                assert(state.gen(2,GEN_STATUS)==0 && result.gen_tripped(2,1)==1);
            case 'VC'
                assert(isscalar(outcomes) && records{outcomes}.detail.success && event.detail.bus_rows==2);
                assert(abs(records{outcomes}.detail.dispatchable_shed_mw-15)<1e-5);
                assert(abs(state.bus(2,PD)-25)<1e-5 && verification_succeeded(records,stages));
                loss(3) = 15;
            case 'SH'
                assert(numel(outcomes)==2 && ~records{outcomes(1)}.detail.success && ...
                    records{outcomes(2)}.detail.success && verification_succeeded(records,stages));
                assert(states{attempts(1)}.opf_network.bus(2,BS)==-5000);
                assert(states{attempts(2)}.opf_network.bus(2,BS)==0 && state.bus(2,BS)==0);
                assert(event.detail.bus_rows==2);
            case 'OPF'
                assert(numel(outcomes)==2 && all(cellfun(@(e) ~e.detail.success,records(outcomes))));
                assert(~any(strcmp(stages,'verification_pf')) && strcmp(event.detail.reason,'recovery_attempts_exhausted'));
                assert(isequal(event.detail.bus_rows,[1;2]) && all(state.bus(:,BUS_TYPE)==NONE));
                loss(4) = 40;
        end
        actual = [result.ls_ufls result.ls_uvls result.ls_vcls result.ls_opf result.ls_tripped]*40;
        assert(max(abs(actual-loss))<1e-5 && abs(40-sum(result.bus(:,PD))-sum(loss))<1e-5,kind);
        fprintf('PASS isolated %s with real NR/MIPS\n',kind);
    end

    function collect(entry,state)
        records{end+1} = entry;
        states{end+1} = state;
    end
end

function success = verification_succeeded(events,stages)
    event = find(strcmp(stages,'verification_pf'),1);
    success = ~isempty(event) && events{event}.detail.success;
end

function real_verification_limit()
% Force a genuine numerical return failure using a zero NR iteration budget.
% The OPF still uses ordinary MIPS settings. No solver doubles are on path.
    [PQ,~,~,NONE,~,BUS_TYPE,PD,~,~,~,~,~,~,~,~,~,VMIN] = idx_bus;
    [~,~,~,~,~,~,~,GEN_STATUS,PMAX] = idx_gen;
    input = fixture();
    input.success = true;
    input.bus(:,BUS_TYPE) = PQ;
    input.bus(:,VMIN) = 0.2;
    input.gen(1,PMAX) = 25;
    input.gen(2,GEN_STATUS) = 0;
    s = get_default_settings();
    s.grid_forming = {};
    s.mpopt = mpoption(s.mpopt,'exp.use_legacy_core',1,'opf.ac.solver','MIPS', ...
        'pf.nr.max_it',0,'pf.tol',1e-13);
    s.record_states = false;
    s.observer = @collect;
    journal = {};
    rng(75,'twister');
    actual = accfm_observed(input,struct(),s);
    rng(75,'twister');
    stock = accfm(input,struct(),rmfield(s,{'observer','record_states'}));
    stages = cellfun(@(e) e.stage,journal,'UniformOutput',false);
    solved = find(strcmp(stages,'recovery_opf_result'));
    checked = find(strcmp(stages,'verification_pf'));
    tripped = find(cellfun(@(e) strcmp(e.stage,'action') && strcmp(e.detail.type,'OPF'),journal));
    assert(isscalar(solved) && isscalar(checked) && isscalar(tripped));
    assert(solved<checked && checked<tripped && journal{solved}.detail.success && ...
        ~journal{checked}.detail.success);
    assert(strcmp(journal{tripped}.detail.reason,'verification_pf_failed'));
    assert(isequal(journal{tripped}.detail.bus_rows,[1;2]) && nnz(actual.bus_uvls)>0);
    assert(all(actual.bus(:,BUS_TYPE)==NONE) && sum(actual.bus(:,PD))==0 && actual.ls_opf==1);
    assert(isequaln(actual.bus,stock.bus) && isequaln(actual.G.Edges,stock.G.Edges));
    fprintf('PASS real MIPS success followed by real NR budget failure and island shutdown\n');

    function collect(entry,~)
        journal{end+1} = entry;
    end
end

function net = fixture()
    net = struct('version','2','baseMVA',100);
    net.bus = [11 3 0 0 0 0 1 1 0 110 1 1.1 0.9;
               27 2 40 0 0 0 1 1 0 110 1 1.1 0.9];
    net.gen = [[11 40 0 50 -50 1 100 1 100 0;
                27 0 0 50 -50 1 100 1 30 0], zeros(2,11)];
    line = [11 27 0 0.1 0 100 100 100 0 0 1 -360 360 0 0 0 0];
    net.branch = [line; line];
    net.branch(2,4) = 0.2;
    net.gencost = [2 0 0 2 10 0; 2 0 0 2 20 0];
end

function restore(priorRng,priorWarnings,priorPath)
    path(priorPath);
    rng(priorRng);
    warning(priorWarnings);
    for name = {'accfmlab_test_pf','accfmlab_test_opf'}
        if isappdata(groot,name{1})
            rmappdata(groot,name{1});
        end
    end
end
