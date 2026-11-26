function result = runpf(network, options)
% Only visible during the isolated protection branch tests.
    callback = getappdata(0,'accfmlab_test_pf');
    result = callback(network, options);
end
