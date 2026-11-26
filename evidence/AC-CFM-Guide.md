# AC-CFM 仿真平台搭建与使用指南

适用环境为 Windows、MATLAB、MATPOWER。研究主线采用 IEEE 118-bus 的 PGLib-OPF v23.07 Typical Operations 算例。AC-CFM 固定到上游提交 `48eebaa19b96b00ee40d7a86f5c1132be74efd8b`。源码行号均指该提交。核查日期为 2026-11-25。

**初期交付标准**是复现仓库的 39-bus 示例，建立经交流潮流和无扰动试验验收的 118-bus 基准工况，并能从同一工况重复运行、保存和复查一组明确的初始故障。第 1–6 节支持这条主线。第 7–8 节的中间状态追踪、保护改动和并行化按研究问题启用。

文中以 **原生** 标记上游实现，以 **扩展** 标记需要自己加入的代码，以 **建议** 标记实验设计和验收口径。代码块标题给出保存位置或执行顺序。

## 1. 仿真原理与适用范围

### 1.1 目的与模型

AC-CFM 为一组给定的初始停运计算后续交流潮流、孤岛演化、保护动作和失供负荷。输入是含已知调度的 MATPOWER 算例及初始停运集合。一个计算阶段在给定拓扑、负荷、机组设定值和母线类型下求交流潮流。节点注入约束可写为以下复数方程。

$$
S_{i,\mathrm{G}}-S_{i,\mathrm{D}}
=V_i\overline{\sum_j Y_{ij}V_j}.
$$

这里 $Y$ 为对应拓扑的节点导纳矩阵，含算例中的并联导纳。每个孤岛独立选参考母线、求解并检查动作条件。发电机出力和电压受算例限值及模型规则约束。固定负荷切除通常同时缩减 $P$ 与 $Q$。频率保护通过有功不平衡的代理量触发。线路热保护通过静态视在功率超限代理触发。原论文第 III 节、图 2–3 描述了整体框架。MATPOWER 手册第 4、6 节分别给出 AC PF 与 AC OPF 方程。[原论文全文][paper-full] · [MATPOWER 手册][mp-manual]

### 1.2 从输入到终态

1. `accfm` 初始化元件行号、动作矩阵和有向图。之后同批应用母线、支路与机组初始停运。母线设置为 `NONE`，支路与机组分别更新状态列。该入口直接读取传入算例的出力，入口本身没有专门的故障前潮流验收。
2. `apply_recursion` 通过 `find_islands` 得到连通分量和孤立母线。多岛时以 `extract_islands` 切出子网，深度优先求解。各子网返回后按原始行号写回终态。当前代数 `i` 随保护造成的后续递归递增，检测到分岛时子岛继承 `i`，局部计数 `k` 重置。源码用 `i + k > max_recursion_depth` 抛出上限错误。
3. 单岛先检查可用发电、可选的成网类型及负荷条件。无正 `PMAX` 的在线可用容量、命中成网条件或岛内总 `PD` 为零，均可进入停运分支。`trip_nodes` 清零母线负荷，断开相连支路与机组。对继续运行的岛选择参考母线、求 AC 潮流并分摊 slack 变化。参考选择依赖 PV/REF、在线机组及容量。主潮流失败或缺少合适参考机组时进入 OPF 恢复逻辑。
4. 对满足求解条件的岛先判 UFLS/OFGS。发生改变则重算并推进递归，跳过本代后续保护检查。否则由同一份求解状态预先算出四组越限，再顺序执行 XL、ULGT、UVLS、OL。它们可在同一代共同动作。这个实现没有在这四组动作之间重新判定一遍全部越限。
5. 仍有正有功负荷且工况发生改变时进入下一代。终态由各岛结果合并。递归代数描述模型顺序，分岛后的不同支路之间由图记录父子关系。

源码入口与调用链见 [accfm.m L1–117][c-entry]、[L119–297][c-recur]、[L298–602][c-protect]、[L901–969][c-ref]。论文描述的初始扰动范围比该公开入口的三个字段更宽。给定负荷变化、并联补偿投切时，可显式构造改变后的算例，并单独记录外部扰动和分母口径。变压器如在 `branch` 中建模，可按支路行停运。

### 1.3 保护及求解回退

| 机制或图边 | 实现与解释 | 源码 |
| --- | --- | --- |
| `EV` / `ISL` | 初始扰动 / 岛分支。缺少合格电源或零总有功负荷的岛可退出。 | [入口][c-entry]、[分岛与终止][c-recur] |
| slack 分摊 | 对参考机组求解前后有功差进行再分配，初始权重为在线机组 `PMAX` 的比例，含小于 1 MW 的跳过条件及饱和处理。受截限算法、潮流再平衡和舍入影响，研究时从实际出力重算各台机组裕度。 | [L634–723][c-slack] |
| `UFLS` 欠频减载 | 代理量是求解前后机组总出力变化 $\Delta G$。正失衡、容量条件与 `dP_limit` 决定是否减载。目标发电取容量和前出力上浮上限的较小值，负荷保留比例还除以 $1+p_{\mathrm{overhead}}$，其中 $p_{\mathrm{overhead}}$ 对应 `P_overhead`。源码将比例舍入到 5 位，比例达到或超过 1 时设为 0。改参数时专门覆盖此边界，并检查离线机组初始 `PG/QG` 的处理。 | [L298–355][c-frequency] |
| `OFGS` 过频切机 | 负失衡超过门槛后按容量从小到大选机，切机台数的决策还依赖累积 `PG`，代码有至少 1 台的回退。切机后更新母线类型、重选参考并尽可能求 PF。 | [L358–409][c-frequency] |
| `XL` 励磁限幅 | `QG` 超过 `QMIN/QMAX` 加相对容差后，多母线岛将涉及的母线置为 PQ 并钳位机组无功。单母线岛另有按无功能力缩放负荷的分支。 | [L414–457][c-protect] |
| `ULGT` 低出力切机 | 在线机组 `PG` 舍入到 5 位后低于 `PMIN`，清零出力并停机。 | [L459–487][c-protect] |
| `UVLS` 低电压减载 | 对带正有功或正无功负荷的在役母线，比较三位小数的 `VM` 与 `VMIN`。逐次按 `uvls_per_step / (1 - uvls_per_step * n)` 缩减当前负荷，其中 `n` 来自 `bus_uvls` 非零记录计数。到上限后若仍欠压，切掉剩余负荷。VCLS 也会写入该矩阵，计数因此可能包含 VCLS。 | [L489–547][c-uvls]、[OPF 回写][c-opf] |
| `OL` 过载切线 | 同一代一次切除所有命中支路。实际判据为 $\operatorname{round}((\lvert S_f\rvert+\lvert S_t\rvert)/2,5)>\operatorname{round}(1.01\,S_{\mathrm{A}},5)$，其中 $\lvert S\rvert=\sqrt{P^2+Q^2}$，$S_{\mathrm{A}}$ 对应 `RATE_A`，单位 MVA。该判断无显式在线掩码，依赖 PF 正确回写停运支路流量。 | [L414–420][c-protect]、[L549–574][c-protect] |
| `VC` / `SH` / `OPF` | PF 失败或参考条件失败时，用 `load2disp` 把正有功需求转为可调负荷，以 AC OPF 尝试恢复。工作副本的 `RATE_A` 置零以从 MATPOWER OPF 中移除该限额，`VMIN` 置 0.2 p.u.。遇到特定参考条件还会调整电压上限、锁定已达限值的无功。OPF 失败后可能放宽正 `PMIN`、再尝试撤除母线 `BS`。经 OPF 恢复后仍做 PF 检查。所有尝试失败，或 OPF 成功而验证 PF 失败，均可能得到 `OPF` 停岛边。 | [L725–818][c-vcls]、[L820–899][c-opf]、[MATPOWER load2disp][mp-load] |

`apply_opf` 对 OPF 后的 PF 检查调用结果放在局部变量 `result`，随后据其 `success` 决定图边。它没有把这个 PF 对象整体回写为 `network`，所以应在插桩时分别记录 OPF 解、被验证的潮流解和下一次递归入口状态。`ls_opf` 也覆盖 OPF 成功后验证 PF 失败的情形。对恢复失败，求解器路径与数值参数构成模型结果的一部分。[OPF 回写与失败分支][c-opf]

### 1.4 结果可以支持什么

可研究给定算例、调度和保护规则下，拓扑改变怎样影响潮流重分配、过载、无功限幅、失供和分岛。受控机制比较应固定工况及外生扰动，再改变单项假设。模型的稳态代理对频率极值、RoCoF、转子功角轨迹、故障清除时间、继电器定时与时序配合均没有直接观测能力。涉及这些量时应使用带参数和控制器的 RMS 或 EMT 网络模型验证。论文第 III 节中的动态仿真用于论证个别机制，IV–VII 节分别研究参数敏感性、历史统计、性能与收敛、模型交叉验证。论文验证结果适用于其所用的模型和数据条件。[原论文第 III–VIII 节][paper-full]

