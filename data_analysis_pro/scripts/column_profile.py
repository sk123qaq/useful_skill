#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# Add the scripts directory to sys.path so we can import common and io_router
sys.path.append(str(Path(__file__).parent))
import common
import io_router

def _top_values(series: pd.Series, top_n: int) -> list[dict[str, Any]]:
    counts = series.astype(str).value_counts(dropna=False).head(top_n)
    total = len(series) or 1
    return [
        {
            "value": str(value),
            "count": int(count),
            "share": float(count / total),
        }
        for value, count in counts.items()
    ]

def infer_semantic_type(series: pd.Series, column_name: str, row_count: int, unique_count: int) -> str:
    # 1. Check for Datetime
    if pd.api.types.is_datetime64_any_dtype(series):
        return "Datetime"
    
    # Try converting to datetime if object
    if series.dtype == "object" or pd.api.types.is_string_dtype(series):
        # Sample non-null values for speed
        sample = series.dropna().head(100)
        if not sample.empty:
            try:
                converted = pd.to_datetime(sample, errors="coerce")
                if converted.notna().mean() > 0.8:
                    return "Datetime"
            except (ValueError, TypeError):
                pass

    # 2. Check for ID heuristic (High uniqueness + naming)
    if unique_count == row_count and row_count > 0:
        return "ID"
    if "id" in column_name.lower() or "key" in column_name.lower() or "uuid" in column_name.lower():
        if unique_count > row_count * 0.9 and row_count > 0:
            return "ID"

    # 3. Check for Numeric
    if pd.api.types.is_numeric_dtype(series):
        return "Numeric"

    # 4. Default to Categorical
    return "Categorical"

def build_column_profile(df: pd.DataFrame, target: str | None = None, top_n: int = 5) -> dict[str, Any]:
    profiles: list[dict[str, Any]] = []
    row_count = len(df)
    for column in df.columns:
        series = df[column]
        missing_rate = float(series.isna().mean())
        unique_count = int(series.nunique(dropna=True))
        non_null = series.dropna()
        dominant_share = float(non_null.astype(str).value_counts(normalize=True).iloc[0]) if not non_null.empty else 0.0
        
        semantic_type = infer_semantic_type(series, column, row_count, unique_count)
        
        flags: list[str] = []
        if unique_count <= 1: flags.append("constant")
        if missing_rate >= 0.2: flags.append("high_missingness")
        if row_count > 100 and unique_count > max(50, int(row_count * 0.95)):
            flags.append("high_cardinality")
        if unique_count > 1 and dominant_share >= 0.95:
            flags.append("dominant_category")
        if column == target: flags.append("target")
        
        profiles.append({
            "column": column,
            "dtype": str(series.dtype),
            "semantic_type": semantic_type,
            "missing_rate": missing_rate,
            "unique_count": unique_count,
            "dominant_share": dominant_share,
            "top_values": _top_values(series, top_n=top_n),
            "flags": flags,
        })
    
    summary = {
        "row_count": row_count,
        "constant_features": [p["column"] for p in profiles if "constant" in p["flags"]],
        "high_missingness": [p["column"] for p in profiles if "high_missingness" in p["flags"]],
        "high_cardinality": [p["column"] for p in profiles if "high_cardinality" in p["flags"]],
    }
    return {"row_count": row_count, "column_count": len(df.columns), "profiles": profiles, "summary": summary}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-path")
    parser.add_argument("--target")
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--comment", default=None)
    parser.add_argument("--skiprows", type=int, default=None)
    parser.add_argument("--encoding", default=None)
    parser.add_argument("--sample-rows", type=int, default=None)
    args = parser.parse_args()

    df = io_router.load_dataframe(
        args.input_path, sample_rows=args.sample_rows, auto_sample=False,
        sheet=args.sheet, comment=args.comment, skiprows=args.skiprows, encoding=args.encoding,
    )
    if args.target and args.target not in df.columns:
        raise SystemExit(f"target not found in data: {args.target}")
    profile = build_column_profile(df, target=args.target)
    profile["source"] = str(Path(args.input_path).resolve())
    profile["created_at"] = common.now_utc_iso()

    if args.output_path:
        common.write_json(args.output_path, profile)
    else:
        print(json.dumps(profile, indent=2, ensure_ascii=False))
