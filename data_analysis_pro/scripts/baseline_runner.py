#!/usr/bin/env python3
"""baseline_runner.py: CLI-first baseline ladder with leakage-safe splits."""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score, f1_score, log_loss, mean_absolute_error, mean_squared_error,
    r2_score, roc_auc_score,
)
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402
import io_router  # noqa: E402
from model_catalog import get_model_catalog, get_model_spec  # noqa: E402
from split_plan import create_plan, validate_plan  # noqa: E402
from workflow import file_sha256, load_json, write_json  # noqa: E402

warnings.filterwarnings("ignore", category=UserWarning)


def _num(value: Any) -> float | None:
    try:
        out = float(value)
        return out if np.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _features(df: pd.DataFrame, target: str, time_col: str | None, group_col: str | None) -> tuple[list[str], list[str]]:
    excluded = {target, time_col, group_col}
    numeric, categorical = [], []
    for col in df.columns:
        if col in excluded or pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        if pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col]):
            numeric.append(str(col))
        else:
            categorical.append(str(col))
    return numeric, categorical


def _preprocessor(numeric: list[str], categorical: list[str]) -> ColumnTransformer:
    transformers = []
    if numeric:
        transformers.append(("num", Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]), numeric))
    if categorical:
        transformers.append(("cat", Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]), categorical))
    return ColumnTransformer(transformers=transformers, remainder="drop")


def _metric_set(task: str, y_true: pd.Series, y_pred: np.ndarray, proba: np.ndarray | None) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    if task == "regression":
        out["rmse"] = _num(np.sqrt(mean_squared_error(y_true, y_pred)))
        out["mae"] = _num(mean_absolute_error(y_true, y_pred))
        out["r2"] = _num(r2_score(y_true, y_pred))
        return out
    out["accuracy"] = _num(accuracy_score(y_true, y_pred))
    out["f1_macro"] = _num(f1_score(y_true, y_pred, average="macro", zero_division=0))
    if proba is not None:
        try:
            out["log_loss"] = _num(log_loss(y_true, proba, labels=list(np.unique(y_true))))
        except Exception:
            out["log_loss"] = None
        if len(np.unique(y_true)) == 2:
            try:
                out["roc_auc"] = _num(roc_auc_score(y_true, proba[:, 1]))
            except Exception:
                out["roc_auc"] = None
    return out


def _fit_one(spec, X_train, y_train, X_test, numeric, categorical):
    model = spec.builder()
    pipe = Pipeline([("prep", _preprocessor(numeric, categorical)), ("model", model)])
    pipe.fit(X_train, y_train)
    pred = pipe.predict(X_test)
    proba = None
    if hasattr(pipe, "predict_proba"):
        try:
            proba = pipe.predict_proba(X_test)
        except Exception:
            proba = None
    return pred, proba