**完成标准。** 能取一个岛说明这代的输入、PF/OPF 所在阶段、保护判据和状态变化，并指出要用哪些额外信息才能判定真实的暂态行为。

## 2. Windows 安装与官方示例

### 2.1 目的与取舍

先隔离依赖与算例变更，获得可重跑的上游基线。上游 README 推荐 MATLAB R2019a 或更新、要求 MATPOWER 7.1 或更新，建议 IPOPT。已有 MATLAB R2025a 和 MATPOWER 8.1 时可先用这组，锁定 7.1 作为版本对照。首轮用自带 MIPS 跑通 PF/OPF，之后只在需要时安装 IPOPT，并对同一批输入做成对回归。只要 `have_fcn('ipopt')` 返回真，AC-CFM 恢复分支会覆盖 `settings.mpopt.opf.ac.solver` 为 IPOPT。要保持 MIPS 基线，在未加载 IPOPT 的独立会话运行并检查探测值。[官方 README][readme] · [MATPOWER 安装][mp-install] · [可选求解器][mp-solvers] · [求解器分支][c-opf]

串行核心只需 MATLAB 和 MATPOWER。原生批处理有 `parfor`，并行池需要 Parallel Computing Toolbox。原生随机时间后处理的 `exprnd` 属于 Statistics and Machine Learning Toolbox。初期自写串行循环可避开这两个额外依赖。[MathWorks parfor][mw-parfor] · [MathWorks exprnd][mw-exprnd]

### 2.2 安装操作

1. 选一个可写的科研目录，例如 `D:/Research/ac-cfm-lab`。建议使用 `vendor/` 放固定版依赖，`cases/` 放原始输入与经校验的故障前工况，`scripts/` 放研究代码，`runs/` 放产物和日志。现有 MATPOWER 可位于此目录外，启动脚本指向其绝对路径即可。
2. 从 [MATPOWER 发布页][mp-releases] 下载发行包，解压后确认根目录存在 `install_matpower.m`。用 PowerShell 在实验目录执行以下命令。PGLib 仓库只使用根目录的 Typical Operations 算例文件。

```powershell
New-Item -ItemType Directory -Force vendor,cases,scripts,runs | Out-Null
git clone https://github.com/mnoebels/AC-CFM.git vendor/AC-CFM
git -C vendor/AC-CFM checkout --detach 48eebaa19b96b00ee40d7a86f5c1132be74efd8b
git clone --depth 1 --branch v23.07 https://github.com/power-grid-lib/pglib-opf.git vendor/pglib-opf
Copy-Item vendor/pglib-opf/pglib_opf_case118_ieee.m cases/
git -C vendor/AC-CFM rev-parse HEAD
git -C vendor/pglib-opf rev-parse HEAD
git -C vendor/pglib-opf rev-parse HEAD:pglib_opf_case118_ieee.m
Get-FileHash -Algorithm SHA256 cases/pglib_opf_case118_ieee.m
```

3. 从实验根目录启动 MATLAB。保存以下脚本为 `setup_accfm.m`，把 `matpowerRoot` 改为本机目录。显式执行 `setup_accfm` 以建立该会话的路径。升级或切换版本时开新会话再检查各函数解析路径。

```matlab
labRoot = fileparts(mfilename('fullpath'));
matpowerRoot = 'D:/matpower8.1';
assert(isfile(fullfile(matpowerRoot,'install_matpower.m')));
addpath(matpowerRoot);
assert(install_matpower(1, 0, 0) == 1);
addpath(fullfile(labRoot,'vendor','AC-CFM'), ...
        fullfile(labRoot,'cases'), fullfile(labRoot,'scripts'));
if ~isfolder(fullfile(labRoot,'runs')), mkdir(fullfile(labRoot,'runs')); end
which accfm -all
which runpf -all
which runopf -all
which case39 -all
which pglib_opf_case118_ieee -all
disp(version);
disp(mpver);
fprintf('IPOPT detected: %d\n', have_fcn('ipopt'));
```

4. 首次运行 `test_matpower`，区分通过、失败与因可选组件缺失跳过的测试。再在 MATLAB 执行下列最小 PF/OPF 检查。

```matlab
s = get_default_settings();
s.mpopt = mpoption(s.mpopt, 'opf.ac.solver','MIPS');
[~, pfOK] = runpf('case9', s.mpopt);
[~, opfOK] = runopf('case9', s.mpopt);
assert(pfOK && opfOK, 'MATPOWER case9 PF/OPF smoke test failed.');
% Optional: after installing an IPOPT MATLAB MEX compatible with your MATLAB
if have_fcn('ipopt')
    [~, ipoptOK] = runopf('case9', mpoption(s.mpopt,'opf.ac.solver','IPOPT'));
    assert(ipoptOK, 'IPOPT is visible but the OPF test failed.');
end
```

### 2.3 复现官方 39-bus 用例

在同一个 MATLAB 会话执行下列脚本。使用上游示例的原始 `case39`、支路**第 9 行**和默认保护参数。上一小节的 `s` 用于求解器测试，这里重新创建默认设置。保留默认 `verbose=0` 可在非交互环境运行数值回归。

```matlab
define_constants;
mpc39 = loadcase('case39');
fprintf('case39 branch row 9: %d -> %d\n', ...
        mpc39.branch(9,F_BUS), mpc39.branch(9,T_BUS));
s39 = get_default_settings();
rng(391,'twister');
r39 = accfm(mpc39,struct('branches',9),s39);
assert(r39.branch(9,BR_STATUS) == 0);
assert(abs(r39.ls_total - (1 - sum(r39.bus(:,PD))/sum(mpc39.bus(:,PD)))) < 1e-10);
figures39 = 100*[r39.ls_total r39.ls_ufls r39.ls_uvls r39.ls_vcls r39.ls_opf r39.ls_tripped];
log39 = sprintf('Total %.2f%% | UFLS %.2f%% | UVLS %.2f%% | VCLS %.2f%% | OPF %.2f%% | remainder %.2f%%',figures39);
disp(log39);
disp(r39.G.Edges(:,{'Type','Weight','Base','LS'}));
save(fullfile(labRoot,'runs','case39-reference.mat'),'mpc39','s39','r39','log39','-v7');
```

上游 README 中参考总失负荷为 **45.05%**，其中 UFLS 20.97%、UVLS 0.88%、VCLS 4.61%、OPF 停岛 0.00%、余项 18.59%。第一批过载跳闸包含 6–11。以这些数值及支路事件作为参照，保存本机观测值、路径、选项和图边。运行耗时和随机节点名不参加回归。若总量或动作差异明显，逐个核对 `case39` 来源、MATPOWER 与 IPOPT 可见性、神经网络或自定义路径中的同名函数、初始行号和第一处分歧。上游输出来自特定环境，复现公开示例和复现论文全部试验是两个任务。[官方示例和参考日志][readme]

在支持图形的 MATLAB 桌面会话，可用 `s39.verbose = 1;` 再运行相同调用，以获取上游逐步日志和传播图。无图形会话优先使用已保存的图结构、求解结论和文本记录。

**完成标准。** `case9` 通过 PF 与指定求解器的 OPF。官方 39-bus 示例保留本机的输入、保护结果和日志，可定位与官方记录的差异。研究代码和上游源码分别维护，改动上游时创建研究分支并保留原提交。

## 3. 建立有物理约束的 IEEE 118-bus 工况

### 3.1 目的与算例选择

这一阶段把网络参数、额定值和故障前调度落实到一个可审计的输入。两个公开文件都给出 118 个母线、186 条支路、54 行机组和 4242 MW 原始有功需求。对应的线路约束和机组能力数据关系如下。

| 算例 | 容量和出力假设 | 用途 |
| --- | --- | --- |
| MATPOWER 7.1/8.1 标准 `case118` | 核查的两个版本中，186 条支路的 A/B/C 全为 0，文件注释说明原始 MVA 限额缺失。MATPOWER OPF 以 0 表示无限额。AC-CFM 的原生过载比较直接使用这一列，任何高于舍入门槛的正视在功率会超过 0。 | 核对网络拓扑和 MATPOWER 基本功能。直接运行原生 AC-CFM 会把缺失限额解释为极低门槛。 |
| PGLib-OPF v23.07 `pglib_opf_case118_ieee` | 186 条支路均有正 A/B/C，三列逐条相同，A 范围 72–7218 MVA。文件尾部的变更日志给出容量等修订。机组数据也经过整理，例如 35 行 `PMAX=0`。这些行可能提供无功支持，需按机组注释核对，不能仅凭该字段删除。 | 作为有完整 benchmark 约束的首选基线。限额来源包含估计值，个别大值应查文件注释。 |

