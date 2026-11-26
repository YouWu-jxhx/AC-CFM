function manifest = scenarios(faults, firstSeed)
% Build a deterministic manifest from an explicit, ordered list of faults.
    arguments
        faults (1,:) struct
        firstSeed (1,1) double {mustBeInteger,mustBeNonnegative} = 118001
    end
    assert(~isempty(faults) && firstSeed + numel(faults) - 1 <= 2^32-1, ...
        'ACCFMLab:Manifest', 'Use a nonempty list and seeds in the uint32 range.');
    manifest = repmat(struct('id', 0, 'seed', 0, 'fault', accfmlab.fault()), 1, numel(faults));
    for n = 1:numel(faults)
        manifest(n) = struct('id', n, 'seed', firstSeed+n-1, 'fault', faults(n));
    end
end
