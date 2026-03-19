from __future__ import annotations

import math
from typing import Any

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from data_analysis_V2.scripts.common import write_artifact
from data_analysis_V2.scripts.model_catalog import ModelSpec, get_model_catalog
from data_analysis_V2.scripts.schemas import validate_baseline_results


def _make_one_hot_encoder() -> OneHotEncoder:
    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=False)


def _build_preprocessor(features: pd.DataFrame) -> ColumnTransformer:
    numeric_columns = features.select_dtypes(include=["number", "bool"]).columns.tolist()
    categorical_columns = [column for column in features.columns if column not in numeric_columns]
    numeric_pipeline = Pipeline([("imputer", SimpleImputer(strategy="median"))])
    categorical_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", _make_one_hot_encoder()),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("numeric", numeric_pipeline, numeric_columns),
            ("categorical", categorical_pipeline, categorical_columns),
        ]
    )


def _classification_cv(y: pd.Series, n_splits: int) -> StratifiedKFold:
    min_class_count = int(y.value_counts().min())
    effective_splits = max(2, min(n_splits, min_class_count))
    return StratifiedKFold(n_splits=effective_splits, shuffle=True, random_state=42)


def _regression_cv(length: int, n_splits: int) -> KFold:
    effective_splits = max(2, min(n_splits, length))
    return KFold(n_splits=effective_splits, shuffle=True, random_state=42)


def _positive_label(y_true: pd.Series) -> Any:
    classes = list(pd.Series(y_true).dropna().unique())
    if 1 in classes:
        return 1
    return sorted(classes)[-1]


def _classification_scores(pipeline: Pipeline, x_test: pd.DataFrame) -> pd.Series | None:
    if hasattr(pipeline, "predict_proba"):
        probabilities = pipeline.predict_proba(x_test)
        classes = list(pipeline.classes_)
        positive_label = 1 if 1 in classes else classes[-1]
        positive_index = classes.index(positive_label)
        return pd.Series(probabilities[:, positive_index], index=x_test.index)
    if hasattr(pipeline, "decision_function"):
        scores = pipeline.decision_function(x_test)
        return pd.Series(scores, index=x_test.index)
    return None


def _classification_metrics(
    y_true: pd.Series,
    y_pred: pd.Series,
    y_score: pd.Series | None = None,
) -> dict[str, float]:
    positive_label = _positive_label(y_true)
    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro")),
        "precision_pos": float(precision_score(y_true, y_pred, pos_label=positive_label, zero_division=0)),
        "recall_pos": float(recall_score(y_true, y_pred, pos_label=positive_label, zero_division=0)),
    }
    if y_score is not None and pd.Series(y_true).nunique(dropna=True) == 2:
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_score))
        metrics["average_precision"] = float(average_precision_score(y_true, y_score, pos_label=positive_label))
        if ((y_score >= 0) & (y_score <= 1)).all():
            metrics["brier_loss"] = float(brier_score_loss(y_true, y_score, pos_label=positive_label))
    return metrics


def _regression_metrics(y_true: pd.Series, y_pred: pd.Series) -> dict[str, float]:
    mse = float(mean_squared_error(y_true, y_pred))
    return {
        "rmse": math.sqrt(mse),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "r2": float(r2_score(y_true, y_pred)),
    }


def _summarize_fold_metrics(fold_metrics: list[dict[str, float]]) -> tuple[dict[str, float], dict[str, float]]:
    metric_names = fold_metrics[0].keys()
    mean_metrics = {}
    std_metrics = {}
    for metric in metric_names:
        values = [fold[metric] for fold in fold_metrics]
        mean_metrics[metric] = float(sum(values) / len(values))
        variance = sum((value - mean_metrics[metric]) ** 2 for value in values) / len(values)
        std_metrics[metric] = float(math.sqrt(variance))
    return mean_metrics, std_metrics


def _evaluate_model(
    spec: ModelSpec,
    features: pd.DataFrame,
    target: pd.Series,
    task_type: str,
    n_splits: int,
    heartbeat=None,
) -> dict[str, Any]:
    preprocessor = _build_preprocessor(features)
    estimator = spec.builder()
    pipeline = Pipeline([("preprocessor", preprocessor), ("model", estimator)])
    splitter = _classification_cv(target, n_splits) if task_type == "classification" else _regression_cv(len(features), n_splits)
    fold_metrics: list[dict[str, float]] = []
    for fold_index, (train_index, test_index) in enumerate(splitter.split(features, target), start=1):
        if heartbeat:
            heartbeat(f"evaluating {spec.name} fold {fold_index}")
        x_train = features.iloc[train_index]
        x_test = features.iloc[test_index]
        y_train = target.iloc[train_index]
        y_test = target.iloc[test_index]
        pipeline.fit(x_train, y_train)
        predictions = pipeline.predict(x_test)
        scores = _classification_scores(pipeline, x_test) if task_type == "classification" else None
        metrics = (
            _classification_metrics(y_test, predictions, scores)
            if task_type == "classification"
            else _regression_metrics(y_test, predictions)
        )
        fold_metrics.append({"fold": fold_index, **metrics})
    mean_metrics, std_metrics = _summarize_fold_metrics(
        [{key: value for key, value in fold.items() if key != "fold"} for fold in fold_metrics]
    )
    return {
        "model_name": spec.name,
        "level": spec.level,
        "family": spec.family,
        "fold_metrics": fold_metrics,
        "mean_metrics": mean_metrics,
        "std_metrics": std_metrics,
    }


