function recovery(output)
% Exercise corruption and failed publication on disposable local batches.
    assert(~isfolder(output),'ACCFMLab:TestOutput','Choose a new directory.');
    mkdir(output);
    accfmlab.setup();
    cfg = accfmlab.config();
    cfg.case_file = which('case9');
    cfg.output_dir = fullfile(output,'integrity');
    scenarios = accfmlab.scenarios([accfmlab.fault(),accfmlab.fault([1 1])],cfg.seed);
    summary = accfmlab.batch(cfg,scenarios);
    assert(isequal(summary.status,["completed_model";"error"]));
    first = fullfile(cfg.output_dir,'scenario_000001');
    second = fullfile(cfg.output_dir,'scenario_000002');
    original = fileread(fullfile(first,'checksums.json'));
    assert(isfile(fullfile(second,'nodes.csv')) && isfile(fullfile(second,'checksums.json')));

    % Simulate a stranded, uncommitted staging directory and missing summary.
    stranded = fullfile(cfg.output_dir,'.staging','test-stranded');
    mkdir(stranded);
    touch(fullfile(stranded,'record.mat'));
    assert(movefile(fullfile(cfg.output_dir,'summary.csv'),fullfile(output,'held-summary.csv')));
    assert(isequaln(accfmlab.batch(cfg,scenarios),summary));
    assert(isfile(fullfile(stranded,'record.mat')));
    assert(strcmp(fileread(fullfile(first,'checksums.json')),original));

    journal = fullfile(second,'events.jsonl');
    assert(movefile(journal,fullfile(output,'held-journal.jsonl')));
    touch(journal);
    assert_error(@() accfmlab.batch(cfg,scenarios),'ACCFMLab:RecordIntegrity');
    assert(strcmp(fileread(journal),'injected corruption'));
    assert(movefile(journal,fullfile(output,'corrupt-journal.jsonl')));
    assert(movefile(fullfile(output,'held-journal.jsonl'),journal));
    for name = {'nodes.csv','checksums.json'}
        file = fullfile(second,name{1});
        held = fullfile(output,name{1});
        assert(movefile(file,held));
        assert_error(@() accfmlab.batch(cfg,scenarios),'ACCFMLab:IncompleteRecord');
        assert(~isfile(file));
        assert(movefile(held,file));
    end
    reference = fullfile(cfg.output_dir,'plan.json');
    held = fullfile(output,'held-plan.json');
    assert(movefile(reference,held));
    touch(reference);
    assert_error(@() accfmlab.batch(cfg,scenarios),'ACCFMLab:PlanIntegrity');
    assert(movefile(reference,fullfile(output,'corrupt-plan.json')));
    assert(movefile(held,reference));
    assert(isequaln(accfmlab.batch(cfg,scenarios),summary));
    fprintf('PASS staged leftovers, file and plan corruption, missing exports and resume\n');

    % An obstructed summary path fails after the first scenario publication.
    cfg.output_dir = fullfile(output,'summary-write-error');
    blocker = fullfile(cfg.output_dir,'summary.csv');
    mkdir(blocker);
    assert_error(@() accfmlab.batch(cfg,scenarios),'ACCFMLab:Publish');
    first = fullfile(cfg.output_dir,'scenario_000001');
    original = fileread(fullfile(first,'checksums.json'));
    assert(~isfolder(fullfile(cfg.output_dir,'scenario_000002')));
    assert(movefile(blocker,fullfile(output,'held-summary-directory')));
    assert(height(accfmlab.batch(cfg,scenarios))==2);
    assert(strcmp(fileread(fullfile(first,'checksums.json')),original));
    fprintf('PASS filesystem publication failure preserves completed output and can resume\n');

    cfg.output_dir = fullfile(output,'staging-write-error');
    mkdir(cfg.output_dir);
    touch(fullfile(cfg.output_dir,'.staging'));
    assert_error(@() accfmlab.batch(cfg,scenarios),'ACCFMLab:Output');
    assert(~isfile(fullfile(cfg.output_dir,'plan.mat')));
    fprintf('PASS staging creation failure publishes no plan or scenario\n');

    % Exercise the production simulation boundary with a malformed internal
    % prepared struct that public preflight would never permit.
    probe = fullfile(output,'private-probe');
    mkdir(probe);
    root = fileparts(fileparts(mfilename('fullpath')));
    assert(copyfile(fullfile(root,'+accfmlab','private','simulate.m'),probe));
    addpath(probe,'-begin');
    restorePath = onCleanup(@() rmpath(probe)); %#ok<NASGU>
    plan = load(fullfile(output,'integrity','plan.mat'),'prepared');
    prepared = plan.prepared;
    prepared.pre = rmfield(prepared.pre,'branch');
    assert_error(@() simulate(prepared,scenarios(1)),'MATLAB:nonExistentField');
    fprintf('PASS unknown program error propagates through simulation boundary\n');
    fixtureDir = fullfile(fileparts(mfilename('fullpath')),'fixtures','protection');
    addpath(fixtureDir,'-begin');
    restoreSolvers = onCleanup(@() reset_solvers(fixtureDir)); %#ok<NASGU>
    setappdata(groot,'accfmlab_test_pf',@fail_pf);
    setappdata(groot,'accfmlab_test_opf',@fail_opf);
    failed = simulate(plan.prepared,scenarios(1));
    assert(failed.summary.status=="solver_error" && failed.summary.has_solver_failure);
    assert(strcmp(failed.error_category,'solver_exception') && isempty(failed.result));
    stages = cellfun(@(event) event.stage,failed.events,'UniformOutput',false);
    assert(any(strcmp(stages,'ac_pf_exception')) && strcmp(stages{end},'recovery_opf_exception'));
    assert(failed.summary.error_id=="ACCFMLabTest:OPF" && numel(failed.opf_networks)==1);
    fprintf('PASS solver exceptions retain a journal and distinct failure category\n');
    fprintf('ACCFMLAB_RECOVERY_PASSED %s\n',output);
end

function touch(file)
    fid = fopen(file,'wt');
    assert(fid>=0);
    assert(fprintf(fid,'injected corruption')>0);
    assert(fclose(fid)==0);
end

function assert_error(action,identifier)
    try
        action();
    catch err
        assert(strcmp(err.identifier,identifier),'Expected %s, got %s: %s', ...
            identifier,err.identifier,err.message);
        return
    end
    error('Expected %s.',identifier);
end

function result = fail_pf(~,~) %#ok<STOUT>
    error('ACCFMLabTest:PF','Injected PF exception.');
end

function result = fail_opf(~,~) %#ok<STOUT>
    error('ACCFMLabTest:OPF','Injected OPF exception.');
end

function reset_solvers(folder)
    rmpath(folder);
    rmappdata(groot,'accfmlab_test_pf');
    rmappdata(groot,'accfmlab_test_opf');
end