def _summarize(fold_metrics: list[dict[str, Any]], metric_names: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    mean, std = {}, {}
    for name in metric_names:
        values = [row[name] for row in fold_metrics if row.get(name) is not None]
        mean[name] = _num(np.mean(values)) if values else None
        std[name] = _num(np.std(values)) if values else None
    return mean, std


def _default_metric(task: str, requested: str | None) -> tuple[str, str]:
    if requested:
        return requested, "lower" if requested in {"rmse", "mae", "log_loss"} else "higher"
    return ("rmse", "lower") if task == "regression" else ("f1_macro", "higher")


def run_baseline(
    df: pd.DataFrame,
    target: str,
    task: str,
    *,
    time_col: str | None = None,
    group_col: str | None = None,
    split_plan: dict[str, Any] | None = None,
    model_names: list[str] | None = None,
    max_level: int = 2,
    primary_metric: str | None = None,
    n_splits: int = 5,
    test_size: float = 0.3,
    gap: int = 0,
    seed: int = 42,
) -> dict[str, Any]:
    if task not in {"classification", "regression"}:
        raise ValueError("task must be classification or regression")
    if target not in df.columns:
        raise ValueError(f"target not found: {target}")
    frame = df.dropna(subset=[target]).reset_index(drop=True)
    if len(frame) < 20:
        raise ValueError("need at least 20 rows with non-missing target")
    numeric, categorical = _features(frame, target, time_col, group_col)
    if not numeric and not categorical:
        raise ValueError("no usable features after excluding target/time/group")
    if model_names:
        specs = [get_model_spec(task, name, include_tuning=True) for name in model_names]
    else:
        specs = [spec for spec in get_model_catalog(task) if spec.level <= max_level]
    if split_plan is None:
        strategy = "temporal" if time_col and time_col in frame.columns else "kfold"
        split_plan = create_plan(frame, target, time_col, strategy, n_splits, test_size, group_col, gap, seed)
    errors = validate_plan(split_plan, frame)
    if errors:
        raise ValueError("invalid split plan: " + "; ".join(errors))

    metric_name, direction = _default_metric(task, primary_metric)
    model_results = []
    for spec in specs:
        fold_metrics, fold_errors = [], []
        for fold in split_plan["folds"]:
            train_idx = [i for i in fold["train_indices"] if i < len(frame)]
            test_idx = [i for i in fold["test_indices"] if i < len(frame)]
            if not train_idx or not test_idx:
                continue
            train = frame.iloc[train_idx]
            test = frame.iloc[test_idx]
            if task == "classification" and train[target].nunique() < 2:
                fold_errors.append(f"fold {fold['fold']}: train has one class")
                continue
            try:
                pred, proba = _fit_one(spec, train[numeric + categorical], train[target],
                                       test[numeric + categorical], numeric, categorical)
                metrics = _metric_set(task, test[target], pred, proba)
                metrics["fold"] = int(fold["fold"])
                metrics["n_train"] = len(train)
                metrics["n_test"] = len(test)
                fold_metrics.append(metrics)
            except Exception as exc:
                fold_errors.append(f"fold {fold['fold']}: {type(exc).__name__}: {exc}")
        mean, std = _summarize(fold_metrics, [metric_name] + (["rmse", "mae", "r2"] if task == "regression" else ["accuracy", "f1_macro", "log_loss", "roc_auc"]))
        model_results.append({
            "model_name": spec.name,
            "level": spec.level,
            "family": spec.family,
            "fold_metrics": fold_metrics,
            "mean_metrics": mean,
            "std_metrics": std,
            "errors": fold_errors,
        })

    valid = [m for m in model_results if m["mean_metrics"].get(metric_name) is not None]
    if not valid:
        raise ValueError("every model failed or produced no metric")
    reverse = direction == "higher"
    valid.sort(key=lambda m: m["mean_metrics"][metric_name], reverse=reverse)
    best = valid[0]
    dummies = [m for m in valid if m["family"] == "dummy"]
    non_dummies = [m for m in valid if m["family"] != "dummy"]
    best_dummy = dummies[0] if dummies else (min(valid, key=lambda m: m["level"]) if valid else None)
    best_non_dummy = non_dummies[0] if non_dummies else None

    comparison = {"metric": metric_name, "direction": direction, "threshold": None, "beats_dummy": False,
                  "delta": None, "relative": None}
    if best_dummy and best_non_dummy:
        dummy_value = best_dummy["mean_metrics"][metric_name]
        model_value = best_non_dummy["mean_metrics"][metric_name]
        if dummy_value is not None and model_value is not None:
            delta = (model_value - dummy_value) if reverse else (dummy_value - model_value)
            relative = delta / abs(dummy_value) if dummy_value not in (0, None) else None
            threshold = 0.02 if task == "classification" else 0.05
            comparison.update({
                "dummy_model": best_dummy["model_name"],
                "best_non_dummy": best_non_dummy["model_name"],
                "dummy_value": _num(dummy_value),
                "model_value": _num(model_value),
                "delta": _num(delta),
                "relative": _num(relative),
                "threshold": threshold,
                "beats_dummy": bool(relative is not None and relative >= threshold),
            })

    stability = {"metric": metric_name, "std": best["std_metrics"].get(metric_name),
                 "mean": best["mean_metrics"].get(metric_name), "ratio": None, "stable": None}
    if stability["std"] is not None and stability["mean"] not in (None, 0):
        ratio = abs(stability["std"] / stability["mean"])
        stability["ratio"] = _num(ratio)
        stability["stable"] = bool(ratio <= 0.2)

    return {
        "stage": "baseline",
        "task_type": task,
        "target": target,
        "time_col": time_col,
        "group_col": group_col,
        "n_rows": int(len(frame)),
        "features": {"numeric": numeric, "categorical": categorical},
        "primary_metric": metric_name,
        "primary_metric_direction": direction,
        "split_strategy": split_plan.get("strategy"),
        "split_plan": split_plan,
        "models": model_results,
        "best_model_name": best["model_name"],
        "best_dummy_name": best_dummy["model_name"] if best_dummy else None,
        "dummy_comparison": comparison,
        "stability": stability,
        "warnings": [],
        "created_at": common.now_utc_iso(),
    }


def run_model_ladder(df: pd.DataFrame, target: str, task: str, **kwargs) -> dict[str, Any]:
    """Compatibility wrapper for the old Python helper."""
    return run_baseline(df, target, task, **kwargs)


def run_baseline_ladder(df: pd.DataFrame, target: str, task: str, **kwargs) -> dict[str, Any]:
    return run_baseline(df, target, task, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit baseline models on explicit folds.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--task", required=True, choices=["classification", "regression"])
    parser.add_argument("--time-col", default=None)
    parser.add_argument("--group-col", default=None)
    parser.add_argument("--split-plan", default=None)
    parser.add_argument("--models", default=None, help="comma-separated model names")
    parser.add_argument("--max-level", type=int, default=2)
    parser.add_argument("--primary-metric", default=None)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--test-size", type=float, default=0.3)
    parser.add_argument("--gap", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--comment", default=None)
    args = parser.parse_args()

    df = io_router.load_dataframe(args.input_path, auto_sample=False, sheet=args.sheet, comment=args.comment)
    plan = load_json(args.split_plan) if args.split_plan else None
    if plan and plan.get("data_hash") and plan["data_hash"] != file_sha256(args.input_path):
        print("warning: split_plan data_hash differs from input; indices may not align")
    model_names = [m.strip() for m in args.models.split(",") if m.strip()] if args.models else None
    report = run_baseline(
        df, args.target, args.task, time_col=args.time_col, group_col=args.group_col,
        split_plan=plan, model_names=model_names, max_level=args.max_level,
        primary_metric=args.primary_metric, n_splits=args.n_splits,
        test_size=args.test_size, gap=args.gap, seed=args.seed,
    )
    report["source"] = str(Path(args.input_path).resolve())
    report["data_hash"] = file_sha256(args.input_path)
    write_json(args.output_path, report)
    print(f"wrote {args.output_path}: best={report['best_model_name']} "
          f"{report['primary_metric']}={report['models'][0]['mean_metrics'].get(report['primary_metric'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
