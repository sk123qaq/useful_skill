from __future__ import annotations

import json
from pathlib import Path

from data_analysis_V2.scripts.common import write_json
from data_analysis_V2.scripts.orchestrator import run_pipeline


FIXTURES = Path(__file__).parent / "fixtures"


def _write_scout_decision(run_dir: Path, decision: str = "continue_to_baseline") -> None:
    write_json(
        run_dir / "data_processing_decision.json",
        {
            "stage": "after_scout",
            "decision": decision,
            "summary": "Reviewed scout findings from a whole-run perspective.",
            "reasons": ["Judgment context was reviewed."],
            "actions": ["Continue to baseline."],
        },
    )


def _write_baseline_decision(run_dir: Path, decision: str = "continue_to_report") -> None:
    write_json(
        run_dir / "modeling_decision.json",
        {
            "stage": "after_baseline",
            "decision": decision,
            "summary": "Reviewed the whole analysis so far, including data quality and model results.",
            "reasons": ["Judgment context was reviewed."],
            "actions": ["Continue to report."],
        },
    )


def test_good_dataset_reaches_report_ready_after_checkpoints(tmp_path: Path) -> None:
    first = run_pipeline(
        question="predict target",
        input_path=str(FIXTURES / "easy_classification.csv"),
        task="classification",
        target="target",
        data_scope="full",
        continue_after_scout=False,
        continue_after_baseline=False,
        output_dir=str(tmp_path),
    )
    run_dir = Path(first["run_dir"])
    assert first["state"] == "awaiting_agent_review_after_scout"
    assert (run_dir / "scout_report.json").exists()
    assert (run_dir / "column_profile.json").exists()
    assert (run_dir / "judgment_context_after_scout.json").exists()
    assert (run_dir / "judgment_context_after_scout.md").exists()
    assert not (run_dir / "gate_review.json").exists()
    _write_scout_decision(run_dir)

    second = run_pipeline(
        question="predict target",
        input_path=str(FIXTURES / "easy_classification.csv"),
        task="classification",
        target="target",
        data_scope="full",
        continue_after_scout=True,
        continue_after_baseline=False,
        output_dir=str(run_dir),
    )
    assert second["state"] == "awaiting_agent_review_after_baseline"
    assert (run_dir / "baseline_results.json").exists()
    assert (run_dir / "judgment_context_after_baseline.json").exists()
    assert (run_dir / "judgment_context_after_baseline.md").exists()
    _write_baseline_decision(run_dir)

    third = run_pipeline(
        question="predict target",
        input_path=str(FIXTURES / "easy_classification.csv"),
        task="classification",
        target="target",
        data_scope="full",
        continue_after_scout=True,
        continue_after_baseline=True,
        formal_report=True,
        output_dir=str(run_dir),
    )
    assert third["state"] == "completed"
    assert third["report_mode"] == "report-ready"
    assert (run_dir / "gate_review.json").exists()
    assert (run_dir / "judgment_bundle.json").exists()
    assert (run_dir / "claim_registry.json").exists()
    assert (run_dir / "formal_report_v2.md").exists()


def test_weak_dataset_is_downgraded_to_exploratory(tmp_path: Path) -> None:
    first = run_pipeline(
        question="predict target",
        input_path=str(FIXTURES / "noisy_classification.csv"),
        task="classification",
        target="target",
        data_scope="full",
        output_dir=str(tmp_path),
    )
    run_dir = Path(first["run_dir"])
    _write_scout_decision(run_dir)
    run_pipeline(
        question="predict target",
        input_path=str(FIXTURES / "noisy_classification.csv"),
        task="classification",
        target="target",
        data_scope="full",
        continue_after_scout=True,
        output_dir=str(run_dir),
    )
    _write_baseline_decision(run_dir)
    result = run_pipeline(
        question="predict target",
        input_path=str(FIXTURES / "noisy_classification.csv"),
        task="classification",
        target="target",
        data_scope="full",
        continue_after_scout=True,
        continue_after_baseline=True,
        output_dir=str(run_dir),
    )
    assert result["report_mode"] == "exploratory"
    judgment = json.loads((run_dir / "judgment_bundle.json").read_text())
    assert judgment["evidence_grade"] == "exploratory"


def test_post_outcome_top_feature_cannot_reach_report_ready(tmp_path: Path) -> None:
    first = run_pipeline(
        question="predict target",
        input_path=str(FIXTURES / "post_outcome_proxy.csv"),
        task="classification",
        target="target",
        data_scope="full",
        output_dir=str(tmp_path),
    )
    run_dir = Path(first["run_dir"])
    _write_scout_decision(run_dir)
    run_pipeline(
        question="predict target",
        input_path=str(FIXTURES / "post_outcome_proxy.csv"),
        task="classification",
        target="target",
        data_scope="full",
        continue_after_scout=True,
        output_dir=str(run_dir),
    )
    _write_baseline_decision(run_dir)
    result = run_pipeline(
        question="predict target",
        input_path=str(FIXTURES / "post_outcome_proxy.csv"),
        task="classification",
        target="target",
        data_scope="full",
        continue_after_scout=True,
        continue_after_baseline=True,
        output_dir=str(run_dir),
    )
    assert result["report_mode"] == "exploratory"
