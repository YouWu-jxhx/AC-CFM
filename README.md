# AC-CFM 科研仿真平台

用交流稳态潮流、离散保护与递归分岛研究电力系统的级联故障。平台将原版 AC-CFM、只读观察点和实验管理分离，支持单场景及串行受控实验。默认算例为 PGLib-OPF v23.07 的 IEEE 118 母线 Typical Operations。

## 快速开始

```powershell
git clone https://github.com/YouWu-jxhx/AC-CFM.git
cd AC-CFM
```

在已有 MATLAB R2025a、MATPOWER 8.1 legacy 和 MIPS 的 Windows 会话中切换到本仓库。默认从 `D:/matpower8.1` 加载 MATPOWER。

```matlab
accfmlab.setup();
cfg = accfmlab.config();
cfg.fault = accfmlab.fault(9);
cfg.record_states = true;
cfg.output_dir = fullfile(pwd,'runs','ieee118-row9');
record = accfmlab.run(cfg);
disp(record.summary)
```

默认工况下，支路第 9 行场景的摘要应为 `completed_model`，失供约 2352.30 MW。输出位于 `runs/ieee118-row9/scenario_000001`。批次根下的 `plan.json` 和 `summary.csv` 提供来源与索引。按安装文档准备 Python 3.11 后，可核验校验和、计划引用及动作和图的数据语义。

```powershell
python python/read_run.py --require-plan runs/ieee118-row9/scenario_000001
```

## 代码结构

| 目录 | 内容 |
| --- | --- |
| `+accfmlab/` | 配置、工况验收、场景执行、账本与提交 |
| `core/` | 只读观察版、生成器和固定的上游源码清单 |
| `vendor/AC-CFM/` | 固定授权上游源码 |
| `cases/` | 固定的 PGLib 118 算例 |
| `examples/`、`tests/`、`benchmarks/` | 使用示例、回归与恢复测试、可重复性能基准 |
| `python/`、`evidence/` | 独立的交换数据读者、历史验证证据 |

## 使用与维护

- [安装和会话配置](docs/installation.md)、[用户指南](docs/user-guide.md)、[配置参考](docs/configuration.md)
- [架构](docs/architecture.md)、[数据格式](docs/data-format.md)、[批次与恢复](docs/batch-and-recovery.md)
- [验证和局限](docs/validation.md)、[实际验证报告](VALIDATION-REPORT.md)、[性能报告](PERFORMANCE-REPORT.md)
- [初始审计](AUDIT.md)、[实施计划](IMPROVEMENT-PLAN.md)、[当前进展](PROGRESS.md)
- [项目 MIT 许可证](LICENSE)、[第三方许可证](THIRD-PARTY-NOTICES.md)、[引用](CITATION.cff)

验证覆盖固定 118 工况、独立双母线保护夹具、1000 个不同事故工况组合和 Windows 本地卷串行恢复。数值求解失败、模型停岛和动态物理失稳需分别解释。大型生产任务的规模、抽样及数据留存策略应以实际批次测量为依据。
