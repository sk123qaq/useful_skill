from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline

if __package__ in {None, ""}:
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))

from data_analysis_V2.scripts.baseline_runner import _build_preprocessor, _classification_cv, _summarize_fold_metrics
from data_analysis_V2.scripts.column_profile import load_table
from data_analysis_V2.scripts.common import ensure_dir, write_json, write_markdown
from data_analysis_V2.scripts.monitored_job import run_monitored_job


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    family: str
    params: dict[str, Any]
    builder: Callable[[], object]


SUPPORTED_SELECTION_METRICS = {
    "accuracy",
    "balanced_accuracy",
    "f1_macro",
    "f1_positive",
    "precision_positive",
    "recall_positive",
    "roc_auc",
    "average_precision",
}
SUPPORTED_THRESHOLD_METRICS = {
    "accuracy",
    "balanced_accuracy",
    "f1_positive",
    "precision_positive",
    "recall_positive",
}


def build_tuning_catalog() -> list[CandidateSpec]:
    return [
        CandidateSpec(
            "logistic_regression_c0.5",
            "linear",
            {"C": 0.5, "class_weight": None},
            lambda: LogisticRegression(max_iter=1000, solver="liblinear", random_state=42, C=0.5),
        ),
        CandidateSpec(
            "logistic_regression_c1.0",
            "linear",
            {"C": 1.0, "class_weight": None},
            lambda: LogisticRegression(max_iter=1000, solver="liblinear", random_state=42, C=1.0),
        ),
        CandidateSpec(
            "logistic_regression_c1.0_balanced",
            "linear",
            {"C": 1.0, "class_weight": "balanced"},
            lambda: LogisticRegression(
                max_iter=1000,
                solver="liblinear",
                random_state=42,
                C=1.0,
                class_weight="balanced",
            ),
        ),
        CandidateSpec(
            "logistic_regression_c4.0_balanced",
            "linear",
            {"C": 4.0, "class_weight": "balanced"},
            lambda: LogisticRegression(
                max_iter=1000,
                solver="liblinear",
                random_state=42,
                C=4.0,
                class_weight="balanced",
            ),
        ),
        CandidateSpec(
            "random_forest_depth12_leaf5",
            "tree",
            {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 5, "class_weight": None},
            lambda: RandomForestClassifier(
                n_estimators=200,
                max_depth=12,
                min_samples_leaf=5,
                random_state=42,
                n_jobs=-1,
            ),
        ),
        CandidateSpec(
            "random_forest_depth12_leaf5_balanced",
            "tree",
            {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 5, "class_weight": "balanced"},
            lambda: RandomForestClassifier(
                n_estimators=200,
                max_depth=12,
                min_samples_leaf=5,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            ),
        ),
    ]


def _pick_positive_label(target: pd.Series) -> tuple[Any, Any]:
    classes = [value for value in target.dropna().unique().tolist()]
    if len(classes) != 2:
        raise ValueError("Classification tuning currently supports only binary targets.")
    if 1 in classes:
        positive = 1
    else:
        positive = sorted(classes, key=lambda value: str(value))[-1]
    negative = next(value for value in classes if value != positive)
    return negative, positive


def _safe_auc(metric_fn: Callable[[np.ndarray, np.ndarray], float], y_true_binary: np.ndarray, y_score: np.ndarray) -> float:
    try:
        return float(metric_fn(y_true_binary, y_score))
    except ValueError:
        return float("nan")


def _classification_metrics(
    y_true: pd.Series,
    y_pred: np.ndarray,
    y_score: np.ndarray,
    positive_label: Any,
) -> dict[str, float]:
    y_true_binary = (y_true.to_numpy() == positive_label).astype(int)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "f1_positive": float(f1_score(y_true, y_pred, pos_label=positive_label, zero_division=0)),
        "precision_positive": float(precision_score(y_true, y_pred, pos_label=positive_label, zero_division=0)),
        "recall_positive": float(recall_score(y_true, y_pred, pos_label=positive_label, zero_division=0)),
        "roc_auc": _safe_auc(roc_auc_score, y_true_binary, y_score),
        "average_precision": _safe_auc(average_precision_score, y_true_binary, y_score),
    }


