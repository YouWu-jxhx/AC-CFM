function s = model_settings(overrides)
    s = get_default_settings();
    s.grid_forming = {};
    allowed = {'max_recursion_depth','uvls_per_step','uvls_max_steps', ...
        'dP_limit','P_overhead','Q_tolerance','grid_forming'};
    assert(isstruct(overrides) && isscalar(overrides) && ...
        all(ismember(fieldnames(overrides), allowed)), ...
        'ACCFMLab:Protection', 'Unknown or invalid protection settings.');
    names = fieldnames(overrides);
    for n = 1:numel(names)
        s.(names{n}) = overrides.(names{n});
    end
    validateattributes(s.max_recursion_depth, {'numeric'}, {'scalar','integer','positive','finite'});
    validateattributes(s.uvls_max_steps, {'numeric'}, {'scalar','integer','nonnegative','finite'});
    validateattributes(s.uvls_per_step, {'numeric'}, {'scalar','real','finite','>=',0,'<=',1});
    assert(s.uvls_per_step * s.uvls_max_steps <= 1, 'ACCFMLab:UVLS', ...
        'UVLS steps cannot shed more than the starting load.');
    for name = {'dP_limit','P_overhead','Q_tolerance'}
        validateattributes(s.(name{1}), {'numeric'}, {'scalar','real','finite','nonnegative'});
    end
    if isstring(s.grid_forming)
        s.grid_forming = cellstr(s.grid_forming);
    end
    assert(iscellstr(s.grid_forming), 'ACCFMLab:GridForming', 'Use a cell array of type codes.');
    s.mpopt = mpoption(s.mpopt, 'pf.alg','NR', 'pf.enforce_q_lims',0, ...
        'opf.ac.solver','MIPS', 'opf.flow_lim','S', 'exp.use_legacy_core',1);
end
