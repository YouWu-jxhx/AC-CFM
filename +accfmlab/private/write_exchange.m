function write_exchange(folder,record,prepared,planReference)
    define_constants;
    eventFile = open_file(fullfile(folder,'events.jsonl'));
    closeEvents = onCleanup(@() close_if_open(eventFile)); %#ok<NASGU>
    for n = 1:numel(record.events)
        assert(fprintf(eventFile,'%s\n',jsonencode(record.events{n}))>=0, ...
            'ACCFMLab:Output','Could not write the event journal.');
    end
    [eventMessage,eventError] = ferror(eventFile);
    assert(eventError==0,'ACCFMLab:Output','%s',eventMessage);
    assert(fclose(eventFile)==0,'ACCFMLab:Output','Could not close the event journal.');

    columns = struct('bus_number',BUS_I,'bus_type',BUS_TYPE,'bus_pd',PD,'bus_qd',QD, ...
        'bus_vm',VM,'bus_va',VA,'branch_from',F_BUS,'branch_to',T_BUS,'branch_status',BR_STATUS, ...
        'branch_pq',[PF QF PT QT],'gen_bus',GEN_BUS,'gen_status',GEN_STATUS,'gen_pq',[PG QG], ...
        'bus_shunt',BS,'gen_pmin',PMIN);
    metadata = struct('schema_version',prepared.environment.schema_version, ...
        'observations_version',2,'plan',planReference, ...
        'error_category',record.error_category,'scenario',record.scenario,'summary',record.summary,'case_sha256',prepared.environment.case_sha256, ...
        'base_mva',prepared.pre.baseMVA,'load_scale',prepared.config.load_scale, ...
        'initial',record.initial,'ledger',record.ledger,'columns_1based',columns, ...
        'record_states',record.record_states,'result_available',~isempty(record.result), ...
        'finished_utc',record.finished_utc);
    write_json(fullfile(folder,'metadata.json'),metadata);

    r = record.result;
    pre = prepared.pre;
    numeric = struct('pre_bus',pre.bus,'pre_gen',pre.gen,'pre_branch',pre.branch);
    if ~isempty(r)
        names = {'bus','gen','branch','bus_id','gen_id','branch_id', ...
            'branch_tripped','gen_tripped','bus_tripped','bus_ufls','bus_uvls','load'};
        for n = 1:numel(names)
            numeric.(names{n}) = r.(names{n});
        end
        e = r.G.Edges;
        edges = table(string(e.EndNodes(:,1)),string(e.EndNodes(:,2)), ...
            string(e.Type),e.Weight,e.Base,e.LS, ...
            'VariableNames',{'source','target','action','weight','base','loss_mw'});
        writetable(edges,fullfile(folder,'edges.csv'));
        writetable(r.G.Nodes,fullfile(folder,'nodes.csv'));
    else
        edges = table(strings(0,1),strings(0,1),strings(0,1),zeros(0,1),zeros(0,1),zeros(0,1), ...
            'VariableNames',{'source','target','action','weight','base','loss_mw'});
        nodes = table(strings(0,1),zeros(0,1),strings(0,1),zeros(0,1),zeros(0,1),zeros(0,1), ...
            'VariableNames',{'Name','Buses','Type','Load','Generators','Lines'});
        writetable(edges,fullfile(folder,'edges.csv'));
        writetable(nodes,fullfile(folder,'nodes.csv'));
    end
    numeric.opf_networks = record.opf_networks;
    if record.record_states
        numeric.state_bus = cellfun(@(s) s.bus,record.states,'UniformOutput',false);
        numeric.state_gen = cellfun(@(s) s.gen,record.states,'UniformOutput',false);
        numeric.state_branch = cellfun(@(s) s.branch,record.states,'UniformOutput',false);
    end
    save(fullfile(folder,'numeric.mat'),'-struct','numeric','-v7');
end

function fid = open_file(file)
    [fid,message] = fopen(file,'wt','n','UTF-8');
    assert(fid>=0,'ACCFMLab:Output','%s',message);
end

function close_if_open(fid)
    if ismember(fid,openedFiles())
        fclose(fid);
    end
end
