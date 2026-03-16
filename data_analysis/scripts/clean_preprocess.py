#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import MinMaxScaler, StandardScaler

from common import parse_json_arg
from feature_engineering import add_calendar_features, add_pca_features, add_technical_indicators, encode_categoricals
from io_router import load_dataframe


def column_roles(df, time_col: str | None = None, target: str | None = None) -> dict[str, list[str]]:
    numeric = list(df.select_dtypes(include=["number", "bool"]).columns)
    categorical = [col for col in df.columns if col not in numeric]
    roles = {
        "numeric": numeric,
        "categorical": categorical,
        "time": [time_col] if time_col and time_col in df.columns else [],
        "target": [target] if target and target in df.columns else [],
    }
    return roles


def missing_value_summary(df) -> dict[str, Any]:
    counts = df.isna().sum()
    ratios = (counts / len(df)).fillna(0.0) if len(df) else counts
    return {
        "total_missing_cells": int(counts.sum()),
        "columns_with_missing_values": int((counts > 0).sum()),
        "by_column": {
            col: {
                "missing_count": int(counts[col]),
                "missing_ratio": round(float(ratios[col]), 4),
            }
            for col in df.columns
            if int(counts[col]) > 0
        },
    }


def duplicate_summary(df) -> dict[str, Any]:
    duplicate_rows = int(df.duplicated().sum())
    return {
        "duplicate_rows": duplicate_rows,
        "duplicate_ratio": round(duplicate_rows / len(df), 4) if len(df) else 0.0,
    }


def outliers_iqr(df, numeric_columns: list[str], max_columns: int = 20) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for col in numeric_columns[:max_columns]:
        series = df[col].dropna()
        if len(series) < 4:
            continue
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        mask = (series < lower) | (series > upper)
        results[col] = {
            "outlier_count": int(mask.sum()),
            "outlier_ratio": round(float(mask.mean()), 4),
            "lower_bound": float(lower),
            "upper_bound": float(upper),
        }
    return results


def outliers_zscore(df, numeric_columns: list[str], threshold: float = 3.0, max_columns: int = 20) -> dict[str, Any]:
    import scipy.stats as stats

    results: dict[str, Any] = {}
    for col in numeric_columns[:max_columns]:
        series = df[col].dropna()
        if len(series) < 3:
            continue
        zscores = stats.zscore(series, nan_policy="omit")
        count = int((abs(zscores) > threshold).sum())
        results[col] = {
            "outlier_count": count,
            "outlier_ratio": round(count / len(series), 4),
            "threshold": threshold,
        }
    return results


def outliers_isolation_forest(df, numeric_columns: list[str], max_columns: int = 20) -> dict[str, Any]:
    columns = numeric_columns[:max_columns]
    if len(columns) < 2:
        return {}
    frame = df[columns].dropna()
    if len(frame) < 10:
        return {}
    model = IsolationForest(random_state=42, contamination="auto")
    flags = model.fit_predict(frame)
    outlier_count = int((flags == -1).sum())
    return {
        "columns": columns,
        "rows_scored": int(len(frame)),
        "outlier_count": outlier_count,
        "outlier_ratio": round(outlier_count / len(frame), 4),
    }


def build_preprocessing_plan(df, time_col: str | None = None, target: str | None = None) -> list[str]:
    roles = column_roles(df, time_col=time_col, target=target)
    plan: list[str] = []
    if roles["numeric"]:
        plan.append("Consider median imputation for skewed numeric columns and z-score or robust scaling for model-ready features.")
    if roles["categorical"]:
        plan.append("Review category cardinality and choose one-hot or frequency encoding based on downstream model type.")
    if time_col and time_col in df.columns:
        plan.append("Parse the time column early, sort by time, and create calendar or lag features before temporal modeling.")
    if target and target in df.columns:
        plan.append("Separate target leakage checks from normal feature engineering before train/validation splitting.")
    return plan


def build_cleaning_report(df, time_col: str | None = None, target: str | None = None) -> dict[str, Any]:
    roles = column_roles(df, time_col=time_col, target=target)
    return {
        "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
        "roles": roles,
        "missing_values": missing_value_summary(df),
        "duplicates": duplicate_summary(df),
        "outliers_iqr": outliers_iqr(df, roles["numeric"]),
        "outliers_zscore": outliers_zscore(df, roles["numeric"]),
        "outliers_isolation_forest": outliers_isolation_forest(df, roles["numeric"]),
        "preprocessing_plan": build_preprocessing_plan(df, time_col=time_col, target=target),
    }


