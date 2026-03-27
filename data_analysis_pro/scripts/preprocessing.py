#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

# Add the scripts directory to sys.path so we can import common and io_router
sys.path.append(str(Path(__file__).parent))
import common
import io_router
from metadata_manager import MetadataManager

manager = MetadataManager()

def missing_summary(df) -> dict[str, Any]:
    counts = df.isna().sum()
    ratios = (counts / len(df)).fillna(0.0) if len(df) else counts
    return {
        "total_missing": int(counts.sum()),
        "by_column": {col: {"count": int(counts[col]), "pct": float(ratios[col])} 
                      for col in df.columns if counts[col] > 0}
    }

def _normalize_subset(df: pd.DataFrame, subset: list[str] | None) -> tuple[list[str] | None, list[str]]:
    if not subset:
        return None, []
    valid = [col for col in subset if col in df.columns]
    missing = [col for col in subset if col not in df.columns]
    return (valid or None), missing

def _duplicate_examples(df: pd.DataFrame, subset: list[str], top_n: int = 5) -> list[dict[str, Any]]:
    if df.empty or not subset:
        return []
    duplicate_mask = df.duplicated(subset=subset, keep=False)
    if not duplicate_mask.any():
        return []

    grouped = (
        df.loc[duplicate_mask, subset]
        .value_counts(dropna=False)
        .head(top_n)
    )
    examples: list[dict[str, Any]] = []
    for values, count in grouped.items():
        if not isinstance(values, tuple):
            values = (values,)
        examples.append({
            "key": {column: (None if pd.isna(value) else str(value)) for column, value in zip(subset, values)},
            "count": int(count),
        })
    return examples

def duplicate_summary(
    df: pd.DataFrame,
    key_columns: list[str] | None = None,
    top_n: int = 5,
) -> dict[str, Any]:
    dup_count = int(df.duplicated().sum())
    summary: dict[str, Any] = {
        "count": dup_count,
        "pct": float(dup_count / len(df)) if len(df) else 0.0,
        "exact_row_duplicates": {
            "count": dup_count,
            "pct": float(dup_count / len(df)) if len(df) else 0.0,
        },
        "warning": (
            "Exact duplicate rows may still be valid repeated observations. "
            "Confirm row grain and business keys before removing duplicates."
        ),
    }

    normalized_keys, missing_keys = _normalize_subset(df, key_columns)
    if key_columns:
        summary["key_columns_requested"] = key_columns
    if missing_keys:
        summary["missing_key_columns"] = missing_keys
    if normalized_keys:
        key_duplicate_mask = df.duplicated(subset=normalized_keys, keep=False)
        grouped = df.loc[key_duplicate_mask, normalized_keys].value_counts(dropna=False)
        duplicate_groups = int(grouped.shape[0])
        rows_in_duplicate_groups = int(grouped.sum()) if duplicate_groups else 0
        extra_rows = int((grouped - 1).clip(lower=0).sum()) if duplicate_groups else 0
        summary["key_duplicates"] = {
            "key_columns": normalized_keys,
            "groups": duplicate_groups,
            "rows_in_duplicate_groups": rows_in_duplicate_groups,
            "extra_rows": extra_rows,
            "pct_rows_in_duplicate_groups": float(rows_in_duplicate_groups / len(df)) if len(df) else 0.0,
            "examples": _duplicate_examples(df, normalized_keys, top_n=top_n),
        }
    return summary

def _normalize_drop_duplicates_config(config_value: Any) -> dict[str, Any]:
    if isinstance(config_value, bool):
        return {"enabled": config_value, "subset": None, "keep": "first"}
    if isinstance(config_value, dict):
        keep = config_value.get("keep", "first")
        if keep not in {"first", "last", False}:
            keep = "first"
        return {
            "enabled": bool(config_value.get("enabled", True)),
            "subset": config_value.get("subset"),
            "keep": keep,
        }
    return {"enabled": False, "subset": None, "keep": "first"}

def encode_categoricals(df, columns: list[str] | None = None, dummy_na: bool = True):
    frame = df.copy()
    target_cols = columns or list(frame.select_dtypes(exclude=["number", "bool"]).columns)
    if not target_cols: return frame
    frame[target_cols] = frame[target_cols].fillna("__MISSING__").astype("string")
    result = pd.get_dummies(frame, columns=target_cols, dummy_na=dummy_na)
    
    # Register Lineage for Categorical Encoding
    for col in target_cols:
        derived = [c for c in result.columns if c.startswith(f"{col}_")]
        for d in derived:
            manager.register_lineage(
                target=d,
                sources=[col],
                operation="one_hot_encoding",
                reason=f"Derived from categorical feature '{col}'"
            )
    return result

def add_calendar_features(df, time_col: str):
    if time_col not in df.columns: return df
    frame = df.copy()
    t = pd.to_datetime(frame[time_col], errors="coerce")
    
    new_cols = {
        f"{time_col}_year": t.dt.year,
        f"{time_col}_month": t.dt.month,
        f"{time_col}_day": t.dt.day,
        f"{time_col}_dow": t.dt.dayofweek
    }
    
    for name, series in new_cols.items():
        frame[name] = series
        # Register Lineage for Calendar Features
        manager.register_lineage(
            target=name,
            sources=[time_col],
            operation="calendar_extraction",
            reason=f"Extracted from time column '{time_col}'"
        )
    return frame

