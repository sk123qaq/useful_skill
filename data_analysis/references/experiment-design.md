# Experiment Design

## Before Running The Test

- define primary metric
- define guardrail metrics
- define randomization unit
- define exposure rules
- define observation window
- define stopping rule

## During Analysis

- check sample ratio mismatch
- compare treatment and control balance
- report absolute lift and relative lift
- report significance and effect size separately
- check business significance, not p-value only

## Supported Execution Contract

Use `scripts/experiment_analysis.py` or `scripts/run_pipeline.py --task experiment` with a config like:

```json
{
  "group_col": "variant",
  "control": "control",
  "treatment": "treatment",
  "expected_allocation": {
    "control": 0.5,
    "treatment": 0.5
  },
  "metrics": [
    {"name": "converted", "type": "binary", "role": "primary", "success_value": 1, "preferred_direction": "increase", "practical_significance": 0.02},
    {"name": "revenue", "type": "continuous", "role": "secondary", "preferred_direction": "increase", "cuped_covariate": "pre_revenue"},
    {"name": "refund", "type": "binary", "role": "guardrail", "success_value": 1, "preferred_direction": "decrease"}
  ],
  "covariates": ["pre_sessions", "device"],
  "multiple_testing": {"method": "holm", "metric_names": ["converted", "revenue", "refund"]},
  "sequential_monitoring": {"method": "obrien_fleming", "current_look": 3, "total_looks": 5, "metric_names": ["converted", "revenue"]},
  "power_analysis": {"power": 0.8, "metric_names": ["converted", "revenue"], "mde": {"converted": 0.03, "revenue": 10}},
  "alpha": 0.05
}
```

The current implementation supports:

- two-arm experiments only
- binary metrics through two-sample proportion z-tests
- continuous metrics through Welch t-tests
- optional `CUPED` for continuous metrics through `cuped_covariate`
- categorical balance checks through chi-square tests
- SRM detection through chi-square goodness-of-fit
- optional multiple-testing correction through `bonferroni`, `holm`, or `fdr_bh`
- optional sequential monitoring through `bonferroni`, `pocock`, or `obrien_fleming`
- optional power / sample-size estimation for binary and continuous metrics

## Common Pitfalls

- peeking and early stopping without correction
- mixing exposure units and analysis units
- treatment contamination
- using post-treatment variables as controls
- interpreting noisy subgroup cuts as facts
