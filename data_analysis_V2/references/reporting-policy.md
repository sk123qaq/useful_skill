# Reporting Policy

## Allowed Narrative

Reporting must be constrained by `judgment_bundle.json`.

- `report_ready`: may describe measurable predictive utility
- `exploratory`: may describe patterns worth follow-up, but not operational readiness
- `not_usable`: must explicitly say the current result is not yet usable

## Forbidden Narrative

- causal wording from predictive features
- intervention advice from `post_outcome` or `hard_leakage` features
- claiming usefulness when the model fails the baseline gate
