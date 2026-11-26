# 第三方许可证与署名

平台自有代码采用 [MIT](LICENSE)。下列内容继续适用各自的上游条款。

| 内容 | 授权与出处 |
| --- | --- |
| `vendor/AC-CFM/` | Matthias Noebels 的 AC-CFM，固定上游提交 `48eebaa19b96b00ee40d7a86f5c1132be74efd8b`。源码采用 BSD-3-Clause，`parfor_progress.m` 和 `randraw.m` 各自保留原作者和文件内的两条款 BSD 许可声明。见 [上游仓库](https://github.com/mnoebels/AC-CFM) 和 [随附许可](vendor/AC-CFM/LICENSE)。 |
| `core/accfm_observed.m` | 从上游生成的观察版。上游部分沿用同一 BSD-3-Clause 及原作者署名。平台原创的观察和导出增量按 MIT 发布。分发该文件时保留 [随附的上游许可](vendor/AC-CFM/LICENSE)。 |
| `cases/pglib_opf_case118_ieee.m` | IEEE PES PGLib-OPF v23.07 Typical Operations 的原文件。数据采用 CC BY 4.0。源算例保留 Richard D. Christie 等文件头署名和来源。PGLib 上游的软件部分采用 MIT。见 [固定版本许可](https://github.com/power-grid-lib/pglib-opf/blob/v23.07/LICENSE) 和 [源算例](https://github.com/power-grid-lib/pglib-opf/blob/v23.07/pglib_opf_case118_ieee.m)。 |
| MATLAB、MATPOWER、MIPS | MATLAB 使用用户已有授权。MATPOWER 和 MIPS 的代码采用 BSD-3-Clause。MATPOWER 算例适用各自条款。见 [MATPOWER 许可](https://matpower.org/license/) 和 [MIPS 许可](https://github.com/MATPOWER/mips/blob/master/LICENSE)。 |
| NumPy、SciPy | Python 运行时依赖采用 BSD-3-Clause，发行包可附其他依赖的许可。见 [NumPy v1.26.4](https://github.com/numpy/numpy/blob/v1.26.4/LICENSE.txt) 和 [SciPy v1.11.4](https://github.com/scipy/scipy/blob/v1.11.4/LICENSE.txt)。 |

使用 AC-CFM 模型的研究请同时引用 Noebels、Preece 和 Panteli 的上游论文。正式刊载于 IEEE Systems Journal 16(1), 374–385，2022 年，2020 年提前发布。使用 PGLib 数据时保留算例文件头署名和版本。平台引用信息见 [CITATION.cff](CITATION.cff)。[IEEE 出版记录](https://ieeexplore.ieee.org/document/9282067)
