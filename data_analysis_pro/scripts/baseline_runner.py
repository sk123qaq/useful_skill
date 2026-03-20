from __future__ import annotations

import inspect
import math
from typing import Any

import numpy as np
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

from common import write_artifact
from model_catalog import ModelSpec, get_model_catalog
from schemas import validate_baseline_results


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


def _classification_split_strategy(y: pd.Series, sample_weight: pd.Series | None = None) -> str:
    return "weighted_stratified_greedy" if sample_weight is not None else "stratified_kfold"


def _regression_split_strategy(sample_weight: pd.Series | None = None) -> str:
    return "weighted_kfold_greedy" if sample_weight is not None else "kfold"


def _ordered_labels(y: pd.Series) -> list[Any]:
    labels = list(pd.Series(y).dropna().unique())
    return sorted(labels, key=lambda value: str(value))


def _effective_classification_splits(y: pd.Series, n_splits: int) -> int:
    min_class_count = int(y.value_counts().min())
    return max(2, min(n_splits, min_class_count))


def _folds_from_test_indices(test_indices_by_fold: list[list[int]], length: int) -> list[tuple[np.ndarray, np.ndarray]]:
    all_indices = np.arange(length)
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for test_indices in test_indices_by_fold:
        test_index = np.array(sorted(test_indices), dtype=int)
        train_mask = np.ones(length, dtype=bool)
        train_mask[test_index] = False
        folds.append((all_indices[train_mask], test_index))
    return folds


def _weighted_classification_splits(
    y: pd.Series,
    sample_weight: pd.Series,
    n_splits: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    effective_splits = _effective_classification_splits(y, n_splits)
    weights = pd.Series(sample_weight, index=y.index).fillna(0.0).astype(float)
    test_indices_by_fold: list[list[int]] = [[] for _ in range(effective_splits)]
    total_weight_by_fold = [0.0] * effective_splits
    row_count_by_fold = [0] * effective_splits
    class_weight_by_fold = {
        label: [0.0] * effective_splits
        for label in _ordered_labels(y)
    }
    for label in _ordered_labels(y):
        class_positions = [position for position, value in enumerate(y.tolist()) if value == label]
        class_positions.sort(key=lambda position: (-weights.iloc[position], position))
        for position in class_positions:
            best_fold = min(
                range(effective_splits),
                key=lambda fold: (
                    class_weight_by_fold[label][fold],
                    total_weight_by_fold[fold],
                    row_count_by_fold[fold],
                    fold,
                ),
            )
            test_indices_by_fold[best_fold].append(position)
            class_weight_by_fold[label][best_fold] += float(weights.iloc[position])
            total_weight_by_fold[best_fold] += float(weights.iloc[position])
            row_count_by_fold[best_fold] += 1
    return _folds_from_test_indices(test_indices_by_fold, len(y))


def _weighted_regression_splits(
    length: int,
    sample_weight: pd.Series,
    n_splits: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    effective_splits = max(2, min(n_splits, length))
    weights = pd.Series(sample_weight).fillna(0.0).astype(float).reset_index(drop=True)
    test_indices_by_fold: list[list[int]] = [[] for _ in range(effective_splits)]
    total_weight_by_fold = [0.0] * effective_splits
    row_count_by_fold = [0] * effective_splits
    ordered_positions = list(range(length))
    ordered_positions.sort(key=lambda position: (-weights.iloc[position], position))
    for position in ordered_positions:
        best_fold = min(
            range(effective_splits),
            key=lambda fold: (
                total_weight_by_fold[fold],
                row_count_by_fold[fold],
                fold,
            ),
        )
        test_indices_by_fold[best_fold].append(position)
        total_weight_by_fold[best_fold] += float(weights.iloc[position])
        row_count_by_fold[best_fold] += 1
    return _folds_from_test_indices(test_indices_by_fold, length)


def _classification_splits(
    y: pd.Series,
    n_splits: int,
    sample_weight: pd.Series | None = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    if sample_weight is None:
        splitter = _classification_cv(y, n_splits)
        return list(splitter.split(np.zeros(len(y)), y))
    return _weighted_classification_splits(y, sample_weight, n_splits)


def _regression_splits(
    length: int,
    n_splits: int,
    sample_weight: pd.Series | None = None,
) -> list[tuple[np.ndarray, np.ndarray]]:
    if sample_weight is None:
        splitter = _regression_cv(length, n_splits)
        return list(splitter.split(np.zeros(length)))
    return _weighted_regression_splits(length, sample_weight, n_splits)


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
    sample_weight: pd.Series | None = None,
) -> dict[str, float]:
    positive_label = _positive_label(y_true)
    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred, sample_weight=sample_weight)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred, sample_weight=sample_weight)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", sample_weight=sample_weight)),
        "precision_pos": float(
            precision_score(y_true, y_pred, pos_label=positive_label, zero_division=0, sample_weight=sample_weight)
        ),
        "recall_pos": float(
            recall_score(y_true, y_pred, pos_label=positive_label, zero_division=0, sample_weight=sample_weight)
        ),
    }
    if y_score is not None and pd.Series(y_true).nunique(dropna=True) == 2:
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_score, sample_weight=sample_weight))
        metrics["average_precision"] = float(
            average_precision_score(y_true, y_score, pos_label=positive_label, sample_weight=sample_weight)
        )
        if ((y_score >= 0) & (y_score <= 1)).all():
            metrics["brier_loss"] = float(
                brier_score_loss(y_true, y_score, pos_label=positive_label, sample_weight=sample_weight)
            )
    return metrics