保持 PGLib 的典型工况和 `api/` 重载版本的身份独立。迁移限额时要检查变压器、端点方向与并联支路。端点对只是查询键，一对端点可有多条支路。按数据源、版本和行号生成元件映射，核对对应的 $R/X/B$、tap、shift 和状态。若以后以故障前潮流比例生成容量，那是依赖该调度的参数化实验，应冻结一套容量再跨工况比较，记录弱载支路下限，报告容量假设敏感性。[MATPOWER 7.1 case118][mp118] · [PGLib 固定版本算例和修订日志][pglib118] · [MATPOWER caseformat][mp-format] · [AC-CFM 过载判据][c-ol]

### 3.2 构造并验收故障前状态

**思路。** 以 PGLib 正常工况为原始输入。改变指定母线的 `PD/QD` 后求带约束 AC OPF，再用其结果初始化 AC PF。OPF 确定满足调度和运行约束的起点，PF 复核传给 AC-CFM 的状态。偏离参考调度的研究应显式记录重调度政策。按比例缩放 P/Q 保留各已缩放负荷的功率因数。个别负荷或区域变化可用母线号选择目标行。机组 `PMIN/PMAX/QMIN/QMAX` 与线路额定值固定，除非它们本身是实验因素。

**扩展。** 保存为 `scripts/accfm_lab_settings.m`。这套设置用于 118 实验。使用 MATPOWER 8.1 的 legacy 计算路径以兼容上游 AC-CFM 的潮流回退，有实测依据见第 9 节。7.1 无需此选项。保留 AC-CFM 的 Q 限幅顺序意味着 PF 中设 `pf.enforce_q_lims=0`。基准验收仍检查故障前实际 `QG`。成网类型先显式关闭，再在有可信机组标签时作为实验条件启用。

```matlab
function s = accfm_lab_settings()
    s = get_default_settings();
    s.grid_forming = {};
    s.mpopt = mpoption(s.mpopt, 'pf.alg','NR', 'pf.enforce_q_lims',0, ...
        'opf.ac.solver','MIPS', 'opf.flow_lim','S');
    if isfield(s.mpopt.exp, 'use_legacy_core')
        s.mpopt = mpoption(s.mpopt, 'exp.use_legacy_core',1);
    end
end
```

**扩展。** 保存为 `scripts/prepare_118.m`，传入总负荷倍率和上述设置。该示例适用于这里的原始 PGLib 118 文件。故意改变输入格式、在线拓扑或调度策略时，应更新相应的前置检查。

```matlab
function [pre, audit] = prepare_118(alpha, s)
    define_constants;
    validateattributes(alpha, {'numeric'}, {'scalar','real','finite','positive'});
    raw = loadcase('pglib_opf_case118_ieee');
    assert(size(raw.bus,1)==118 && size(raw.branch,1)==186 && size(raw.gen,1)==54);
    assert(~any(isload(raw.gen)), 'Pass fixed loads to AC-CFM.');
    assert(all(raw.gen(:,PMIN) <= raw.gen(:,PMAX)));
    assert(all(raw.gen(:,QMIN) <= raw.gen(:,QMAX)));
    online = raw.branch(:,BR_STATUS)>0;
    rates = raw.branch(online,RATE_A);
    assert(all(isfinite(rates) & rates>0), 'Missing active branch ratings.');
    raw.bus(:,[PD QD]) = alpha * raw.bus(:,[PD QD]);
    assert(sum(raw.bus(:,PD)) > 0);

    [op, opOK] = runopf(raw,s.mpopt);
    assert(opOK, 'Pre-contingency AC OPF failed.');
    raw.bus(:,[VM VA]) = op.bus(:,[VM VA]);
    raw.gen(:,[PG QG VG]) = op.gen(:,[PG QG VG]);
    raw.gen(raw.gen(:,GEN_STATUS)<=0,[PG QG]) = 0;
    [pre, pfOK] = runpf(raw,s.mpopt);
    assert(pfOK, 'Pre-contingency AC PF failed.');

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
               pre.gen(g,PG) >= pre.gen(g,PMIN)-tolPQ),'P limit violation.');
    assert(all(pre.gen(g,QG) <= pre.gen(g,QMAX)+tolPQ & ...
               pre.gen(g,QG) >= pre.gen(g,QMIN)-tolPQ),'Q limit violation.');
    assert(all(pre.bus(b,VM) >= pre.bus(b,VMIN)-tolV & ...
               pre.bus(b,VM) <= pre.bus(b,VMAX)+tolV),'Voltage limit violation.');
    assert(all(max(sf,st) <= pre.branch(l,RATE_A)+tolS),'Branch rating violation.');
    assert(all(angle(useLower)>=amin(useLower)-tolAngle) && ...
           all(angle(useUpper)<=amax(useUpper)+tolAngle),'Angle limit violation.');
    assert(audit.max_mismatch_pu < 1e-6, 'AC balance residual too large.');
    [groups, isolated] = find_islands(pre);
    assert(numel(groups)==1 && isempty(isolated) && nnz(pre.bus(:,BUS_TYPE)==REF)==1);
end
```

基准检查采用线路两端较大值，以承接这里的 OPF 约束。级联实验同时保留原生均值口径。这两个指标可以在同一条线上给出不同判断。系统总有功备用是基本体检，研究分岛时还应逐岛核对可用 $P/Q$ 容量、参考机组和负荷。总需求上升并不自动说明某条支路的裕度下降，OPF 重调度可以改变潮流方向和瓶颈位置。[MATPOWER runpf][mp-pf] · [runopf][mp-opf] · [makeSbus][mp-sbus] · [MATPOWER 手册][mp-manual]

回到 MATLAB 命令窗口，配置路径后执行无扰动验收并保存工况。

```matlab
define_constants;
s = accfm_lab_settings();
assert(~have_fcn('ipopt'), 'For the MIPS baseline, use a session without IPOPT.');
[pre, audit] = prepare_118(1.00,s);
r0 = accfm(pre,struct(),s);
assert(abs(r0.ls_total)<1e-9,'N-0 unexpectedly shed load.');
assert(isequal(pre.branch(:,BR_STATUS),r0.branch(:,BR_STATUS)));
assert(isequal(pre.gen(:,GEN_STATUS),r0.gen(:,GEN_STATUS)));
assert(isequal(pre.bus(:,BUS_TYPE),r0.bus(:,BUS_TYPE)));
assert(isequal(r0.G.Edges.Type,{'EV'}),'N-0 triggered an internal action.');
disp(audit);
save(fullfile(labRoot,'cases','pre118_alpha100.mat'),'pre','audit','s','-v7');

% Repeat the full PF/limits/N-0 acceptance for every new operating point.
[pre95, audit95] = prepare_118(0.95,s);
```

对区域负荷调整，在 `prepare_118` 中用类似 `rows = ismember(raw.bus(:,BUS_I),[10 12 15]);` 筛选母线，再只对选中行的 `PD/QD` 应用倍率。若要指定发电调度，直接构造机组 `PG` 与电压设定值。通过 PF 后核算参考机组承担的差额、机组限值和支路负载。若状态不可接受，用有界重调度或约束 OPF 重建。含可调负荷伪机组的外部算例应先转成固定负荷。原生 `disp2load` 直接用负荷机组行与母线逻辑行对齐，使用前先验证一对一且顺序匹配、成本矩阵行布局适配。一般情形按 `GEN_BUS` 聚合并核对每个节点的负荷守恒。[disp2load.m L1–22][c-disp]

**完成标准。** 算例哈希、限额来源、机组能力、故障前出力及负荷可追回。初始状态通过 AC 平衡、机组和支路限额、参考母线及 N-0 验收。活跃约束和低裕度有记录。N-0 通过是批量故障实验的起点。

## 4. 单次实验与原生结果

### 4.1 定义初始停运

**原生。** `r = accfm(pre, initial, s)` 的 `pre` 是 MATPOWER 结构体，`initial` 为结构体，字段 `branches`、`buses`、`gens` 可分别给定支路、母线、机组的 **1 基行号**。未写出的字段为空。同次调用中这些扰动同时施加。母线的 `BUS_I` 是物理编号，同母线可有多台机组。端点对可命中并联支路。原生入口会删去部分非法索引，研究接口应提前对空集合、范围、整数、重复和已停运元件做显式处理。[入口 L1–78][c-entry]

```matlab
define_constants;
% pre and s come from Section 3; this branch row starts in service
initial = struct('branches',9);
assert(pre.branch(9,BR_STATUS)>0);
disp(pre.branch(9,[F_BUS T_BUS RATE_A]));
r = accfm(pre,initial,s);

% Conversion from physical identifiers to row indices; inspect all matches.
busRow = find(pre.bus(:,BUS_I)==65);
genRows = find(pre.gen(:,GEN_BUS)==65 & pre.gen(:,GEN_STATUS)>0);
assert(isscalar(busRow));
busOut = struct('buses',busRow);
if ~isempty(genRows)
    genOut = struct('gens',genRows(1));   % explicitly choose one unit
end
ends = pre.branch(:,[F_BUS T_BUS]);
parallelRows = find(all(sort(ends,2)==[1 2],2));
disp(parallelRows);
```

