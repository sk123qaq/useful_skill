# Workflow

## Analysis Contract

Write these fields before loading or modeling data:

- `objective`: what decision the analysis should support
- `task_type`: descriptive, diagnostic, predictive, causal, experiment, financial, or business KPI
- `unit_of_analysis`: user, order, session, product, day, account, trade, or other atomic unit
- `target_metric`: the main outcome or KPI
- `time_window`: the calendar or event window
- `business_context`: why the result matters
- `success_criteria`: what a useful answer looks like

If any of the first four fields are unknown, pause and surface the ambiguity.

## Output Contract

Prefer to save these artifacts per run:

- `run_summary.md`
- `environment.json`
- `read_plan.json`
- `data_profile.json`
- `cleaning_report.json`
- `stats_report.json`
- `model_report.json`
- `chart_plan.json`
- `business_report.json`

## Quality Gates

Do not advance to modeling until:

- join logic is understood
- the target variable is defined
- missingness is summarized
- duplicates are checked
- time leakage risks are reviewed for temporal tasks
- units and currency are confirmed for financial or business metrics

## Failure Conditions

Stop and report instead of improvising when:

- the data source is unavailable
- the grain is inconsistent with the question
- key packages are missing
- a claimed Excel size exceeds worksheet limits
- the target metric is not measurable from the available fields
