# Statistics And Tests

## Quick Selection

- compare 2 independent numeric groups: t-test, or Mann-Whitney if assumptions fail
- compare 3 or more groups: ANOVA, or Kruskal-Wallis if assumptions fail
- compare proportions: chi-square or Fisher's exact test
- measure correlation: Pearson or Spearman
- test distribution normality: Shapiro-Wilk or D'Agostino
- test time-series stationarity: ADF
- test heteroskedasticity: Breusch-Pagan or White test

## Always Check

- sample size
- missingness
- outliers
- normality for parametric summaries
- independence assumptions
- variance homogeneity for ANOVA and classic t-tests
- whether the KPI is additive before doing root-cause contribution decomposition
- whether the design identifies a causal effect or only an association

## Reporting

Report:

- test name
- null and alternative
- p-value
- effect size when available
- confidence interval when available
- business interpretation
- practical significance