初始支路 9 是本指南的 118 故障回归样本，和 39-bus 的同号行分别指向各自算例。MATPOWER 中的发电机电气母线号、元件行号和并联标识均应保存。对母线停运或机组停运先用小规模试验核对相邻支路、电源状态和未失供母线。初始母线的直接写入仅改 `BUS_TYPE`，惯例上要按母线停运语义单独重建和校验失供口径，见第 6 节。

### 4.2 参数表

始终先调用 `get_default_settings()`，再改动必要字段。传入非空但字段不全的结构体，入口没有逐字段合并默认值。[默认设置 L1–21][c-settings] · [入口 L39–63][c-entry]

| 原生字段 | 默认 | 影响与使用方法 |
| --- | --- | --- |
| `verbose` | 0 | 1 会输出日志并调用 `plot_cascade_graph`。批量运行时用 0。 |
| `mpopt` | AC，安静求解 | 经 `mpoption` 修改 PF 算法、容差和 OPF 策略。对 8.1 显式选 legacy 的依据见第 9 节。 |
| `max_recursion_depth` | 100 | 同时影响动作矩阵列数和 `i+k` 守卫。上限错误保留为中止，比较扩大上限前后的输出。 |
| `dP_limit` | 0.15 | 发电响应允许相对失衡。影响 UFLS 和 OFGS，且 UFLS 还有约 1 MW 例外和容量条件。 |
| `P_overhead` | 0.10 | UFLS 为损耗等预留的出力余量系数。 |
| `Q_tolerance` | 0.10 | 相对机组无功上、下限绝对值的容差，零限值对应零比例容差。 |
| `uvls_per_step` | 0.05 | 见第 1 节每步相对于当前剩余负荷的公式。参数扫描保持最大步数与步长的乘积小于 1，避免分母或最终保留比例异常。 |
| `uvls_max_steps` | 5 | 达到计数后仍欠压时清零剩余负荷。设为 0 会令欠压直接切除负荷。 |
| `grid_forming` | `{'PS','ST','GT'}` | 源码检查字段是单数 `gentype`，缺字段时跳过这一检查。取 `{}` 关闭。多岛使用前应实际检查 `extract_islands` 后标签仍与机组行一致，缺失或无标签时先定义数据政策。 |
| `keep_networks_after_cascade` | 0 | 控制 `accfm_branch_scenarios` 的 `networks_after_cascade`，不改变单次返回。 |

线路阈值 1.01、VCLS 试算电压下限 0.2 p.u. 及主算法中的舍入规则在源码内。改变这些规则需要分支版本与回归试验。网侧阈值如 `RATE_A`、`VMIN` 和机组能力属于输入算例。

### 4.3 读取终态、动作和传播图

| 原生输出 | 含义与读取口径 |
| --- | --- |
| `bus/gen/branch` | 合并后的网络矩阵，以行号回写。判断供电状态优先看 `BUS_TYPE`、`GEN_STATUS`、`BR_STATUS`。离线行的旧电压、旧出力或流量不可直接解释为在线物理量。需要一致的终态潮流时，在剔除失电岛的独立诊断副本上复算并记录。 |
| `bus_id/gen_id/branch_id` | 原输入行位置，供分岛切出、合并与插桩使用。 |
| `branch_tripped/gen_tripped/bus_tripped` | 原始行 × 模型代数。分别显式记录 OL、OFGS/ULGT、部分岛停运。初始直接停运不写这些标志。`trip_nodes` 还会间接停运支路和机组，统计总停运应另用状态差。 |
| `bus_ufls/bus_uvls` | 原始母线行 × 代数，以分数表示动作。UFLS 按岛写行，标记不一定对应有负荷的母线。UVLS 矩阵也可被 VCLS 写入，无法单凭它区分动作原因或反算总 MW。 |
| `load` | 每代服务有功负荷，单位 MW，分岛后按代数累加，终止会填充尾部。绘图时注明代数，按实际动作代数截取或显示尾部平台。与终态 PD 和图的聚合值交叉核对。 |
| `ls_total` | $1-P_{\mathrm{final}}/P_{\mathrm{initial}}$。入口分母是 `sum(pre.bus(:,PD))`。结果是比例，乘 100 得百分比。 |
| `ls_ufls/ls_uvls/ls_vcls/ls_opf` | 对应图边 `UFLS/UVLS/VC/OPF` 的 LS 清单汇总，再除以分母。`XL` 的单母线缩载等路径可能产生未单列的失负荷。 |
| `ls_tripped` | 总损失扣去上述四项的剩余。包括未按这四类登记的损失，不能当作独立原因量测。 |
| `G` | 有向多重图。节点字段为 `Name/Buses/Type/Load/Generators/Lines`，边字段为 `EndNodes/Type/Weight/Base/LS`。边的 `Weight/Base` 随类型变化，`LS` 用 MW，未登记处常为 NaN。 |
| `pf_count/elapsed` | 源码累计的 PF 调用数与 MATLAB 经过时间（秒）。前者不含 OPF 次数，遇到抛异常、回退等分支时也不能等同于完整的求解调用审计。 |
| `success`（可能存在） | 继承或来自局部 MATPOWER 求解状态。多岛合并不把它提升为全局成功标志，个别输入或路径可能没有该字段。应同时核对图中 `OPF`、闭合的负荷账本与异常记录。 |

图上同一父子节点可有不同动作边。节点计数是创建时记录的快照，`Load` 在递归收尾还可能更新，同一代的后续同组动作也可能未更新所有计数。图可读出岛的分支及递归路径，但边行顺序和随机节点名不定义全网事件时间。OFGS 边权重源码取的是标量 `gens_to_shed` 的长度，所以求实际切机台数应用 `gen_tripped` 或插桩记录。图的失负荷分类也应留意无源岛分支对出边 LS 的写法，终态 PD 守恒更适合核查总量。[入口与聚合][c-entry] · [分岛和无源岛][c-recur] · [OFGS][c-frequency] · [保护和递归结束][c-protect] · [OPF][c-opf]

```matlab
define_constants;
offInitially = initial.branches(:);
offAll = find(pre.branch(:,BR_STATUS)>0 & r.branch(:,BR_STATUS)==0);
offAfterInitial = setdiff(offAll,offInitially);
[lineRow, generation] = find(r.branch_tripped~=0);
olEvents = table(generation,lineRow,pre.branch(lineRow,F_BUS), ...
    pre.branch(lineRow,T_BUS),'VariableNames',{'generation','branch_row','from_bus','to_bus'});
disp(sortrows(olEvents,{'generation','branch_row'}));
disp(r.G.Edges(:,{'Type','Weight','Base','LS'}));
fprintf('Initial lines: %d, all off: %d, secondary off: %d, OL lines: %d\n', ...
    numel(offInitially),numel(offAll),numel(offAfterInitial),numel(unique(lineRow)));
fprintf('Lost demand: %.3f MW (%.3f%%)\n',sum(pre.bus(:,PD))-sum(r.bus(:,PD)),100*r.ls_total);
```

在支持图形的 MATLAB 桌面查看图和逐代负荷。

```matlab
figure;
plot_cascade_graph(r);
figure;
stairs(1:numel(r.load),r.load);
xlabel('Cascade generation'); ylabel('Served load (MW)');
```

`get_load_vs_time(r)` 是可选的统计后处理。它为含 `OL` 的图跃迁从均值 19.5797 的指数分布抽取延迟并取整，然后沿分岛路径合并。输出四列为合成时间、服务负荷 MW、机组数、线路数，起始有两个时间 0 的记录。论文第 III-C 节明确核心 OLP 没有动作延迟，第 III-E 节将级联结果接入韧性指标。该后处理函数自身没有为时间列标注单位或提供参数校准来源。保存种子，为韧性指标明确时间单位和延迟假设，并验证分岛合并与固定缓冲对长序列的适用性。[get_load_vs_time.m L1–51][c-time] · [原论文第 III 节][paper-full]

```matlab
if exist('exprnd','file') == 2
    rng(20261125,'twister');
    series = get_load_vs_time(r);
    disp(series(1:min(10,size(series,1)),:));
end
```

**完成标准。** 对同一故障能分别核对初始停运、OL 标志、最终全部停运与实际失负荷，能沿图追到至少一个孤岛的后续动作。所有图和表都注明代数或合成时间。

## 5. 批量实验、保存与 Python 交换

### 5.1 目的与接口选择

批量实验重复调用同一求解入口。输入清单先生成并保存，结果每个场景一条记录。先覆盖基准状态、一个轻故障和一个有多代传播的故障，再对比一小组已知合格场景。只有审计口径稳定后，才扩展到全 N-1 或按研究问题设计的组合与运行工况。满网 186 支路二元组合为 17,205 组，计算量按场景数和实际 PF/OPF 成本估算。

