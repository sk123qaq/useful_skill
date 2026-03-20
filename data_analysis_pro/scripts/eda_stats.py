#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Add the scripts directory to sys.path so we can import common and io_router
sys.path.append(str(Path(__file__).parent))
import common
import io_router

def summary_statistics(df, max_numeric: int = 50) -> dict[str, Any]:
    numeric_columns = list(df.select_dtypes(include=["number", "bool"]).columns)[:max_numeric]
    if not numeric_columns: return {}
    summary = df[numeric_columns].describe(percentiles=[0.25, 0.5, 0.75]).transpose()
    # Add missing counts
    missing = df[numeric_columns].isnull().sum()
    results = {}
    for col, row in summary.iterrows():
        d = {metric: common.to_serializable(value) for metric, value in row.to_dict().items()}
        d["missing"] = int(missing[col])
        d["missing_pct"] = float(missing[col] / len(df))
        results[col] = d
    return results

def correlation_summary(df, max_numeric: int = 20) -> dict[str, Any]:
    numeric_columns = list(df.select_dtypes(include=["number", "bool"]).columns)[:max_numeric]
    if len(numeric_columns) < 2: return {}
    correlation = df[numeric_columns].corr(numeric_only=True).round(4)
    return correlation.to_dict()

def normality_tests(df, max_numeric: int = 10) -> dict[str, Any]:
    if not common.module_available("scipy"): return {}
    import scipy.stats as stats
    results: dict[str, Any] = {}
    numeric_columns = list(df.select_dtypes(include=["number"]).columns)[:max_numeric]
    for col in numeric_columns:
        series = df[col].dropna()
        if len(series) < 3: continue
        sample = series.sample(min(len(series), 5000), random_state=42) if len(series) > 5000 else series
        try:
            statistic, p_value = stats.shapiro(sample)
            results[col] = {
                "test": "shapiro", "sample_size": int(len(sample)),
                "statistic": float(statistic), "p_value": float(p_value),
                "approximately_normal": bool(p_value >= 0.05)
            }
        except: pass
    return results

def build_eda_report(df, time_col: str | None = None, target: str | None = None) -> dict[str, Any]:
    return {
        "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "summary_statistics": summary_statistics(df),
        "correlation_matrix": correlation_summary(df),
        "normality_tests": normality_tests(df)
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--time-col")
    parser.add_argument("--target")
    parser.add_argument("--output-path")
    args = parser.parse_args()

    df = io_router.load_dataframe(args.input_path)
    report = build_eda_report(df, time_col=args.time_col, target=args.target)
    
    if args.output_path:
        common.write_json(args.output_path, report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
