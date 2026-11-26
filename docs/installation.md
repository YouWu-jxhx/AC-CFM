# 安装与会话配置

基准环境为 Windows、MATLAB R2025a、MATPOWER 8.1 legacy、NR 和 MIPS。MATLAB 需要可用许可证，MATPOWER 使用现有安装。平台自动给当前会话添加路径，保留全局 MATLAB 路径。检测到 IPOPT 或关键函数被其他安装遮蔽时会报错。

```matlab
cd('D:/ac-cfm-platform')
environment = accfmlab.setup('D:/matpower8.1');
disp(environment)
```

MATPOWER 路径优先取 `cfg.matpower_root`，其次是 `ACCFM_MATPOWER_ROOT`，最后是 `D:/matpower8.1`。使用路径冲突诊断 `which -all runpf` 和 `which -all runopf`。更改数值环境时，用新目录跑独立基准。

Python 用于读取、校验与维护生成器。运行 MATLAB 不需要 Python。可使用已有的 Python 3.11 和依赖，或在项目内的隔离环境安装锁定的版本。

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r python/requirements.txt
.venv/Scripts/python python/read_run.py evidence/verified-row9
```
