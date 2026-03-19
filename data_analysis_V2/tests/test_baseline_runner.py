from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_analysis_V2.scripts.baseline_runner import run_baseline_ladder


FIXTURES = Path(__file__).parent / "fixtures"


def test_classification_baseline_order_is_deterministic() -> None:
    df = pd.read_csv(FIXTURES / "easy_classification.csv")
    results_one = run_baseline_ladder(df, target="target", task="classification")
    results_two = run_baseline_ladder(df, target="target", task="classification")
    assert results_one["model_order"] == [
        "dummy_most_frequent",
        "logistic_regression",
        "random_forest_classifier",
    ]
    assert results_one["model_order"] == results_two["model_order"]
    assert all("fold_metrics" in model and "mean_metrics" in model and "std_metrics" in model for model in results_one["models"])
    logistic = next(model for model in results_one["models"] if model["model_name"] == "logistic_regression")
    assert "balanced_accuracy" in logistic["mean_metrics"]
    assert "average_precision" in logistic["mean_metrics"]


def test_regression_baseline_order_includes_dummy_then_linear() -> None:
    df = pd.read_csv(FIXTURES / "weak_regression.csv")
    results = run_baseline_ladder(df, target="target", task="regression")
    assert results["model_order"][:3] == ["dummy_mean", "dummy_median", "linear_regression"]
    assert results["primary_metric"] == "rmse"
    assert results["primary_metric_direction"] == "min"
