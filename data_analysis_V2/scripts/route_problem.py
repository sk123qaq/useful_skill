from __future__ import annotations

from typing import Any

from data_analysis_V2.scripts.schemas import validate_analysis_contract, validate_route_decision


CAUSAL_HINTS = ("cause", "effect", "impact", "intervention", "treatment", "uplift", "did")
DESCRIPTIVE_HINTS = ("describe", "summary", "distribution", "segment", "eda", "diagnostic")
PREDICTIVE_HINTS = ("predict", "forecast", "classif", "regress", "score", "propensity", "churn")


def build_analysis_contract(
    question: str = "",
    task: str | None = None,
    target: str | None = None,
    time_col: str | None = None,
    data_scope: str = "sample",
    sample_rows: int | None = 5000,
    continue_after_scout: bool = False,
    continue_after_baseline: bool = False,
) -> dict[str, Any]:
    normalized_task = task or ("predictive" if target else "descriptive")
    payload = {
        "question": question or "",
        "task": normalized_task,
        "target": target,
        "time_col": time_col,
        "data_scope": data_scope,
        "sample_rows": sample_rows,
        "continue_after_scout": continue_after_scout,
        "continue_after_baseline": continue_after_baseline,
    }
    return validate_analysis_contract(payload)


def _infer_predictive_subtask(contract: dict[str, Any], scout_report: dict[str, Any]) -> str:
    task = contract["task"].lower()
    if task in {"classification", "regression"}:
        return task
    target_distribution = scout_report.get("target_distribution", {})
    unique_values = target_distribution.get("unique_values", 0)
    if unique_values and unique_values <= 10:
        return "classification"
    return "regression"


def route_problem(
    contract: dict[str, Any],
    scout_report: dict[str, Any],
    feature_risk_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_text = f"{contract.get('question', '')} {contract.get('task', '')}".lower()
    blockers: list[str] = []
    reasons: list[str] = []
    next_actions: list[str] = []

    label_counts = (feature_risk_report or {}).get("summary", {}).get("label_counts", {})
    if label_counts.get("hard_leakage", 0) > 0:
        blockers.append("Detected hard leakage features; supervised route is unsafe.")
        decision = {
            "route": "stop_and_report",
            "reasons": ["Feature-risk audit found hard leakage."],
            "blockers": blockers,
            "next_actions": ["Remove or quarantine leakage fields before retrying."],
            "suggested_task_type": None,
        }
        return validate_route_decision(decision)

    if contract["task"].lower() == "causal" or any(token in task_text for token in CAUSAL_HINTS):
        reasons.append("Question is intervention-oriented and should be treated as causal triage.")
        decision = {
            "route": "causal",
            "reasons": reasons,
            "blockers": blockers,
            "next_actions": ["Collect treatment timing and identification assumptions."],
            "suggested_task_type": None,
        }
        return validate_route_decision(decision)

    predictive_requested = contract["task"].lower() in {"predictive", "classification", "regression"} or any(
        token in task_text for token in PREDICTIVE_HINTS
    )
    descriptive_requested = contract["task"].lower() in {"descriptive", "eda"} or any(
        token in task_text for token in DESCRIPTIVE_HINTS
    )

    if predictive_requested and not contract.get("target"):
        blockers.append("Predictive work requires an explicit target column.")
        decision = {
            "route": "stop_and_report",
            "reasons": ["Predictive route requested without target."],
            "blockers": blockers,
            "next_actions": ["Define the target column before modeling."],
            "suggested_task_type": None,
        }
        return validate_route_decision(decision)

    if predictive_requested:
        suggested_task_type = _infer_predictive_subtask(contract, scout_report)
        reasons.append("Target is defined and the request is predictive.")
        next_actions.extend(["Run the baseline ladder.", "Stop at checkpoint unless explicit continue flag is set."])
        decision = {
            "route": "predictive",
            "reasons": reasons,
            "blockers": blockers,
            "next_actions": next_actions,
            "suggested_task_type": suggested_task_type,
        }
        return validate_route_decision(decision)

    if descriptive_requested or not contract.get("target"):
        reasons.append("The request is descriptive or lacks a predictive target.")
        decision = {
            "route": "descriptive",
            "reasons": reasons,
            "blockers": blockers,
            "next_actions": ["Produce descriptive outputs and honest limitations."],
            "suggested_task_type": None,
        }
        return validate_route_decision(decision)

    decision = {
        "route": "stop_and_report",
        "reasons": ["Unable to safely route the request."],
        "blockers": ["Contract is underspecified."],
        "next_actions": ["Clarify the business question and task type."],
        "suggested_task_type": None,
    }
    return validate_route_decision(decision)
