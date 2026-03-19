# Formal Report Chart Governance Plan

**Goal:** Rework `data_analysis` so formal report body charts are chosen by audience needs and evidence quality rather than task defaults, rendered PNG filenames, or encoded model features.

**Primary policy:** Adopt an audience-first rule for formal report正文 charts.

- `management`: prioritize decision relevance, key evidence, and risk boundaries.
- `operator`: prioritize actionable segmentation, ranking, and intervention/supporting evidence.
- `analyst`: allow more technical explanation, but still prefer raw business concepts over encoded features.

**Non-goals:**
- Do not remove existing dashboard/process-report behavior in the first pass.
- Do not redesign every chart renderer before the governance layer exists.
- Do not require identical chart packs across sessions; allow controlled variation inside a constrained candidate pool.

## Success Criteria

- Formal report正文 charts can be traced back to raw business fields or explicit model-level evidence objects.
- The final report exporter consumes an explicit chart decision artifact instead of implicitly taking the first few PNGs.
- Agent second pass can vary chart choice and order within a governed candidate pool.
- One-hot derived features no longer enter正文 by default.
- Supervised, business, experiment, and causal tasks all expose chart candidates with body-vs-diagnostic intent.

## Design Principles

1. Separate `raw field semantics` from `model feature columns`.
2. Separate `chart intent` from `chart type`.
3. Separate `candidate generation` from `final body-chart selection`.
4. Let agents rank within allowed candidates, not invent arbitrary body charts.
5. Validate chart appropriateness, not just chart prose quality.

## Workstream 1: Define the New Data Contracts

**Files:**
- Update: [references/workflow.md](/Users/sk/program/useful_skill/data_analysis/references/workflow.md)
- Update: [references/chart-selection.md](/Users/sk/program/useful_skill/data_analysis/references/chart-selection.md)
- Update: [references/reporting.md](/Users/sk/program/useful_skill/data_analysis/references/reporting.md)
- Update: [references/report-delivery-templates-zh.md](/Users/sk/program/useful_skill/data_analysis/references/report-delivery-templates-zh.md)
- Create or document schema in: [scripts/common.py](/Users/sk/program/useful_skill/data_analysis/scripts/common.py)

**Add these artifacts:**
- `semantic_schema.json`
- `feature_lineage.json`
- `chart_candidates.json`
- `report_chart_decision.json`

**Required fields**

`semantic_schema.json`
- `field_name`
- `business_label`
- `role`: `target | time | dimension | measure`
- `semantic_type`: `binary | ordered_category | nominal_category | continuous`
- `report_priority`
- `allowed_chart_intents`
- `preferred_audiences`

`feature_lineage.json`
- `feature_name`
- `source_field`
- `derivation`
- `category_value`
- `is_model_internal`

`chart_candidates.json`
- `chart_id`
- `file`
- `chart_type`
- `chart_intent`
- `section_role`: `context | core_evidence | decision_support | risk_boundary | mechanism | diagnostic | appendix`
- `source_fields`
- `derived_features`
- `audience_fit`
- `diagnostic_only`
- `allow_in_formal_body`
- `evidence_links`
- `business_value_score`
- `suitability_score`

`report_chart_decision.json`
- `report_audience`
- `selected_chart_ids`
- `ordered_chart_ids`
- `selection_rationales`
- `rejected_high_ranked_chart_ids`
- `overall_chart_story`
- per-chart `interpretation`, `implication`, `caption_note`

## Workstream 2: Preserve Raw-Field Semantics Through the Pipeline

**Files:**
- Update: [scripts/feature_engineering.py](/Users/sk/program/useful_skill/data_analysis/scripts/feature_engineering.py)
- Update: [scripts/model_runner.py](/Users/sk/program/useful_skill/data_analysis/scripts/model_runner.py)
- Update: [scripts/common.py](/Users/sk/program/useful_skill/data_analysis/scripts/common.py)
- Update: [scripts/run_pipeline.py](/Users/sk/program/useful_skill/data_analysis/scripts/run_pipeline.py)

**Changes**
- Build `semantic_schema.json` immediately after data load.
- Extend feature engineering so encoded columns retain lineage to raw fields.
- Change model prep helpers to return feature lineage alongside transformed matrices.
- Replace hard-coded, dataset-specific label recovery with schema-backed labeling, while keeping heuristics as fallback only.
- Remove target-specific assumptions such as hard-coded `obese` summary access.

**Acceptance checks**
- For any one-hot column such as `age_group_80`, the pipeline can recover `source_field=age_group`.
- The report layer can ask whether a field is ordered, nominal, binary, or continuous without reverse-engineering feature names.

## Workstream 3: Introduce a Chart Candidate Layer

**Files:**
- Update: [scripts/explain_viz.py](/Users/sk/program/useful_skill/data_analysis/scripts/explain_viz.py)
- Update: [scripts/model_explainability.py](/Users/sk/program/useful_skill/data_analysis/scripts/model_explainability.py)
- Update: [scripts/run_pipeline.py](/Users/sk/program/useful_skill/data_analysis/scripts/run_pipeline.py)
- Update task-specific producers as needed in later workstreams

**Changes**
- Replace the current “task -> planned chart types” logic with “task + semantics -> chart intents -> candidate charts”.
- Keep `chart_plan.json` for backward compatibility, but generate it from `chart_candidates.json`.
- Downgrade `_choose_pdp_features()` from a report-default selector to an explainability helper.
- Make PDP body eligibility explicit:
  - allowed only for raw continuous fields or natural binary fields
  - disallowed for one-hot derived features by default
  - disallowed when a more readable raw-field comparison chart exists

