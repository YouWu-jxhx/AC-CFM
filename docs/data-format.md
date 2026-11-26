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
