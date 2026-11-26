function prepared = prepare(cfg)
% Prepare and accept one immutable pre-contingency operating point in memory.
    [cfg, settings, environment] = context(cfg);
    prepared = prepare_validated(cfg, settings, environment);
end