def apply_cleaning(df, config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = df.copy()
    report = {"actions": []}
    
    # Simple Missing Value Strategy
    if "missing" in config:
        strat = config["missing"].get("strategy", "drop")
        cols = config["missing"].get("columns", list(frame.columns))
        if strat == "drop":
            before = len(frame)
            frame = frame.dropna(subset=cols)
            report["actions"].append(f"Dropped {before - len(frame)} rows with missing values")
            # Register Lineage for Row Dropping
            manager.register_lineage(
                target="dataset",
                sources=cols,
                operation="missing_value_drop",
                reason=f"Dropped {before - len(frame)} rows due to nulls in {cols}"
            )
        elif strat in ["mean", "median", "mode"]:
            for col in cols:
                if col in frame.columns:
                    val = getattr(frame[col], strat)()
                    if isinstance(val, pd.Series): val = val.iloc[0]
                    frame[col] = frame[col].fillna(val)
                    # Register Lineage for Imputation
                    manager.register_lineage(
                        target=col,
                        sources=[col],
                        operation=f"imputation_{strat}",
                        reason=f"Filled missing values with column {strat}: {val}"
                    )
            report["actions"].append(f"Filled missing in {cols} with {strat}")

    dedupe_config = _normalize_drop_duplicates_config(config.get("drop_duplicates"))
    if dedupe_config["enabled"]:
        before = len(frame)
        subset, missing_subset = _normalize_subset(frame, dedupe_config["subset"])
        frame = frame.drop_duplicates(subset=subset, keep=dedupe_config["keep"])
        removed = before - len(frame)
        
        # Register Lineage for Deduplication
        if removed > 0:
            manager.register_lineage(
                target="dataset", 
                sources=list(frame.columns), 
                operation="drop_duplicates", 
                reason=f"Removed {removed} duplicates (keep={dedupe_config['keep']})"
            )

        dedupe_report: dict[str, Any] = {
            "removed_rows": removed,
            "keep": dedupe_config["keep"],
            "subset": subset,
        }
        if missing_subset:
            dedupe_report["missing_subset_columns"] = missing_subset
        report["dedupe"] = dedupe_report
        if subset:
            report["actions"].append(
                f"Removed {removed} duplicate rows based on columns {subset} (keep={dedupe_config['keep']})"
            )
        else:
            report["actions"].append(
                f"Removed {removed} exact duplicate rows across all columns (keep={dedupe_config['keep']})"
            )

    # Outlier Capping
    if "outlier_capping" in config:
        cap_config = config["outlier_capping"]
        target_cols = cap_config.get("columns", {})
        capped_info = []
        for col, params in target_cols.items():
            if col not in frame.columns:
                continue
            
            method = params.get("method", "quantile")
            if method == "quantile":
                upper_q = params.get("upper", 1.0)
                lower_q = params.get("lower", 0.0)
                upper_val = frame[col].quantile(upper_q)
                lower_val = frame[col].quantile(lower_q)
            else: # fixed
                upper_val = params.get("upper", float("inf"))
                lower_val = params.get("lower", float("-inf"))
            
            frame[col] = frame[col].clip(lower=lower_val, upper=upper_val)
            capped_info.append(f"{col}({method}: {lower_val} to {upper_val})")
            
            # Register Lineage for Outlier Capping per column
            manager.register_lineage(
                target=col,
                sources=[col],
                operation="outlier_capping",
                reason=f"Applied capping via {method} (lower: {lower_val}, upper: {upper_val})"
            )
        
        if capped_info:
            report["actions"].append(f"Applied outlier capping to: {', '.join(capped_info)}")

    return frame, report

def build_schema(df, target=None, time_col=None):
    fields = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        unique = int(df[col].nunique())
        missing = float(df[col].isna().mean())
        fields.append({
            "name": col, "label": common.friendly_label(col),
            "dtype": dtype, "unique": unique, "missing_pct": missing,
            "role": "target" if col == target else "time" if col == time_col else "feature"
        })
    return {"fields": fields, "target": target, "time_col": time_col}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--target")
    parser.add_argument("--time-col")
    parser.add_argument("--config-json")
    parser.add_argument("--output-path")
    args = parser.parse_args()

    config = json.loads(args.config_json) if args.config_json else {}
    duplicate_check = config.get("duplicate_check", {})
    duplicate_keys = duplicate_check.get("key_columns") if isinstance(duplicate_check, dict) else None

    df = io_router.load_dataframe(args.input_path)
    report = {
        "initial_stats": {
            "missing": missing_summary(df),
            "duplicates": duplicate_summary(df, key_columns=duplicate_keys),
            "schema": build_schema(df, target=args.target, time_col=args.time_col)
        }
    }
    
    if args.config_json:
        df, clean_report = apply_cleaning(df, config)
        report["cleaning"] = clean_report
        
        if config.get("encode"):
            df = encode_categoricals(df)
            report["encoded"] = True
            
        if args.output_path:
            # Simple save based on extension
            p = Path(args.output_path)
            if p.suffix == ".csv": df.to_csv(p, index=False)
            else: df.to_parquet(p, index=False)
            report["output_path"] = str(p.resolve())

    print(json.dumps(report, indent=2, ensure_ascii=False))
