function f = fault(branchRows, genRows, busNumbers)
% Branch/generator identifiers are 1-based input rows. Buses use BUS_I.
    arguments
        branchRows {mustBeNumeric} = []
        genRows {mustBeNumeric} = []
        busNumbers {mustBeNumeric} = []
    end
    f = struct('branch_rows', branchRows(:), 'gen_rows', genRows(:), ...
        'bus_numbers', busNumbers(:));
end