| 入口 | 输入与返回 | 选择依据 |
| --- | --- | --- |
| `accfm_branch_scenarios(pre,{1;9;[1 9]},s)` | 同一算例，元胞中每项为支路行号向量。输出 `scenarios`、`lost_load`、`lost_load_final`、跳闸和时间等汇总。可开启 `keep_networks_after_cascade` 保留终态核心矩阵。 | 原生汇总使用 `r.load(end)` 的失负荷比例，建议与 `r.ls_total` 抽样对照。宽泛的 `catch` 将异常标为 `lost_load_final=-1`，其他字段可能仍是零、空或部分写入。`-1` 表示该场景结果无效。例程在当前目录写进度临时文件，多个批次应使用各自的工作目录。 |
| `accfm_pdf_batch(network,distribName,distribParams,number_of_scenarios,settings,output_file)` | 意图先用 `randraw` 抽初始切线数，再抽支路行，可传 case 结构体、文件路径或 case 元胞。 | 固定提交的抽样代码把 `randraw` 的数值返回写成 `contingencies{i}`，后面又用圆括号，通常在实际仿真前出错。文件输入的 `loadcase` 状态判断、元胞分支的预分配及字段也需独立修复和复测。科研主线用显式输入清单。 |
| 本指南 `run_118_task` | 确定的数值行列表，保留真正的 MATLAB 异常及停岛标识。 | 扩展。串行、可调试，便于共同使用同一套审计和后续并行。 |

原生批处理调用 `get_load_vs_time`，依赖 `exprnd` 的分支抛异常也可能产生 -1。读取 `uvls_buses` 应采用第 4 节解释。原生批处理保存的终态精简结构不含原始 `G`。[已知场景批处理 L15–164][c-batch] · [分布采样 L19–132][c-pdf] · [进度文件][c-progress]

### 5.2 可复用串行接口

**扩展。** 保存为 `scripts/run_118_task.m`。用支路故障构建最小接口，后续需要母线或机组故障时，沿用第 4 节的映射并给对应输入加相同的索引检查。该接口把 MATLAB 异常、模型停岛标志和账本检查分开记录。它不会将任何模型返回自动提升为真实系统结论。

```matlab
function [row, r] = run_118_task(pre, s, branchRows, scenarioID, seed)
    define_constants;
    priorRng = rng;
    priorWarnings = warning;
    restore = onCleanup(@() restore_session(priorRng,priorWarnings)); %#ok<NASGU>
    row = struct('scenario_id',scenarioID, 'initial_rows',"", ...
        'seed',seed,'status',"error",'ls_total',NaN,'lost_mw',NaN, ...
        'ls_ufls',NaN,'ls_uvls',NaN,'ls_vcls',NaN,'ls_opf',NaN,'ls_tripped',NaN, ...
        'n_off',NaN,'n_secondary',NaN,'n_ol',NaN,'pf_count',NaN, ...
        'elapsed_sec',NaN,'load_curve_delta_mw',NaN, ...
        'has_opf_trip',false,'error_id',"",'error_message',"",'error_stack',"");
    r = [];
    try
        n = size(pre.branch,1);
        idx = branchRows(:);
        assert(isnumeric(idx) && isreal(idx) && all(isfinite(idx)) && ...
            all(idx==fix(idx) & idx>=1 & idx<=n) && numel(unique(idx))==numel(idx), ...
            'ACCFM:BadBranchRows','Use unique, finite, integer branch row indices.');
        row.initial_rows = string(jsonencode(num2cell(idx.')));
        assert(all(pre.branch(idx,BR_STATUS)>0),'ACCFM:OfflineBranch','Initial branch is offline.');
        assert(sum(pre.bus(:,PD))>0,'ACCFM:ZeroLoad','Pre-contingency PD sum must be positive.');
        rng(seed,'twister');
        r = accfm(pre,struct('branches',idx),s);
        assert(isequal(r.branch_id,(1:n).') && isequal(r.branch(:,[F_BUS T_BUS]),pre.branch(:,[F_BUS T_BUS])));
        off = find(pre.branch(:,BR_STATUS)>0 & r.branch(:,BR_STATUS)==0);
        before = sum(pre.bus(:,PD));
        served = sum(r.bus(:,PD));
        expected = 1-served/before;
        assert(all(ismember(idx,off)) && nnz(r.branch(pre.branch(:,BR_STATUS)<=0,BR_STATUS)>0)==0);
        assert(isfinite(expected) && expected>=-1e-8 && expected<=1+1e-8 && ...
            abs(expected-r.ls_total)<1e-9,'ACCFM:LoadLedger','Invalid total demand ledger.');
        ls = [r.ls_ufls r.ls_uvls r.ls_vcls r.ls_opf r.ls_tripped];
        assert(all(isfinite(ls)) && abs(sum(ls)-r.ls_total)<1e-9, ...
            'ACCFM:LossBreakdown','Invalid loss breakdown.');
        row.status = "completed_model";
        row.ls_total = r.ls_total;
        row.lost_mw = before-served;
        row.ls_ufls = ls(1); row.ls_uvls = ls(2); row.ls_vcls = ls(3);
        row.ls_opf = ls(4); row.ls_tripped = ls(5);
        row.n_off = numel(off);
        row.n_secondary = numel(setdiff(off,idx));
        row.n_ol = nnz(any(r.branch_tripped~=0,2));
        row.pf_count = r.pf_count;
        row.elapsed_sec = r.elapsed;
        row.load_curve_delta_mw = r.load(end)-served;
        row.has_opf_trip = any(strcmp(r.G.Edges.Type,'OPF'));
        if any(ls<-1e-8) || ~isfinite(row.load_curve_delta_mw) || abs(row.load_curve_delta_mw)>1e-6
            row.status = "review_ledger";
        elseif row.has_opf_trip
            row.status = "model_opf_trip";
        end
    catch ME
        row.error_id = string(ME.identifier);
        row.error_message = string(ME.message);
        row.error_stack = strjoin(string({ME.stack.name})+":"+string([ME.stack.line])," | ");
        if strcmp(ME.message,'Iteration limit reached')
            row.status = "iteration_limit";
        end
    end
end

function restore_session(priorRng,priorWarnings)
    rng(priorRng);
    warning(priorWarnings);
end
```

**扩展。** 保存为 `scripts/pilot_118.m`。从实验根目录先运行 `setup_accfm`，然后运行 `pilot_118`。通过结构化摘要保留所有任务的成功或失败状态，逐任务 MAT 文件保存异常信息与原始输出供抽查。后续大样本可只保存抽样案例、异常案例和必要事件表。

```matlab
source = fullfile(labRoot,'cases','pre118_alpha100.mat');
input = load(source,'pre','audit','s');
scenarios = {[];1;9;[1 9]};
ids = (1:numel(scenarios)).';
seeds = 118000+ids;
out = fullfile(labRoot,'runs','pilot-118-001');
assert(~isfolder(out),'Choose a new run ID before rerunning this pilot.');
mkdir(out);
env = struct('matlab',version,'matpower',mpver,'ipopt_visible',have_fcn('ipopt'), ...
    'accfm_path',which('accfm'),'runpf_path',which('runpf'), ...
    'runopf_path',which('runopf'),'rng_algorithm','twister');
save(fullfile(out,'inputs.mat'),'input','scenarios','ids','seeds','env','-v7');
rows = cell(numel(ids),1);
for k = 1:numel(ids)
    [rows{k}, r] = run_118_task(input.pre,input.s,scenarios{k},ids(k),seeds(k));
    row = rows{k};
    save(fullfile(out,sprintf('scenario_%04d.mat',ids(k))),'row','r','-v7');
end
summary = struct2table(vertcat(rows{:}));
writetable(summary,fullfile(out,'summary.csv'));
disp(summary(:,{'scenario_id','status','ls_total','n_secondary','has_opf_trip'}));
```

若需随机 N-2，从已在线支路中抽样。固定种子，排序每个组合，先生成清单再仿真。抽样重复是否保留取决于目标分布。均匀抽支路代表你规定的试验抽样，不自动对应天气或其他真实风险分布。

```matlab
define_constants;
online = find(pre.branch(:,BR_STATUS)>0);
pairs = nchoosek(online,2);
rng(20261125,'twister');
ix = randperm(size(pairs,1),min(20,size(pairs,1)));
sampleN2 = num2cell(pairs(ix,:),2);
```

### 5.3 导出结构化结果

**扩展。** 用 MATLAB 保存复查原件，用 csv 或纯数值 MAT 保存与 Python 交换的布局。下面对第 4 节的单次结果 `r` 执行，假定工作区保留对应的 `pre`。原始 `digraph` 另存 MATLAB 文件，跨语言表中展开端点。场景结果含错误时先检查状态再导出。

