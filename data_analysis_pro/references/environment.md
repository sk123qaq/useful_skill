# 环境配置

## 当前定位

这份文档只描述 `data_analysis_pro` 当前真实会检查、会依赖、或常见会受影响的环境条件。

不要把它理解成“必须装齐所有高级库才能使用这个 skill”。

## 1. 核心依赖

当前最重要的一组依赖，对应 `common.py` 里的 `core`：

- `numpy`
- `pandas`
- `scipy`
- `sklearn`

少了它们中的关键项时，很多核心脚本都无法稳定运行。

## 2. 常用可视化依赖

对应 `viz`：

- `matplotlib`
- `seaborn`

如果缺失：

- 统计和表格分析仍可能继续
- 但不要承诺会稳定产出图

## 3. Excel / 大文件 / 高级依赖

这些依赖是“按需增强”，不是默认必装。

### Excel / 兼容性相关

- `openpyxl`

用途：

- 读取一部分 Excel 文件时会更稳

### 大数据相关

- `polars`
- `duckdb`
- `pyarrow`

注意：

- 当前 `io_router.py` 可能会给出 `polars_or_duckdb` 一类建议
- 但这主要是“建议后端”，不是已经形成稳定大数据工作流

### 高级依赖

- `statsmodels`
- `xgboost`
- `lightgbm`
- `prophet`
- `plotly`
- `streamlit`
- `shap`
- `torch`

注意：

- 它们出现在依赖分组里，不等于当前 skill 对这些方向都已有稳定脚本能力
- 尤其不要因为这里列出了 `prophet`、`plotly`、`streamlit`，就默认承诺时间序列建模、交互式 dashboard 或完整可视化应用

## 4. 外部工具

`common.py` 当前会检查这些命令：

- `pdftotext`
- `qpdf`
- `pandoc`
- `soffice`

它们更偏文档/PDF 辅助能力，不是当前 `data_analysis_pro` 的核心前提。

如果缺失：

- 最合理的做法通常是降低交付形式承诺
- 而不是假装这些导出链已经可用

## 5. 中文图表相关

当前环境里，中文图表最关键的是两件事：

- `matplotlib` 可用
- 系统里有可用的 CJK 字体

`common.py` 的候选字体包括：

- `Noto Sans CJK SC`
- `Source Han Sans SC`
- `PingFang SC`
- `Hiragino Sans GB`
- `Songti SC`
- `Microsoft YaHei`
- `SimHei`
- `Arial Unicode MS`

另外，运行时会尽量设置：

- `MPLCONFIGDIR`
- `MPLBACKEND=Agg`
- `axes.unicode_minus = False`

## 6. `check_environment.py` 现在真实会做什么

当前脚本会输出：

- Python 版本
- 时间戳
- `MPLCONFIGDIR`
- 各依赖分组的可用情况
- 外部工具可用情况
- 是否找到可用的中文字体

它不会稳定输出以下“高级就绪标识”：

- `chinese_chart_ready`
- `formal_report_ready`
- `pdf_text_validation_ready`

所以不要把这些字段写成当前能力前提。

## 7. 实用回退规则

- 缺少核心依赖：
  - 优先报告环境缺口，不要继续承诺完整分析
- 缺少绘图库：
  - 继续做表格/统计分析，但把图表改成文字建议或不产图
- 缺少高级库：
  - 只影响特定高级路径，不应阻断全部分析
- 缺少文档/PDF 工具：
  - 改为 Markdown 交付，不要强行承诺 DOCX/PDF

## 防护准则

- 不要引用当前 skill 里并不存在的 `requirements.txt` 或 `requirements-optional.txt`。
- 不要把“可选库列表”误写成“能力已经落地”。
- 缺依赖时优先降级交付，不要补写不存在的功能。
