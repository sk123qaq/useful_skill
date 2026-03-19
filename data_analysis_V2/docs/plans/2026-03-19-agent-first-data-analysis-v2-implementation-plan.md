# Data Analysis V2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an agent-first `data_analysis_V2` skill for Claude Code / Codex style environments where the LLM owns analytical judgment, Python scripts act as deterministic tools, model training is observable, and reports are gated by evidence quality instead of auto-generated optimism.

**Architecture:** `data_analysis_V2` should be a layered skill. `SKILL.md` defines the contract and routing rules. `references/` encodes modeling, monitoring, reporting, and gate policies. `scripts/` provides deterministic execution units with structured artifacts. The orchestrator coordinates state transitions and asks tools for bounded work, but it must not silently turn weak modeling output into strong business advice.

**Tech Stack:** Python 3.13, `pandas`, `numpy`, `scikit-learn`, `scipy`, `duckdb`, `matplotlib`, `seaborn`, optional `xgboost`, optional `lightgbm`, `pydantic` or dataclass-based schemas, `joblib`, `logging`, `tqdm`, Markdown + JSON artifacts.

---

## Scope

### In Scope

- Structured data analysis for tabular files and SQL sources
- Agent-guided problem definition, routing, and model selection
- Baseline-first classification and regression
- Explicit escalation from sklearn-compatible models to custom code
- Long-running model monitoring with heartbeat and stall detection
- Hard gates for baseline, stability, feature risk, and reporting
- Evidence-graded reporting and report-safe language controls

### Out of Scope for V2 Phase 1

- Full parity with every V1 business template before core architecture is stable
- Spark / distributed workloads
- Deep learning as a default modeling path
- Automatic dependency installation during normal runs
- Auto-deployment or online serving

## Primary Design Principles

1. Agent decides; scripts execute.
2. No modeling without an explicit problem contract.
3. No “best model” claim without a baseline ladder.
4. No business recommendation without passing report gate.
5. No silent long-running jobs; every heavy step must emit heartbeat.
6. No SHAP-based causal storytelling.
7. Weak results must remain weak in the final report.

## Target Directory Structure

The V2 skill should use this structure:

```text
data_analysis_V2/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── references/
│   ├── workflow.md
│   ├── modeling-policy.md
│   ├── monitoring-protocol.md
│   ├── reporting-policy.md
│   ├── gate-rules.md
│   ├── artifact-schemas.md
│   └── failure-recovery.md
├── scripts/
│   ├── common.py
│   ├── schemas.py
│   ├── check_environment.py
│   ├── run_pipeline_v2.py
│   ├── orchestrator.py
│   ├── route_problem.py
│   ├── scout_audit.py
│   ├── feature_risk_audit.py
│   ├── model_catalog.py
│   ├── baseline_runner.py
│   ├── optimize_runner.py
│   ├── monitored_job.py
│   ├── gate_evaluator.py
│   ├── evidence_grader.py
│   ├── explainability_guarded.py
│   ├── report_bundle_builder.py
│   └── formal_report_export_v2.py
├── templates/
│   ├── analysis-report-docx-template.md
│   └── analysis-report-pdf-template.md
├── tests/
│   ├── fixtures/
│   ├── test_route_problem.py
│   ├── test_baseline_runner.py
│   ├── test_monitored_job.py
│   ├── test_gate_evaluator.py
│   ├── test_evidence_grader.py
│   └── test_report_bundle_builder.py
└── docs/
    └── plans/
```

## Core Runtime States

The orchestrator must manage an explicit state machine:

1. `initialized`
2. `contract-defined`
3. `scout-running`
4. `scout-completed`
5. `route-decided`
6. `awaiting-model-confirmation`
7. `baseline-running`
8. `baseline-completed`
9. `optimization-running`
10. `gate-review`
11. `report-ready`
12. `completed`
13. `failed`
14. `stalled`

Every state transition must be written to `run_status.json` with:

- `state`
- `updated_at`
- `task_type`
- `current_step`
- `current_artifact`
- `last_message`
- `blocking_reason`

## Required Artifacts

Every supervised run must produce these artifacts before report export:

- `analysis_contract.json`
- `data_health_report.json`
- `route_decision.json`
- `feature_risk_report.json`
- `baseline_results.json`
- `optimization_log.json`
- `job_status.json`
- `job_status.jsonl`
- `gate_review.json`
- `judgment_bundle.json`
- `claim_registry.json`
- `report_context.json`
- `run_summary.md`

