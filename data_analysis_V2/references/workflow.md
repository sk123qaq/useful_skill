# Workflow

## Runtime States

The V2 orchestrator uses explicit states:
- `initialized`
- `scouting`
- `awaiting_agent_review_after_scout`
- `baselining`
- `awaiting_agent_review_after_baseline`
- `agent_halt_after_scout`
- `agent_halt_after_baseline`
- `gating`
- `reporting`
- `completed`
- `stop_and_report`
- `failed`

## Required Artifacts

Every predictive-capable run should be able to write:
- `analysis_contract.json`
- `scout_report.json`
- `feature_risk_report.json`
- `route_decision.json`
- `judgment_context_after_scout.json`
- `judgment_context_after_scout.md`
- `data_processing_decision.json` (agent-authored)
- `baseline_results.json` when the route reaches modeling
- `judgment_context_after_baseline.json`
- `judgment_context_after_baseline.md`
- `modeling_decision.json` (agent-authored)
- `gate_review.json` before any final report
- `judgment_bundle.json` before any final report
- `claim_registry.json` before any final report

## Flow Rules

1. Load the dataset and write `analysis_contract.json`.
2. Run scout audit and feature-risk audit.
3. Route the problem.
4. If route is `stop_and_report`, write the blocker and stop.
5. If route is predictive, build a scout judgment context that summarizes actual analysis findings: data shape, missingness, duplicates, target balance, candidate features, and feature-risk findings.
6. Stop and wait for an agent-authored `data_processing_decision.json`.
7. If scout review identifies data issues, the agent should call helper scripts such as `column_profile.py` and `prepare_modeling_dataset.py`, inspect the new results, and only then allow continuation. When `prepare_modeling_dataset.py --deduplicate` is used, de-duplication is applied again after feature drops so the final modeling table is checked in its post-selection shape.
8. Run baseline ladder only if the latest agent decision explicitly allows continuation.
9. Build a baseline judgment context that summarizes both the earlier data findings and the model comparison results.
10. Stop and wait for an agent-authored `modeling_decision.json`.
11. If the agent chooses `tune_models`, call monitored helpers such as `optimize_runner.py` and `classification_threshold_review.py` to generate richer candidate metrics and threshold review artifacts before making another modeling decision.
12. Only after that decision allows continuation should the workflow build explainability, gates, evidence grading, and final report artifacts.

## Report Modes

- `report_ready`: gates pass and language may describe usable predictive signal
- `exploratory`: some evidence exists but not enough for strong narrative
- `not_usable`: the run should conclude the model or data is not usable yet

## Agent Review Principle

Checkpoint review context must focus on analysis content, for example:
- descriptive findings already observed
- duplicates and missingness
- target distribution and class balance
- risky fields and candidate feature set
- model-vs-baseline comparison
- limitations already visible from the run

The agent should not be asked to decide from command flags, file names, or implementation details alone.
