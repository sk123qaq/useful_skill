from __future__ import annotations

from typing import Any, Callable


ALLOWED_ROUTES = {"descriptive", "predictive", "causal", "stop_and_report"}
ALLOWED_DATASET_KINDS = {"single_table", "dataset_package", "sql_query"}
ALLOWED_REPORT_LOCALES = {"zh", "en"}
ALLOWED_RISK_LABELS = {
    "safe",
    "soft_proxy",
    "post_outcome",
    "hard_leakage",
    "collection_artifact",
}
ALLOWED_EVIDENCE_GRADES = {"report-ready", "exploratory", "not_usable"}
ALLOWED_JUDGMENT_STAGES = {"after_scout", "after_feature_selection", "after_baseline"}
ALLOWED_AGENT_DECISIONS = {
    "continue_to_baseline",
    "clean_first",
    "run_feature_selection_review",
    "stop_and_report",
    "continue_to_report",
    "tune_models",
    "stop_as_not_usable",
}


class SchemaValidationError(ValueError):
    """Raised when an artifact does not match the expected schema."""


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaValidationError(message)


def _ensure_keys(payload: dict[str, Any], required: set[str], schema_name: str) -> None:
    missing = sorted(required - set(payload))
    _ensure(not missing, f"{schema_name} missing keys: {', '.join(missing)}")


def _ensure_list_of_dicts(value: Any, field_name: str) -> None:
    _ensure(isinstance(value, list), f"{field_name} must be a list")
    for index, item in enumerate(value):
        _ensure(isinstance(item, dict), f"{field_name}[{index}] must be a dict")


def validate_analysis_contract(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "analysis_contract must be a dict")
    _ensure_keys(
        payload,
        {
            "decision_question",
            "question",
            "task",
            "target",
            "time_col",
            "data_scope",
            "sample_rows",
            "continue_after_scout",
            "continue_after_baseline",
            "data_source",
            "unit_of_analysis",
            "success_criteria",
            "constraints",
            "report_locale",
            "focus_columns",
            "dataset_kind",
        },
        "analysis_contract",
    )
    _ensure(isinstance(payload["decision_question"], str), "analysis_contract.decision_question must be a string")
    _ensure(isinstance(payload["question"], str), "analysis_contract.question must be a string")
    _ensure(isinstance(payload["task"], str), "analysis_contract.task must be a string")
    _ensure(payload["target"] is None or isinstance(payload["target"], str), "analysis_contract.target must be null or string")
    _ensure(payload["time_col"] is None or isinstance(payload["time_col"], str), "analysis_contract.time_col must be null or string")
    _ensure(payload["data_scope"] in {"sample", "full"}, "analysis_contract.data_scope must be sample or full")
    _ensure(payload["sample_rows"] is None or isinstance(payload["sample_rows"], int), "analysis_contract.sample_rows must be null or int")
    _ensure(isinstance(payload["continue_after_scout"], bool), "analysis_contract.continue_after_scout must be bool")
    _ensure(isinstance(payload["continue_after_baseline"], bool), "analysis_contract.continue_after_baseline must be bool")
    _ensure(isinstance(payload["data_source"], str), "analysis_contract.data_source must be a string")
    _ensure(isinstance(payload["unit_of_analysis"], str), "analysis_contract.unit_of_analysis must be a string")
    _ensure(isinstance(payload["success_criteria"], list), "analysis_contract.success_criteria must be a list")
    _ensure(all(isinstance(item, str) for item in payload["success_criteria"]), "analysis_contract.success_criteria[] must be strings")
    _ensure(isinstance(payload["constraints"], list), "analysis_contract.constraints must be a list")
    _ensure(all(isinstance(item, str) for item in payload["constraints"]), "analysis_contract.constraints[] must be strings")
    _ensure(payload["report_locale"] in ALLOWED_REPORT_LOCALES, "analysis_contract.report_locale is invalid")
    _ensure(isinstance(payload["focus_columns"], list), "analysis_contract.focus_columns must be a list")
    _ensure(all(isinstance(item, str) for item in payload["focus_columns"]), "analysis_contract.focus_columns[] must be strings")
    _ensure(payload["dataset_kind"] in ALLOWED_DATASET_KINDS, "analysis_contract.dataset_kind is invalid")
    return payload


def validate_route_decision(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "route_decision must be a dict")
    _ensure_keys(payload, {"route", "reasons", "blockers", "next_actions"}, "route_decision")
    _ensure(payload["route"] in ALLOWED_ROUTES, "route_decision.route is invalid")
    _ensure(isinstance(payload["reasons"], list), "route_decision.reasons must be a list")
    _ensure(isinstance(payload["blockers"], list), "route_decision.blockers must be a list")
    _ensure(isinstance(payload["next_actions"], list), "route_decision.next_actions must be a list")
    return payload


