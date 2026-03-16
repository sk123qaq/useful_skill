# Model Selection

## Baseline First

Use the lightest method that can answer the question:

1. descriptive summary
2. statistical test
3. simple rule-based or benchmark baseline
4. classical machine learning
5. advanced time-series or deep learning

## Time-Series Rules

- start with naive and seasonal-naive baselines
- then consider ARIMA / SARIMA
- treat Prophet as an optional baseline, not the default answer
- use boosted trees or tabular ML only after feature engineering is defined
- use LSTM only when sequence dependence is material and simpler baselines fail

## Tabular ML Rules

- classification: logistic regression or tree baseline first, then random forest or boosting
- regression: linear or tree baseline first, then ensemble methods
- clustering: K-means baseline first, then density or hierarchical methods if justified
- association rules: Apriori baseline first for basket-style data; only move to heavier graph or embedding methods if baskets are wide and sparse
- diagnostic group comparisons: one-way ANOVA first when assumptions hold, otherwise Kruskal-Wallis
- root-cause: start with additive segment contribution before regression-based attribution
- causal effect estimation: randomized experiments first, then DID or PSM when the design assumptions are defensible

## Validation Rules

- random split is acceptable only for i.i.d. tabular problems
- use `TimeSeriesSplit` or rolling windows for temporal tasks
- evaluate leakage risk before feature generation