def _evaluate_candidate(
    spec: CandidateSpec,
    features: pd.DataFrame,
    target: pd.Series,
    n_splits: int,
    negative_label: Any,
    positive_label: Any,
    heartbeat: Callable[[str | None], None] | None = None,
) -> tuple[dict[str, Any], np.ndarray]:
    preprocessor = _build_preprocessor(features)
    splitter = _classification_cv(target, n_splits)
    oof_scores = np.zeros(len(features), dtype=float)
    fold_metrics: list[dict[str, float]] = []
    for fold_index, (train_index, test_index) in enumerate(splitter.split(features, target), start=1):
        if heartbeat:
            heartbeat(f"evaluating {spec.name} fold {fold_index}")
        pipeline = Pipeline([("preprocessor", preprocessor), ("model", spec.builder())])
        x_train = features.iloc[train_index]
        x_test = features.iloc[test_index]
        y_train = target.iloc[train_index]
        y_test = target.iloc[test_index]
        pipeline.fit(x_train, y_train)
        model = pipeline.named_steps["model"]
        if not hasattr(model, "predict_proba"):
            raise ValueError(f"Candidate {spec.name} does not support predict_proba.")
        probabilities = pipeline.predict_proba(x_test)
        positive_index = list(model.classes_).index(positive_label)
        y_score = probabilities[:, positive_index]
        y_pred = np.where(y_score >= 0.5, positive_label, negative_label)
        oof_scores[test_index] = y_score
        metrics = _classification_metrics(y_test, y_pred, y_score, positive_label)
        fold_metrics.append({"fold": fold_index, **metrics})
    mean_metrics, std_metrics = _summarize_fold_metrics(
        [{key: value for key, value in fold.items() if key != "fold"} for fold in fold_metrics]
    )
    return (
        {
            "candidate_name": spec.name,
            "family": spec.family,
            "params": spec.params,
            "fold_metrics": fold_metrics,
            "mean_metrics": mean_metrics,
            "std_metrics": std_metrics,
        },
        oof_scores,
    )


def _threshold_rows(
    y_true: pd.Series,
    y_score: np.ndarray,
    negative_label: Any,
    positive_label: Any,
) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for threshold in np.arange(0.10, 0.91, 0.05):
        rounded_threshold = round(float(threshold), 2)
        y_pred = np.where(y_score >= rounded_threshold, positive_label, negative_label)
        metrics = _classification_metrics(y_true, y_pred, y_score, positive_label)
        metrics["predicted_positive_rate"] = float(np.mean(y_pred == positive_label))
        rows.append({"threshold": rounded_threshold, **metrics})
    return rows


def _best_threshold(
    threshold_rows: list[dict[str, float]],
    threshold_metric: str,
) -> dict[str, float]:
    return sorted(
        threshold_rows,
        key=lambda row: (
            row[threshold_metric],
            row["balanced_accuracy"],
            row["f1_positive"],
            -abs(row["threshold"] - 0.5),
        ),
        reverse=True,
    )[0]


def _render_tuning_summary(results: dict[str, Any], threshold_review: dict[str, Any]) -> str:
    best = results["best_candidate"]
    default_threshold = threshold_review["default_threshold_metrics"]
    best_threshold = threshold_review["best_threshold_metrics"]
    return "\n".join(
        [
            "# Classification Tuning Summary",
            "",
            f"- target: {results['target']}",
            f"- selection_metric: {results['selection_metric']}",
            f"- best_candidate: {best['candidate_name']}",
            f"- best_candidate_{results['selection_metric']}: {best['mean_metrics'][results['selection_metric']]:.4f}",
            f"- default_threshold_{threshold_review['threshold_metric']}: {default_threshold[threshold_review['threshold_metric']]:.4f}",
            f"- best_threshold: {best_threshold['threshold']:.2f}",
            f"- best_threshold_{threshold_review['threshold_metric']}: {best_threshold[threshold_review['threshold_metric']]:.4f}",
            "",
            "Use this output as a tuning checkpoint, not as final reporting evidence.",
            "",
        ]
    )


