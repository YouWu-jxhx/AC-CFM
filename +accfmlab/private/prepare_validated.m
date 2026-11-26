function prepared = prepare_validated(cfg, settings, environment)
    define_constants;
    [pre, audit, raw] = prepare_case(cfg.case_file, cfg.operating_point, cfg.load_scale, settings);
    previousRng = rng;
    previousWarnings = warning;
    rngCleanup = onCleanup(@() rng(previousRng)); %#ok<NASGU>
    warningCleanup = onCleanup(@() warning(previousWarnings)); %#ok<NASGU>
    rng(0, 'twister');
    n0 = accfm(pre, struct(), settings);
    assert(abs(n0.ls_total)<1e-9 && isequal(n0.G.Edges.Type, {'EV'}) && ...
        isequal(n0.branch(:,BR_STATUS), pre.branch(:,BR_STATUS)) && ...
        isequal(n0.gen(:,GEN_STATUS), pre.gen(:,GEN_STATUS)) && ...
        isequal(n0.bus(:,BUS_TYPE), pre.bus(:,BUS_TYPE)), ...
        'ACCFMLab:PreflightN0', 'Configured operating point failed N-0 acceptance.');
    audit.n0_loss_fraction = n0.ls_total;
    audit.n0_graph_edges = height(n0.G.Edges);
    prepared = struct('pre', pre, 'raw', raw, 'audit', audit, ...
        'config', cfg, 'settings', settings, 'environment', environment);
end
