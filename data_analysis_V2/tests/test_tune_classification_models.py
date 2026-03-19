from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from data_analysis_V2.scripts.optimize_runner import run_optimized_candidates
from data_analysis_V2.scripts.tune_classification_models import run_classification_tuning


FIXTURES = Path(__file__).parent / "fixtures"


def test_run_classification_tuning_writes_richer_metrics_and_threshold_review(tmp_path: Path) -> None:
    df = pd.read_csv(FIXTURES / "easy_classification.csv")
    result = run_classification_tuning(df, target="target", output_dir=tmp_path, n_splits=3)
    tuning_results = result["tuning_results"]
    threshold_review = result["threshold_review"]

    assert tuning_results["best_candidate"]["candidate_name"] in tuning_results["candidate_order"]
    assert "average_precision" in tuning_results["best_candidate"]["mean_metrics"]
    assert "roc_auc" in tuning_results["best_candidate"]["mean_metrics"]
    assert threshold_review["best_threshold_metrics"]["threshold"] >= 0.1
    assert (tmp_path / "tuning_results.json").exists()
    assert (tmp_path / "threshold_review.json").exists()
    assert (tmp_path / "tuning_summary.md").exists()


def test_run_optimized_candidates_completes_and_writes_monitoring_artifacts(tmp_path: Path) -> None:
    df = pd.read_csv(FIXTURES / "easy_classification.csv")
    result = run_optimized_candidates(df, target="target", task="classification", output_dir=str(tmp_path), n_splits=3)

    assert result["status"] == "completed"
    status_payload = json.loads((tmp_path / "optimize_runner_status.json").read_text())
    assert status_payload["status"] == "completed"
    assert (tmp_path / "optimized_results.json").exists()