def run_classification_tuning(
    df: pd.DataFrame,
    target: str,
    output_dir: str | Path | None = None,
    selection_metric: str = "average_precision",
    threshold_metric: str = "f1_positive",
    n_splits: int = 5,
    heartbeat: Callable[[str | None], None] | None = None,
) -> dict[str, Any]:
    if selection_metric not in SUPPORTED_SELECTION_METRICS:
        raise ValueError(f"Unsupported selection_metric: {selection_metric}")
    if threshold_metric not in SUPPORTED_THRESHOLD_METRICS:
        raise ValueError(f"Unsupported threshold_metric: {threshold_metric}")
    if target not in df.columns:
        raise ValueError(f"Target column not found: {target}")
    features = df.drop(columns=[target])
    target_series = df[target]
    negative_label, positive_label = _pick_positive_label(target_series)
    candidate_results: list[dict[str, Any]] = []
    candidate_scores: dict[str, np.ndarray] = {}
    for spec in build_tuning_catalog():
        result, oof_scores = _evaluate_candidate(
            spec,
            features=features,
            target=target_series,
            n_splits=n_splits,
            negative_label=negative_label,
            positive_label=positive_label,
            heartbeat=heartbeat,
        )
        candidate_results.append(result)
        candidate_scores[spec.name] = oof_scores
    best_candidate = sorted(
        candidate_results,
        key=lambda item: (item["mean_metrics"][selection_metric], item["mean_metrics"]["balanced_accuracy"]),
        reverse=True,
    )[0]
    threshold_rows = _threshold_rows(
        y_true=target_series,
        y_score=candidate_scores[best_candidate["candidate_name"]],
        negative_label=negative_label,
        positive_label=positive_label,
    )
    best_threshold_metrics = _best_threshold(threshold_rows, threshold_metric)
    default_threshold_metrics = next(row for row in threshold_rows if math.isclose(row["threshold"], 0.5))
    tuning_results = {
        "task_type": "classification",
        "target": target,
        "selection_metric": selection_metric,
        "threshold_metric": threshold_metric,
        "negative_label": negative_label,
        "positive_label": positive_label,
        "candidate_order": [item["candidate_name"] for item in candidate_results],
        "candidate_results": candidate_results,
        "best_candidate": {
            "candidate_name": best_candidate["candidate_name"],
            "family": best_candidate["family"],
            "params": best_candidate["params"],
            "mean_metrics": best_candidate["mean_metrics"],
            "std_metrics": best_candidate["std_metrics"],
        },
    }
    threshold_review = {
        "best_candidate_name": best_candidate["candidate_name"],
        "threshold_metric": threshold_metric,
        "default_threshold": 0.5,
        "default_threshold_metrics": default_threshold_metrics,
        "best_threshold_metrics": best_threshold_metrics,
        "threshold_rows": threshold_rows,
        "improvement_over_default_threshold": float(
            best_threshold_metrics[threshold_metric] - default_threshold_metrics[threshold_metric]
        ),
    }
    if output_dir:
        output_path = ensure_dir(output_dir)
        write_json(output_path / "tuning_results.json", tuning_results)
        write_json(output_path / "threshold_review.json", threshold_review)
        write_markdown(output_path / "tuning_summary.md", _render_tuning_summary(tuning_results, threshold_review))
    return {
        "tuning_results": tuning_results,
        "threshold_review": threshold_review,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Tune classification candidates and review thresholds for agent-guided modeling.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--selection-metric", default="average_precision")
    parser.add_argument("--threshold-metric", default="f1_positive")
    parser.add_argument("--cv-splits", type=int, default=5)
    args = parser.parse_args()

    df = load_table(args.input_path)

    def job(heartbeat):
        heartbeat("starting classification tuning")
        result = run_classification_tuning(
            df,
            target=args.target,
            output_dir=args.output_dir,
            selection_metric=args.selection_metric,
            threshold_metric=args.threshold_metric,
            n_splits=args.cv_splits,
            heartbeat=heartbeat,
        )
        heartbeat("completed classification tuning")
        return result

    result = run_monitored_job(
        "optimize_runner",
        args.output_dir,
        job,
        heartbeat_interval=1.0,
        stall_after=300.0,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