### Artifact Intent

`analysis_contract.json`
- Captures what question we are answering, why, and under what decision constraints.

`route_decision.json`
- Captures why the agent chose descriptive, predictive, causal, or “stop and report limitations”.

`feature_risk_report.json`
- Captures leakage, proxy, post-outcome, and collection-artifact risk by field.

`gate_review.json`
- Captures pass/fail plus rationale for every hard gate.

`judgment_bundle.json`
- Captures the safe conclusion language the report layer is allowed to use.

`claim_registry.json`
- Captures every reportable claim with evidence type and evidence grade.

## Problem Contract Schema

`analysis_contract.json` should include:

- `business_question`
- `task_type_candidate`
- `decision_use_case`
- `success_metric_primary`
- `success_metric_secondary`
- `error_cost_profile`
- `minimum_acceptable_performance`
- `target_field`
- `entity_grain`
- `time_scope`
- `data_scope`
- `sampling_strategy`
- `known_risk_fields`
- `forbidden_claim_types`
- `allowed_output_levels`

### Required Decision Use Cases

- `descriptive_insight`
- `risk_ranking`
- `screening`
- `resource_allocation`
- `forecasting`
- `causal_decision_support`
- `exploration_only`

## Routing Rules

`route_problem.py` must never treat “has target column” as sufficient to start predictive modeling.

### Predictive Route Allowed Only If

- target exists
- target is meaningfully defined
- success metric is explicit
- business use case is predictive rather than purely descriptive
- leakage/post-outcome audit does not immediately invalidate the setup

### Causal Route Required If

- user asks whether intervention causes outcome
- proposed recommendation depends on “what changes outcome”
- top candidate variables are likely consequences or proxies of the outcome

### Stop-and-Report Route Required If

- sample size is too small for the requested split strategy
- target definition is unstable or ambiguous
- baseline cannot exceed trivial benchmark
- feature risk is severe and unresolved

## Baseline Ladder

All supervised modeling must follow an ordered ladder.

### Classification Ladder

Level 0:
- `DummyClassifier(strategy="most_frequent")`
- `DummyClassifier(strategy="stratified")`

Level 1:
- `LogisticRegression`
- `RidgeClassifier` if appropriate

Level 2:
- `RandomForestClassifier`
- `HistGradientBoostingClassifier`

Level 3:
- `XGBoostClassifier` if installed and justified
- `LGBMClassifier` if installed and justified

Level 4:
- custom code only with explicit `custom_model_justification.md`

### Regression Ladder

Level 0:
- `DummyRegressor(strategy="mean")`
- `DummyRegressor(strategy="median")`

Level 1:
- `LinearRegression`
- `Ridge`
- `Lasso`

Level 2:
- `RandomForestRegressor`
- `HistGradientBoostingRegressor`

Level 3:
- `XGBoostRegressor`
- `LGBMRegressor`

Level 4:
- custom objective or custom model only with justification artifact

## Custom Code Escalation Rules

Custom modeling code is allowed only when at least one condition holds:

- the data structure is not well served by sklearn estimators
- the loss function must reflect asymmetric business cost not achievable with thresholding or sample weights
- the workflow requires multi-stage estimation not available in the standard catalog
- the model must support domain-specific constraints that existing libraries cannot express cleanly

Before custom code starts, the run must write `custom_model_justification.md` containing:

- why sklearn-level tools are insufficient
- what new capability is required
- expected extra risk
- rollback path if the custom implementation fails

## Monitoring Protocol

Heavy steps must be observable both by the user and the agent.

### Required Monitoring Outputs

`job_status.json`
- latest snapshot

`job_status.jsonl`
- append-only event stream

### Required Fields

- `job_id`
- `state`
- `stage`
- `current_model`
- `current_trial`
- `current_fold`
- `current_epoch`
- `heartbeat_at`
- `started_at`
- `elapsed_seconds`
- `last_event`
- `warning_count`
- `error_count`
- `artifacts_written`

### Required States

- `queued`
- `running`
- `completed`
- `failed`
- `stalled`
- `cancelled`

### Stall Detection

`monitored_job.py` should mark a job as `stalled` when:

- no heartbeat is written within 2x expected heartbeat interval, or
- process is still alive but stdout/stderr and status files are unchanged beyond threshold

### Console Logging Rules

Every long step must log:

- start line with timestamp
- periodic heartbeat
- finish line with duration
- failure line with traceback path

Example checkpoints:

- data loaded
- feature matrix built
- baseline level started
- fold `k/n`
- optimization trial started
- explainability started
- gate evaluation started

## Hard Gates

`gate_evaluator.py` must implement four independent gates.

### 1. Baseline Gate

Purpose:
- prevent “worse than trivial” or “barely above trivial” models from being narrated as useful.

Classification checks:
- compare primary metric against best dummy baseline
- compare against best linear baseline
- compare against majority-class accuracy for context only, not as sole criterion
- require minimum delta over dummy on primary metric

Default fail rules:
- primary metric does not beat best dummy by configured `min_delta`
- precision/recall tradeoff violates the declared error cost profile
- top-k retrieval is poor for ranking use case

Regression checks:
- R2 near or below 0
- error not meaningfully better than mean/median baseline

### 2. Stability Gate

Purpose:
- prevent unstable CV results from being narrated as reliable.

Checks:
- fold count validity
- fold-level metric dispersion
- minimum positives per fold for classification
- train/validation gap if holdout exists
- repeated-seed consistency for small samples

Default fail rules:
- too few positive examples per fold
- metric standard deviation above threshold
- strong variance across seeds

### 3. Feature Risk Gate

Purpose:
- prevent high-risk variables from being treated as intervention levers.

Checks:
- leakage flags
- post-outcome flags
- proxy variables
- collection-artifact variables
- suspicious target-derived transformations

Default fail rules:
- any top-ranked feature labeled `hard_leakage`
- more than configured share of top features labeled `post_outcome`
- report tries to convert risky feature into causal recommendation

### 4. Report Gate

Purpose:
- map modeling evidence to allowed report language.

Allowed evidence grades:
- `unusable`
- `exploratory`
- `directional`
- `ranking_candidate`
- `pilot_candidate`

Default mapping:
- any failed gate -> at most `exploratory`
- baseline pass only -> at most `directional`
- baseline + stability pass -> at most `ranking_candidate`
- baseline + stability + feature risk pass and business metric threshold met -> `pilot_candidate`

## Evidence and Claim Model

`claim_registry.json` should be the truth source for report claims.

Each claim must include:

- `claim_id`
- `claim_text`
- `claim_type`: `descriptive | predictive | causal | data_quality | operational`
- `evidence_type`: `summary_stat | cv_metric | ranking_metric | explainability | causal_estimate | audit_flag`
- `evidence_grade`
- `source_artifacts`
- `safe_for_management_summary`
- `forbidden_expansions`

### Non-Negotiable Reporting Rules

- SHAP or feature importance may support “model relied on X”, never “changing X will change Y”.
- A model that fails baseline or stability gate cannot be described as “可用于分层”.
- If evidence grade is `exploratory`, final recommendation language must remain exploratory.
- Report exporter may not synthesize stronger claims than those present in `judgment_bundle.json`.

## Reporting Bundle

`report_bundle_builder.py` must compile:

- `judgment_bundle.json`
- `claim_registry.json`
- `report_context.json`
- `report_summary.md`

`formal_report_export_v2.py` must consume only those artifacts.

The exporter must not:

- infer usability from raw metric thresholds alone
- invent recommendations based on top features
- auto-upgrade weak results into business advice

## Implementation Tasks

### Task 1: Create the V2 Skeleton and Skill Contract

**Files:**
- Create: `data_analysis_V2/SKILL.md`
- Create: `data_analysis_V2/agents/openai.yaml`
- Create: `data_analysis_V2/references/workflow.md`
- Create: `data_analysis_V2/references/modeling-policy.md`
- Create: `data_analysis_V2/references/monitoring-protocol.md`
- Create: `data_analysis_V2/references/reporting-policy.md`
- Create: `data_analysis_V2/references/gate-rules.md`
- Create: `data_analysis_V2/references/artifact-schemas.md`
- Create: `data_analysis_V2/references/failure-recovery.md`

**Step 1**
- Write `SKILL.md` as a concise contract.
- It must explain when to route to descriptive, predictive, causal, or stop-and-report flows.

**Step 2**
- Write reference docs with progressive disclosure.
- Keep `SKILL.md` lean; move detailed gate and monitoring rules into `references/`.

**Verification**
- `SKILL.md` remains under 500 lines.
- `openai.yaml` matches the skill’s actual trigger conditions.

### Task 2: Define Shared Schemas and Core Utilities

**Files:**
- Create: `data_analysis_V2/scripts/common.py`
- Create: `data_analysis_V2/scripts/schemas.py`