def validate_feature_risk_report(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "feature_risk_report must be a dict")
    _ensure_keys(payload, {"features", "summary"}, "feature_risk_report")
    _ensure_list_of_dicts(payload["features"], "feature_risk_report.features")
    _ensure(isinstance(payload["summary"], dict), "feature_risk_report.summary must be a dict")
    for feature in payload["features"]:
        _ensure_keys(feature, {"feature", "label", "reason"}, "feature_risk_report.features[]")
        _ensure(feature["label"] in ALLOWED_RISK_LABELS, f"invalid risk label: {feature['label']}")
    return payload


def validate_baseline_results(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "baseline_results must be a dict")
    _ensure_keys(
        payload,
        {"task_type", "models", "primary_metric", "primary_metric_direction", "best_model_name", "best_dummy_name"},
        "baseline_results",
    )
    _ensure(payload["task_type"] in {"classification", "regression"}, "baseline_results.task_type is invalid")
    _ensure_list_of_dicts(payload["models"], "baseline_results.models")
    for model in payload["models"]:
        _ensure_keys(
            model,
            {"model_name", "level", "family", "fold_metrics", "mean_metrics", "std_metrics"},
            "baseline_results.models[]",
        )
    return payload


def validate_gate_review(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "gate_review must be a dict")
    _ensure_keys(payload, {"gate_results", "max_evidence_grade", "blockers", "warnings"}, "gate_review")
    _ensure(payload["max_evidence_grade"] in ALLOWED_EVIDENCE_GRADES, "gate_review.max_evidence_grade is invalid")
    _ensure(isinstance(payload["gate_results"], dict), "gate_review.gate_results must be a dict")
    for name in ("baseline", "stability", "feature_risk", "report"):
        _ensure(name in payload["gate_results"], f"gate_review.gate_results missing {name}")
    return payload


def validate_judgment_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "judgment_bundle must be a dict")
    _ensure_keys(
        payload,
        {"evidence_grade", "allowed_report_mode", "narrative_guardrails", "safe_summary"},
        "judgment_bundle",
    )
    _ensure(payload["evidence_grade"] in ALLOWED_EVIDENCE_GRADES, "judgment_bundle.evidence_grade is invalid")
    _ensure(payload["allowed_report_mode"] in ALLOWED_EVIDENCE_GRADES, "judgment_bundle.allowed_report_mode is invalid")
    _ensure(isinstance(payload["narrative_guardrails"], list), "judgment_bundle.narrative_guardrails must be a list")
    _ensure(isinstance(payload["safe_summary"], str), "judgment_bundle.safe_summary must be a string")
    return payload


def validate_claim_registry(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "claim_registry must be a dict")
    _ensure_keys(payload, {"claims"}, "claim_registry")
    _ensure_list_of_dicts(payload["claims"], "claim_registry.claims")
    for claim in payload["claims"]:
        _ensure_keys(claim, {"claim_id", "text", "evidence_grade", "supported_by", "status"}, "claim_registry.claims[]")
        _ensure(claim["evidence_grade"] in ALLOWED_EVIDENCE_GRADES, "claim evidence grade is invalid")
    return payload


def validate_judgment_context(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "judgment_context must be a dict")
    _ensure_keys(
        payload,
        {
            "stage",
            "question",
            "task",
            "target",
            "dataset_overview",
            "feature_summary",
            "global_assessment",
            "decision_prompt",
        },
        "judgment_context",
    )
    _ensure(payload["stage"] in ALLOWED_JUDGMENT_STAGES, "judgment_context.stage is invalid")
    _ensure(isinstance(payload["dataset_overview"], dict), "judgment_context.dataset_overview must be a dict")
    _ensure(isinstance(payload["feature_summary"], dict), "judgment_context.feature_summary must be a dict")
    _ensure(isinstance(payload["global_assessment"], list), "judgment_context.global_assessment must be a list")
    _ensure(isinstance(payload["decision_prompt"], str), "judgment_context.decision_prompt must be a string")
    return payload


def validate_agent_decision(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "agent_decision must be a dict")
    _ensure_keys(payload, {"stage", "decision", "summary", "reasons", "actions"}, "agent_decision")
    _ensure(payload["stage"] in ALLOWED_JUDGMENT_STAGES, "agent_decision.stage is invalid")
    _ensure(payload["decision"] in ALLOWED_AGENT_DECISIONS, "agent_decision.decision is invalid")
    _ensure(isinstance(payload["summary"], str), "agent_decision.summary must be a string")
    _ensure(isinstance(payload["reasons"], list), "agent_decision.reasons must be a list")
    _ensure(isinstance(payload["actions"], list), "agent_decision.actions must be a list")
    return payload


VALIDATORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "analysis_contract": validate_analysis_contract,
    "route_decision": validate_route_decision,
    "feature_risk_report": validate_feature_risk_report,
    "baseline_results": validate_baseline_results,
    "gate_review": validate_gate_review,
    "judgment_bundle": validate_judgment_bundle,
    "claim_registry": validate_claim_registry,
    "judgment_context": validate_judgment_context,
    "agent_decision": validate_agent_decision,
}


def validate_schema(schema_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    validator = VALIDATORS[schema_name]
    return validator(payload)
