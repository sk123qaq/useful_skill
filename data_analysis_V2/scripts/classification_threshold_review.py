from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))

from data_analysis_V2.scripts.baseline_runner import _classification_metrics, collect_binary_classification_oof_scores
from data_analysis_V2.scripts.column_profile import load_table
from data_analysis_V2.scripts.common import write_artifact
from data_analysis_V2.scripts.model_catalog import get_model_spec
from data_analysis_V2.scripts.monitored_job import run_monitored_job


def _threshold_grid(min_threshold: float, max_threshold: float, step: float) -> list[float]:
    grid: list[float] = []
    current = min_threshold
    while current <= max_threshold + 1e-9:
        grid.append(round(current, 4))
        current += step
    return grid


def build_threshold_review(
    df: pd.DataFrame,
    target: str,
    model_name: str,
    n_splits: int = 5,
    min_threshold: float = 0.1,
    max_threshold: float = 0.9,
    step: float = 0.05,
    precision_floor: float = 0.5,
    heartbeat=None,
) -> dict[str, Any]:
    spec = get_model_spec("classification", model_name, include_tuning=True)
    oof = collect_binary_classification_oof_scores(
        df,
        target=target,
        spec=spec,
        n_splits=n_splits,
        heartbeat=heartbeat,
    )
    y_true = pd.Series(oof["y_true"])
    scores = pd.Series(oof["scores"])
    positive_label = oof["positive_label"]
    negative_label = oof["negative_label"]
    threshold_rows: list[dict[str, Any]] = []
    for threshold in _threshold_grid(min_threshold, max_threshold, step):
        predictions = pd.Series(
            [positive_label if score >= threshold else negative_label for score in scores],
            index=scores.index,
        )
        metrics = _classification_metrics(y_true, predictions, scores)
        threshold_rows.append(
            {
                "threshold": threshold,
                "positive_prediction_rate": float((predictions == positive_label).mean()),
                **metrics,
            }
        )

    def best_row(metric_name: str) -> dict[str, Any]:
        return sorted(threshold_rows, key=lambda row: row[metric_name], reverse=True)[0]

    precision_floor_candidates = [row for row in threshold_rows if row["precision_pos"] >= precision_floor]
    best_precision_floor = (
        sorted(precision_floor_candidates, key=lambda row: row["recall_pos"], reverse=True)[0]
        if precision_floor_candidates
        else None
    )

    return {
        "model_name": model_name,
        "positive_label": positive_label,
        "default_threshold": 0.5,
        "default_metrics": oof["default_metrics"],
        "score_summary": {
            "min_score": float(scores.min()),
            "max_score": float(scores.max()),
            "mean_score": float(scores.mean()),
        },
        "best_threshold_by_metric": {
            "balanced_accuracy": best_row("balanced_accuracy"),
            "f1_macro": best_row("f1_macro"),
            "recall_pos_subject_to_precision_floor": best_precision_floor,
        },
        "precision_floor": precision_floor,
        "threshold_rows": threshold_rows,
    }


def run_threshold_review(
    df: pd.DataFrame,
    target: str,
    model_name: str,
    output_dir: str,
    n_splits: int = 5,
    min_threshold: float = 0.1,
    max_threshold: float = 0.9,
    step: float = 0.05,
    precision_floor: float = 0.5,
) -> dict[str, Any]:
    def job(heartbeat):
        heartbeat("starting threshold review")
        review = build_threshold_review(
            df,
            target=target,
            model_name=model_name,
            n_splits=n_splits,
            min_threshold=min_threshold,
            max_threshold=max_threshold,
            step=step,
            precision_floor=precision_floor,
            heartbeat=heartbeat,
        )
        write_artifact(output_dir, "threshold_review", review)
        heartbeat("completed threshold review")
        return review

    return run_monitored_job("threshold_review", output_dir, job)


def main() -> int:
    parser = argparse.ArgumentParser(description="Review operating thresholds for a binary classification model.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--min-threshold", type=float, default=0.1)
    parser.add_argument("--max-threshold", type=float, default=0.9)
    parser.add_argument("--step", type=float, default=0.05)
    parser.add_argument("--precision-floor", type=float, default=0.5)
    args = parser.parse_args()

    df = load_table(args.input_path)
    review = run_threshold_review(
        df,
        target=args.target,
        model_name=args.model_name,
        output_dir=args.output_dir,
        n_splits=args.n_splits,
        min_threshold=args.min_threshold,
        max_threshold=args.max_threshold,
        step=args.step,
        precision_floor=args.precision_floor,
    )
    print(json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
