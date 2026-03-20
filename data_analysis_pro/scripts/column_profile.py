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

def build_column_profile(df: pd.DataFrame, target: str | None = None, top_n: int = 5) -> dict[str, Any]:
    profiles: list[dict[str, Any]] = []
    row_count = len(df)
    for column in df.columns:
        series = df[column]
        missing_rate = float(series.isna().mean())
        unique_count = int(series.nunique(dropna=True))
        non_null = series.dropna()
        dominant_share = float(non_null.astype(str).value_counts(normalize=True).iloc[0]) if not non_null.empty else 0.0
        
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
    return {"row_count": row_count, "profiles": profiles, "summary": summary}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-path")
    parser.add_argument("--target")
    args = parser.parse_args()

    df = io_router.load_dataframe(args.input_path)
    profile = build_column_profile(df, target=args.target)
    
    if args.output_path:
        common.write_json(args.output_path, profile)
    else:
        print(json.dumps(profile, indent=2, ensure_ascii=False))
