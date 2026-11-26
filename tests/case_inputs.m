function case_inputs(output)
% Exercise structure admission and export with nontrivial original identities.
    assert(~isfolder(output),'ACCFMLab:TestOutput','Choose a new directory.');
    mkdir(output);
    accfmlab.setup();
    define_constants;
    stock = loadcase('case9');
    cfg = accfmlab.config();
    cfg.case_file = fullfile(output,'invalid.mat');
    cfg.output_dir = fullfile(output,'invalid-result');
    cases = {
        'duplicate bus', @() set_at(stock,'bus',2,BUS_I,stock.bus(1,BUS_I)), 'CaseFormat';
        'noninteger bus', @() set_at(stock,'bus',2,BUS_I,0.5), 'CaseFormat';
        'nonpositive bus', @() set_at(stock,'bus',2,BUS_I,0), 'CaseFormat';
        'invalid bus type', @() set_at(stock,'bus',2,BUS_TYPE,7), 'CaseFormat';
        'branch endpoint', @() set_at(stock,'branch',1,F_BUS,999), 'CaseFormat';
        'generator bus', @() set_at(stock,'gen',1,GEN_BUS,999), 'CaseFormat';
        'zero base', @() change_field(stock,'baseMVA',0), 'CaseFormat';
        'infinite base', @() change_field(stock,'baseMVA',Inf), 'CaseFormat';
        'missing bus matrix', @() rmfield(stock,'bus'), 'CaseFormat';
        'small bus matrix', @() change_field(stock,'bus',stock.bus(:,1:12)), 'CaseFormat';
        'nonfinite impedance', @() set_at(stock,'branch',1,BR_X,NaN), 'CaseFormat';
        'nonfinite tap', @() set_at(stock,'branch',1,TAP,Inf), 'CaseFormat';
        'invalid branch status', @() set_at(stock,'branch',1,BR_STATUS,2), 'CaseFormat';
        'nonfinite demand', @() set_at(stock,'bus',2,QD,Inf), 'CaseFormat';
        'inverted voltage bounds', @() set_at(stock,'bus',2,VMIN,2), 'CaseFormat';
        'inverted Q bounds', @() set_at(stock,'gen',1,QMIN,1000), 'CaseFormat';
        'inverted angle bounds', @() set_at(set_at(stock,'branch',1,ANGMIN,20),'branch',1,ANGMAX,10), 'CaseFormat';
        'cost rows', @() change_field(stock,'gencost',stock.gencost(1,:)), 'CaseFormat';
        'invalid cost degree', @() set_at(stock,'gencost',1,NCOST,100), 'CaseFormat';
        'inverted P/Q curve', @() set_at(set_at(stock,'gen',1,PC1,10),'gen',1,PC2,5), 'CaseFormat';
        'unsupported gentype orientation', @() change_field(stock,'gentype',{'GT','GT','GT'}), 'CaseUnsupported';
        'gentype rows', @() change_field(stock,'gentype',{'GT'}), 'CaseFormat';
        'valid unlimited rating', @() set_at(stock,'branch',1,RATE_A,0), 'CaseUnsupported';
        'valid generator status', @() set_at(stock,'gen',1,GEN_STATUS,2), 'CaseUnsupported';
        'valid separate Q costs', @() change_field(stock,'gencost',[stock.gencost;stock.gencost]), 'CaseUnsupported';
        'valid negative generator PMIN', @() set_at(stock,'gen',1,PMIN,-1), 'CaseUnsupported';
        'valid case without costs', @() rmfield(stock,'gencost'), 'CaseUnsupported';
        'deenergized bus', @() set_at(stock,'bus',2,BUS_TYPE,NONE), 'CaseUnsupported';
        'isolated topology', @() change_field(stock,'branch',stock.branch(2:end,:)), 'CaseUnsupported';
    };
    for n = 1:size(cases,1)
        mpc = cases{n,2}(); %#ok<NASGU>
        save(cfg.case_file,'mpc','-v7');
        expected = ['ACCFMLab:' cases{n,3}];
        try
            accfmlab.prepare(cfg);
        catch err
            assert(strcmp(err.identifier,expected),'Case %s expected %s, got %s: %s', ...
                cases{n,1},expected,err.identifier,err.message);
            continue
        end
        error('Invalid input accepted: %s.',cases{n,1});
    end
    fprintf('PASS %d format and platform admission checks\n',size(cases,1));

    mpc = stock;
    labels = [11;24;36;40;52;67;71;89;103];
    mpc.bus(:,BUS_I) = labels(mpc.bus(:,BUS_I));
    mpc.gen(:,GEN_BUS) = labels(mpc.gen(:,GEN_BUS));
    mpc.branch(:,F_BUS) = labels(mpc.branch(:,F_BUS));
    mpc.branch(:,T_BUS) = labels(mpc.branch(:,T_BUS));
    % Split an existing branch and non-reference generator into parallel rows.
    mpc.branch(1,[BR_R BR_X]) = 2*mpc.branch(1,[BR_R BR_X]);
    mpc.branch(1,[BR_B RATE_A RATE_B RATE_C]) = 0.5*mpc.branch(1,[BR_B RATE_A RATE_B RATE_C]);
    mpc.branch(end+1,:) = mpc.branch(1,:);
    mpc.branch(end,RATE_B) = Inf;
    mpc.branch(end,[ANGMIN ANGMAX]) = [-Inf Inf];
    mpc.gen(2,[PG QG QMAX QMIN PMAX PMIN]) = 0.5*mpc.gen(2,[PG QG QMAX QMIN PMAX PMIN]);
    mpc.gen(end+1,:) = mpc.gen(2,:);
    mpc.gen(end,VG) = mpc.gen(2,VG);
    mpc.gencost(end+1,:) = mpc.gencost(2,:);
    mpc.gen(end+1,:) = mpc.gen(2,:);
    mpc.gen(end,[PG QG VG GEN_STATUS]) = 0;
    mpc.gencost(end+1,:) = mpc.gencost(2,:);
    mpc.gentype = repmat({'GT'},size(mpc.gen,1),1);
    cfg.case_file = fullfile(output,'legal.mat');
    save(cfg.case_file,'mpc','-v7');
    cfg.output_dir = fullfile(output,'custom');
    cfg.record_states = true;
    report = accfmlab.prepare(cfg);
    assert(isequal(report.pre.bus(:,BUS_I),labels));
    assert(isequal(report.pre.gen(:,GEN_BUS),mpc.gen(:,GEN_BUS)));
    assert(isequal(report.pre.branch(:,[F_BUS T_BUS]),mpc.branch(:,[F_BUS T_BUS])));
    outputRecord = accfmlab.run(cfg);
    assert(outputRecord.summary.status=="completed_model" && abs(outputRecord.summary.lost_mw)<1e-6);
    fprintf('ACCFMLAB_CASE_INPUTS_PASSED %s\n',output);
end

function mpc = set_at(mpc,field,row,column,value)
    mpc.(field)(row,column) = value;
end

function mpc = change_field(mpc,field,value)
    mpc.(field) = value;
end