```matlab
define_constants;
exchange = fullfile(labRoot,'runs','exchange-118-row9');
assert(~isfolder(exchange),'Choose a new export directory.');
mkdir(exchange);
edges = r.G.Edges;
edgeTable = table(string(edges.EndNodes(:,1)),string(edges.EndNodes(:,2)), ...
    string(edges.Type),edges.Weight,edges.Base,edges.LS, ...
    'VariableNames',{'source','target','action','weight','base','loss_mw'});
writetable(edgeTable,fullfile(exchange,'edges.csv'));
writetable(r.G.Nodes,fullfile(exchange,'nodes.csv'));
branchMap = array2table([(1:size(pre.branch,1)).' pre.branch(:,[F_BUS T_BUS RATE_A])], ...
    'VariableNames',{'branch_row','from_bus','to_bus','rate_a_mva'});
writetable(branchMap,fullfile(exchange,'branch_map.csv'));
bus = r.bus; gen = r.gen; branch = r.branch;
bus_id = r.bus_id; gen_id = r.gen_id; branch_id = r.branch_id;
branch_tripped = r.branch_tripped; served_mw = r.load;
columnNames = struct('branch_power_1based',[PF QF PT QT], ...
    'branch_status_1based',BR_STATUS,'bus_number_1based',BUS_I);
save(fullfile(exchange,'numeric.mat'),'bus','gen','branch','bus_id','gen_id', ...
    'branch_id','branch_tripped','served_mw','columnNames','-v7');
```

```python
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.io import loadmat

out = Path("runs/exchange-118-row9")
data = loadmat(out / "numeric.mat")
branch_map = pd.read_csv(out / "branch_map.csv")
edges = pd.read_csv(out / "edges.csv", keep_default_na=False)
edges["loss_mw"] = pd.to_numeric(edges["loss_mw"], errors="coerce")
branch_ids = data["branch_id"].ravel().astype(int)
assert np.array_equal(branch_ids, branch_map["branch_row"].to_numpy())
assert data["branch_tripped"].shape[0] == len(branch_map)
print(edges.groupby("action").size())
```

约定 CSV 的支路行和代数沿用 MATLAB 的 1 基编号。访问 NumPy 行下标时减 1，物理母线编号保留原值。标明单位 MW、MVAr、MVA、p.u.、度及比例。较大数据可改用显式 HDF5 布局分块写入，按双方实测验证数组方向、维度和缺失值。`scipy.io.loadmat` 支持 `-v7`，MATLAB `-v7.3` 需要 HDF5 读取方案，尤其要注意对象与引用。[SciPy loadmat][scipy-mat]

**完成标准。** 任务清单先于求解生成，任一场景能靠保存的工况、参数和种子重跑。Python 读取后的元件 ID、维度、功率和动作计数与 MATLAB 逐项一致。失败场景保留状态与错误原因，原始对象可在 MATLAB 返回查看。

## 6. 诊断不收敛与物理异常

### 6.1 目的与诊断次序

保留原输入及基线输出，再用副本定位异常。求解器失败、基线运行规则触发的停运和对真实电网稳定性的判断需要各自的证据。

| 现象 | 优先核查 | 结果归档 |
| --- | --- | --- |
| 路径、维数、索引、工具箱等 MATLAB 异常 | 检查 `which -all`、堆栈、原始 ID、案例结构和求解器可见性。8.1 若在 MP-Core 的 `runpf` 抛出内部字段访问异常，先复现后使用相同版本的 legacy 选项重新执行全套验收。 | `error`，保存标识、消息和栈。 |
| `Iteration limit reached` | 找最后一个递归岛及连续动作。排查零额定值、VCLS 重复恢复、出力钳位反复触发、UVLS 一次次无效等。增加上限是单独的重跑实验。 | `iteration_limit`。扩大上限后的结果另存。 |
| 故障前 `runopf` / `runpf` 失败 | 核对正负荷、限额、机组调度和参考。确认是否因过紧约束、起点差或算法路径触发。模型输入要求为经独立验收的工况。 | 预处理不合格，保留未进入级联的原因。 |
| 岛内 PF 失败后有 `VC` | 用插桩记录失败 PF 输入、恢复 OPF 的约束松弛、恢复负荷和后续验证 PF。优先复算同一个岛、同一拓扑以及同一出力设定。 | 恢复策略参与结果。对选定样本做求解器或初值稳健性比较。 |
| 图上有 `OPF` | 确认首次及重试 OPF 的标志、是否曾成功但校验 PF 失败，检查有无正的有功容量、足够的无功支持及可达参考。 | 标记模型按回退政策停岛。对于需要物理失供标签的数据集，同时保留求解器相关性信息。 |
| 损失或动作计数异常 | 复查支路额定值、同代保护顺序、孤岛中仍残留的失电母线 PD、可调负荷映射、原始行映射以及图的 LS 账本。 | 记录异常条目，即使运行返回也要求复核。 |

原生 `apply_recursion` 的首次 PF 与 slack 分摊处有宽泛 `catch`，会转入 VCLS。其他位置的 PF 或 OPF 异常可直接传播。上游 `accfm` 在运行时关掉两个奇异矩阵警告，正常结束时直接打开，异常中断可能留在关闭状态。本指南的试验包装器恢复会话原状态。交互排错可在调试分支上断到第一次 `runpf` 或 `apply_opf`，用 `dbstop if caught error` 辅助找到被吞掉的异常，再用 `dbclear if caught error` 解除。求解失败时至少保留最早失败岛输入，而非反复调整全网数据。[入口警告处理][c-entry] · [主 PF 与 catch][c-recur] · [求解回退][c-opf]

对重跑，在同一失败岛和相同约束下可以换初值、谨慎调迭代与容差、对比 MIPS/IPOPT 或 MATPOWER 计算路径。每次同时保留原设置与变更。若能找到满足约束的平衡点，说明原算法至少漏掉了该解。多种算法未找到解仍应标为未确定。对静态电压可行边界可用连续潮流或可行域分析。动态不稳定判断还需结合模型、扰动和相应稳定性验证。README 的放宽 `PMIN/Q` 建议会改变物理假设，应作为独立工况或敏感性试验。[README Troubleshooting][readme] · [原论文第 III-B、VI 节][paper-full]

### 6.2 母线故障的输入约定

对母线故障，`accfm` 入口只把 `BUS_TYPE` 改为 `NONE`，`find_islands` 的连接矩阵基于 `BR_STATUS`。因此原生 `buses` 输入与“事件时切掉该母线、切除本地负荷并切开所有关联设备”需要逐项核对，尤其是分岛和 `sum(PD)` 的分母。若研究采用后者，可在模型外显式建立故障后输入，再用原始故障前负荷重建损失账本。该示例的网络分割发生在故障前工况上，不再做一次人为的故障后 OPF 预调度。[入口事件赋值][c-entry] · [MATPOWER find_islands][mp-islands]

```matlab
define_constants;
target = 65;                         % BUS_I, not matrix row
failed = pre.bus(:,BUS_I)==target;
assert(nnz(failed)==1);
changed = pre;
changed.bus(failed,BUS_TYPE) = NONE;
changed.bus(failed,[PD QD]) = 0;
changed.gen(pre.gen(:,GEN_BUS)==target,[PG QG GEN_STATUS]) = 0;
incident = pre.branch(:,F_BUS)==target | pre.branch(:,T_BUS)==target;
changed.branch(incident,[BR_STATUS PF QF PT QT]) = 0;
assert(sum(changed.bus(:,PD))>0);
rBus = accfm(changed,struct(),s);
initialLostMW = sum(pre.bus(failed,PD));
cascadeLostMW = sum(changed.bus(:,PD))-sum(rBus.bus(:,PD));
totalLostFraction = (initialLostMW+cascadeLostMW)/sum(pre.bus(:,PD));
fprintf('Bus %d: initial %.2f MW, secondary %.2f MW, total %.2f%%\n', ...
    target,initialLostMW,cascadeLostMW,100*totalLostFraction);
```

把 `target`、原始 `pre`、`changed` 和外部停运元件保存为事件清单。原生 `EV` 随 `changed` 初始化，外部切掉的负荷应单列。若母线是原岛参考，应通过图和状态验证替代 REF、邻接支路和剩余负荷。

**完成标准。** 对一个失败样本能定位首个失败阶段，复现原失败条件并展示一次有记录的诊断对照。发布失供数据时，保留模型停岛与求解异常相关字段，对用户定义的母线事件核对完整 MW 账本。

## 7. 中间状态、保护改动与受控实验

### 7.1 目的与实现思路

当研究需要解释“某条线为什么在这一代跳闸”，最低充分证据是该岛该代保护判定时的 `PF/QF/PT/QT`、阈值、PF 状态和实际动作。需要研究无功时，同时记录 `VM/VA`、母线类型、`PG/QG`、各限值和参考机组。原生终态、代数动作矩阵与有向图共同提供顺序及摘要，中间 PF/OPF 矩阵需在实际求解位置捕获。每条记录要带原始行 ID、递归代数、岛图节点和阶段标签。

### 7.2 最小插桩