**Acceptance checks**
- Classification/regression runs produce both:
  - raw-field body candidates
  - technical diagnostic candidates
- `chart_candidates.json` includes audience fit and section role per chart.

## Workstream 4: Redesign the Formal Report Selection Flow

**Files:**
- Update: [scripts/formal_report_export.py](/Users/sk/program/useful_skill/data_analysis/scripts/formal_report_export.py)
- Update: [scripts/full_process_report_export.py](/Users/sk/program/useful_skill/data_analysis/scripts/full_process_report_export.py)
- Update: [scripts/report_export.py](/Users/sk/program/useful_skill/data_analysis/scripts/report_export.py)

**Changes**
- Stop choosing正文 charts from “all PNGs sorted by filename metadata”.
- Read `chart_candidates.json` and build a governed candidate pool.
- Replace `chart_review.json` as the only second-pass contract with `report_chart_decision.json` plus chart prose.
- Let the agent decide among allowed candidates for the chosen audience.
- Keep dashboard/process report permissive; only formal report正文 uses strict governance.

**Audience-first rules**

`management`
- include charts that support decision, priority, and risk boundary
- exclude charts that only explain model internals unless they materially change confidence

`operator`
- include segmentation, ranking, funnel/drop-off, uplift, subgroup, and intervention-relevant charts
- exclude charts that are technically correct but not action-guiding

`analyst`
- allow limited diagnostic charts when they clarify uncertainty or mechanism
- still prefer raw-field views before encoded-feature views

**Acceptance checks**
- The second-pass agent can change chart inclusion and order.
- The final exporter refuses to render正文 without a valid chart decision artifact.

## Workstream 5: Add Validation for Reasonableness

**Files:**
- Update: [scripts/formal_report_export.py](/Users/sk/program/useful_skill/data_analysis/scripts/formal_report_export.py)
- Update: [references/report-delivery-templates-zh.md](/Users/sk/program/useful_skill/data_analysis/references/report-delivery-templates-zh.md)

**New validation rules**
- Every body chart must have a raw field or explicit model-evidence source.
- `diagnostic_only=true` charts cannot enter正文.
- Multiple正文 charts from the same `source_field` require explicit justification.
- Chart choice must fit the declared audience.
- Narrative text must match the chart’s declared `chart_intent` or `section_role`.
- Body charts must cover:
  - main evidence
  - at least one context or risk boundary need
- Selected charts must exist in the current run directory and match current candidate metadata.

## Workstream 6: Upgrade Task-Specific Producers

**Files:**
- Update: [scripts/business_templates.py](/Users/sk/program/useful_skill/data_analysis/scripts/business_templates.py)
- Update: [scripts/experiment_analysis.py](/Users/sk/program/useful_skill/data_analysis/scripts/experiment_analysis.py)
- Update: [scripts/analysis_methods.py](/Users/sk/program/useful_skill/data_analysis/scripts/analysis_methods.py)
- Update: [scripts/causal_analysis.py](/Users/sk/program/useful_skill/data_analysis/scripts/causal_analysis.py)
- Update: [scripts/clean_preprocess.py](/Users/sk/program/useful_skill/data_analysis/scripts/clean_preprocess.py)
- Update: [scripts/eda_stats.py](/Users/sk/program/useful_skill/data_analysis/scripts/eda_stats.py)

**Task-specific priorities**

Business tasks
- Funnel: distinguish `cumulative_step_reach` from `terminal_stage_distribution`
- Retention: make retention rate the body default, not active-user counts
- LTV: compare same-age cohorts for正文
- Monetization: add concentration candidates such as top-decile share / Lorenz-style view

Experiment
- emit first-class chart candidates for primary metric with CI, SRM, guardrails, CUPED/sequential context

Clustering / ANOVA / Root cause
- clustering body default should be cluster profile, not PCA projection
- ANOVA should emit group comparison charts tied to the statistical question
- root cause should emit diverging positive/negative contribution views

Causal / uplift / heterogeneity
- body defaults should prefer validity and actionability:
  - DID trend over simple 2x2 means when time series exists
  - RD binned means over raw scatter
  - balance/overlap + treatment effect over score histograms
  - uplift bucket lift and subgroup effect ranking over raw distributions

EDA / data quality
- produce context/risk candidates, not just machine-readable JSON

## Rollout Order

### Phase 1: Contracts and compatibility
- Add schemas and new JSON artifacts.
- Keep existing exporters working.

### Phase 2: Candidate generation
- Start emitting `chart_candidates.json`.
- Keep `chart_plan.json` as a backward-compatible projection.

### Phase 3: Formal report governance
- Introduce `report_chart_decision.json`.
- Switch formal report正文 to governed selection.

### Phase 4: Task upgrades
- Improve business, experiment, non-supervised, and causal chart candidates.

### Phase 5: Cleanup
- Remove filename-specific special cases once schema-backed chart governance is complete.

## Test Plan

- Golden-path supervised sample:
  - ensure正文 prefers raw-field charts over one-hot PDPs
- Golden-path business sample:
  - ensure retention正文 uses retention rate
- Golden-path experiment sample:
  - ensure primary metric + CI + SRM candidates exist
- Golden-path causal sample:
  - ensure validity-first candidates are available
- Regression tests:
  - old dashboard still renders
  - process report still shows full artifact gallery
  - draft/final chart review flow still works

## Implementation Notes

- Preserve low-risk heuristics:
  - limit the number of explainability charts
  - prefer permutation importance over model-native importance for candidate shortlisting
  - keep graceful fallback when plotting libraries are missing
  - keep Chinese font configuration
- Do not encode audience policy as a fixed chart-count quota.
- Diversity should come from agent ranking inside an eligible set, not from unconstrained free choice.
