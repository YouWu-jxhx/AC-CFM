# AC-CFM 科研仿真平台

本工程以交流潮流、离散保护动作和递归分岛为基础，用于可重复的级联故障仿真。默认使用 IEEE 118 母线 PGLib-OPF v23.07 Typical Operations 算例。已有验证的依据、原始日志和历史数值保存在 [evidence](evidence/)。

## 运行环境

使用 Windows、MATLAB R2025a 和现有 MATPOWER 8.1，默认用 MIPS 和 legacy 路径。开始前切换到本工程根目录。MATPOWER 的默认位置为 `D:/matpower8.1`，也可以设置环境变量 `ACCFM_MATPOWER_ROOT` 或配置字段 `cfg.matpower_root`。上游恢复逻辑在 IPOPT 可见时会自动选用 IPOPT，因此本平台要求在 IPOPT 未启用的会话中运行，以固定求解器。

```matlab
accfmlab.setup();
addpath('examples');
single_118;
batch_118;
```

需要 Python 读取时，使用有 NumPy 和 SciPy 的环境。MATLAB 运行不依赖 Python。Python 也是重新生成观察版核心时所需的工具。

## 配置与实验

| 字段 | 用法 |
| --- | --- |
| `case_file` | 一个符合 MATPOWER 格式的 `.m` 或 `.mat` 文件。基准工况要求负荷固定、网络连通、在运支路有正的 RATE_A。算例更新时保留独立文件并核对元件行号。 |
| `operating_point` | `'opf'` 先做 AC OPF，再做 AC PF。用 `'pf'` 可以读取已有调度，仅重新求 PF，参考机组仍可能因平衡需求调整。两种模式均检查 AC 平衡、限值、参考母线和 N-0。 |
| `load_scale` | 同时缩放固定有功和无功负荷。跨工况实验按工况建立独立批次。 |
| `fault` | `accfmlab.fault(branchRows, genRows, busNumbers)`。支路和机组使用算例矩阵中的 **1 基行号**，母线使用算例的 `BUS_I`。 |
| `protection` | 支持配置 `dP_limit`、`P_overhead`、`Q_tolerance`、`uvls_per_step`、`uvls_max_steps`、`grid_forming` 和 `max_recursion_depth`。非空的 `grid_forming` 要求算例包含 `gentype`。 |
| `record_states` | `true` 保存各记录点的岛内 bus、gen、branch 数值矩阵。`false` 仍保留事件日志及处理顺序。 |
| `seed`、`output_dir` | 单次实验的随机种子及输出目录。批次可以用 `accfmlab.scenarios` 从给定种子和故障列表生成清单。 |

```matlab
cfg = accfmlab.config();
cfg.load_scale = 1.05;
cfg.fault = accfmlab.fault(9);
cfg.protection.dP_limit = 0.15;
cfg.record_states = true;
cfg.output_dir = fullfile(pwd,'runs','alpha105-row9');
record = accfmlab.run(cfg);
disp(record.summary)
```

`accfmlab.prepare(cfg)` 只准备和验收工况并返回 `prepared`。正常执行入口会在每个新批次自动做一次前置验收，然后复用同一份故障前状态。在一次受控实验中改变保护阈值时，为每组配置指定独立的输出目录，并固定算例、故障及随机种子。检查差异时先比较首次分歧的岛和保护动作，再比较最终失供。

母线事件采用指南中的外部定义，同时切除该母线的固定负荷、本地机组和相连支路。与直接指定的支路或机组重合时，计算初始集合使用并集。账本以事件之前的需求为分母，另外记录直接切除的负荷。若事件直接切除全部有功需求，结果明确报错，因为 AC-CFM 需要正的内部负荷分母。

## 串行批次与续算

```matlab
cfg = accfmlab.config();
cfg.output_dir = fullfile(pwd,'runs','pilot');
faults = [accfmlab.fault(), accfmlab.fault(1), accfmlab.fault(9), accfmlab.fault([1 9])];
manifest = accfmlab.scenarios(faults,cfg.seed);
summary = accfmlab.batch(cfg,manifest);
```

每个批次使用一个算例、一个负荷工况和一套保护配置。`plan.mat` 保存冻结的工况、设置、软件版本、输入清单和源码哈希。`manifest.csv` 可直接查看。每个场景先写入同一输出盘的临时目录，MAT、JSON 和 CSV 均成功保存后再发布为 `scenario_000001` 等目录。`summary.csv` 随运行更新，恢复时以已经发布的场景文件为准。

