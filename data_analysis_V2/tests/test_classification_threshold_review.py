from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_analysis_V2.scripts.classification_threshold_review import build_threshold_review, run_threshold_review


FIXTURES = Path(__file__).parent / "fixtures"


def test_build_threshold_review_returns_best_thresholds() -> None:
    df = pd.read_csv(FIXTURES / "easy_classification.csv")
    review = build_threshold_review(
        df,
        target="target",
        model_name="logistic_regression",
        n_splits=3,
        min_threshold=0.3,
        max_threshold=0.7,
        step=0.2,
    )
    assert review["model_name"] == "logistic_regression"
    assert len(review["threshold_rows"]) == 3
    assert review["best_threshold_by_metric"]["balanced_accuracy"]["threshold"] in {0.3, 0.5, 0.7}


def test_run_threshold_review_writes_artifact(tmp_path: Path) -> None:
    df = pd.read_csv(FIXTURES / "easy_classification.csv")
    result = run_threshold_review(
        df,
        target="target",
        model_name="logistic_regression",
        output_dir=str(tmp_path),
        n_splits=3,
    )
    assert result["status"] == "completed"
    assert result["result"]["model_name"] == "logistic_regression"
    assert (tmp_path / "threshold_review.json").exists()
