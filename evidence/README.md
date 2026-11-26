# 验证证据

| 文件或目录 | 来历 |
| --- | --- |
| `AC-CFM-Guide.md` | 平台整理前的技术指南，第 9 节记录当时的实验范围和结果。 |
| `guide-harness-final.log` | 原指南的 MATLAB 最终运行日志。 |
| `guide-case39-reference.mat` | 原 39 母线官方示例的输入、设置和原生结果。 |
| `guide-pilot-summary.csv`、`guide-pilot-mat/` | 原四场景试跑的摘要、冻结工况和各场景的 MAT 结果。 |
| `guide-trace-row9.mat` | 原插桩的第 9 行故障记录，覆盖 15 个保护判定前快照。 |
| `guide-exchange-118-row9/` | 原指南的 MAT 和 CSV 导出样本。 |
| `probe2.log`、`legacy.log` | 原开发中的求解路径与兼容性诊断日志。 |
| `verification.log`、`python-verification.log` | 工程封装后的 MATLAB 回归及 Python 读写核对。 |
| `crash-resume.log` | Windows 下独立 MATLAB 运行被强制终止，以及同一清单续算的实测记录。 |
| `verified-row9/` | 封装后第 9 行场景的完整导出样本，可直接运行 `python python/read_run.py evidence/verified-row9`。 |

在同一台电脑继续实验时，可在本工程根目录运行 README 中的回归命令，结果会写入新的 `runs/` 子目录。
