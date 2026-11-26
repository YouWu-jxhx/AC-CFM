function summary = batch(cfg, manifest)
% Execute or resume an ordered manifest on one operating point.
    manifest = validate_manifest(manifest);
    [cfg, settings, environment] = context(cfg);
    out = cfg.output_dir;
    if ~isfolder(out)
        [ok,message] = mkdir(out);
        assert(ok,'ACCFMLab:Output','%s',message);
    end
    try
        lockFile = java.io.RandomAccessFile(fullfile(out,'.writer.lock'),'rw');
    catch err
        error('ACCFMLab:Output','Cannot open the batch writer lock: %s',err.message);
    end
    unlock = onCleanup(@() lockFile.close()); %#ok<NASGU>
    try
        lock = lockFile.getChannel().tryLock();
    catch err
        error('ACCFMLab:BatchLock','Cannot acquire the output directory lock: %s',err.message);
    end
    assert(~isempty(lock),'ACCFMLab:BatchLock','Another process is writing this batch.');
    stageRoot = fullfile(out,'.staging');
    [ok,message] = mkdir(stageRoot);
    assert(ok,'ACCFMLab:Output','%s',message);
    planFile = fullfile(out,'plan.mat');
    request = struct('config',cfg,'manifest',manifest,'environment',environment,'settings',settings);
    if isfile(planFile)
        saved = load(planFile,'request','prepared');
        assert(all(isfield(saved,{'request','prepared'})),'ACCFMLab:PlanIntegrity', ...
            'The saved plan is missing required variables.');
        assert(isequaln(saved.request,request),'ACCFMLab:ResumeMismatch', ...
            'Configuration, manifest, case, versions or code changed. Use a new output directory.');
        prepared = saved.prepared;
    else
        assert(isempty(dir(fullfile(out,'scenario_*'))),'ACCFMLab:MissingPlan', ...
            'Output already contains scenarios without a plan. Choose a new output directory.');
        prepared = prepare_validated(cfg, settings, environment);
        temporary = [tempname(stageRoot) '.mat'];
        save(temporary,'request','prepared','-v7');
        publish_new(temporary,planFile);
    end

    planReference = export_plan(out,stageRoot,request,prepared,planFile);
    planCsv = fullfile(out,'manifest.csv');
    if ~isfile(planCsv)
        requested = table([manifest.id].',[manifest.seed].', ...
            string(arrayfun(@(x) jsonencode(x.fault),manifest,'UniformOutput',false)).', ...
            'VariableNames',{'scenario_id','seed','fault_json'});
        write_table(requested,planCsv,stageRoot);
    end
    rows = cell(numel(manifest),1);
    for n = 1:numel(manifest)
        scenario = manifest(n);
        folder = fullfile(out,sprintf('scenario_%06d',scenario.id));
        if isfolder(folder)
            scene_checksums(folder,planReference.sha256,scenario.id,true);
            saved = load(fullfile(folder,'record.mat'),'record');
            assert(isequaln(saved.record.scenario,scenario),'ACCFMLab:RecordMismatch', ...
                'Scenario %d does not match the saved manifest.',scenario.id);
            rows{n} = saved.record.summary;
        else
            assert(~isfile(folder),'ACCFMLab:Output','Expected a scenario directory at %s.',folder);
            fprintf('[running %d/%d] scenario %d\n',n,numel(manifest),scenario.id);
            record = simulate(prepared,scenario);
            stage = tempname(stageRoot);
            [ok,message] = mkdir(stage);
            assert(ok,'ACCFMLab:Output','%s',message);
            save(fullfile(stage,'record.mat'),'record','-v7');
            write_exchange(stage,record,prepared,planReference);
            scene_checksums(stage,planReference.sha256,scenario.id,false);
            publish_new(stage,folder);
            rows{n} = record.summary;
            fprintf('[%d/%d] scenario %d %s\n',n,numel(manifest),scenario.id,rows{n}.status);
        end
        summary = struct2table(vertcat(rows{1:n}));
        write_table(summary,fullfile(out,'summary.csv'),stageRoot);
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

function reference = export_plan(out,stageRoot,request,prepared,planFile)
    planHash = file_hash(planFile);
    payload = struct('schema_version',request.environment.schema_version, ...
        'plan_sha256',planHash,'environment',request.environment, ...
        'config',request.config,'settings',request.settings,'manifest',request.manifest, ...
        'operating_point_audit',prepared.audit, ...
        'seed_semantics','twister seed for native graph node labels; no scenario fault sampling', ...
        'grid_forming_upstream_default',{{'PS','ST','GT'}});
    destination = fullfile(out,'plan.json');
    if isfile(destination)
        expected = jsondecode(jsonencode(payload));
        try
            saved = jsondecode(fileread(destination));
        catch err
            error('ACCFMLab:PlanIntegrity','Could not read plan.json: %s',err.message);
        end
        assert(isequaln(saved,expected),'ACCFMLab:PlanIntegrity', ...
            'plan.json disagrees with the frozen plan or configuration.');
    else
        temporary = [tempname(stageRoot) '.json'];
        write_json(temporary,payload);
        publish_new(temporary,destination);
    end
    reference = struct('mat','../plan.mat','json','../plan.json','sha256',planHash, ...
        'json_sha256',file_hash(destination));
end

function write_table(values,destination,stageRoot)
    temporary = [tempname(stageRoot) '.csv'];
    writetable(values,temporary);
    assert(~isfolder(destination),'ACCFMLab:Publish','Expected a file at %s.',destination);
    atomic_move(temporary,destination);
end

function publish_new(source,destination)
    assert(~isfile(destination) && ~isfolder(destination),'ACCFMLab:Publish', ...
        'Destination already exists: %s.',destination);
    atomic_move(source,destination);
end

function atomic_move(source,destination)
    % Same-volume atomic rename or explicit failure.
    sourcePath = java.io.File(source).toPath();
    destinationPath = java.io.File(destination).toPath();
    options = javaArray('java.nio.file.CopyOption',1);
    options(1) = java.nio.file.StandardCopyOption.ATOMIC_MOVE;
    try
        java.nio.file.Files.move(sourcePath,destinationPath,options);
    catch err
        error('ACCFMLab:Publish','Could not atomically publish %s: %s',destination,err.message);
    end
end
