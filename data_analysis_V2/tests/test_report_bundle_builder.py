from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_analysis_V2.scripts.common import write_json
from data_analysis_V2.scripts.formal_report_export_v2 import export_formal_report_v2
from data_analysis_V2.scripts.report_bundle_builder import build_report_bundle


def test_report_export_fails_without_judgment_bundle(tmp_path: Path) -> None:
    write_json(tmp_path / "claim_registry.json", {"claims": []})
    with pytest.raises(FileNotFoundError):
        export_formal_report_v2(tmp_path)


def test_claim_grade_transition_violation_blocks_bundle(tmp_path: Path) -> None:
    write_json(
        tmp_path / "judgment_bundle.json",
        {
            "evidence_grade": "exploratory",
            "allowed_report_mode": "exploratory",
            "narrative_guardrails": ["guardrail"],
            "safe_summary": "Exploratory only.",
        },
    )
    write_json(
        tmp_path / "claim_registry.json",
        {
            "claims": [
                {
                    "claim_id": "too_strong",
                    "text": "Decision ready claim.",
                    "evidence_grade": "report-ready",
                    "supported_by": ["fake.json"],
                    "status": "allowed",
                }
            ]
        },
    )
    with pytest.raises(ValueError):
        build_report_bundle(tmp_path)


def test_exploratory_bundle_stays_exploratory(tmp_path: Path) -> None:
    write_json(
        tmp_path / "judgment_bundle.json",
        {
            "evidence_grade": "exploratory",
            "allowed_report_mode": "exploratory",
            "narrative_guardrails": ["Do not overclaim."],
            "safe_summary": "This result is exploratory only.",
        },
    )
    write_json(
        tmp_path / "claim_registry.json",
        {
            "claims": [
                {
                    "claim_id": "weak_signal",
                    "text": "Treat this result as exploratory.",
                    "evidence_grade": "exploratory",
                    "supported_by": ["gate_review.json"],
                    "status": "allowed",
                }
            ]
        },
    )
    bundle = build_report_bundle(tmp_path)
    assert bundle["report_mode"] == "exploratory"
    assert "exploratory" in bundle["summary"].lower()
    export = export_formal_report_v2(tmp_path, title="Exploratory Report")
    assert Path(export["report_path"]).exists()
