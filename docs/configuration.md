# 配置参考

| `accfmlab.config` 字段 | 语义 |
| --- | --- |
| `case_file` | MATLAB `.m` 或 `.mat` 的 MATPOWER 算例。基准工况要求连接且带电，固定非负有功负荷，活动支路有正的 RATE_A。可执行算例应来自可信来源，外部依赖也要固定。 |
| `operating_point` | `'opf'` 先做 AC OPF 并将结果作为 NR PF 的初值。`'pf'` 用已有调度做 PF，平衡机组可能调整出力。均做电压、角度、支路、P/Q 限值及 N-0 校核。 |
| `load_scale` | 固定 P/Q 负荷的统一正比例，默认 1。 |
| `fault` | 单场景入口的原始事故。 `accfmlab.fault(branchRows,genRows,busNumbers)`。支路和机组为 1 基原行号，母线为 BUS_I。 |
| `protection` | 可覆盖 `dP_limit`、`P_overhead`、`Q_tolerance`、`uvls_per_step`、`uvls_max_steps`、`grid_forming`、`max_recursion_depth`。有效设置和全部 `mpopt` 均写入计划。 |
| `record_states` | 默认 false。true 保存每个观测点的岛内 bus/gen/branch，恢复 OPF 的专用矩阵在两种模式下都保存。 |
| `seed` | 单场景调用传入 `rng(seed,'twister')`。固定模型的随机调用用于图节点命名，物理算法本身未抽样。`scenarios(faults,firstSeed)` 按给定故障次序生成递增种子。 |
| `matpower_root`、`output_dir` | 安装路径及唯一批次目录。使用同一批次续算需保持冻结请求相同。 |

上游的 `grid_forming` 默认为 `{'PS','ST','GT'}`。平台基准显式用空列表，允许有活动发电容量的岛继续按其余上游条件执行。启用过滤需提供 `gentype`，并可根据类型导致停岛。核对比较实验时记录这个差异。平台设置 legacy、NR、关闭 PF 的 MATPOWER Q 限值强制、MIPS 和 OPF 视在功率限值。级联的 Q 限值动作仍由原版模型处理。
