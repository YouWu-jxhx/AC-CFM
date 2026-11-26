function hex = file_hash(filename)
% Hash large files without allocating an equally large MATLAB array.
    [fid,message] = fopen(filename,'rb');
    assert(fid>=0,'ACCFMLab:File','%s',message);
    closeFile = onCleanup(@() fclose(fid)); %#ok<NASGU>
    digest = java.security.MessageDigest.getInstance('SHA-256');
    assert(fseek(fid,0,'eof')==0,'ACCFMLab:File','Could not seek %s.',filename);
    remaining = ftell(fid);
    assert(remaining>=0 && fseek(fid,0,'bof')==0,'ACCFMLab:File', ...
        'Could not determine the size of %s.',filename);
    while remaining>0
        count = min(remaining,1024*1024);
        [bytes,readCount] = fread(fid,count,'*uint8');
        assert(readCount==count,'ACCFMLab:File','Short read of %s.',filename);
        digest.update(typecast(bytes,'int8'));
        remaining = remaining-readCount;
    end
    hex = lower(reshape(dec2hex(typecast(digest.digest(),'uint8'),2).',1,[]));
end
