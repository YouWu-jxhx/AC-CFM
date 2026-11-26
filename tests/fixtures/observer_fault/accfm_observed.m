function result = accfm_observed(input,~,settings)
% Deliberately malformed observations presented to the production collector.
    result = [];
    if strcmp(input.observer_test,'callback')
        settings.observer(struct('stage','graph_node'),struct('bus_rows',[]));
    else
        event = struct('stage','pf_exception','detail', ...
            struct('identifier','ACCFMLabTest:OutsideSolver','message','Injected model program error.'));
        settings.observer(event,struct());
    end
end
