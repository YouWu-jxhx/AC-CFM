function environment = setup(matpowerRoot)
% Configure the pinned numerical environment for the current MATLAB session.
    root = fileparts(fileparts(mfilename('fullpath')));
    if nargin < 1 || strlength(string(matpowerRoot)) == 0
        matpowerRoot = getenv('ACCFM_MATPOWER_ROOT');
    end
    if strlength(string(matpowerRoot)) == 0
        matpowerRoot = 'D:/matpower8.1';
    end
    matpowerRoot = absolute_path(matpowerRoot);
    vendor = fullfile(root, 'vendor', 'AC-CFM');
    core = fullfile(root, 'core');
    expectedCore = fullfile(vendor, 'accfm.m');
    assert(isfile(fullfile(matpowerRoot, 'install_matpower.m')), ...
        'ACCFMLab:MATPOWER', 'Set ACCFM_MATPOWER_ROOT to an existing MATPOWER 8.1 directory.');
    if ~strcmpi(which('runpf'), fullfile(matpowerRoot, 'lib', 'runpf.m'))
        addpath(matpowerRoot, '-begin');
        assert(install_matpower(1, 0, 0) == 1, 'ACCFMLab:MATPOWER', 'Could not configure MATPOWER.');
    end
    addpath(vendor, core, '-begin');
    assert(strcmpi(which('runpf'), fullfile(matpowerRoot, 'lib', 'runpf.m')) && ...
        strcmpi(which('runopf'), fullfile(matpowerRoot, 'lib', 'runopf.m')) && ...
        strcmpi(which('accfm'), expectedCore) && ...
        strcmpi(which('get_default_settings'), fullfile(vendor, 'get_default_settings.m')) && ...
        strcmpi(which('accfm_observed'), fullfile(core, 'accfm_observed.m')), ...
        'ACCFMLab:PathConflict', 'Check which -all for shadowed MATPOWER and AC-CFM functions.');
    assert(strcmp(mpver, '8.1') && strcmp(version('-release'), '2025a'), ...
        'ACCFMLab:Version', 'This baseline requires MATPOWER 8.1 and MATLAB R2025a.');
    assert(~have_fcn('ipopt'), 'ACCFMLab:IPOPTVisible', ...
        'Use a MATLAB session without IPOPT enabled. Upstream auto-selects it in recovery.');
    lockFile = fullfile(core,'vendor-lock.json');
    locked = jsondecode(fileread(lockFile));
    vendorFiles = dir(fullfile(vendor,'**','*'));
    vendorFiles = vendorFiles(~[vendorFiles.isdir]);
    files = [vendorFiles; dir(fullfile(root,'+accfmlab','**','*.m')); ...
        dir(fullfile(core,'accfm_observed.m')); dir(fullfile(core,'build_observed.py')); ...
        dir(lockFile)];
    inventory = strings(numel(files), 2);
    for n = 1:numel(files)
        file = fullfile(files(n).folder, files(n).name);
        relative = replace(string(file(length(root)+2:end)),'\','/');
        inventory(n,:) = [relative, string(file_hash(file))];
    end
    expected = ["vendor/AC-CFM/"+string({locked.files.path}).', ...
        string({locked.files.sha256}).'];
    assert(isequal(sortrows(inventory(1:numel(vendorFiles),:),1),sortrows(expected,1)), ...
        'ACCFMLab:VendorChanged','The pinned AC-CFM files differ from core/vendor-lock.json.');

    inventory = sortrows(inventory,1);
    implementation = java.security.MessageDigest.getInstance('SHA-256');
    implementation.update(typecast(unicode2native(jsonencode(inventory),'UTF-8'),'int8'));
    sourceHash = lower(reshape(dec2hex(typecast(implementation.digest(),'uint8'),2).',1,[]));

    dependencies = {'runpf','runopf','mpoption','mips','nlpopf_solver','newtonpf', ...
        'ext2int','extract_islands','load2disp'};
    solverInventory = strings(numel(dependencies),2);
    for n = 1:numel(dependencies)
        file = which(dependencies{n});
        assert(startsWith(file,[matpowerRoot filesep],'IgnoreCase',true), ...
            'ACCFMLab:PathConflict','%s is outside the configured MATPOWER tree.',dependencies{n});
        solverInventory(n,:) = [string(dependencies{n}),string(file_hash(file))];
    end
    environment = struct('matlab', version, 'computer', computer, 'matpower', mpver, ...
        'matpower_root', matpowerRoot, 'solver', 'MIPS', 'pf_core', 'legacy', ...
        'matpower_entry_hashes', {{file_hash(which('runpf')), file_hash(which('runopf'))}}, ...
        'upstream_commit', locked.upstream_commit, 'vendor_lock_sha256',file_hash(lockFile), ...
        'observer_generator_version',locked.generator_version, ...
        'implementation_files', inventory, 'platform_source_sha256', sourceHash, ...
        'observer_generator_sha256', file_hash(fullfile(core,'build_observed.py')), ...
        'solver_inventory', solverInventory, 'schema_version', 2);
end
