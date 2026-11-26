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

## 算例支持边界

输入先通过 `loadcase` 解析为 MATPOWER v2，然后区分结构错误 `ACCFMLab:CaseFormat` 和当前平台的支持限制 `ACCFMLab:CaseUnsupported`。其后才进行工况求解和 N-0 验收。可使用非连续母线编号、并行支路和同母线多个发电机，MATPOWER 的 10 列机组基础矩阵和带可选列的机组矩阵均可进入检查。

平台要求一个连通、均带电、单参考母线的输入，固定非负 P 负荷、正总需求、在线机组状态 1 和有限 PMAX。AC-CFM 的恢复路径以负 PMIN 识别派生负荷，因此输入机组需使用非负 PMIN。活动支路需有有限正 RATE_A 及非零阻抗。MATPOWER 允许的无界 RATE_A、双组 P/Q 成本和无成本算例超出该级联路径的支持范围。 `load2disp` 需要每台机组一行有功费用及至少六列。 `gentype` 按机组矩阵原行顺序提供列 cell 数组。保留线性/多项式成本及 MATPOWER 的零变比和未约束角差语义。