**扩展。** 在 AC-CFM 仓库内 `git switch -c research/trace`。把下面的局部函数加到 `accfm.m` 末尾。指向只读观察的回调，默认关闭。回调得到去除图对象的状态副本，暂存于内存。插桩行号以原提交定位。改动后重跑第 2–3 节和典型故障。

```matlab
function emit_trace(settings, stage, network, i, k, parent, detail)
    if ~isfield(settings,'trace_sink') || isempty(settings.trace_sink)
        return
    end
    x = struct('stage',stage,'generation',i,'local_depth',k,'graph_parent',parent, ...
        'bus_id',network.bus_id,'gen_id',network.gen_id,'branch_id',network.branch_id, ...
        'bus',network.bus,'gen',network.gen,'branch',network.branch,'detail',detail);
    if isfield(network,'success')
        x.stored_success = network.success;
    end
    settings.trace_sink(x);
end
```

先实现最直接的观测点。在原始 L420 后插入以下代码，完整保留检测到的四类越限行。原生用 `network` 的局部行访问越限元件，经原始 ID 映射后才能与全网终态关联。

```matlab
detail = struct('ol_branch_id',network.branch_id(exceeded_lines), ...
    'uv_bus_id',network.bus_id(exceeded_buses), ...
    'low_p_gen_id',network.gen_id(exceeded_gens_p), ...
    'xl_gen_id',network.gen_id(exceeded_gens_q));
emit_trace(settings,'before_limit_actions',network,i,k,Gnode_parent,detail);
```

如需保护后的实际状态，在原始 L575 后加同样形式的调用，阶段用 `'after_limit_actions'`，`detail` 可取判定时保存的清单。此时的矩阵可能仍带上一次 PF 的数值，新的开关状态和旧的潮流列必须区分。建议按下表扩展，只捕获回答当前问题所需的阶段。

| 源码位置 | 最有价值的字段 | 读取约束 |
| --- | --- | --- |
| L173–190 分岛 | 父节点、子节点、子岛的物理母线号与原始行、在线设备 | 独立岛在程序中深度优先处理，保留岛间父子关系。 |
| L277–294 主 PF、slack 分摊及捕获异常 | 求解前快照、第一次 PF、分摊后 PF、两次状态标志。将 `catch` 改成 `catch ME` 后保存 `ME.identifier/message`，保持原恢复路径。 | 第一次 PF 与分摊后的 PF 解可能不同。 |
| L303–353、L373–405 频率代理 | `dG`、正负容量、`ls_factor`、选中机组 ID、动作前后 PD/QD | 增加这些字段后能解释 UFLS/OFGS 门槛。依旧只有不平衡代理。 |
| L736–782、L829–835 求解回退 | `network_disp` 单独的 OPF 工作数据、求解器、每次尝试的约束修改与成功标志 | `load2disp` 后 `gen` 增加负负荷行，不可复用原始机组 ID 去索引这些新增行。记录其 `GEN_BUS` 和伪机组标识。 |
| L838–895 OPF 验证 | 局部 `results_disp`、验证 PF `result`、原始失负荷与最终 `VC/OPF` 原因 | 这些变量与返回 `network` 是不同状态。区分 OPF 失败和 OPF 后 PF 失败。 |

保存为 `scripts/make_trace_recorder.m`，返回独立的写入和读取函数。示例一次只追一个场景，计算结束后再写盘。

```matlab
function [sink, collect] = make_trace_recorder()
    events = {};
    sink = @add;
    collect = @get;
    function add(event)
        events{end+1,1} = event;
    end
    function snapshots = get()
        snapshots = events;
    end
end
```

```matlab
[sink, collect] = make_trace_recorder();
sTrace = s; sTrace.trace_sink = sink;
rTrace = accfm(pre,struct('branches',9),sTrace);
snapshots = collect();
assert(~isempty(snapshots),'Check which accfm is active and where tracing is installed.');
assert(isequaln(rTrace.branch_tripped,r.branch_tripped));
assert(isequaln(rTrace.bus_uvls,r.bus_uvls));
assert(abs(rTrace.ls_total-r.ls_total)<1e-9);
save(fullfile(labRoot,'runs','trace-row9.mat'),'snapshots','-v7');
```

原始记录的 graph_parent 使用随机节点名。重跑时比较可通过父子拓扑和动作类型映射到原始元件 ID。若还需最终原因标签，在动作实际执行的位置记一条事件，并用相同的岛/代数上下文关联触发条件。状态快照对几百条支路用起来足够，规模上升后抽取字段、分块写盘，或只保存指定岛。

### 7.3 设计可解释的对照试验

1. 固定 `pre`、故障清单、MATPOWER 计算路径和可选求解器。基线先跑 N-0 和代表场景。记录判据的裕度，例如 $\bar{S}/S_{\mathrm{A}}$ 与 1.01 的距离。
2. 第一组适合对照 `dP_limit`、`Q_tolerance` 或 UVLS 参数。一项改变可能影响多个机制，例如 `dP_limit` 同时改变欠频和过频规则。要独立识别某支机制，再引入一个显式开关或单独阈值，默认行为保持上游一致。保护关闭时也应处理相应的递归触发条件，避免越限永久存在导致空转。
3. 若研究过载阈值，先对同一 PF 解计算均值与两端较大值，再做分别触发的成对实验。只有在验证存储的两端功率、状态掩码、阈值和单位后才替换 L417。对接近阈值的支路和并联支路构造小网算例，验证故障前、故障后和分岛的判定。
4. 比较每对场景的首个不同动作、首先分岔的岛、后续可用出力和负荷。最终负荷差是模型对改变的总效应。若改变有功调度或松弛算例限额而同时改变保护，就要另设对照才能区分具体原因。

```matlab
alternate = s;
alternate.dP_limit = 0.20;
[baseRow, baseRun] = run_118_task(pre,s,9,1,118001);
[altRow, altRun] = run_118_task(pre,alternate,9,1,118001);
disp(struct2table([baseRow; altRow]));
if ~isempty(baseRun) && ~isempty(altRun)
    disp(find(any(baseRun.branch_tripped~=altRun.branch_tripped,2)).');
end
```

**完成标准。** 追踪关闭与开启时，典型故障的物理结果和关键动作一致。规则改动能由受控小网和固定 118 样本触发测试覆盖，解释从判据变化经过首个动作到终态的路径。

## 8. 扩大样本与长期维护

### 8.1 批量性能与数据质量

先用串行小批量估计每个场景的耗时分布、PF 次数、含 `VC/OPF` 的比例和实际内存。用代表场景的中位数和高分位数做时间预算。现有路径的主要工作是 CPU 上的稀疏潮流与非线性 OPF，增加可用 CPU worker 和减少不必要的结果写入通常直接影响吞吐量。大批量之前对同一清单测串行和小 worker 池的总耗时。下面只返回摘要，避免每个 worker 把大图传回。

```matlab
% After the pilot passes and Parallel Computing Toolbox is available.
% Run setup_accfm before creating the pool; verify worker paths and solvers.
pool = gcp('nocreate');
if isempty(pool), pool = parpool('local',2); end
rowsParallel = cell(numel(ids),1);
parfor k = 1:numel(ids)
    rowsParallel{k} = run_118_task(input.pre,input.s,scenarios{k},ids(k),seeds(k));
end
parallelSummary = struct2table(vertcat(rowsParallel{:}));
disp(parallelSummary(:,{'scenario_id','status','ls_total','n_secondary'}));
```

独立 worker 使用相同版本、路径和求解器。使用稳定场景 ID 派生随机种子。保留清单中的单一结果文件名或分块编号，数据汇总后验证场景数和唯一性，再比较串并行的状态、`ls_total`、停运集合和保护计数，耗时和节点随机名独立看待。在 Windows 实验根目录可用 `matlab -wait -batch "setup_accfm; pilot_118"` 等待批次结束并获取进程状态。选项和目录版本记入清单。

### 8.2 每批产物应保留的信息

| 对象 | 最小内容 |
| --- | --- |
| 算例 | 数据来源、版本/提交、文件哈希、原始元件行映射、初始开关状态、容量来源、修改脚本。 |
| 工况 | 负荷倍率或每母线负荷、调度策略及 PF/OPF 选项、故障前实际调度、裕度和 N-0 验收。 |
| 场景 | 场景 ID、工况 ID、初始元件、抽样规则、种子。保留发生于外部预处理的事件和对应的负荷口径。 |
| 运行环境 | AC-CFM 提交及本地差异、MATLAB/MATPOWER 版本、求解器和可见性、worker 数、代码提交、开始结束时间。 |
| 产物 | 结果和错误计数，初始/显式保护/总停运，损失比例和 MW，OPF 标志、核心动作、列定义。 |