def metric_direction(metric_name: str) -> str:
    return "min" if metric_name in {"rmse", "mae", "mse", "brier_loss"} else "max"


def _primary_metric(task_type: str) -> tuple[str, str]:
    metric_name = "accuracy" if task_type == "classification" else "rmse"
    return metric_name, metric_direction(metric_name)


def _best_model(models: list[dict[str, Any]], metric_name: str, direction: str, family: str | None = None) -> dict[str, Any]:
    candidates = [model for model in models if family is None or model["family"] == family]
    reverse = direction == "max"
    return sorted(candidates, key=lambda model: model["mean_metrics"][metric_name], reverse=reverse)[0]


def run_model_ladder(
    df: pd.DataFrame,
    target: str,
    task: str,
    model_specs: list[ModelSpec] | None = None,
    output_dir: str | None = None,
    time_col: str | None = None,
    n_splits: int = 5,
    max_level: int | None = None,
    primary_metric: str | None = None,
    artifact_name: str = "baseline_results",
    heartbeat=None,
) -> dict[str, Any]:
    del time_col
    task_type = task
    if task_type not in {"classification", "regression"}:
        raise ValueError(f"Unsupported task for baseline ladder: {task}")
    features = df.drop(columns=[target])
    target_series = df[target]
    models: list[dict[str, Any]] = []
    specs = model_specs or get_model_catalog(task_type)
    for spec in specs:
        if max_level is not None and spec.level > max_level:
            continue
        if heartbeat:
            heartbeat(f"starting {spec.name}")
        models.append(_evaluate_model(spec, features, target_series, task_type, n_splits=n_splits, heartbeat=heartbeat))
    default_metric_name, default_direction = _primary_metric(task_type)
    metric_name = primary_metric or default_metric_name
    direction = metric_direction(metric_name) if primary_metric else default_direction
    best_model = _best_model(models, metric_name, direction)
    best_dummy = _best_model(models, metric_name, direction, family="dummy")
    results = {
        "task_type": task_type,
        "target": target,
        "model_order": [model["model_name"] for model in models],
        "models": models,
        "primary_metric": metric_name,
        "primary_metric_direction": direction,
        "best_model_name": best_model["model_name"],
        "best_dummy_name": best_dummy["model_name"],
    }
    validate_baseline_results(results)
    if output_dir:
        write_artifact(output_dir, artifact_name, results)
    return results


def run_baseline_ladder(
    df: pd.DataFrame,
    target: str,
    task: str,
    output_dir: str | None = None,
    time_col: str | None = None,
    n_splits: int = 5,
    max_level: int | None = None,
) -> dict[str, Any]:
    return run_model_ladder(
        df,
        target=target,
        task=task,
        model_specs=get_model_catalog(task),
        output_dir=output_dir,
        time_col=time_col,
        n_splits=n_splits,
        max_level=max_level,
        primary_metric=None,
        artifact_name="baseline_results",
    )


def collect_binary_classification_oof_scores(
    df: pd.DataFrame,
    target: str,
    spec: ModelSpec,
    n_splits: int = 5,
    heartbeat=None,
) -> dict[str, Any]:
    target_series = df[target]
    if target_series.nunique(dropna=True) != 2:
        raise ValueError("Threshold review currently requires a binary target.")
    features = df.drop(columns=[target])
    splitter = _classification_cv(target_series, n_splits)
    preprocessor = _build_preprocessor(features)
    pipeline = Pipeline([("preprocessor", preprocessor), ("model", spec.builder())])
    oof_scores = pd.Series(index=features.index, dtype=float)
    oof_true = pd.Series(index=features.index, dtype=target_series.dtype)
    for fold_index, (train_index, test_index) in enumerate(splitter.split(features, target_series), start=1):
        if heartbeat:
            heartbeat(f"scoring {spec.name} fold {fold_index}")
        x_train = features.iloc[train_index]
        x_test = features.iloc[test_index]
        y_train = target_series.iloc[train_index]
        y_test = target_series.iloc[test_index]
        pipeline.fit(x_train, y_train)
        scores = _classification_scores(pipeline, x_test)
        if scores is None:
            raise ValueError(f"Model `{spec.name}` does not expose classification scores for threshold review.")
        oof_scores.iloc[test_index] = scores.to_numpy()
        oof_true.iloc[test_index] = y_test.to_numpy()
    positive_label = _positive_label(target_series)
    negative_candidates = [label for label in sorted(target_series.dropna().unique()) if label != positive_label]
    negative_label = negative_candidates[0]
    default_predictions = pd.Series(
        [positive_label if score >= 0.5 else negative_label for score in oof_scores],
        index=oof_scores.index,
    )
    return {
        "positive_label": positive_label,
        "negative_label": negative_label,
        "y_true": oof_true,
        "scores": oof_scores,
        "default_metrics": _classification_metrics(oof_true, default_predictions, oof_scores),
    }
