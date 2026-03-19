from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression, Ridge


@dataclass(frozen=True)
class ModelSpec:
    name: str
    task_type: str
    level: int
    family: str
    builder: Callable[[], object]


def get_model_catalog(task_type: str) -> list[ModelSpec]:
    if task_type == "classification":
        return [
            ModelSpec("dummy_most_frequent", "classification", 0, "dummy", lambda: DummyClassifier(strategy="most_frequent")),
            ModelSpec("logistic_regression", "classification", 1, "linear", lambda: LogisticRegression(max_iter=1000, solver="liblinear", random_state=42)),
            ModelSpec("random_forest_classifier", "classification", 2, "tree", lambda: RandomForestClassifier(n_estimators=100, random_state=42)),
        ]
    if task_type == "regression":
        return [
            ModelSpec("dummy_mean", "regression", 0, "dummy", lambda: DummyRegressor(strategy="mean")),
            ModelSpec("dummy_median", "regression", 0, "dummy", lambda: DummyRegressor(strategy="median")),
            ModelSpec("linear_regression", "regression", 1, "linear", lambda: LinearRegression()),
            ModelSpec("random_forest_regressor", "regression", 2, "tree", lambda: RandomForestRegressor(n_estimators=100, random_state=42)),
        ]
    raise ValueError(f"Unsupported task_type: {task_type}")


def get_tuning_catalog(task_type: str) -> list[ModelSpec]:
    if task_type == "classification":
        return [
            ModelSpec(
                "logistic_regression_balanced_c0_5",
                "classification",
                3,
                "linear",
                lambda: LogisticRegression(
                    C=0.5,
                    class_weight="balanced",
                    max_iter=1000,
                    solver="liblinear",
                    random_state=42,
                ),
            ),
            ModelSpec(
                "logistic_regression_balanced_c1",
                "classification",
                3,
                "linear",
                lambda: LogisticRegression(
                    C=1.0,
                    class_weight="balanced",
                    max_iter=1000,
                    solver="liblinear",
                    random_state=42,
                ),
            ),
            ModelSpec(
                "logistic_regression_balanced_c4",
                "classification",
                3,
                "linear",
                lambda: LogisticRegression(
                    C=4.0,
                    class_weight="balanced",
                    max_iter=1000,
                    solver="liblinear",
                    random_state=42,
                ),
            ),
            ModelSpec(
                "random_forest_classifier_balanced_leaf5",
                "classification",
                4,
                "tree",
                lambda: RandomForestClassifier(
                    class_weight="balanced_subsample",
                    min_samples_leaf=5,
                    n_estimators=200,
                    random_state=42,
                ),
            ),
            ModelSpec(
                "random_forest_classifier_balanced_depth12",
                "classification",
                4,
                "tree",
                lambda: RandomForestClassifier(
                    class_weight="balanced_subsample",
                    max_depth=12,
                    min_samples_leaf=2,
                    n_estimators=300,
                    random_state=42,
                ),
            ),
        ]
    if task_type == "regression":
        return [
            ModelSpec("ridge_alpha_1", "regression", 3, "linear", lambda: Ridge(alpha=1.0)),
            ModelSpec("ridge_alpha_10", "regression", 3, "linear", lambda: Ridge(alpha=10.0)),
            ModelSpec(
                "random_forest_regressor_depth12",
                "regression",
                4,
                "tree",
                lambda: RandomForestRegressor(
                    max_depth=12,
                    min_samples_leaf=5,
                    n_estimators=200,
                    random_state=42,
                ),
            ),
        ]
    raise ValueError(f"Unsupported task_type: {task_type}")


def get_model_spec(task_type: str, model_name: str, include_tuning: bool = False) -> ModelSpec:
    catalog = list(get_model_catalog(task_type))
    if include_tuning:
        catalog.extend(get_tuning_catalog(task_type))
    for spec in catalog:
        if spec.name == model_name:
            return spec
    raise ValueError(f"Unknown model_name for {task_type}: {model_name}")
