# Causal Inference

## Scope

Use `scripts/causal_analysis.py` when the user is trying to estimate the effect of an action, intervention, or policy rather than just describe or predict outcomes.
Use `scripts/causal_narrative.py` when the user needs a stakeholder-facing explanation that turns causal estimates into question, design, assumptions, diagnostics, business interpretation, risks, and recommendation.

## Supported Methods

- `did`: difference-in-differences for treatment/control x pre/post designs, with optional robust OLS interaction estimates
- `rd`: regression discontinuity for cutoff-based policies or eligibility rules
- `synthetic-control`: weighted donor construction for a single treated unit with pre/post trajectories
- `iv`: two-stage least squares with first-stage, reduced-form, and weak-instrument diagnostics
- `dml`: partially linear double machine learning with cross-fitted nuisance models and orthogonal residual regression
- `dr`: doubly robust / AIPW estimation with cross-fitted nuisance models and overlap diagnostics
- `psm`: propensity score matching for observational data with overlap and balance diagnostics
- `orthogonal`: orthogonal learner with cross-fitted nuisance models and weighted pseudo-outcome regression
- `uplift`: model-based treatment heterogeneity / uplift scoring with subgroup summaries
- `cate`: meta-learner comparison for conditional average treatment effects, currently with `s_learner` and `t_learner`
- `causal`: run multiple causal methods and collect a single report

## Reporting

- save the machine-readable output in `causal_report.json`
- also render `causal_narrative_report.md` and `causal_narrative_report.json` for business-facing delivery
- narrative output should state assumptions and diagnostics explicitly; never present a causal coefficient without that context

## Config Expectations

- DID: `outcome_col`, `treatment_col`, and either `post_col` or `period_col` + `pre_value` / `post_value`
- RD: `outcome_col`, `running_col`, `cutoff`; `bandwidth`, `covariate_cols`, and `treatment_col` optional
- Synthetic control: `unit_col`, `time_col`, `outcome_col`, `treated_unit`, and `intervention_time` or `post_col`
- IV: `outcome_col`, `treatment_col`, `instrument_col`; `covariate_cols` optional
- DML: `treatment_col`, `outcome_col`, `covariate_cols`; current implementation is for continuous outcomes
- DR: `treatment_col`, `outcome_col`, `covariate_cols`; `heterogeneity_cols` optional
- PSM: `treatment_col`, `outcome_col`, `covariate_cols`
- Orthogonal learner: `treatment_col`, `outcome_col`, `feature_cols` or `covariate_cols`; `heterogeneity_cols` optional
- Uplift: `treatment_col`, `outcome_col`, `feature_cols` or `covariate_cols`; `heterogeneity_cols` optional
- CATE: `treatment_col`, `outcome_col`, `feature_cols` or `covariate_cols`; `heterogeneity_cols` optional
- Causal suite: `methods` plus per-method sub-configs under `did`, `rd`, `synthetic-control`, `iv`, `dml`, `dr`, `psm`, `orthogonal`, `uplift`, and `cate`

## Guardrails

- do not present causal estimates without stating identifying assumptions
- use DID only when a parallel-trends story is defensible
- use RD only when units cannot precisely manipulate the running variable around the cutoff, and inspect local covariate continuity rather than relying on raw mean differences alone
- use synthetic control only when the donor pool can reproduce the treated unit well before treatment
- treat IV as unreliable when the first stage is weak or the exclusion restriction is not defensible
- use DML only when the treatment residual still has enough variance after orthogonalization
- use doubly robust estimators only when overlap is adequate and nuisance models are reasonable
- use PSM only when common support exists and balance improves after matching
- treat orthogonal-learner pseudo-outcomes as noisy training targets, not directly interpretable business effects
- treat uplift as treatment-effect prioritization, not proof of mechanism
- treat meta-learner CATE disagreement as model uncertainty, not as a reason to cherry-pick one estimate
- do not control for post-treatment variables
