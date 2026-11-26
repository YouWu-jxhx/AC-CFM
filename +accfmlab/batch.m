function summary = batch(cfg, manifest)
% Execute or resume an ordered manifest on one operating point.
    manifest = validate_manifest(manifest);
    [cfg, settings, environment] = context(cfg);
    out = cfg.output_dir;
    if ~isfolder(out)
        [ok,message] = mkdir(out);
        assert(ok,'ACCFMLab:Output','%s',message);
    end
    lockFile = java.io.RandomAccessFile(fullfile(out,'.writer.lock'),'rw');
    unlock = onCleanup(@() lockFile.close()); %#ok<NASGU>
    try
        lock = lockFile.getChannel().tryLock();
    catch err
        error('ACCFMLab:BatchLock','Cannot acquire the output directory lock: %s',err.message);
    end
    assert(~isempty(lock),'ACCFMLab:BatchLock','Another process is writing this batch.');
    planFile = fullfile(out,'plan.mat');
    request = struct('config',cfg,'manifest',manifest,'environment',environment,'settings',settings);
    if isfile(planFile)
        saved = load(planFile,'request','prepared');
        assert(isequaln(saved.request,request),'ACCFMLab:ResumeMismatch', ...
            'Configuration, manifest, case, versions or code changed. Use a new output directory.');
        prepared = saved.prepared;
    else
        assert(isempty(dir(fullfile(out,'scenario_*'))),'ACCFMLab:MissingPlan', ...
            'Output already contains scenarios without a plan. Choose a new output directory.');
        prepared = prepare_validated(cfg, settings, environment);
        temporary = [tempname(out) '.mat'];
        save(temporary,'request','prepared','-v7');
        publish(temporary,planFile);
    end

    planCsv = fullfile(out,'manifest.csv');
    if ~isfile(planCsv)
        requested = table([manifest.id].',[manifest.seed].', ...
            string(arrayfun(@(x) jsonencode(x.fault),manifest,'UniformOutput',false)).', ...
            'VariableNames',{'scenario_id','seed','fault_json'});
        write_table(requested,planCsv);
    end
    rows = cell(numel(manifest),1);
    for n = 1:numel(manifest)
        scenario = manifest(n);
        folder = fullfile(out,sprintf('scenario_%06d',scenario.id));
        if isfolder(folder)
            saved = load(fullfile(folder,'record.mat'),'record');
            assert(isequaln(saved.record.scenario,scenario),'ACCFMLab:RecordMismatch', ...
                'Scenario %d does not match the saved manifest.',scenario.id);
            files = {'events.jsonl','metadata.json','numeric.mat'};
            if ~isempty(saved.record.result)
                files = [files,{'edges.csv','nodes.csv'}]; %#ok<AGROW>
            end
            assert(all(isfile(fullfile(folder,files))),'ACCFMLab:IncompleteRecord', ...
                'A previously committed scenario %d is missing files.',scenario.id);
            rows{n} = saved.record.summary;
        else
            record = simulate(prepared,scenario);
            stage = tempname(out);
            [ok,message] = mkdir(stage);
            assert(ok,'ACCFMLab:Output','%s',message);
            save(fullfile(stage,'record.mat'),'record','-v7');
            write_exchange(stage,record,prepared);
            publish(stage,folder);
            rows{n} = record.summary;
            fprintf('[%d/%d] scenario %d %s\n',n,numel(manifest),scenario.id,rows{n}.status);
        end
        summary = struct2table(vertcat(rows{1:n}));
        write_table(summary,fullfile(out,'summary.csv'));
    end
end

function manifest = validate_manifest(manifest)
    assert(isstruct(manifest) && isvector(manifest) && ~isempty(manifest) && ...
        isequal(sort(fieldnames(manifest)),{'fault';'id';'seed'}),'ACCFMLab:Manifest', ...
        'A nonempty scenario manifest must contain id, seed and fault.');
    for n = 1:numel(manifest)
        validateattributes(manifest(n).id,{'numeric'},{'scalar','integer','positive','<=',2^32-1});
        validateattributes(manifest(n).seed,{'numeric'},{'scalar','integer','nonnegative','<=',2^32-1});
    end
    assert(numel(unique([manifest.id]))==numel(manifest),'ACCFMLab:Manifest', ...
        'Scenario IDs must be unique.');
    manifest = reshape(manifest,1,[]);
end

function write_table(values,destination)
    temporary = [tempname(fileparts(destination)) '.csv'];
    writetable(values,temporary);
    publish(temporary,destination);
end

function publish(source,destination)
    [ok,message] = movefile(source,destination,'f');
    assert(ok,'ACCFMLab:Publish','%s',message);
end