def _regression_metrics(
    y_true: pd.Series,
    y_pred: pd.Series,
    sample_weight: pd.Series | None = None,
) -> dict[str, float]:
    mse = float(mean_squared_error(y_true, y_pred, sample_weight=sample_weight))
    return {
        "rmse": math.sqrt(mse),
        "mae": float(mean_absolute_error(y_true, y_pred, sample_weight=sample_weight)),
        "r2": float(r2_score(y_true, y_pred, sample_weight=sample_weight)),
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


def _estimator_supports_sample_weight(estimator: object) -> bool:
    signature = inspect.signature(estimator.fit)
    return "sample_weight" in signature.parameters


def _fit_pipeline(
    pipeline: Pipeline,
    x_train: pd.DataFrame,
    y_train: pd.Series,
    estimator: object,
    sample_weight: pd.Series | None = None,
) -> None:
    if sample_weight is not None and _estimator_supports_sample_weight(estimator):
        pipeline.fit(x_train, y_train, model__sample_weight=sample_weight.to_numpy())
        return
    pipeline.fit(x_train, y_train)


def _evaluate_model(
    spec: ModelSpec,
    features: pd.DataFrame,
    target: pd.Series,
    task_type: str,
    n_splits: int,
    sample_weight: pd.Series | None = None,
    heartbeat=None,
) -> dict[str, Any]:
    preprocessor = _build_preprocessor(features)
    estimator = spec.builder()
    pipeline = Pipeline([("preprocessor", preprocessor), ("model", estimator)])
    split_strategy = (
        _classification_split_strategy(target, sample_weight)
        if task_type == "classification"
        else _regression_split_strategy(sample_weight)
    )
    splits = (
        _classification_splits(target, n_splits, sample_weight=sample_weight)
        if task_type == "classification"
        else _regression_splits(len(features), n_splits, sample_weight=sample_weight)
    )
    fold_metrics: list[dict[str, float]] = []
    for fold_index, (train_index, test_index) in enumerate(splits, start=1):
        if heartbeat:
            heartbeat(f"evaluating {spec.name} fold {fold_index}")
        x_train = features.iloc[train_index]
        x_test = features.iloc[test_index]
        y_train = target.iloc[train_index]
        y_test = target.iloc[test_index]
        train_weight = sample_weight.iloc[train_index] if sample_weight is not None else None
        test_weight = sample_weight.iloc[test_index] if sample_weight is not None else None
        _fit_pipeline(pipeline, x_train, y_train, estimator, train_weight)
        predictions = pipeline.predict(x_test)
        scores = _classification_scores(pipeline, x_test) if task_type == "classification" else None
        metrics = (
            _classification_metrics(y_test, predictions, scores, sample_weight=test_weight)
            if task_type == "classification"
            else _regression_metrics(y_test, predictions, sample_weight=test_weight)
        )
        fold_metrics.append({"fold": fold_index, **metrics})
    mean_metrics, std_metrics = _summarize_fold_metrics(
        [{key: value for key, value in fold.items() if key != "fold"} for fold in fold_metrics]
    )
    return {
        "model_name": spec.name,
        "level": spec.level,
        "family": spec.family,
        "split_strategy": split_strategy,
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
    weight_col: str | None = None,
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
    feature_drop_columns = [target] + ([weight_col] if weight_col else [])
    features = df.drop(columns=feature_drop_columns)
    target_series = df[target]
    sample_weight = df[weight_col] if weight_col else None
    models: list[dict[str, Any]] = []
    specs = model_specs or get_model_catalog(task_type)
    for spec in specs:
        if max_level is not None and spec.level > max_level:
            continue
        if heartbeat:
            heartbeat(f"starting {spec.name}")
        models.append(
            _evaluate_model(
                spec,
                features,
                target_series,
                task_type,
                n_splits=n_splits,
                sample_weight=sample_weight,
                heartbeat=heartbeat,
            )
        )
    default_metric_name, default_direction = _primary_metric(task_type)
    metric_name = primary_metric or default_metric_name
    direction = metric_direction(metric_name) if primary_metric else default_direction
    best_model = _best_model(models, metric_name, direction)
    best_dummy = _best_model(models, metric_name, direction, family="dummy")
    results = {
        "task_type": task_type,
        "target": target,
        "weight_col": weight_col,
        "split_strategy": (
            _classification_split_strategy(target_series, sample_weight)
            if task_type == "classification"
            else _regression_split_strategy(sample_weight)
        ),
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
    weight_col: str | None = None,
    output_dir: str | None = None,
    time_col: str | None = None,
    n_splits: int = 5,
    max_level: int | None = None,
) -> dict[str, Any]:
    return run_model_ladder(
        df,
        target=target,
        task=task,
        weight_col=weight_col,
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
    weight_col: str | None = None,
    n_splits: int = 5,
    heartbeat=None,
) -> dict[str, Any]:
    target_series = df[target]
    if target_series.nunique(dropna=True) != 2:
        raise ValueError("Threshold review currently requires a binary target.")
    features = df.drop(columns=[target] + ([weight_col] if weight_col else []))
    sample_weight = df[weight_col] if weight_col else None
    splits = _classification_splits(target_series, n_splits, sample_weight=sample_weight)
    oof_scores = pd.Series(index=features.index, dtype=float)
    oof_true = pd.Series(index=features.index, dtype=target_series.dtype)
    for fold_index, (train_index, test_index) in enumerate(splits, start=1):
        if heartbeat:
            heartbeat(f"scoring {spec.name} fold {fold_index}")
        preprocessor = _build_preprocessor(features)
        estimator = spec.builder()
        pipeline = Pipeline([("preprocessor", preprocessor), ("model", estimator)])
        x_train = features.iloc[train_index]
        x_test = features.iloc[test_index]
        y_train = target_series.iloc[train_index]
        y_test = target_series.iloc[test_index]
        train_weight = sample_weight.iloc[train_index] if sample_weight is not None else None
        _fit_pipeline(pipeline, x_train, y_train, estimator, train_weight)
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
        "split_strategy": _classification_split_strategy(target_series, sample_weight),
        "y_true": oof_true,
        "scores": oof_scores,
        "sample_weight": sample_weight,
        "default_metrics": _classification_metrics(oof_true, default_predictions, oof_scores, sample_weight=sample_weight),
    }
