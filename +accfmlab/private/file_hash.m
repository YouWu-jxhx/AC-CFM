function hex = file_hash(filename)
    [fid, message] = fopen(filename, 'rb');
    assert(fid >= 0, 'ACCFMLab:File', '%s', message);
    closeFile = onCleanup(@() fclose(fid)); %#ok<NASGU>
    bytes = fread(fid, Inf, '*uint8');
    digest = java.security.MessageDigest.getInstance('SHA-256');
    digest.update(typecast(bytes, 'int8'));
    hex = lower(reshape(dec2hex(typecast(digest.digest(), 'uint8'), 2).', 1, []));
end
