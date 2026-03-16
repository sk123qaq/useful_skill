#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import io
import re
from typing import Any

from common import module_available
from evaluate import choose_cv


def select_model_candidates(task: str, is_time_series: bool = False) -> dict[str, Any]:
    if is_time_series:
        return {
            "task": task,
            "execution_mode": "recommendation",
            "models": ["seasonal_naive", "arima_or_sarima", "prophet_if_available", "gradient_boosting_with_lags"],
            "note": "Time-series execution should respect temporal splits and lag design.",
        }
    if task == "classification":
        models = ["hist_gradient_boosting_classifier", "random_forest_classifier"]
        if module_available("xgboost"):
            models.append("xgboost_classifier")
        if module_available("lightgbm"):
            models.append("lightgbm_classifier")
        return {
            "task": task,
            "execution_mode": "baseline",
            "models": models,
        }
    if task == "regression":
        models = ["hist_gradient_boosting_regressor", "random_forest_regressor"]
        if module_available("xgboost"):
            models.append("xgboost_regressor")
        if module_available("lightgbm"):
            models.append("lightgbm_regressor")
        return {
            "task": task,
            "execution_mode": "baseline",
            "models": models,
        }
    return {
        "task": task,
        "execution_mode": "recommendation",
        "models": [],
        "note": "Use descriptive, diagnostic, or business-analysis templates before predictive models.",
    }


def _prepare_matrix(df, target: str):
    if target not in df.columns:
        raise ValueError(f"Unknown target column: {target}")

    model_df = df.dropna(subset=[target]).copy()
    feature_df = model_df.drop(columns=[target])
    encoded = feature_df.copy()
    categorical_columns = list(encoded.select_dtypes(exclude=["number", "bool"]).columns)
    if categorical_columns:
        encoded = encoded.fillna({col: "__MISSING__" for col in categorical_columns})
        encoded = encoded.astype({col: "string" for col in categorical_columns})
        encoded = encoded.assign(**{col: encoded[col].astype("string") for col in categorical_columns})
        encoded = encoded.pipe(lambda frame: __import__("pandas").get_dummies(frame, dummy_na=True))
    else:
        encoded = encoded.fillna(0)

    encoded.columns = [_sanitize_feature_name(column) for column in encoded.columns]

    return encoded, model_df[target]


def _sanitize_feature_name(column: Any) -> str:
    text = str(column)
    text = re.sub(r"[\[\]<>]", "_", text)
    text = re.sub(r"[^0-9a-zA-Z_]+", "_", text)
    return text.strip("_") or "feature"


def build_model_catalog(task: str) -> dict[str, Any]:
    from sklearn.ensemble import (
        HistGradientBoostingClassifier,
        HistGradientBoostingRegressor,
        RandomForestClassifier,
        RandomForestRegressor,
    )

    if task == "classification":
        models: dict[str, Any] = {
            "hist_gradient_boosting_classifier": HistGradientBoostingClassifier(random_state=42),
            "random_forest_classifier": RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=1),
        }
        if module_available("xgboost"):
            from xgboost import XGBClassifier  # type: ignore

            models["xgboost_classifier"] = XGBClassifier(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=42,
                n_jobs=1,
                eval_metric="logloss",
                verbosity=0,
            )
        if module_available("lightgbm"):
            from lightgbm import LGBMClassifier  # type: ignore

            models["lightgbm_classifier"] = LGBMClassifier(
                n_estimators=200,
                learning_rate=0.05,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=42,
                n_jobs=1,
                verbosity=-1,
            )
        return models

    if task == "regression":
        models = {
            "hist_gradient_boosting_regressor": HistGradientBoostingRegressor(random_state=42),
            "random_forest_regressor": RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=1),
        }
        if module_available("xgboost"):
            from xgboost import XGBRegressor  # type: ignore

            models["xgboost_regressor"] = XGBRegressor(
                n_estimators=200,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=42,
                n_jobs=1,
                verbosity=0,
            )
        if module_available("lightgbm"):
            from lightgbm import LGBMRegressor  # type: ignore

            models["lightgbm_regressor"] = LGBMRegressor(
                n_estimators=200,
                learning_rate=0.05,
                subsample=0.9,
                colsample_bytree=0.9,
                random_state=42,
                n_jobs=1,
                verbosity=-1,
            )
        return models

    return {}


def best_model_name_from_report(model_report: dict[str, Any], task: str) -> str | None:
    models = model_report.get("models", {})
    if not models:
        return None

    ranking_metric = "test_f1_weighted" if task == "classification" else "test_r2" if task == "regression" else None
    if ranking_metric is None:
        return None

    candidates = []
    for model_name, metrics in models.items():
        if "error" in metrics or ranking_metric not in metrics:
            continue
        candidates.append((float(metrics[ranking_metric]), model_name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def fit_selected_model(df, target: str, task: str, model_name: str | None = None, test_size: float = 0.2, random_state: int = 42) -> dict[str, Any]:
    from sklearn.model_selection import train_test_split

    if task not in {"classification", "regression"}:
        raise ValueError("Explainability fitting supports classification and regression only.")

    X, y = _prepare_matrix(df, target)
    models = build_model_catalog(task)
    selected_name = model_name or next(iter(models.keys()), None)
    if not selected_name or selected_name not in models:
        raise ValueError(f"Unknown model for {task}: {selected_name}")

    stratify = y if task == "classification" else None
    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=test_size,
        random_state=random_state,
        stratify=stratify,
    )
    model = models[selected_name]
    with contextlib.redirect_stderr(io.StringIO()):
        model.fit(X_train, y_train)
    return {
        "model_name": selected_name,
        "model": model,
        "X_train": X_train,
        "X_test": X_test,
        "y_train": y_train,
        "y_test": y_test,
        "feature_names": list(X.columns),
    }


def run_baseline_model(df, target: str, task: str, time_col: str | None = None) -> dict[str, Any]:
    from sklearn.model_selection import cross_validate

    is_time_series = bool(time_col and time_col in df.columns)
    if is_time_series:
        return select_model_candidates(task, is_time_series=True)

    X, y = _prepare_matrix(df, target)

    if task == "classification":
        models = build_model_catalog(task)
        scoring = ["accuracy", "precision_weighted", "recall_weighted", "f1_weighted"]
        cv = choose_cv(classification=True)
    elif task == "regression":
        models = build_model_catalog(task)
        scoring = ["neg_root_mean_squared_error", "neg_mean_absolute_error", "r2"]
        cv = choose_cv(classification=False)
    else:
        return select_model_candidates(task, is_time_series=False)

    results: dict[str, Any] = {
        "task": task,
        "n_rows_used": int(len(y)),
        "n_features_used": int(X.shape[1]),
        "models": {},
    }
    for name, model in models.items():
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                scores = cross_validate(model, X, y, cv=cv, scoring=scoring, n_jobs=1, error_score="raise")
            results["models"][name] = {
                metric: float(values.mean())
                for metric, values in scores.items()
                if metric.startswith("test_")
            }
        except Exception as exc:
            results["models"][name] = {"error": str(exc)}
    return results
