#!/usr/bin/env python3
"""Cleaning primitives.

This module is deliberately side-effect free: no global registry, no writes to
the current working directory. The CLI is retained as a thin compatibility
wrapper; new workflows should call clean.py / features.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402
import io_router  # noqa: E402


def missing_summary(df: pd.DataFrame) -> dict[str, Any]:
    counts = df.isna().sum()
    ratios = (counts / len(df)).fillna(0.0) if len(df) else counts
    return {
        "total_missing": int(counts.sum()),
        "by_column": {
            str(col): {"count": int(counts[col]), "pct": float(ratios[col])}
            for col in df.columns if counts[col] > 0
        },
    }


def _normalize_subset(df: pd.DataFrame, subset: list[str] | None) -> tuple[list[str] | None, list[str]]:
    if subset is None:
        return None, []
    present = [c for c in subset if c in df.columns]
    missing = [c for c in subset if c not in df.columns]
    return (present or None), missing


def duplicate_summary(df: pd.DataFrame, key_columns: list[str] | None = None, top_n: int = 5) -> dict[str, Any]:
    subset, missing = _normalize_subset(df, key_columns)
    duplicates = df.duplicated(subset=subset, keep=False)
    groups = int(df.loc[duplicates].groupby(subset, dropna=False).ngroups) if subset and duplicates.any() else int(duplicates.sum())
    return {
        "key_columns": subset,
        "missing_key_columns": missing,
        "rows_in_duplicate_groups": int(duplicates.sum()),
        "duplicate_groups": int(groups),
        "extra_rows": int(df.duplicated(subset=subset).sum()),
        "pct_rows_in_duplicate_groups": float(duplicates.mean()) if len(df) else 0.0,
        "examples": df.loc[duplicates].head(top_n).to_dict(orient="records"),
    }


def encode_categoricals(df: pd.DataFrame, columns: list[str] | None = None, dummy_na: bool = True) -> pd.DataFrame:
    frame = df.copy()
    target_cols = columns or list(frame.select_dtypes(exclude=["number", "bool"]).columns)
    target_cols = [c for c in target_cols if c in frame.columns and not pd.api.types.is_datetime64_any_dtype(frame[c])]
    if not target_cols:
        return frame
    frame[target_cols] = frame[target_cols].fillna("__MISSING__").astype("string")
    return pd.get_dummies(frame, columns=target_cols, dummy_na=dummy_na)


def add_calendar_features(df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    if time_col not in df.columns:
        return df
    frame = df.copy()
    t = pd.to_datetime(frame[time_col], errors="coerce")
    frame[f"{time_col}_year"] = t.dt.year
    frame[f"{time_col}_month"] = t.dt.month
    frame[f"{time_col}_day"] = t.dt.day
    frame[f"{time_col}_dow"] = t.dt.dayofweek
    return frame


def apply_cleaning(df: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = df.copy()
    report: dict[str, Any] = {"actions": [], "initial_rows": int(len(frame))}

    missing = config.get("missing", {})
    if missing:
        strategy = missing.get("strategy", "drop")
        columns = [c for c in missing.get("columns", list(frame.columns)) if c in frame.columns]
        if strategy == "drop" and columns:
            before = len(frame)
            frame = frame.dropna(subset=columns)
            report["actions"].append(f"dropped {before - len(frame)} rows with missing values in {columns}")
        elif strategy in {"mean", "median", "mode"}:
            for col in columns:
                if frame[col].isna().any():
                    if strategy == "mode":
                        mode = frame[col].mode(dropna=True)
                        value = mode.iloc[0] if not mode.empty else None
                    else:
                        value = getattr(frame[col], strategy)()
                    if value is not None and not (isinstance(value, float) and np.isnan(value)):
                        frame[col] = frame[col].fillna(value)
            report["actions"].append(f"filled missing values in {columns} with {strategy}")

    dedupe = config.get("drop_duplicates")
    if isinstance(dedupe, bool):
        dedupe = {"enabled": dedupe}
    if isinstance(dedupe, dict) and dedupe.get("enabled", True):
        subset, _ = _normalize_subset(frame, dedupe.get("subset"))
        keep = dedupe.get("keep", "first")
        if keep not in {"first", "last", False}:
            keep = "first"
        before = len(frame)
        frame = frame.drop_duplicates(subset=subset, keep=keep)
        report["dedupe"] = {"removed_rows": before - len(frame), "subset": subset, "keep": keep}
        report["actions"].append(f"removed {before - len(frame)} duplicate rows")

    capping = config.get("outlier_capping", {})
    capped = []
    for col, params in (capping.get("columns", {}) if isinstance(capping, dict) else {}).items():
        if col not in frame.columns or not pd.api.types.is_numeric_dtype(frame[col]):
            continue
        method = params.get("method", "quantile")
        if method == "quantile":
            lower = frame[col].quantile(params.get("lower", 0.0))
            upper = frame[col].quantile(params.get("upper", 1.0))
        else:
            lower = params.get("lower", -np.inf)
            upper = params.get("upper", np.inf)
        frame[col] = frame[col].clip(lower=lower, upper=upper)
        capped.append(f"{col}:[{lower}, {upper}]")
    if capped:
        report["actions"].append("capped outliers: " + ", ".join(capped))

    report["final_rows"] = int(len(frame))
    report["removed_rows"] = int(report["initial_rows"] - len(frame))
    return frame, report


def build_schema(df: pd.DataFrame, target: str | None = None, time_col: str | None = None) -> dict[str, Any]:
    fields = []
    for col in df.columns:
        fields.append({
            "name": str(col),
            "label": common.friendly_label(str(col)),
            "dtype": str(df[col].dtype),
            "unique": int(df[col].nunique(dropna=True)),
            "missing_pct": float(df[col].isna().mean()),
            "role": "target" if col == target else "time" if col == time_col else "feature",
        })
    return {"fields": fields, "target": target, "time_col": time_col}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compatibility cleaning CLI; prefer clean.py.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--target")
    parser.add_argument("--time-col")
    parser.add_argument("--config-json")
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--report-path", default="cleaning_report.json")
    args = parser.parse_args()

    config = json.loads(args.config_json) if args.config_json else {}
    df = io_router.load_dataframe(args.input_path, auto_sample=False)
    report = {
        "initial_stats": {
            "missing": missing_summary(df),
            "duplicates": duplicate_summary(df, key_columns=config.get("duplicate_check", {}).get("key_columns")
                                            if isinstance(config.get("duplicate_check"), dict) else None),
            "schema": build_schema(df, target=args.target, time_col=args.time_col),
        }
    }
    cleaned, clean_report = apply_cleaning(df, config)
    report["cleaning"] = clean_report
    if config.get("encode"):
        cleaned = encode_categoricals(cleaned)
        report["encoded"] = True
    p = Path(args.output_path)
    if p.suffix.lower() == ".csv":
        cleaned.to_csv(p, index=False)
    else:
        cleaned.to_parquet(p, index=False)
    report["output_path"] = str(p.resolve())
    common.write_json(args.report_path, report)
    print(json.dumps({"output_path": str(p.resolve()), "rows": len(cleaned), "report_path": str(Path(args.report_path).resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
