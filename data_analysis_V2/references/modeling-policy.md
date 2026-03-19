# Modeling Policy

## Baseline First

For predictive work:
- always run dummy baselines first
- always run linear or generalized linear baselines next
- only then consider stronger tree-based models

## Allowed Phase 1 Ladder

Classification:
- `dummy_most_frequent`
- `logistic_regression`
- `random_forest_classifier`

Regression:
- `dummy_mean`
- `dummy_median`
- `linear_regression`
- `random_forest_regressor`

## Escalation Rules

- If the best non-dummy model does not clearly beat the best dummy baseline, downgrade the run.
- If variance across folds is high, downgrade the run even if the mean looks good.
- Do not turn interpretability output into causal advice.
- If the agent requests `tune_models`, move to monitored tuning rather than repeating the same baseline ladder.
- For classification tuning, compare candidates with richer metrics such as `balanced_accuracy`, `roc_auc`, and `average_precision`, then review threshold trade-offs before any report continuation.