def apply_missing_value_strategy(df, config: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    frame = df.copy()
    report: dict[str, Any] = {"actions": []}
    strategy = config.get("strategy")
    columns = config.get("columns")
    if not strategy:
        return frame, report

    target_columns = columns or list(frame.columns)
    if strategy == "drop_rows":
        before = len(frame)
        frame = frame.dropna(subset=target_columns)
        report["actions"].append({"strategy": strategy, "rows_removed": before - len(frame)})
        return frame, report

    if strategy == "mark":
        created = []
        for col in target_columns:
            indicator = f"{col}_was_missing"
            frame[indicator] = frame[col].isna().astype(int)
            created.append(indicator)
        report["actions"].append({"strategy": strategy, "created_columns": created})
        return frame, report

    for col in target_columns:
        if col not in frame.columns:
            continue
        if strategy == "mean":
            frame[col] = frame[col].fillna(frame[col].mean())
        elif strategy == "median":
            frame[col] = frame[col].fillna(frame[col].median())
        elif strategy == "mode":
            modes = frame[col].mode(dropna=True)
            if not modes.empty:
                frame[col] = frame[col].fillna(modes.iloc[0])
        elif strategy == "ffill":
            frame[col] = frame[col].ffill()
        elif strategy == "bfill":
            frame[col] = frame[col].bfill()
        else:
            raise ValueError(f"Unsupported missing value strategy: {strategy}")
    report["actions"].append({"strategy": strategy, "columns": target_columns})
    return frame, report


def apply_scaling(df, config: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    frame = df.copy()
    method = config.get("method")
    if not method:
        return frame, {}
    columns = config.get("columns") or list(frame.select_dtypes(include=["number", "bool"]).columns)
    if not columns:
        return frame, {"method": method, "columns": []}

    scaler = StandardScaler() if method == "zscore" else MinMaxScaler() if method == "minmax" else None
    if scaler is None:
        raise ValueError(f"Unsupported scaling method: {method}")
    frame[columns] = scaler.fit_transform(frame[columns])
    return frame, {"method": method, "columns": columns}


def apply_log_transform(df, columns: list[str]) -> tuple[Any, dict[str, Any]]:
    import numpy as np

    frame = df.copy()
    transformed = []
    for col in columns:
        if col not in frame.columns:
            continue
        min_value = frame[col].dropna().min()
        if min_value <= -1:
            raise ValueError(f"Column {col} contains values <= -1 and cannot use log1p safely.")
        frame[col] = np.log1p(frame[col])
        transformed.append(col)
    return frame, {"columns": transformed}


def apply_feature_steps(df, config: dict[str, Any], time_col: str | None = None) -> tuple[Any, dict[str, Any]]:
    frame = df.copy()
    report: dict[str, Any] = {}
    if config.get("calendar_features") and time_col and time_col in frame.columns:
        frame = add_calendar_features(frame, time_col)
        report["calendar_features"] = True
    if config.get("encode"):
        frame = encode_categoricals(frame, columns=config["encode"].get("columns"))
        report["encoding"] = config["encode"]
    if config.get("technical_indicators"):
        ti_cfg = config["technical_indicators"]
        frame = add_technical_indicators(frame, price_col=ti_cfg["price_col"], time_col=ti_cfg.get("time_col", time_col))
        report["technical_indicators"] = ti_cfg
    if config.get("pca"):
        pca_cfg = config["pca"]
        frame, pca_report = add_pca_features(frame, columns=pca_cfg["columns"], n_components=pca_cfg.get("n_components", 2))
        report["pca"] = pca_report
    return frame, report


def run_preprocessing(df, config: dict[str, Any], time_col: str | None = None) -> tuple[Any, dict[str, Any]]:
    frame = df.copy()
    steps: dict[str, Any] = {}

    if config.get("missing"):
        frame, steps["missing"] = apply_missing_value_strategy(frame, config["missing"])
    if config.get("log_transform"):
        frame, steps["log_transform"] = apply_log_transform(frame, config["log_transform"])
    if config.get("scale"):
        frame, steps["scale"] = apply_scaling(frame, config["scale"])
    if config.get("features"):
        frame, steps["features"] = apply_feature_steps(frame, config["features"], time_col=time_col)

    return frame, steps


def save_transformed_data(df, output_path: str) -> None:
    path = Path(output_path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df.to_csv(path, index=False)
        return
    if suffix in {".parquet", ".pq"}:
        df.to_parquet(path, index=False)
        return
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        df.to_excel(path, index=False)
        return
    raise ValueError(f"Unsupported output format: {suffix}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a cleaning and preprocessing summary.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--time-col")
    parser.add_argument("--target")
    parser.add_argument("--config-json", help="Optional preprocessing config JSON.")
    parser.add_argument("--output-path", help="Optional path to save transformed data.")
    args = parser.parse_args()

    df = load_dataframe(args.input_path)
    report = build_cleaning_report(df, time_col=args.time_col, target=args.target)
    config = parse_json_arg(args.config_json)
    if config:
        transformed, execution_report = run_preprocessing(df, config, time_col=args.time_col)
        report["execution"] = execution_report
        report["transformed_shape"] = {"rows": int(transformed.shape[0]), "columns": int(transformed.shape[1])}
        if args.output_path:
            save_transformed_data(transformed, args.output_path)
            report["output_path"] = str(Path(args.output_path).resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