**Step 1**
- Define shared output helpers, timestamp helpers, JSONL append helpers, and structured status writers.

**Step 2**
- Define schema validators for:
  - `analysis_contract`
  - `route_decision`
  - `feature_risk_report`
  - `baseline_results`
  - `gate_review`
  - `judgment_bundle`
  - `claim_registry`

**Verification**
- `python3.13 -m py_compile data_analysis_V2/scripts/common.py data_analysis_V2/scripts/schemas.py`
- schema validation fails on malformed fixtures and passes on valid ones

### Task 3: Implement the Problem Router and Scout Audit

**Files:**
- Create: `data_analysis_V2/scripts/route_problem.py`
- Create: `data_analysis_V2/scripts/scout_audit.py`
- Create: `data_analysis_V2/scripts/feature_risk_audit.py`
- Test: `data_analysis_V2/tests/test_route_problem.py`

**Step 1**
- Build scout audit for row count, missingness, duplicates, target distribution, cardinality, and suspicious fields.

**Step 2**
- Build route decision logic that can return:
  - `descriptive`
  - `predictive`
  - `causal`
  - `stop_and_report`

**Step 3**
- Build feature risk audit with field labels:
  - `safe`
  - `soft_proxy`
  - `post_outcome`
  - `hard_leakage`
  - `collection_artifact`

**Verification**
- route tests cover at least:
  - missing target definition
  - clear descriptive-only question
  - predictive question with valid target
  - causal question requiring causal route
  - hard leakage causing stop-and-report

### Task 4: Build the Baseline Ladder

**Files:**
- Create: `data_analysis_V2/scripts/model_catalog.py`
- Create: `data_analysis_V2/scripts/baseline_runner.py`
- Test: `data_analysis_V2/tests/test_baseline_runner.py`

**Step 1**
- Implement explicit model ladder and level metadata.

**Step 2**
- Ensure level 0 and level 1 always run before heavier models.

**Step 3**
- Persist fold-level metrics, mean metrics, and standard deviations.

**Verification**
- classification run output includes dummy and linear baselines before tree models
- regression run output includes mean/median dummy and linear baselines
- tests confirm model ordering is deterministic

### Task 5: Build Monitored Execution

**Files:**
- Create: `data_analysis_V2/scripts/monitored_job.py`
- Create: `data_analysis_V2/scripts/optimize_runner.py`
- Test: `data_analysis_V2/tests/test_monitored_job.py`

**Step 1**
- Create a monitored job wrapper for long-running tasks.

**Step 2**
- Add heartbeat writes and append-only event logs.

**Step 3**
- Add stall detection and failure surface standardization.

**Verification**
- synthetic slow job writes heartbeat at configured interval
- synthetic stalled job transitions to `stalled`
- failed job writes traceback path and final status

### Task 6: Implement Gate Evaluation

**Files:**
- Create: `data_analysis_V2/scripts/gate_evaluator.py`
- Create: `data_analysis_V2/scripts/evidence_grader.py`
- Test: `data_analysis_V2/tests/test_gate_evaluator.py`
- Test: `data_analysis_V2/tests/test_evidence_grader.py`

**Step 1**
- Encode baseline, stability, feature risk, and report gates.

**Step 2**
- Convert gate outcomes into evidence grades.

**Step 3**
- Ensure failed gates downgrade report language.

**Verification**
- a model weaker than dummy fails baseline gate
- a highly variable CV result fails stability gate
- a report with risky top features fails feature risk gate
- evidence grade cannot exceed gate-allowed maximum

### Task 7: Guard Explainability

**Files:**
- Create: `data_analysis_V2/scripts/explainability_guarded.py`

**Step 1**
- Build explainability output that preserves field lineage.

**Step 2**
- Add safe phrasing metadata:
  - `predictive_reliance_statement`
  - `not_a_causal_claim`

**Step 3**
- If top features are risky, include warning artifact rather than business-friendly narrative.

**Verification**
- explainability output includes raw-field lineage
- explainability output cannot directly emit intervention advice

### Task 8: Build the Report Bundle Layer

**Files:**
- Create: `data_analysis_V2/scripts/report_bundle_builder.py`
- Create: `data_analysis_V2/scripts/formal_report_export_v2.py`
- Test: `data_analysis_V2/tests/test_report_bundle_builder.py`

**Step 1**
- Compile report-safe claims from gated artifacts only.

**Step 2**
- Build final report context from `judgment_bundle.json` and `claim_registry.json`.

**Step 3**
- Refuse export when required gated artifacts are missing.

