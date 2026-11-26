function scene_checksums(folder, planHash, scenarioId, verify)
% Commit and validate the exact portable scenario file set.
    files = {'record.mat','metadata.json','events.jsonl','numeric.mat','nodes.csv','edges.csv'};
    manifestFile = fullfile(folder,'checksums.json');
    if verify
        assert(isfile(manifestFile),'ACCFMLab:IncompleteRecord', ...
            'Missing checksum manifest in %s.',folder);
        try
            expected = jsondecode(fileread(manifestFile));
        catch err
            error('ACCFMLab:RecordIntegrity','Invalid checksum manifest in %s: %s',folder,err.message);
        end
        assert(isstruct(expected) && isscalar(expected) && ...
            all(isfield(expected,{'version','scenario_id','plan_sha256','files'})) && ...
            isequal(expected.version,1) && isequal(expected.scenario_id,scenarioId) && ...
            strcmp(expected.plan_sha256,planHash) && ...
            isstruct(expected.files) && numel(expected.files)==numel(files) && ...
            all(isfield(expected.files,{'name','bytes','sha256'})) && ...
            isequal({expected.files.name},files), ...
            'ACCFMLab:RecordIntegrity','Invalid file set or plan reference in %s.',folder);
    end
    entries = repmat(struct('name','','bytes',0,'sha256',''),numel(files),1);
    for n = 1:numel(files)
        file = fullfile(folder,files{n});
        assert(isfile(file),'ACCFMLab:IncompleteRecord','Missing committed file %s.',file);
        info = dir(file);
        entry = struct('name',files{n},'bytes',info.bytes,'sha256',file_hash(file));
        if verify
            saved = expected.files(n);
            assert(isequal(saved.bytes,entry.bytes) && strcmp(saved.sha256,entry.sha256), ...
                'ACCFMLab:RecordIntegrity','Checksum mismatch in %s.',file);
        end
        entries(n) = entry;
    end
    if ~verify
        contents = struct('version',1,'scenario_id',scenarioId,'plan_sha256',planHash,'files',entries);
        write_json(manifestFile,contents);
    end
end
