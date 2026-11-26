cfg = accfmlab.config();
cfg.fault = accfmlab.fault(9);
cfg.record_states = true;
cfg.output_dir = fullfile(pwd,'runs','example-row9');
record = accfmlab.run(cfg);
disp(record.summary);
