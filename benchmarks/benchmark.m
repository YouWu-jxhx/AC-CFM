function benchmark(baseOutput, caseSize, recordStates)
% Measure a fresh serial batch. Run each combination in a fresh process.
    arguments
        baseOutput (1,:) char
        caseSize (1,1) double {mustBeMember(caseSize,[9 118])}
        recordStates (1,1) logical
    end
    output = fullfile(baseOutput,sprintf('size%d-states%d',caseSize,recordStates));
    assert(~isfolder(output),'ACCFMLab:TestOutput','Choose a new benchmark directory.');
    cfg = accfmlab.config();
    cfg.output_dir = output;
    cfg.record_states = recordStates;
    if caseSize==9
        environment = accfmlab.setup();
        cfg.case_file = fullfile(environment.matpower_root,'data','case9.m');
        faults = [accfmlab.fault(),accfmlab.fault(1),accfmlab.fault(4),accfmlab.fault([1 4])];
    else
        faults = [accfmlab.fault(),accfmlab.fault(1),accfmlab.fault(9),accfmlab.fault([1 9])];
    end
    repeats = 3;
    manifest = accfmlab.scenarios(repmat(faults,1,repeats),cfg.seed);
    process = System.Diagnostics.Process.GetCurrentProcess();
    process.Refresh();
    workingSetBefore = double(process.WorkingSet64);
    peakBefore = double(process.PeakWorkingSet64);
    timer = tic;
    summary = accfmlab.batch(cfg,manifest);
    batchSeconds = toc(timer);
    process.Refresh();
    peakAfter = double(process.PeakWorkingSet64);

    scenarioRows = table();
    for n = 1:height(summary)
        folder = fullfile(output,sprintf('scenario_%06d',manifest(n).id));
        loaded = load(fullfile(folder,'record.mat'),'record');
        record = loaded.record;
        row = table(caseSize,recordStates,mod(n-1,numel(faults))+1, ...
            floor((n-1)/numel(faults))+1,n, ...
            numel(manifest(n).fault.branch_rows),summary.status(n), ...
            summary.has_solver_failure(n),summary.lost_mw(n),summary.elapsed_sec(n), ...
            summary.pf_count(n),numel(record.events),numel(record.opf_networks), ...
            snapshot_bytes(record.states,{'bus','gen','branch'}), ...
            snapshot_bytes(record.opf_networks,{'bus','gen','branch','gencost','gen_rows'}), ...
            byte_count(folder,'record.mat'),byte_count(folder,'numeric.mat'), ...
            byte_count(folder,'events.jsonl'),folder_bytes(folder), ...
            'VariableNames',{'buses','record_states','fault_case','repeat','scenario_id', ...
            'fault_width','status','solver_issue','lost_mw','scenario_seconds','pf_count', ...
            'events','opf_snapshots','state_matrix_bytes','opf_matrix_bytes','record_bytes', ...
            'numeric_bytes','jsonl_bytes','scenario_bytes'});
        scenarioRows = [scenarioRows;row]; %#ok<AGROW>
    end
    planBytes = byte_count(output,'plan.mat')+byte_count(output,'plan.json');
    payloadBytes = folder_bytes(output)+sum(scenarioRows.scenario_bytes);
    batchRow = table(caseSize,recordStates,height(summary),batchSeconds,workingSetBefore, ...
        peakBefore,peakAfter,planBytes,payloadBytes, ...
        'VariableNames',{'buses','record_states','scenarios','batch_seconds','working_set_before_bytes', ...
        'peak_before_bytes','peak_after_bytes','plan_bytes','batch_file_bytes'});
    writetable(scenarioRows,fullfile(output,'benchmark-scenarios.csv'));
    writetable(batchRow,fullfile(output,'benchmark-batch.csv'));
    fprintf('ACCFMLAB_BENCHMARK_PASSED %s\n',output);
end

function bytes = snapshot_bytes(snapshots,fields)
    bytes = 0;
    for n = 1:numel(snapshots)
        for name = fields
            values = snapshots{n}.(name{1}); %#ok<NASGU>
            info = whos('values');
            bytes = bytes+info.bytes;
        end
    end
end

function bytes = byte_count(folder,name)
    info = dir(fullfile(folder,name));
    bytes = info.bytes;
end

function bytes = folder_bytes(folder)
    items = dir(folder);
    bytes = sum([items(~[items.isdir]).bytes]);
end
