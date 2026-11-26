function [pre, audit, raw] = prepare_case(caseFile, operatingPoint, alpha, s)
    define_constants;
    validateattributes(alpha, {'numeric'}, {'scalar','real','finite','positive'});
    try
        raw = loadcase(caseFile);
    catch err
        error('ACCFMLab:CaseFormat','Could not load the MATPOWER case: %s',err.message);
    end
    validate_case(raw,s);
    input = raw;
    input.bus(:,[PD QD]) = alpha * raw.bus(:,[PD QD]);
    assert(all(isfinite(input.bus(:,[PD QD])),'all') && ...
        isfinite(sum(input.bus(:,PD))) && sum(input.bus(:,PD))>0, ...
        'ACCFMLab:CaseUnsupported','Scaled demands must be representable with positive total PD.');

    if strcmp(operatingPoint, 'opf')
        [op, opOK] = runopf(input,s.mpopt);
        assert(opOK, 'ACCFMLab:PreflightOPF', 'Pre-contingency AC OPF failed.');
        input.bus(:,[VM VA]) = op.bus(:,[VM VA]);
        input.gen(:,[PG QG VG]) = op.gen(:,[PG QG VG]);
    end
    input.gen(input.gen(:,GEN_STATUS)<=0,[PG QG]) = 0;
    [pre, pfOK] = runpf(input,s.mpopt);
    assert(pfOK, 'ACCFMLab:PreflightPF', 'Pre-contingency AC PF failed.');

    b = pre.bus(:,BUS_TYPE)~=NONE;
    g = pre.gen(:,GEN_STATUS)>0;
    l = pre.branch(:,BR_STATUS)>0;
    sf = hypot(pre.branch(l,PF),pre.branch(l,QF));
    st = hypot(pre.branch(l,PT),pre.branch(l,QT));
    [foundF, f] = ismember(pre.branch(l,F_BUS),pre.bus(:,BUS_I));
    [foundT, t] = ismember(pre.branch(l,T_BUS),pre.bus(:,BUS_I));
    assert(all(foundF & foundT));
    angle = pre.bus(f,VA)-pre.bus(t,VA);   % deg
    amin = pre.branch(l,ANGMIN); amax = pre.branch(l,ANGMAX);
    unbounded = amin==0 & amax==0;
    useLower = amin>-360 & ~unbounded;
    useUpper = amax<360 & ~unbounded;

    q = ext2int(pre);
    y = makeYbus(q);
    v = q.bus(:,VM).*exp(1i*pi/180*q.bus(:,VA));
    mismatch = v.*conj(y*v) - makeSbus(q.baseMVA,q.bus,q.gen);
    audit = struct('alpha',alpha,'load_mw',sum(pre.bus(:,PD)), ...
        'p_reserve_mw',sum(pre.gen(g,PMAX)-pre.gen(g,PG)), ...
        'max_end_loading',max(max(sf,st)./pre.branch(l,RATE_A)), ...
        'max_ac_cfm_loading',max((sf+st)./(2*pre.branch(l,RATE_A))), ...
        'max_mismatch_pu',norm(mismatch,inf));
    tolPQ = 1e-3; tolV = 1e-5; tolS = 1e-3; tolAngle = 1e-4;
    assert(all(pre.gen(g,PG) <= pre.gen(g,PMAX)+tolPQ & ...
               pre.gen(g,PG) >= pre.gen(g,PMIN)-tolPQ),'ACCFMLab:PreflightState','P limit violation.');
    assert(all(pre.gen(g,QG) <= pre.gen(g,QMAX)+tolPQ & ...
               pre.gen(g,QG) >= pre.gen(g,QMIN)-tolPQ),'ACCFMLab:PreflightState','Q limit violation.');
    assert(all(pre.bus(b,VM) >= pre.bus(b,VMIN)-tolV & ...
               pre.bus(b,VM) <= pre.bus(b,VMAX)+tolV),'ACCFMLab:PreflightState','Voltage limit violation.');
    assert(all(max(sf,st) <= pre.branch(l,RATE_A)+tolS),'ACCFMLab:PreflightState','Branch rating violation.');
    assert(all(angle(useLower)>=amin(useLower)-tolAngle) && ...
           all(angle(useUpper)<=amax(useUpper)+tolAngle),'ACCFMLab:PreflightState','Angle limit violation.');
    assert(audit.max_mismatch_pu < 1e-6, 'AC balance residual too large.');
    [groups, isolated] = find_islands(pre);
    assert(numel(groups)==1 && isempty(isolated) && nnz(pre.bus(:,BUS_TYPE)==REF)==1);
end
