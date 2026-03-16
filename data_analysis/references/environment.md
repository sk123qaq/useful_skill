# Environment

## Core Packages

These packages should exist for the skill to run end-to-end:

- `pandas`
- `numpy`
- `scipy`
- `scikit-learn`

## Strongly Recommended Packages

- `matplotlib`
- `seaborn`
- `sqlalchemy`
- `openpyxl`
- `statsmodels`

## Large-Data Packages

- `polars`
- `duckdb`
- `pyarrow`

## Optional Advanced Packages

- `xgboost`
- `lightgbm`
- `prophet`
- `plotly`
- `streamlit`
- `shap`
- `torch`

## Optional Database Drivers

- `psycopg`, `psycopg-binary`, or `psycopg2` for PostgreSQL
- `pymysql` or `mysqlclient` for MySQL
- `pyodbc` or `pymssql` for SQL Server
- `duckdb-engine` only if you explicitly need DuckDB through SQLAlchemy; the skill can read DuckDB natively without it

On macOS or minimal Python environments, `psycopg-binary` is often the fastest way to avoid a missing `libpq` runtime.

## macOS Notes

- `xgboost` may need `libomp` on macOS even after `pip install xgboost`.
- Install it with:

```bash
brew install libomp
```

## Preferred Install Command

Recommended baseline:

```bash
cd /path/to/data_analysis
python3 -m pip install -r requirements.txt
```

Optional extras:

```bash
cd /path/to/data_analysis
python3 -m pip install -r requirements-optional.txt
```

If you prefer `uv`, you can substitute `python3 -m pip` with `uv pip`.

Install advanced packages only if the task needs them.

Install database drivers only when the target backend requires them.

## Fallback Rules

- If `pandas` is missing, only do lightweight file inspection or emit an environment gap.
- If `matplotlib` is missing, save a chart plan instead of failing.
- If `sqlalchemy` is missing, allow builtin `sqlite3` only.
- If `statsmodels` is missing, skip ADF and formal heteroskedasticity diagnostics and say so explicitly.

## Runtime Readiness Checks

Before promising Chinese charts or formal report delivery, also verify these non-package prerequisites:

- `MPLCONFIGDIR` points to a writable directory
- a CJK-capable font is detected, for example `PingFang SC`, `Hiragino Sans GB`, `Songti SC`, `Microsoft YaHei`, or `Arial Unicode MS`
- `python-docx` and `reportlab` are available if DOCX / PDF output is required
- at least one PDF validation path exists:
  - `pypdf`, or
  - `pdftotext`, or
  - the `file` command as a weaker fallback

`python3 scripts/check_environment.py` now reports these runtime details explicitly.
It also reports readiness flags such as `chinese_chart_ready`, `formal_report_ready`, and `pdf_text_validation_ready` so the agent can decide whether to promise a full Chinese report workflow.
