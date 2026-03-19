# BRFSS 2024 Obesity Predictive Analysis

## Evidence Grade

report-ready

## Safe Summary

Predictive signal cleared the configured gates and can be reported with evidence-safe language. Best model observed: logistic_regression.

## Claims

- [exploratory] Workflow routed to `predictive`.
- [exploratory] Dataset contains 60000 rows across 18 columns.
- [report-ready] logistic_regression beat the best dummy baseline on accuracy.
- [exploratory] Top features describe predictive reliance only and do not imply causality.

## Guardrails

- Do not turn predictive features into causal recommendations.
- Do not exceed the maximum evidence grade.
- State blockers plainly when the run is exploratory or not usable.
