from __future__ import annotations

from typing import Any

from data_analysis_V2.scripts.schemas import validate_claim_registry, validate_judgment_bundle


GRADE_RANK = {"not_usable": 0, "exploratory": 1, "report-ready": 2}


def build_judgment_bundle(
    gate_review: dict[str, Any],
    baseline_results: dict[str, Any] | None = None,
    explainability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del explainability
    grade = gate_review["max_evidence_grade"]
    if grade == "report-ready":
        summary = "Predictive signal cleared the configured gates and can be reported with evidence-safe language."
    elif grade == "exploratory":
        summary = "Some signal exists, but the current evidence is only suitable for exploratory follow-up."
    else:
        summary = "The current run is not usable yet and should not be framed as decision-ready."
    if baseline_results:
        summary += f" Best model observed: {baseline_results['best_model_name']}."
    bundle = {
        "evidence_grade": grade,
        "allowed_report_mode": grade,
        "narrative_guardrails": [
            "Do not turn predictive features into causal recommendations.",
            "Do not exceed the maximum evidence grade.",
            "State blockers plainly when the run is exploratory or not usable.",
        ],
        "safe_summary": summary,
    }
    return validate_judgment_bundle(bundle)


def _claim(claim_id: str, text: str, grade: str, supported_by: list[str]) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": text,
        "evidence_grade": grade,
        "supported_by": supported_by,
        "status": "allowed",
    }


def build_claim_registry(
    judgment_bundle: dict[str, Any],
    scout_report: dict[str, Any] | None = None,
    baseline_results: dict[str, Any] | None = None,
    explainability: dict[str, Any] | None = None,
    route_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    grade = judgment_bundle["evidence_grade"]
    claims: list[dict[str, Any]] = []
    if route_decision:
        claims.append(
            _claim(
                "route",
                f"Workflow routed to `{route_decision['route']}`.",
                min("exploratory", grade, key=lambda item: GRADE_RANK[item]),
                ["route_decision.json"],
            )
        )
    if scout_report:
        claims.append(
            _claim(
                "data_shape",
                f"Dataset contains {scout_report['row_count']} rows across {scout_report['column_count']} columns.",
                min("exploratory", grade, key=lambda item: GRADE_RANK[item]),
                ["scout_report.json"],
            )
        )
    if baseline_results:
        if grade == "report-ready":
            text = (
                f"{baseline_results['best_model_name']} beat the best dummy baseline on "
                f"{baseline_results['primary_metric']}."
            )
        elif grade == "exploratory":
            text = "Predictive performance did not clear all reporting gates; treat the result as exploratory."
        else:
            text = "Predictive output is not usable yet and should not drive action."
        claims.append(_claim("model_signal", text, grade, ["baseline_results.json", "gate_review.json"]))
    if explainability and explainability.get("top_features"):
        claims.append(
            _claim(
                "feature_reliance",
                "Top features describe predictive reliance only and do not imply causality.",
                min("exploratory", grade, key=lambda item: GRADE_RANK[item]),
                ["explainability_guarded.json"],
            )
        )
    registry = {"claims": claims}
    return validate_claim_registry(registry)


def validate_claim_grade_transitions(claim_registry: dict[str, Any], judgment_bundle: dict[str, Any]) -> None:
    ceiling = GRADE_RANK[judgment_bundle["evidence_grade"]]
    for claim in claim_registry["claims"]:
        if GRADE_RANK[claim["evidence_grade"]] > ceiling:
            raise ValueError(
                f"Claim {claim['claim_id']} exceeds judgment bundle ceiling: {claim['evidence_grade']} > {judgment_bundle['evidence_grade']}"
            )
