# Environment

## 解释器

优先使用项目专用 venv：

```bash
/home/shike/.venvs/data-analysis-pro/bin/python scripts/check_environment.py
```

系统 Python 可能缺 pandas/scipy/sklearn/matplotlib；不要用 `pip install` 污染系统环境。

## 依赖组

| 组 | 模块 | 用途 |
|---|---|---|
| core | numpy, pandas, scipy, sklearn | 清洗、统计、基线 |
| viz | matplotlib, seaborn | 图表 |
| database | sqlalchemy, openpyxl | SQL/Excel |
| large_data | polars, duckdb, pyarrow | 大文件/列式 |
| advanced | statsmodels, xgboost, lightgbm, prophet, plotly, streamlit, shap, torch | 按需 |

`check_environment.py` 只读，输出缺失列表和安装提示；`--output-path` 可写快照，不默认写 cwd。

## 中文字体

- 首选 `Noto Sans CJK SC` / `Source Han Sans SC` / `PingFang SC`。
- 若只有 `Noto Sans CJK VF` 的 Thin 字重，加粗会失效；图表生成器用 `DejaVu Sans` + `Droid Sans Fallback` 双字体。
- 报告中文字体缺失时，图里会出现方框；先修字体，不要用英文标签掩盖。

## 外部工具

- `pdftotext`、`qpdf`、`pandoc`、`soffice`：只在 PDF/DOCX 交付时需要。
- 缺工具时报告缺失，不要静默降级成 Markdown 并声称是 PDF。
