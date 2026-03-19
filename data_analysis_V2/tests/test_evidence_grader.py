from __future__ import annotations

import pytest

from data_analysis_V2.scripts.evidence_grader import (
    build_claim_registry,
    build_judgment_bundle,
    validate_claim_grade_transitions,
)


def _gate_review(max_evidence_grade: str) -> dict:
    return {
        "gate_results": {
            "baseline": {"passed": max_evidence_grade == "report-ready", "reason": "baseline"},
            "stability": {"passed": max_evidence_grade == "report-ready", "reason": "stability"},
            "feature_risk": {"passed": max_evidence_grade == "report-ready", "reason": "risk"},
            "report": {"passed": max_evidence_grade == "report-ready", "reason": "report"},
        },
        "max_evidence_grade": max_evidence_grade,
        "blockers": [],
        "warnings": [],
    }


def test_all_gates_passing_reaches_report_ready() -> None:
    judgment = build_judgment_bundle(_gate_review("report-ready"))
    assert judgment["evidence_grade"] == "report-ready"


def test_failed_gate_caps_evidence_grade() -> None:
    judgment = build_judgment_bundle(_gate_review("exploratory"))
    assert judgment["evidence_grade"] == "exploratory"


def test_claim_registry_cannot_exceed_grade_ceiling() -> None:
    judgment = build_judgment_bundle(_gate_review("exploratory"))
    registry = build_claim_registry(judgment)
    registry["claims"].append(
        {
            "claim_id": "illegal_upgrade",
            "text": "This is decision-ready.",
            "evidence_grade": "report-ready",
            "supported_by": ["fake.json"],
            "status": "allowed",
        }
    )
    with pytest.raises(ValueError):
        validate_claim_grade_transitions(registry, judgment)
