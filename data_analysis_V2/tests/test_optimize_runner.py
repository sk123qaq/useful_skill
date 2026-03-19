from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_analysis_V2.scripts.optimize_runner import run_optimized_candidates


FIXTURES = Path(__file__).parent / "fixtures"


def test_run_optimized_candidates_produces_tuned_catalog_results(tmp_path: Path) -> None:
    df = pd.read_csv(FIXTURES / "easy_classification.csv")
    result = run_optimized_candidates(
        df,
        target="target",
        task="classification",
        output_dir=str(tmp_path),
        n_splits=3,
    )
    assert result["status"] == "completed"
    optimized = result["result"]
    assert optimized["primary_metric"] == "average_precision"
    assert "logistic_regression_balanced_c1" in optimized["model_order"]
    assert (tmp_path / "optimized_results.json").exists()
