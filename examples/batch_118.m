cfg = accfmlab.config();
cfg.output_dir = fullfile(pwd,'runs','example-batch');
cfg.record_states = true;
faults = [accfmlab.fault(), accfmlab.fault(1), accfmlab.fault(9), accfmlab.fault([1 9])];
manifest = accfmlab.scenarios(faults,cfg.seed);
summary = accfmlab.batch(cfg,manifest);
disp(summary(:,{'scenario_id','status','lost_mw','n_secondary'}));
