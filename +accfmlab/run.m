function record = run(cfg)
% Run one configured scenario, using the same durable path as batch runs.
    manifest = accfmlab.scenarios(cfg.fault, cfg.seed);
    accfmlab.batch(cfg, manifest);
    saved = load(fullfile(absolute_path(cfg.output_dir), 'scenario_000001', 'record.mat'), 'record');
    record = saved.record;
end