中断后使用相同的配置、清单、算例、代码和路径再运行。已发布的场景会被跳过，包括已经记录的错误。需要重跑失败场景时，可以将对应条目另建一个带新输出路径的批次。输出写入、磁盘空间或缺失记录等错误会中止当前批次。输出目录同一时间只允许一个写入者，建议使用本地磁盘。

## 结果与事件

| 文件 | 内容 |
| --- | --- |
| `plan.mat` | 原始算例、经过验收的工况、设置、环境与源码哈希、全部场景和种子。 |
| `record.mat` | 本场景请求、有效初始停运、失供与元件状态账本、完整 AC-CFM 结果、事件、中间状态和异常堆栈。 |
| `metadata.json` | schema 版本、场景、状态、账本、基础容量、列号和是否保存状态。 |
| `events.jsonl` | 按实际处理次序记录的事件。包含全局顺序、递归代数、局部深度、图节点、岛内元件原行号和动作详情。 |
| `numeric.mat` | Python 可读的输入、终态、动作矩阵和可选状态矩阵。状态数组的第 `n` 个 cell 对应 JSONL 的第 `n` 个事件。 |
| `nodes.csv`、`edges.csv` | 原生传播图的节点和边，有终态对象时写出。多条保护边可能连接同一对图节点。 |

`branch_tripped`、`gen_tripped` 是上游显式支路及机组动作标记。账本区分初始停运、随后显式保护切除和间接切除。母线 `bus_tripped` 包含停岛波及，UVLS 和 VCLS 的负荷变化结合事件类型与 `bus_uvls` 解释。`ls_*` 为原始总有功需求的份额，`lost_mw` 和 `breakdown_mw` 为 MW。账本分类依次为初始母线失供、UFLS、UVLS、VCLS、OPF 停岛和其余失供。

部分记录点位于拓扑更新与重新潮流求解之间，矩阵可以保留前一求解阶段的功率和电压。分析电气稳态量时以相应 PF 成功标志和记录阶段为准。恢复 OPF 的结果事件记录成功标志，其状态矩阵为尝试当时的原岛状态。模型采用递归代数和深度优先分岛，事件顺序表示程序处理顺序，未标定为物理时间。

| 状态 | 含义 |
| --- | --- |
| `completed_model` | 模型返回并通过账本检查。检查 `has_solver_failure` 可判断中间是否发生过求解失败或异常。 |
| `model_opf_trip` | 模型返回并报告 OPF 恢复相关停岛。具体可查看动作原因和相关求解记录。 |
| `review_ledger` | 模型终态存在，但账本或终态校核需要审查。 |
| `solver_error` | 求解调用抛出异常并结束此场景。 |
| `iteration_limit` | 达到上游递归上限。 |
| `error` | 输入或其他运行错误，见 `error_id`、`error_message` 及 MATLAB 堆栈。 |

这些状态刻画模型与求解过程。要判定真实暂态失稳，需要相应动态模型和独立实验数据。

## 回归和 Python 读取

```matlab
addpath('tests');
testOutput = regression();
disp(testOutput)
```

在 Windows 上也可单独验证强制中断恢复。以下命令启动一个独立的 MATLAB 批次，等首个场景提交后强制终止它，再启动 MATLAB 续算并核对结果。请使用一个尚未存在的测试目录。

```powershell
$matlab = (Get-Command matlab).Source
python tests/crash_resume.py runs/crash-resume-check --matlab $matlab
```

从工程根目录用 Python 核对任一个场景。命令会检查事件与传播图匹配、MATLAB 元件行号、OL 代数和失供账本。

```powershell
python python/read_run.py runs/example-batch/scenario_000003
python python/read_run.py evidence/verified-row9
```

原始 AC-CFM 源码和许可保存在 `vendor/AC-CFM/`。观察版和变更说明见 [core/CHANGES.md](core/CHANGES.md)。基准算例固定为 [PGLib-OPF v23.07](https://github.com/power-grid-lib/pglib-opf/tree/v23.07) 的 `pglib_opf_case118_ieee.m`，Git blob 为 `59f5b27205f8aff56339d9aa666460ce056e6482`，原始署名保留在算例文件头部。
