function absolute = absolute_path(value)
    file = java.io.File(char(value));
    if ~file.isAbsolute()
        file = java.io.File(pwd,char(value));
    end
    absolute = char(file.getCanonicalPath());
end
