# Explainability

## Scope

Use the explainability layer for supervised tabular models after a valid classification or regression fit exists.

## Outputs

- native feature importance when the estimator exposes `feature_importances_` or `coef_`
- permutation importance on a holdout set
- partial dependence plots for the top continuous features with enough variation
- SHAP summary when the estimator and environment support it; prefer tree-specific explainers for tree models

## Guardrails

- do not interpret feature importance as causality
- prefer permutation importance over native importance when they disagree
- use PDP only for features with enough support and reasonable variation
- coerce mixed integer/boolean feature matrices to numeric form before SHAP or PDP
- treat SHAP as an explanatory aid, not as proof of mechanism
