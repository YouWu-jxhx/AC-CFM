function [cfg, settings, environment] = context(cfg)
    fields = fieldnames(accfmlab.config());
    assert(isstruct(cfg) && isscalar(cfg) && isequal(sort(fieldnames(cfg)), sort(fields)), ...
        'ACCFMLab:Config', 'Start with accfmlab.config() and keep its fields.');
    cfg.operating_point = validatestring(cfg.operating_point, {'opf','pf'});
    validateattributes(cfg.load_scale, {'numeric'}, {'scalar','real','finite','positive'});
    validateattributes(cfg.seed, {'numeric'}, {'scalar','integer','nonnegative','<=',2^32-1});
    assert(islogical(cfg.record_states) && isscalar(cfg.record_states), ...
        'ACCFMLab:RecordStates', 'record_states must be true or false.');
    for name = {'case_file','output_dir'}
        value = string(cfg.(name{1}));
        assert(isscalar(value) && strlength(value)>0, 'ACCFMLab:ConfigPath', ...
            'Specify a nonempty case file and output directory.');
        cfg.(name{1}) = absolute_path(value);
    end
    [~,~,extension] = fileparts(cfg.case_file);
    assert(isfile(cfg.case_file) && any(strcmpi(extension, {'.m','.mat'})), ...
        'ACCFMLab:Case', 'Use an existing MATPOWER .m or .mat case file.');
    environment = accfmlab.setup(cfg.matpower_root);
    environment.case_sha256 = file_hash(cfg.case_file);
    cfg.matpower_root = environment.matpower_root;
    settings = model_settings(cfg.protection);
end