**Verification**
- report export fails if `judgment_bundle.json` is absent
- report export fails if claim registry contains unsupported evidence grade transitions
- exploratory runs produce exploratory language, not stronger language

### Task 9: Build the Orchestrator and CLI

**Files:**
- Create: `data_analysis_V2/scripts/orchestrator.py`
- Create: `data_analysis_V2/scripts/run_pipeline_v2.py`

**Step 1**
- Implement orchestration state machine.

**Step 2**
- Add CLI flags for:
  - `--input-path`
  - `--db-url`
  - `--query`
  - `--task`
  - `--target`
  - `--time-col`
  - `--data-scope`
  - `--sample-rows`
  - `--continue-after-scout`
  - `--continue-after-baseline`
  - `--formal-report`

**Step 3**
- Ensure supervised routes stop after scout and after baseline unless explicitly continued.

**Verification**
- `python3.13 data_analysis_V2/scripts/run_pipeline_v2.py --help`
- CLI run without explicit continue flag stops at checkpoint and writes artifacts

### Task 10: Build Validation Fixtures and End-to-End Tests

**Files:**
- Create: `data_analysis_V2/tests/fixtures/*.csv`
- Create: `data_analysis_V2/tests/test_end_to_end_supervised.py`
- Create: `data_analysis_V2/tests/test_end_to_end_stop_and_report.py`

**Required fixture scenarios**

- easy classification where model clearly beats baseline
- noisy classification where model does not beat baseline
- regression with weak explanatory power
- dataset with leakage field
- dataset with post-outcome proxy field

**Verification**
- end-to-end “good” dataset reaches `report-ready`
- weak dataset is downgraded to `exploratory`
- leakage dataset routes to `stop_and_report`

## Acceptance Criteria

V2 is acceptable only if all conditions hold:

1. A supervised run cannot reach final report without `gate_review.json`.
2. A model weaker than dummy baseline cannot be narrated as useful.
3. Top features marked `post_outcome` cannot become intervention recommendations.
4. Long-running jobs emit structured heartbeat and can be labeled `stalled`.
5. Final report language is mechanically constrained by `judgment_bundle.json`.
6. The orchestrator supports checkpoints after scout and after baseline.
7. The skill can honestly conclude “not usable yet”.

## Suggested Validation Commands

Run these once implementation begins:

```bash
python3.13 -m py_compile data_analysis_V2/scripts/*.py
pytest data_analysis_V2/tests/test_route_problem.py -q
pytest data_analysis_V2/tests/test_baseline_runner.py -q
pytest data_analysis_V2/tests/test_monitored_job.py -q
pytest data_analysis_V2/tests/test_gate_evaluator.py -q
pytest data_analysis_V2/tests/test_evidence_grader.py -q
pytest data_analysis_V2/tests/test_report_bundle_builder.py -q
pytest data_analysis_V2/tests/test_end_to_end_supervised.py -q
pytest data_analysis_V2/tests/test_end_to_end_stop_and_report.py -q
python3.13 data_analysis_V2/scripts/run_pipeline_v2.py --help
```

## Rollout Sequence

### Phase 1: Core Safety and Observability

- Tasks 1-6
- Goal: prevent misleading reports before optimizing breadth

### Phase 2: Report Safety and Orchestration

- Tasks 7-9
- Goal: constrain outputs and make workflow checkpointed

### Phase 3: End-to-End Confidence

- Task 10
- Goal: prove the architecture survives bad datasets as well as good ones

## Migration Guidance from V1

Do not clone V1 wholesale. Reuse only bounded pieces after review:

- reusable low-risk helpers from `check_environment.py`
- selected IO helpers if they do not force V1 control flow
- selected chart and export helpers only after report gate design is in place

Do not copy forward without redesign:

- automatic model recommendation as soft prose only
- automatic “best model => usable” narration
- exporter logic that infers business advice directly from metrics
- explainability-to-recommendation shortcuts

## Definition of Done

`data_analysis_V2` is done for first release when:

- the folder contains the V2 skill skeleton and implementation modules
- the orchestrator can stop at checkpoints and resume
- the gates downgrade or block weak results
- the monitoring layer can distinguish running, stalled, failed, and completed jobs
- the report layer only renders evidence-safe claims
- the tests demonstrate both success and failure paths

## Handoff Note

This plan intentionally favors safety and analytical honesty over feature breadth. The most important success condition is not “it trains more models”, but “it cannot confidently say nonsense”.
