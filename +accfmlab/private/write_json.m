function write_json(destination, payload)
% Write UTF-8 JSON with explicit write and close error checks.
    bytes = unicode2native([jsonencode(payload,'PrettyPrint',true) newline],'UTF-8');
    [fid,message] = fopen(destination,'wb');
    assert(fid>=0,'ACCFMLab:Output','%s',message);
    closeFile = onCleanup(@() close_if_open(fid)); %#ok<NASGU>
    assert(fwrite(fid,bytes,'uint8')==numel(bytes),'ACCFMLab:Output', ...
        'Short write to %s.',destination);
    assert(fclose(fid)==0,'ACCFMLab:Output','Could not close %s.',destination);
end

function close_if_open(fid)
    if ismember(fid,openedFiles())
        fclose(fid);
    end
end
