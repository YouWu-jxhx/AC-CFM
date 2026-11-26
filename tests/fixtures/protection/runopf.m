function result = runopf(network, options)
% Only visible during the isolated protection branch tests.
    callback = getappdata(0,'accfmlab_test_opf');
    result = callback(network, options);
end
