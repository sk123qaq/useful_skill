# Data Analysis Skill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a reusable `data-analysis` skill that helps an agent define a structured analysis problem, read data from files or databases, clean and profile it, run EDA/statistics/modeling, and deliver business-ready findings with Chinese-safe visualizations.

**Architecture:** Use a layered design: a concise `SKILL.md` for workflow and routing, `references/` for decision rules, and `scripts/` for deterministic execution. Keep the skill usable even when optional dependencies are missing by shipping environment checks, dependency guards, and graceful degradation.

**Tech Stack:** Python 3.13, `uv`, `pandas`, `polars`, `duckdb`, `pyarrow`, `sqlalchemy`, `scipy`, `statsmodels`, `scikit-learn`, `matplotlib`, `seaborn`, optional `xgboost`, `prophet`, `plotly`, `streamlit`, `shap`

---

### Task 1: Define the skill contract

**Files:**
- Create: `SKILL.md`
- Create: `agents/openai.yaml`
- Create: `references/workflow.md`
- Create: `references/environment.md`

**Step 1: Write the skill trigger metadata**

Describe what the skill does and when it should trigger. Cover:
- tabular data analysis
- business metrics analysis
- time-series analysis
- A/B tests and experiment analysis
- database and file-based workflows

**Step 2: Write the workflow contract**

Document the required sequence:
1. define the question
2. inspect the environment
3. route data access
4. clean and profile data
5. choose statistics/modeling
6. explain results

**Step 3: Add environment rules**

Document required packages, optional packages, and fallback behavior when packages are unavailable.

**Step 4: Validate metadata**

Run:
```bash
python3.13 /Users/sk/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```

Expected: `Skill is valid!`

### Task 2: Create the reusable execution interface

**Files:**
- Create: `scripts/common.py`
- Create: `scripts/check_environment.py`
- Create: `scripts/run_pipeline.py`

**Step 1: Implement shared utilities**

Provide helpers for:
- dependency detection
- output directory creation
- JSON/Markdown writing
- timestamped run folders

**Step 2: Implement environment check**

Support both human-readable and JSON output so other agents can call it programmatically.

**Step 3: Implement the pipeline CLI**

Accept at least:
- `--input-path`
- `--db-url`
- `--query`
- `--task`
- `--target`
- `--time-col`
- `--output-dir`
- `--config-json`

**Step 4: Run smoke checks**

Run:
```bash
python3.13 scripts/check_environment.py --json
python3.13 scripts/run_pipeline.py --help
```

Expected: valid JSON for the first command and help output for the second.

### Task 3: Implement data access routing

**Files:**
- Create: `references/io-strategy.md`
- Create: `scripts/io_router.py`
- Create: `scripts/db_connectors.py`

**Step 1: Encode scale-aware rules**

Document:
- when to use `pandas`
- when to use `polars`
- when to use `duckdb`
- Excel row-limit caveats
- database connector priorities

**Step 2: Implement file read planning**

Detect format, estimate scale, recommend backend, and warn on risky inputs.

**Step 3: Implement database reading**

Support:
- builtin `sqlite3`
- SQLAlchemy-based readers for mainstream databases
- explicit error messages for missing drivers

**Step 4: Run syntax checks**

Run:
```bash
python3.13 -m py_compile scripts/io_router.py scripts/db_connectors.py
```

Expected: no output

### Task 4: Implement cleaning and EDA primitives

**Files:**
- Create: `references/stats-and-tests.md`
- Create: `references/chart-selection.md`
- Create: `scripts/clean_preprocess.py`
- Create: `scripts/eda_stats.py`
- Create: `scripts/explain_viz.py`

**Step 1: Implement data quality reporting**

Cover:
- missing values
- duplicates
- IQR and z-score outliers
- numeric/categorical/time column identification

**Step 2: Implement EDA summaries**

Cover:
- summary statistics
- correlation matrix
- normality tests
- optional ADF and heteroskedasticity checks when packages exist

**Step 3: Implement chart planning**

Return static recommendations even when plotting libraries are missing.

**Step 4: Add plotting fallbacks**

If `matplotlib` is unavailable, save a chart plan instead of failing.

### Task 5: Implement feature engineering and baseline modeling

**Files:**
- Create: `references/model-selection.md`
- Create: `scripts/feature_engineering.py`
- Create: `scripts/model_runner.py`
- Create: `scripts/evaluate.py`

**Step 1: Implement baseline-first routing**

Use:
- descriptive templates first
- statistical baselines second
- classical ML third
- advanced models only when justified

**Step 2: Implement common feature engineering**

Cover:
- time features
- one-hot encoding plan
- PCA plan
- MACD / RSI helpers

**Step 3: Implement baseline model execution**

Support:
- classification and regression via `scikit-learn`
- time-series model suggestions
- time-aware validation for temporal data

**Step 4: Implement metrics**

Cover:
- Accuracy / Precision / Recall / F1
- RMSE / MAE / MAPE / R2
- Sharpe ratio and max drawdown helpers

### Task 6: Implement business analysis templates

**Files:**
- Create: `references/business-metrics.md`
- Create: `references/experiment-design.md`
- Create: `scripts/business_templates.py`

**Step 1: Implement funnel analysis**

Support:
- ordered boolean step columns
- ordered stage column

**Step 2: Implement monetization summaries**

Support:
- paying user rate
- ARPPU / ARPU
- revenue concentration hints

**Step 3: Document experiment design rules**

Cover:
- randomization
- sample ratio mismatch
- guardrail metrics
- significance + effect size + business significance

### Task 7: Integrate external research workflow

**Files:**
- Create: `references/web-research-rules.md`
- Create: `scripts/source_research_adapter.py`

**Step 1: Define when to use `web_search_pro`**

Use it only for:
- context gathering
- metric definition verification
- external benchmark discovery
- missing domain context

**Step 2: Normalize source capture**

Store:
- source
- metric
- definition
- unit
- geography
- date
- confidence
- URL

**Step 3: Add conflict detection rules**

Flag conflicts in:
- units
- time window
- geography
- metric definition

### Task 8: Verify and iterate

**Files:**
- Verify: `SKILL.md`
- Verify: `agents/openai.yaml`
- Verify: `scripts/*.py`
- Verify: `references/*.md`

**Step 1: Run validation**

Run:
```bash
python3.13 /Users/sk/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
python3.13 -m py_compile scripts/*.py
```

Expected: skill validation passes and Python files compile cleanly.

**Step 2: Run representative smoke tests**

Run:
```bash
python3.13 scripts/check_environment.py
python3.13 scripts/io_router.py --help
python3.13 scripts/run_pipeline.py --help
```

Expected: readable output and no tracebacks.

**Step 3: Capture remaining gaps**

List any missing dependencies or non-implemented advanced features as follow-up items instead of silently hiding them.
