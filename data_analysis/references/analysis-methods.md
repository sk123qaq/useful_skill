# Analysis Methods

## Scope

Use `scripts/analysis_methods.py` when the question is descriptive or diagnostic rather than predictive.

## Methods

- `cluster` / `clustering`: K-means baseline with silhouette-based cluster count selection, cluster profiles, and assignments.
- `apriori` / `association`: basket or co-occurrence analysis for transactions, item lists, or binary item flags.
- `anova`: one-way ANOVA when assumptions hold, with Kruskal-Wallis fallback when normality or equal-variance assumptions fail.
- `root-cause`: segment contribution analysis for additive KPI changes across periods, channels, regions, or other dimensions.

## Config Expectations

- clustering: `feature_cols` optional, `n_clusters` optional, `standardize` optional
- apriori: provide `items_col`, or `transaction_col + item_col`, or `item_indicator_cols`
- anova: require `target` and `group_col`
- root-cause: require `metric_col`; compare mode also needs `compare_col`, `baseline_value`, `current_value`, and usually `dimension_cols`

## Guardrails

- treat clustering as segmentation, not proof of naturally occurring classes
- keep Apriori to manageable item spaces; very wide baskets should be pruned first
- do not interpret ANOVA significance as business importance without effect size
- root-cause contribution is strongest for additive metrics such as revenue, cost, or conversions
