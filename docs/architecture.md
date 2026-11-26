# 架构

1. `accfmlab.setup` 配置并核对会话中的数值环境、源码锁和源清单。 `context` 固定用户请求、算例 SHA-256 及有效模型设置。
2. `prepare_case` 计算并检查故障前工况。 `prepare_validated` 使用原版 AC-CFM 运行 N-0。每个新批次做一次前置验收。
3. `simulate` 应用外部母线事故并委托观察版 AC-CFM 处理原生支路、发电机故障。岛内映射沿原版 MATPOWER custom 字段与分岛逻辑保留。
4. `accfm_observed` 由 `core/build_observed.py` 从固定上游生成。包装使用原求解器与原选项，每处包装只执行对应的原调用。回调读取矩阵、图父节点及诊断。MATLAB 的外层恢复调用者 RNG 和警告设置。
5. `batch` 固定实验计划、执行、暂存和发布。MATLAB 保存科研记录及交换数据。Python 对交换数据做独立的完整性与约束验证。

维护观察点时修改生成器，生成后用 `--check` 和 MATLAB 回归确认。原版数值语义的更改需要单独批准及基准。 `vendor/` 保存上游原始文件，`core/` 维护观察派生物。