数据核查分三个层次。首先核对 ID、维度、量纲、在线集合、非有限值和重复场景。其次抽查原始输入、输出、时序矩阵和图的账本是否一致，确认不同故障规模下的异常占比。最后检查物理合理性，包括 AC 平衡残差、故障前的线路和机组约束、分岛有效容量、终态可解性以及对主要阈值与求解策略的敏感性。目标若是评估模型对未见工况的迁移，数据划分时按工况或故障组合分组，再验证同一重复轨迹、镜像样本或近重复前缀的归属。平台接口输出通用状态与事件，预测模型侧选择标签与训练划分。

**完成标准。** 任给场景 ID，能从清单恢复输入并重新得到可比较的结果。运行统计列出完成、异常退出、达到递归上限、模型 OPF 停岛与账本待查的数量。并行、时间拟合、记录全状态和数据集构建都可按需启用。

## 9. 验证记录与证据索引

### 9.1 本次核查基线

验证环境为 Windows、MATLAB R2025a（25.1.0.2943329）、MATPOWER 8.1、无 IPOPT、AC-CFM 固定提交、PGLib-OPF v23.07 Typical Operations。118 生产示例使用 MATPOWER legacy 路径和 MIPS。算例 Git blob 标识为 `59f5b27205f8aff56339d9aa666460ce056e6482`。若 Windows checkout 改写换行，工作文件 SHA-256 可能变化，Git blob 标识与实际工作文件哈希均应记录。

| 验证项目 | 观测结果 |
| --- | --- |
| MATPOWER `case9` | PF 与 MIPS AC OPF 均返回成功。 |
| 官方 `case39` 支路第 9 行 | 对应 4–14。MATPOWER 8.1 默认路径及 legacy 路径都得到总失负荷 45.05%，五项分解按 README 精度一致，终态供电约 3436.54 MW，计数 34 次 PF。 |
| 118 原始数据 | MATPOWER 7.1/8.1 文件与 PGLib v23.07 实际矩阵已核查。两个 MATPOWER 文件的 Git blob 内容一致，186 条支路三组限额均为零。PGLib 容量范围和数量见第 3 节。 |
| PGLib 118 工况 | 倍率 0.95、1.00、1.05，对应 4029.9、4242.0、4454.1 MW。各自 AC OPF、AC PF 与无扰动验收通过，未增加停运或失供。 |
| 118 单支路轻故障 | 倍率 1.00，支路第 1 行停运后失负荷为 0，终态仅该行停运，显式 OL 计数为 0。 |
| 118 单支路多代传播 | 倍率 1.00，支路第 9 行。legacy 路径失负荷约 55.4526%，终态计 43 条支路停运，其中 1 条初始、33 条显示在显式过载标志中，另有岛停运等间接损失。11 行机组停运，计数 58 次 PF，`ls_opf=0`。这些数值对应此算例和求解策略。 |
| 118 的 MATPOWER 8.1 默认 MP-Core 路径 | 以相同 PGLib 工况准备法运行第 9 行场景，在 `accfm>apply_opf` 的验证 PF 中出现 `runpf.m` 第 171 行对 `pf.mm.soln.output.iterations` 的点索引运行时异常。切换 legacy 后该类场景完成。此异常说明计算路径存在兼容问题，不能从异常推出物理失稳，也不能保证 legacy 覆盖所有输入。 |
| 指南 MATLAB 代码的独立走查 | 从本文抽取并运行设置入口、39-bus 数值回归、118 工况验收、单次试验、四场景串行批次、外部定义的母线停运与参数对照。另验证了重复初始行被拒绝，递归上限场景有单独状态。 |
| 数据与插桩 | MATLAB 数值 MAT 与 CSV 已由 Python 实际读取并对照行号、维度和动作计数。插桩重跑第 9 行样本取得 15 个判定前快照，失负荷、显式线路跳闸和 `bus_uvls` 与基线一致。 |
| 原生批处理和绘图的边界 | 实测 `accfm_pdf_batch` 在数值样本的花括号索引报 `MATLAB:cellRefFromNonCell`。当前非交互会话在调用绘图时发生图形初始化异常，数值回归改用 `verbose=0` 成功。 |

本次未验证 MATPOWER 完整测试套件、MATPOWER 7.1 运行、IPOPT、桌面绘图、原生并行批处理和统计时间后处理，也没有穷举 118 的 N-1/N-2。论文第 IV、V、VIII 节的示范主要采用 2736 母线波兰系统，第 IV 节还调整了无功能力。本文的 118 测试验证搭建流程和实现语义，真实系统的继电器、历史事件和 RMS/EMT 对照仍需相应数据独立验证。[论文验证][paper-full] · [MATPOWER 8.1 用户手册][mp81-manual] · [MP-Core 选项][mp81-opt]

### 9.2 从哪里查

| 问题 | 首选资料 |
| --- | --- |
| 论文如何提出该模型并验证机制 | Noebels, Preece & Panteli, *AC Cascading Failure Model for Resilience Analysis in Power Networks*, IEEE Systems Journal 16(1), 374–385（2022 年卷期，2020 年在线发表），第 III–VIII 节及附录。[DOI][paper-doi] · [全文][paper-full] |
| 运行链与技术决策 | [AC-CFM 固定提交][commit] · [入口及计量][c-entry] · [深度优先递归][c-recur] · [保护条件][c-protect] · [OPF 恢复][c-vcls] · [求解器与回写][c-opf] |
| 原生辅助函数 | [默认设置][c-settings] · [已知场景批量][c-batch] · [分布抽样批量][c-pdf] · [传播图绘制][c-plot] · [合成时间][c-time] |
| MATPOWER 数据格式与求解器 | [7.1 手册][mp-manual] · [8.1 手册][mp81-manual] · [caseformat][mp-format] · [runpf][mp-pf] · [runopf][mp-opf] · [ext2int][mp-e2i] · [extract_islands][mp-extract] |
| 118 额定值与标准工况 | [MATPOWER case118][mp118] · [PGLib-OPF 118 固定版][pglib118] · [PGLib 约束构建报告][pglib-paper] |

[paper-doi]: https://doi.org/10.1109/JSYST.2020.3037400
[paper-full]: https://www.researchgate.net/publication/346085105_AC_Cascading_Failure_Model_for_Resilience_Analysis_in_Power_Networks
[commit]: https://github.com/mnoebels/AC-CFM/commit/48eebaa19b96b00ee40d7a86f5c1132be74efd8b
[readme]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/README.md
[c-entry]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/accfm.m#L1-L117
[c-recur]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/accfm.m#L119-L297
[c-protect]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/accfm.m#L298-L602
[c-frequency]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/accfm.m#L298-L409
[c-uvls]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/accfm.m#L489-L547
[c-ol]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/accfm.m#L414-L420
[c-slack]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/accfm.m#L634-L723
[c-vcls]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/accfm.m#L725-L818
[c-opf]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/accfm.m#L820-L899
[c-ref]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/accfm.m#L901-L969
[c-settings]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/get_default_settings.m
[c-time]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/get_load_vs_time.m
[c-plot]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/plot_cascade_graph.m
[c-batch]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/accfm_branch_scenarios.m
[c-pdf]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/accfm_pdf_batch.m#L19-L132
[c-progress]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/parfor_progress.m
[c-disp]: https://github.com/mnoebels/AC-CFM/blob/48eebaa19b96b00ee40d7a86f5c1132be74efd8b/disp2load.m
[mp-install]: https://matpower.org/about/get-started/
[mp-releases]: https://matpower.org/download/all-releases/
[mp-solvers]: https://matpower.org/download/optional-solvers/
[mp-manual]: https://matpower.org/docs/MATPOWER-manual-7.1.pdf
[mp81-manual]: https://matpower.org/docs/MATPOWER-manual-8.1.pdf
[mp81-opt]: https://matpower.org/documentation/ref-manual/legacy/functions/mpoption.html
[mp-format]: https://matpower.org/docs/ref/matpower7.1/lib/caseformat.html
[mp-pf]: https://matpower.org/docs/ref/matpower7.1/lib/runpf.html
[mp-opf]: https://matpower.org/docs/ref/matpower7.1/lib/runopf.html
[mp-load]: https://matpower.org/docs/ref/matpower7.1/lib/load2disp.html
[mp-islands]: https://matpower.org/docs/ref/matpower7.1/lib/find_islands.html
[mp-extract]: https://matpower.org/docs/ref/matpower7.1/lib/extract_islands.html
[mp-e2i]: https://matpower.org/docs/ref/matpower7.1/lib/ext2int.html
[mp-sbus]: https://matpower.org/docs/ref/matpower7.1/lib/makeSbus.html
[mp118]: https://github.com/MATPOWER/matpower/blob/7.1/data/case118.m
[pglib118]: https://github.com/power-grid-lib/pglib-opf/blob/v23.07/pglib_opf_case118_ieee.m
[pglib-paper]: https://arxiv.org/abs/1908.02788
[mw-parfor]: https://www.mathworks.com/help/matlab/ref/parfor.html
[mw-exprnd]: https://www.mathworks.com/help/stats/exprnd.html
[scipy-mat]: https://docs.scipy.org/doc/scipy/reference/generated/scipy.io.loadmat.html
