from __future__ import annotations

from typing import Any

from schemas import validate_gate_review


def _grade_rank(grade: str) -> int:
    return {"not_usable": 0, "exploratory": 1, "report-ready": 2}[grade]


def _best_model(baseline_results: dict[str, Any], family: str | None = None) -> dict[str, Any]:
    candidates = [
        model
        for model in baseline_results["models"]
        if family is None or model["family"] == family
    ]
    metric = baseline_results["primary_metric"]
    reverse = baseline_results["primary_metric_direction"] == "max"
    return sorted(candidates, key=lambda item: item["mean_metrics"][metric], reverse=reverse)[0]


def _baseline_gate(baseline_results: dict[str, Any]) -> dict[str, Any]:
    metric = baseline_results["primary_metric"]
    direction = baseline_results["primary_metric_direction"]
    best_model = _best_model(baseline_results)
    best_dummy = _best_model(baseline_results, family="dummy")
    model_value = best_model["mean_metrics"][metric]
    dummy_value = best_dummy["mean_metrics"][metric]
    if direction == "max":
        improvement = model_value - dummy_value
        passed = best_model["family"] != "dummy" and improvement >= 0.02
    else:
        improvement = dummy_value - model_value
        passed = best_model["family"] != "dummy" and model_value <= dummy_value * 0.95
    return {
        "passed": passed,
        "reason": (
            f"Best non-dummy model improved {metric} by {improvement:.4f}."
            if passed
            else f"Best non-dummy model did not clear the baseline margin on {metric}."
        ),
        "best_model_name": best_model["model_name"],
        "best_dummy_name": best_dummy["model_name"],
    }


def _stability_gate(baseline_results: dict[str, Any]) -> dict[str, Any]:
    metric = baseline_results["primary_metric"]
    best_model = _best_model(baseline_results)
    std_value = best_model["std_metrics"][metric]
    mean_value = abs(best_model["mean_metrics"][metric]) or 1.0
    if baseline_results["task_type"] == "classification":
        passed = std_value <= 0.08
    else:
        passed = std_value <= mean_value * 0.2
    return {
        "passed": passed,
        "reason": (
            f"Fold variance on {metric} stayed within tolerance."
            if passed
            else f"Fold variance on {metric} was too high for a stable claim."
        ),
        "std_value": std_value,
    }


def _feature_risk_gate(
    feature_risk_report: dict[str, Any],
    explainability: dict[str, Any] | None,
) -> dict[str, Any]:
    label_counts = feature_risk_report["summary"]["label_counts"]
    top_features = (explainability or {}).get("top_features", [])
    risky_top_features = [
        feature["feature"]
        for feature in top_features
        if feature.get("risk_label") in {"hard_leakage", "post_outcome"}
    ]
    passed = label_counts.get("hard_leakage", 0) == 0 and not risky_top_features
    return {
        "passed": passed,
        "reason": (
            "Top-ranked features do not rely on hard leakage or post-outcome fields."
            if passed
            else "Risky top-ranked features block strong reporting."
        ),
        "risky_top_features": risky_top_features,
    }


def evaluate_gates(
    route_decision: dict[str, Any],
    feature_risk_report: dict[str, Any],
    baseline_results: dict[str, Any] | None = None,
    explainability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if route_decision["route"] == "stop_and_report":
        review = {
            "gate_results": {
                "baseline": {"passed": False, "reason": "Route stopped before modeling."},
                "stability": {"passed": False, "reason": "Route stopped before modeling."},
                "feature_risk": {"passed": False, "reason": "Unsafe feature risk conditions detected."},
                "report": {"passed": False, "reason": "Final report blocked by route decision."},
            },
            "max_evidence_grade": "not_usable",
            "blockers": list(route_decision["blockers"]),
            "warnings": [],
        }
        return validate_gate_review(review)

    baseline_gate = _baseline_gate(baseline_results) if baseline_results else {"passed": False, "reason": "Missing baseline_results."}
    stability_gate = _stability_gate(baseline_results) if baseline_results else {"passed": False, "reason": "Missing baseline_results."}
    feature_gate = _feature_risk_gate(feature_risk_report, explainability)
    report_passed = baseline_gate["passed"] and stability_gate["passed"] and feature_gate["passed"]

    if report_passed:
        max_grade = "report-ready"
    elif feature_risk_report["summary"]["label_counts"].get("hard_leakage", 0) > 0:
        max_grade = "not_usable"
    else:
        max_grade = "exploratory"

    review = {
        "gate_results": {
            "baseline": baseline_gate,
            "stability": stability_gate,
            "feature_risk": feature_gate,
            "report": {
                "passed": report_passed,
                "reason": "All gating conditions passed." if report_passed else "One or more upstream gates failed.",
            },
        },
        "max_evidence_grade": max_grade,
        "blockers": [
            gate["reason"]
            for gate in (baseline_gate, stability_gate, feature_gate)
            if not gate["passed"]
        ],
        "warnings": list((explainability or {}).get("warnings", [])),
    }
    return validate_gate_review(review)
