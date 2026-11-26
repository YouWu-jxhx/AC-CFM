# 用户指南

## 先验收实验工况

对比保护参数或事故后果时，先固定拓扑、负荷和调度流程。以下示例使用 PGLib 118 算例，将 P/Q 固定负荷统一放大为 1.05 倍。 `prepare` 检查算例、求得故障前工况并执行原版 AC-CFM 的 N-0。 `prepared.audit` 给出总有功需求、限值校核、平衡残差和 N-0 结果。

```matlab
cfg = accfmlab.config();
cfg.load_scale = 1.05;
prepared = accfmlab.prepare(cfg);
disp(prepared.audit)
```

`operating_point='opf'` 先做调度优化再执行 PF。`'pf'` 读取算例给出的工况并做 PF，平衡机组可能调整出力。语法、平台支持的模型范围、数值可行性和 N-0 分别校验。更换算例时请先运行上述验收，在诊断失败时检查异常标识和提示。

## 跟踪一次事故

初始支路和机组按原矩阵的 1 基行号选取，母线按 `BUS_I` 选择。`fault(9)` 表示支路第 9 行，`fault([],1)` 表示机组第 1 行，`fault([],[],2)` 表示母线编号 2。母线停运同时切除本地负荷、发电及相邻支路。与直接指定的机组或支路重合时按并集合并。

```matlab
cfg = accfmlab.config();
cfg.fault = accfmlab.fault(9);
cfg.record_states = true;
cfg.output_dir = fullfile(pwd,'runs','row9-trace');
record = accfmlab.run(cfg);
disp(record.summary)
```

`summary.status` 表示终态或失败类别，`has_solver_failure` 表示过程中至少有一次求解返回失败或抛出异常。恢复成功的场景也可能带有这个标记。进一步查看 `failure`、`error_category` 和求解相关事件。状态快照中的潮流量应与成功求解事件匹配。传播图记录模型执行，事件序号反映处理先后，失供账本按 MW 和事故前需求份额汇总。

## 运行受控对照批次

以下对照改变欠压减载每步比例，同时保持四个事故和工况相同。每个配置独立创建输出目录。`manifest` 固定事故及图节点命名种子。对比摘要可以筛选变化场景，再用事件序列定位首先分歧的分岛或保护动作。

```matlab
cfg = accfmlab.config();
faults = [accfmlab.fault(),accfmlab.fault(9), ...
          accfmlab.fault([],1),accfmlab.fault([],[],2)];
manifest = accfmlab.scenarios(faults,cfg.seed);
cfg.output_dir = fullfile(pwd,'runs','uvls-control');
control = accfmlab.batch(cfg,manifest);

cfg.output_dir = fullfile(pwd,'runs','uvls-treatment');
cfg.protection.uvls_per_step = 0.04;
treatment = accfmlab.batch(cfg,manifest);
disp(table(control.scenario_id,control.lost_mw,treatment.lost_mw))
```

同一批次内固定算例、`load_scale`、调度流程和全部保护设置。对比负荷倍率时也用独立输出目录，并先确认两个工况都通过 N-0。中断后使用相同配置、清单、环境和路径重新调用 `batch`。它会检查已有结果并续跑缺失场景。发现损坏时按恢复指南处理。[批次与恢复](batch-and-recovery.md)

## 检查结果与迁移算例

```powershell
python python/read_run.py --require-plan runs/row9-trace/scenario_000001
```

验证后从 `summary.csv` 筛选场景，用 `plan.json` 追溯配置，用 `events.jsonl` 定位动作，用 `numeric.mat` 比较相应状态。使用 MATLAB 时可加载 `record.mat` 得到原生图和异常堆栈。[数据格式](data-format.md)

新算例可使用 MATPOWER `.m` 或 `.mat`。保留原文件，使用独立目录验收，并建立原行号与研究资产 ID 的对照。非连续 BUS_I、并行支路和同母线多个机组都需要保留各自身份。对照实验从同一原算例派生，避免按设备名或端点重排后误用旧故障行号。输入格式及当前平台支持限制见配置参考。[配置参考](configuration.md)
