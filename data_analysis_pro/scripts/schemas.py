"""schemas.py: artifact contracts used by the workflow.

Only artifacts that an actual script reads or writes are defined here. If a
contract has no consumer, it does not belong in this file.
"""
from __future__ import annotations

from typing import Any, Callable

ALLOWED_ROUTES = {"descriptive", "predictive", "causal", "experiment", "stop_and_report"}
ALLOWED_DATASET_KINDS = {"single_table", "dataset_package", "sql_query"}
ALLOWED_REPORT_LOCALES = {"zh", "en"}
ALLOWED_RISK_LABELS = {"safe", "soft_proxy", "post_outcome", "hard_leakage", "collection_artifact", "unreviewed"}
ALLOWED_EVIDENCE_GRADES = {"report-ready", "exploratory", "not_usable"}
ALLOWED_SPLIT_STRATEGIES = {"temporal", "expanding", "rolling", "kfold", "group"}


class SchemaValidationError(ValueError):
    """Raised when an artifact does not match its contract."""


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaValidationError(message)


def _ensure_keys(payload: dict[str, Any], required: set[str], schema_name: str) -> None:
    missing = sorted(required - set(payload))
    _ensure(not missing, f"{schema_name} missing keys: {', '.join(missing)}")


def _dicts(value: Any, field: str) -> None:
    _ensure(isinstance(value, list), f"{field} must be a list")
    for i, item in enumerate(value):
        _ensure(isinstance(item, dict), f"{field}[{i}] must be a dict")


def validate_analysis_contract(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "analysis_contract must be a dict")
    _ensure_keys(payload, {"decision_question", "task", "unit_of_analysis", "data_source",
                           "data_scope", "success_criteria", "stop_conditions"}, "analysis_contract")
    _ensure(payload["task"] in ALLOWED_ROUTES, "analysis_contract.task is invalid")
    _ensure(payload.get("report_locale", "zh") in ALLOWED_REPORT_LOCALES, "report_locale is invalid")
    _ensure(payload.get("dataset_kind", "single_table") in ALLOWED_DATASET_KINDS, "dataset_kind is invalid")
    for key in ("success_criteria", "stop_conditions"):
        _ensure(isinstance(payload.get(key), list), f"{key} must be a list")
        _ensure(all(isinstance(x, str) for x in payload[key]), f"{key}[] must be strings")
    if payload["task"] in {"predictive", "causal", "experiment"}:
        _ensure(bool(payload.get("target")), f"{payload['task']} requires target")
    return payload


def validate_route_decision(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "route_decision must be a dict")
    _ensure_keys(payload, {"route", "reasons", "blockers", "next_actions"}, "route_decision")
    _ensure(payload["route"] in ALLOWED_ROUTES, "route_decision.route is invalid")
    for key in ("reasons", "blockers", "next_actions"):
        _ensure(isinstance(payload[key], list), f"route_decision.{key} must be a list")
    return payload


def validate_feature_risk_report(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "feature_risk_report must be a dict")
    _ensure_keys(payload, {"features", "summary"}, "feature_risk_report")
    _dicts(payload["features"], "feature_risk_report.features")
    for feature in payload["features"]:
        _ensure_keys(feature, {"feature", "label", "reason", "confirmed"}, "feature_risk_report.features[]")
        _ensure(feature["label"] in ALLOWED_RISK_LABELS, f"invalid risk label: {feature['label']}")
        _ensure(isinstance(feature["confirmed"], bool), "feature.confirmed must be bool")
    return payload


def validate_split_plan(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "split_plan must be a dict")
    _ensure_keys(payload, {"strategy", "folds"}, "split_plan")
    _ensure(payload["strategy"] in ALLOWED_SPLIT_STRATEGIES, "split_plan.strategy is invalid")
    _dicts(payload["folds"], "split_plan.folds")
    return payload


def validate_baseline_results(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "baseline_results must be a dict")
    _ensure_keys(payload, {"task_type", "models", "primary_metric", "primary_metric_direction",
                           "best_model_name", "dummy_comparison", "stability"}, "baseline_results")
    _ensure(payload["task_type"] in {"classification", "regression"}, "baseline_results.task_type is invalid")
    _dicts(payload["models"], "baseline_results.models")
    return payload


def validate_gate_review(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "gate_review must be a dict")
    _ensure_keys(payload, {"status", "max_evidence_grade", "gate_results", "blockers", "warnings"}, "gate_review")
    _ensure(payload["max_evidence_grade"] in ALLOWED_EVIDENCE_GRADES, "gate grade is invalid")
    _ensure(isinstance(payload["gate_results"], dict), "gate_results must be a dict")
    return payload


def validate_claim_registry(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "claim_registry must be a dict")
    _ensure_keys(payload, {"claims"}, "claim_registry")
    _dicts(payload["claims"], "claim_registry.claims")
    for claim in payload["claims"]:
        _ensure_keys(claim, {"claim_id", "text", "evidence_grade", "supported_by"}, "claim_registry.claims[]")
        _ensure(claim["evidence_grade"] in ALLOWED_EVIDENCE_GRADES, "claim evidence grade is invalid")
    return payload


def validate_report_lint(payload: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(payload, dict), "report_lint must be a dict")
    _ensure_keys(payload, {"passed", "errors", "warnings"}, "report_lint")
    _ensure(isinstance(payload["passed"], bool), "report_lint.passed must be bool")
    return payload


VALIDATORS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "analysis_contract": validate_analysis_contract,
    "route_decision": validate_route_decision,
    "feature_risk_report": validate_feature_risk_report,
    "split_plan": validate_split_plan,
    "baseline_results": validate_baseline_results,
    "gate_review": validate_gate_review,
    "claim_registry": validate_claim_registry,
    "report_lint": validate_report_lint,
}


def validate_schema(schema_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if schema_name not in VALIDATORS:
        raise SchemaValidationError(f"unknown schema: {schema_name}")
    return VALIDATORS[schema_name](payload)
