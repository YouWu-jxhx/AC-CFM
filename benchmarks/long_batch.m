function long_batch(root, group, mode)
% Reproducible serial IEEE 118 production pilot and four fixed cohorts.
    arguments
        root (1,:) char
        group (1,1) double {mustBeMember(group,1:4)}
        mode (1,:) char {mustBeMember(mode,{'pilot','pilot-traced','production','resume','recheck'})}
    end
    scales = [1.00 0.95 1.05 1.025];
    cfg = accfmlab.config();
    cfg.load_scale = scales(group);
    cfg.record_states = group==4 || strcmp(mode,'pilot-traced');
    name = sprintf('group-%d',group);
    if startsWith(mode,'pilot')
        name = [name '-' mode];
    end
    cfg.output_dir = fullfile(root,name);
    environment = accfmlab.setup();
    define_constants;
    network = loadcase(cfg.case_file);
    branches = find(network.branch(:,BR_STATUS)==1).';
    generators = find(network.gen(:,GEN_STATUS)==1).';
    buses = network.bus(network.bus(:,PD)>0,BUS_I).';
    prior = rng;
    restore = onCleanup(@() rng(prior)); %#ok<NASGU>
    sampleSeed = 20261126+group;
    rng(sampleSeed,'twister');
    pairs = nchoosek(branches,2);
    genSample = generators(randperm(numel(generators),6));
    busSample = buses(randperm(numel(buses),4));
    if startsWith(mode,'pilot')
        branchSample = branches(randperm(numel(branches),8));
        pairSample = pairs(randperm(size(pairs,1),10),:);
        genSample = genSample(1:3); busSample = busSample(1:2);
    elseif group==1
        branchSample = branches;
        pairSample = pairs(randperm(size(pairs,1),250-numel(branchSample)-10),:);
    else
        branchSample = branches(randperm(numel(branches),40));
        pairSample = pairs(randperm(size(pairs,1),200),:);
    end
    faults = [arrayfun(@(row) accfmlab.fault(row),branchSample), ...
        arrayfun(@(row) accfmlab.fault(pairSample(row,:)),1:size(pairSample,1)), ...
        arrayfun(@(row) accfmlab.fault([],row),genSample), ...
        arrayfun(@(bus) accfmlab.fault([],[],bus),busSample)];
    manifest = accfmlab.scenarios(faults,cfg.seed);
    if ismember(mode,{'resume','recheck'})
        assert(isfile(fullfile(cfg.output_dir,'plan.mat')),'A frozen plan is required.');
    end
    start = tic;
    process = System.Diagnostics.Process.GetCurrentProcess();
    process.Refresh();
    peakBefore = double(process.PeakWorkingSet64);
    profile clear;
    profile on;
    summary = accfmlab.batch(cfg,manifest);
    profile off;
    wall = toc(start);
    process.Refresh();
    peakAfter = double(process.PeakWorkingSet64);
    data = profile('info');
    metrics = struct2table(data.FunctionTable);
    names = string(metrics.FunctionName);
    match = ["write_exchange","file_hash","write_table","simulate","scene_checksums"];
    keep = contains(names,match);
    prefix = fullfile(root,[name '-' mode]);
    writetable(metrics(keep,{'FunctionName','NumCalls','TotalTime'}),[prefix '-profile.csv']);
    writetable(table(group,cfg.load_scale,cfg.record_states,sampleSeed, ...
        height(summary),wall,peakBefore,peakAfter,string(environment.platform_source_sha256), ...
        'VariableNames',{'group','load_scale','record_states','sampling_seed','count','wall_seconds', ...
        'peak_before_bytes','peak_bytes','source_sha256'}),[prefix '-batch.csv']);
    fprintf('ACCFMLAB_LONG_BATCH_PASSED %s\n',prefix);
end
