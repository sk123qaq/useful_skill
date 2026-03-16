#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from common import module_available
from io_router import load_dataframe


def summary_statistics(df, max_numeric: int = 20) -> dict[str, Any]:
    numeric_columns = list(df.select_dtypes(include=["number", "bool"]).columns)[:max_numeric]
    if not numeric_columns:
        return {}
    summary = df[numeric_columns].describe(percentiles=[0.25, 0.5, 0.75]).transpose()
    return {
        col: {metric: float(value) for metric, value in row.to_dict().items()}
        for col, row in summary.iterrows()
    }


def correlation_summary(df, max_numeric: int = 12) -> dict[str, Any]:
    numeric_columns = list(df.select_dtypes(include=["number", "bool"]).columns)[:max_numeric]
    if len(numeric_columns) < 2:
        return {}
    correlation = df[numeric_columns].corr(numeric_only=True).round(4)
    return correlation.to_dict()


def normality_tests(df, max_numeric: int = 8) -> dict[str, Any]:
    import scipy.stats as stats

    results: dict[str, Any] = {}
    numeric_columns = list(df.select_dtypes(include=["number", "bool"]).columns)[:max_numeric]
    for col in numeric_columns:
        series = df[col].dropna()
        if len(series) < 3:
            continue
        sample = series.sample(min(len(series), 5000), random_state=42) if len(series) > 5000 else series
        statistic, p_value = stats.shapiro(sample)
        results[col] = {
            "test": "shapiro",
            "sample_size": int(len(sample)),
            "statistic": float(statistic),
            "p_value": float(p_value),
            "approximately_normal_at_0_05": bool(p_value >= 0.05),
        }
    return results


def adf_test(df, time_col: str | None, target: str | None) -> dict[str, Any]:
    if not time_col or not target or time_col not in df.columns or target not in df.columns:
        return {}
    if not module_available("statsmodels"):
        return {"available": False, "reason": "statsmodels is not installed."}

    from statsmodels.tsa.stattools import adfuller  # type: ignore

    series = df.sort_values(time_col)[target].dropna()
    if len(series) < 10:
        return {"available": False, "reason": "Need at least 10 non-null target observations for ADF."}
    statistic, p_value, usedlag, nobs, critical_values, _ = adfuller(series)
    return {
        "available": True,
        "statistic": float(statistic),
        "p_value": float(p_value),
        "used_lag": int(usedlag),
        "n_obs": int(nobs),
        "critical_values": {key: float(value) for key, value in critical_values.items()},
        "stationary_at_0_05": bool(p_value < 0.05),
    }


def build_eda_report(df, time_col: str | None = None, target: str | None = None) -> dict[str, Any]:
    return {
        "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "summary_statistics": summary_statistics(df),
        "correlation_matrix": correlation_summary(df),
        "normality_tests": normality_tests(df),
        "adf_test": adf_test(df, time_col=time_col, target=target),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an EDA and statistics summary.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--time-col")
    parser.add_argument("--target")
    args = parser.parse_args()

    df = load_dataframe(args.input_path)
    report = build_eda_report(df, time_col=args.time_col, target=args.target)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
