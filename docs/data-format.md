# 数据格式

## 批次级

| 文件 | 内容 |
| --- | --- |
| `plan.mat` | 冻结的请求、原始与已验收的算例、工况审核、保护与求解设置、环境与清单。 |
| `plan.json` | 可独立读取的实验来源。含 `plan_sha256`、算例及源码哈希、上游提交、生成器版本、MATLAB/MATPOWER 版本及关键求解依赖、完整清单和种子语义。 |
| `manifest.csv`、`summary.csv` | 浏览用索引，续算从正式目录恢复汇总。 |

## 场景级

| 文件 | 内容 |
| --- | --- |
| `record.mat` | 原生 MATLAB 结果（包含 digraph）、事件、可选状态、OPF 矩阵、账本和异常堆栈。 |
| `metadata.json` | schema、计划文件相对路径及 SHA-256、场景和有效初始停运、摘要、账本、基础容量和列号。 |
| `events.jsonl` | 线性处理顺序，包含 sequence、generation、local_depth、graph_parent 和各岛的 1 基原行号。 |
| `numeric.mat` | 前置、终态、动作矩阵、可选 `state_bus/gen/branch` 及 `opf_networks`。状态 cell 的序号与事件一致。 |
| `nodes.csv`、`edges.csv` | 原生传播图。相同源、目标可能对应多条动作边，无终态时两个文件均仅有表头。 |
| `checksums.json` | 六个输出文件的名称、字节数及 SHA-256，以及来源计划摘要。 |

MATLAB JSON 可将单项行号序列编码成标量。Python 读者统一将行号解析成向量。 `bus_rows` 是原矩阵位置，`BUS_I` 是母线身份。`gen_id`、`branch_id` 与原算例位置一致。并行支路或同母线机组用稳定列核验，参数完全相同的重复元件仍依赖原行号辨识。

`branch_tripped`、`gen_tripped` 记录显式保护，`bus_tripped` 含停岛。初始停运另外保存。原生 `bus_uvls` 在恢复 OPF 应用可调负荷后也有回写。结合 UVLS、VC、OPF 事件判断来源。快照反映指定观测点。拓扑更新后、下一次 PF 之前的功率与电压可能是上一解，参照阶段和成功标志。递归代数及事件序号未标定为物理时间。

OPF 的 `before_recovery_opf` 和 `recovery_opf_result` 通过 `opf_network_index` 指向实际传给求解器及返回的数据矩阵。快照包括 gencost、baseMVA、bus/gen/branch 和 `gen_rows`。虚拟可调负荷机组以 0 标注并通过 GEN_BUS 定位。结果事件包含目标值、成功状态、可用诊断与可调需求、供电及削减 MW。验证 PF 使用独立事件。MATLAB 专用的图和字符串对象在 SciPy 中可能表现为 opaque 数据，跨语言分析使用交换文件。

账本用事故前总有功需求作统一分母。分项为初始母线直接失供、UFLS、UVLS、VC、OPF 相关停岛和其余失供。其余失供包括无供电岛和单母线 XL 负荷变动。保留上游原始份额与边权，并用实际需求变更与终态进行校验。

Schema 1 历史目录可只读验证，字段能力取决于当时的输出。Schema 2 的独立字节检查需要场景校验清单。使用 `--require-plan` 同时校验整个实验的来源引用。

## 观测修订 3 的独立语义校验

文件布局仍是 Schema 2。新的 `observations_version=3` 增加了 UVLS 的步进母线、有效参数、恢复回写前的 PD 和图节点变更记录。原版和历史数据继续可读。旧观测缺少逐笔回写及节点构造信息，可校验的范围以当时字段为准。

| 记录阶段 | 含义 |
| --- | --- |
| `after_initial`、`island_enter`、`island_split` | 初始停运完成、进入递归、即将求解子岛。岛内行号指向原算例，包含原版保留的局部离线元件。 |
| `ac_pf_input`、`verification_pf_input` | 求解器输入。开断或保护更新之后可能保留前一解的功率及电压。 |
| `ac_pf`、`verification_pf` | 求解器返回。只有 `detail.success=true` 的返回矩阵可按已收敛 PF 解释。 |
| `before_recovery_opf`、`recovery_opf_result` | 独立记录每次恢复尝试的输入和结果，输出状态与原岛快照分开。成功返回后可能回写负荷，再执行独立核验 PF。 |
| `vcls_write` | 至少一个派生负荷通过上游 MW 整数舍入门槛后，模型即将回写所有派生负荷。本事件保存对应原行号及回写前 PD。核验 PF 失败时，终态动作矩阵仍可能带有这些值。 |
| `before_frequency`、`before_limit_actions`、`action` | 保护判定前及原生动作出图时的记录。同代相继动作可共用图节点，且快照可能处于下一次 PF 之前。 |
| `graph_node`、`after_actions`、`graph_success`、`island_without_supply` | 节点创建、更新负荷、标记终止成功以及记录无供给岛。节点初始发电机和支路计数来自创建时在线元件。 |

`bus`、`gen`、`branch` 依次按母线、机组、支路排成二维矩阵。常用列随 `columns_1based` 导出。PG/PD 为 MW，QG/QD 为 MVAr，VM 为 p.u.，VA 为度，支路端功率沿原模型符号约定。状态 cell 的局部行由对应事件的原行号数组定位。动作矩阵为原元件数乘最大递归深度，列为原版代数。开断矩阵使用 0/1，UFLS 与 UVLS 矩阵中的数值表示本动作相对当前需求的削减比例。

`bus_uvls` 统计之前各代非零写入，随后按原模型步进或全切。VCLS 在舍入门槛达到时写入 `1 + PG/PD_before`，同一代的后写入覆盖前值，包含合法精确零。校验器按事件顺序重建两个削减矩阵，并逐项核对非零位置和比例。

图边按上游各自的定义校验。EV 和 ISL 的权重与基数为 1。UFLS 用削减比例和单位基数，UVLS 用涉及母线数和岛内母线总数。XL、ULGT、OL 的权重取动作行数，基数取相应元件总数。OFGS 的上游 `length(gens_to_shed)` 对标量给出 1。SH 两值均为切除的并联设备数。VC 权重为恢复削减份额，OPF 停岛权重为 1，二者基数为恢复尝试前岛需求。非失供边可以没有 MW 值。无供给路径可能更新原出边上的失供。逐边校验保留同端点的多边，并核对节点的名称、类型、母线数量、负荷、在线机组和在线支路计数。

场景类型由 `summary.status`、`error_category` 与 `result_available` 一起解释。`error` 为输入错误，`iteration_limit` 为递归上限，`solver_error` 为求解调用抛出异常。三者可以保存部分事件，无终态图。`review_ledger` 表示存在终态且需要审阅账本，严格语义校验可能拒绝该产物。成功恢复也可能保留中途求解失败标记。`model_opf_trip` 表示模型按规则执行停岛。

校验分三层。文件 SHA-256 检查承诺字节。MATLAB 记录、冻结工况与交换文件比对检查两份导出是否一致。语义层按原版定义重建动作、图及账本。用作训练数据时按物理场景和冻结计划划分数据集，避免把不同快照模式、图种子或同组对照泄漏到评估集。模型执行图与求解失败需要独立工程证据才能解释为真实系统因果或失稳。
