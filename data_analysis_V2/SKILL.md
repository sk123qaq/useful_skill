---
name: data-analysis-v2
description: Agent-first structured data analysis skill for CSV/Excel/Parquet/JSON/SQL sources. Use when the user needs descriptive analysis, predictive modeling, causal triage, or an honest stop-and-report path with baseline-first gates, monitored training jobs, and evidence-safe reporting.
---

# Data Analysis V2

This skill is the V2 contract for structured data analysis. The agent owns analytical judgment; scripts perform bounded, deterministic execution. V2 is designed to prevent overclaiming, especially in supervised modeling.

## When To Use

Use this skill when the task involves:
- tabular files or SQL queries
- descriptive analysis with explicit metrics or slices
- supervised prediction with a defined target
- causal triage where the user is asking why something changed or whether an intervention worked
- evidence-gated reporting where weak results must stay weak

Do not use this skill as the default path for:
- pure NLP or computer vision work
- distributed Spark pipelines
- deep learning by default
- “just give me business recommendations” when no analysis contract exists

## Routing Contract

Before running scripts, write an explicit analysis contract with:
- the user’s decision question
- data source and unit of analysis
- target column if predictive work is requested
- time column if time order matters
- success criteria and constraints

Then route into one of four flows:
- `descriptive`: summaries, distributions, segmentation, diagnostics
- `predictive`: classification or regression with baseline ladder and hard gates
- `causal`: causal triage only when the question is intervention-oriented
- `stop_and_report`: missing target, hard leakage, or unsafe evidence conditions

If the contract is underspecified, stop and surface the blocker instead of guessing.

## Workflow

1. Read [references/workflow.md](references/workflow.md) for the state machine and artifact contract.
2. Run `python3.13 data_analysis_V2/scripts/check_environment.py` if environment viability is unknown.
3. Use scout audit and route logic before any modeling.
4. For predictive work, stop after scout and generate `judgment_context_after_scout.{json,md}`.
5. Before any continue flag is used, the agent must read the judgment context and write `data_processing_decision.json`. The decision must be grounded in analysis findings such as duplicates, missingness, target balance, field risk, and candidate features.
6. Run the baseline ladder only if that agent decision explicitly allows continuation.
7. After baseline, generate `judgment_context_after_baseline.{json,md}` and require the agent to write `modeling_decision.json` from a whole-run perspective before continuing.
8. Apply gate review and evidence grading before explainability or report export.
9. Export only report-safe claims; weak runs must remain `exploratory` or `not_usable`.

If data issues are found after scout, the agent should call deterministic helper scripts before continuing, for example:
- `python3.13 data_analysis_V2/scripts/column_profile.py --input-path ... --output-path ... --target ...`
- `python3.13 data_analysis_V2/scripts/prepare_modeling_dataset.py --input-path ... --output-path ... --summary-path ... --target ... --deduplicate --drop-features ...`
  This helper de-duplicates both before and after feature pruning so the final modeling table is validated in the same column space that will be modeled.

If the baseline checkpoint ends with `tune_models`, the agent should call deterministic modeling helpers before any report continuation:
- `python3.13 data_analysis_V2/scripts/optimize_runner.py --input-path ... --output-dir ... --target ... --task classification`
- `python3.13 data_analysis_V2/scripts/classification_threshold_review.py --input-path ... --output-dir ... --target ... --model-name logistic_regression_balanced_c1`
  These scripts compare tuned candidates with richer metrics such as `balanced_accuracy`, `roc_auc`, and `average_precision`, then review operating thresholds before the agent makes another modeling decision.

## References

Load these on demand:
- [references/workflow.md](references/workflow.md): end-to-end state machine and checkpoints
- [references/modeling-policy.md](references/modeling-policy.md): baseline ladder and modeling escalation
- [references/monitoring-protocol.md](references/monitoring-protocol.md): heartbeat, stalls, failure handling
- [references/reporting-policy.md](references/reporting-policy.md): evidence-safe language rules
- [references/gate-rules.md](references/gate-rules.md): hard gates and downgrade policy
- [references/artifact-schemas.md](references/artifact-schemas.md): required JSON artifact shapes
- [references/failure-recovery.md](references/failure-recovery.md): honest failure and resume guidance

## Core Commands

```bash
python3.13 data_analysis_V2/scripts/check_environment.py
python3.13 data_analysis_V2/scripts/column_profile.py --help
python3.13 data_analysis_V2/scripts/prepare_modeling_dataset.py --help
python3.13 data_analysis_V2/scripts/optimize_runner.py --help
python3.13 data_analysis_V2/scripts/classification_threshold_review.py --help
python3.13 data_analysis_V2/scripts/run_pipeline_v2.py --help
pytest data_analysis_V2/tests -q
```

## Guardrails

- No predictive narrative without a baseline comparison.
- No “best model” language unless gates allow it.
- No recommendation sourced from `post_outcome` or `hard_leakage` features.
- No silent long-running jobs; monitored work must emit heartbeat.
- No final report without `gate_review.json` and `judgment_bundle.json`.
- No checkpoint decision should be made from code execution trivia alone; agent review must be grounded in accumulated data-analysis findings.
