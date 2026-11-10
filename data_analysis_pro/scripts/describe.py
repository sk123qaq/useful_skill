#!/usr/bin/env python3
"""describe.py: deterministic descriptive / time-series / group profile.

This replaces the old eda_stats.py. Unlike that script, it actually uses the
time column and target, and it never labels a relationship as causal.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402
import io_router  # noqa: E402
from workflow import load_json, write_json  # noqa: E402


def _num(value: Any) -> float | None:
    try:
        out = float(value)
        return out if np.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def numeric_profile(series: pd.Series) -> dict[str, Any]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return {"count": 0, "missing_rate": 1.0}
    return {
        "count": int(clean.size),
        "missing_rate": float(series.isna().mean()),
        "mean": _num(clean.mean()),
        "std": _num(clean.std()),
        "min": _num(clean.min()),
        "q25": _num(clean.quantile(0.25)),
        "median": _num(clean.median()),
        "q75": _num(clean.quantile(0.75)),
        "max": _num(clean.max()),
        "skew": _num(clean.skew()),
    }


def time_profile(df: pd.DataFrame, time_col: str, target: str | None) -> dict[str, Any]:
    t = pd.to_datetime(df[time_col], errors="coerce")
    valid = t.notna()
    if valid.sum() < 3:
        return {"error": "time column has fewer than 3 parseable values"}
    frame = df.loc[valid].copy()
    frame["_time"] = t[valid].to_numpy()
    frame = frame.sort_values("_time")
    out: dict[str, Any] = {
        "min": str(frame["_time"].min()),
        "max": str(frame["_time"].max()),
        "n_unique_dates": int(frame["_time"].nunique()),
        "median_interval_days": _num(frame["_time"].diff().dt.total_seconds().div(86400).median()),
    }
    if target and target in frame.columns and pd.api.types.is_numeric_dtype(frame[target]):
        y = frame.set_index("_time")[target].astype(float)
        out["target_first"] = _num(y.iloc[0])
        out["target_last"] = _num(y.iloc[-1])
        if y.iloc[0] not in (0, np.nan) and np.isfinite(y.iloc[0]):
            out["target_change_pct"] = _num((y.iloc[-1] / y.iloc[0] - 1.0) * 100.0)
        out["target_autocorr"] = {str(lag): _num(y.autocorr(lag=lag)) for lag in (1, 5, 20)}
        monthly = y.resample("ME").mean().dropna()
        out["monthly_mean"] = [{"month": str(idx.date()), "value": _num(val)} for idx, val in monthly.items()]
        weekly = y.resample("W").mean().dropna()
        out["weekly_mean_tail"] = [{"week": str(idx.date()), "value": _num(val)} for idx, val in weekly.tail(8).items()]
        z = (y - y.mean()) / y.std(ddof=0) if y.std(ddof=0) else pd.Series(0.0, index=y.index)
        anomalies = y.loc[z.abs() >= 3]
        out["anomalies"] = [{"time": str(idx), "value": _num(val), "z": _num(z.loc[idx])} for idx, val in anomalies.items()]
        by_month = y.groupby(y.index.month).agg(["mean", "count"])
        out["seasonality_by_month"] = [
            {"month": int(month), "mean": _num(row["mean"]), "n": int(row["count"])}
            for month, row in by_month.iterrows()
        ]
    return out


def group_profile(df: pd.DataFrame, target: str, max_categories: int) -> list[dict[str, Any]]:
    if target not in df.columns or not pd.api.types.is_numeric_dtype(df[target]):
        return []
    results: list[dict[str, Any]] = []
    for col in df.columns:
        if col == target or not (pd.api.types.is_object_dtype(df[col]) or isinstance(df[col].dtype, pd.CategoricalDtype)):
            continue
        levels = df[col].nunique(dropna=True)
        if levels < 2 or levels > max_categories:
            continue
        groups = [g[target].dropna().astype(float) for _, g in df.groupby(col, dropna=True)]
        groups = [g for g in groups if len(g) >= 2]
        if len(groups) < 2:
            continue
        means = df.groupby(col, dropna=True)[target].agg(["mean", "count"]).reset_index()
        test_name, p_value = "kruskal", None
        try:
            p_value = float(stats.kruskal(*groups).pvalue) if len(groups) >= 2 else None
        except Exception:
            pass
        if p_value is None or not np.isfinite(p_value):
            try:
                test_name, p_value = "anova", float(stats.f_oneway(*groups).pvalue)
            except Exception:
                test_name, p_value = "none", None
        results.append({
            "column": str(col),
            "levels": int(levels),
            "test": test_name,
            "p_value": _num(p_value),
            "groups": [{"level": str(row[col]), "mean": _num(row["mean"]), "n": int(row["count"])}
                       for _, row in means.iterrows()],
        })
    return results


def correlation_profile(df: pd.DataFrame, target: str | None, max_features: int = 25) -> list[dict[str, Any]]:
    if not target or target not in df.columns or not pd.api.types.is_numeric_dtype(df[target]):
        return []
    rows: list[dict[str, Any]] = []
    y = pd.to_numeric(df[target], errors="coerce")
    for col in df.columns:
        if col == target or not pd.api.types.is_numeric_dtype(df[col]):
            continue
        x = pd.to_numeric(df[col], errors="coerce")
        pair = pd.concat([x, y], axis=1).dropna()
        if len(pair) < 10 or pair.iloc[:, 0].nunique() < 2:
            continue
        pearson = pair.iloc[:, 0].corr(pair.iloc[:, 1], method="pearson")
        spearman = pair.iloc[:, 0].corr(pair.iloc[:, 1], method="spearman")
        rows.append({"feature": str(col), "pearson": _num(pearson), "spearman": _num(spearman), "n": int(len(pair))})
    rows.sort(key=lambda item: abs(item["pearson"] or 0), reverse=True)
    return rows[:max_features]


def main() -> int:
    parser = argparse.ArgumentParser(description="Descriptive and time-series profile.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--contract", default=None)
    parser.add_argument("--target", default=None)
    parser.add_argument("--time-col", default=None)
    parser.add_argument("--max-categories", type=int, default=12)
    parser.add_argument("--markdown-path", default=None)
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--comment", default=None)
    args = parser.parse_args()

    contract = load_json(args.contract) if args.contract else {}
    target = args.target or contract.get("target")
    time_col = args.time_col or contract.get("time_col")
    df = io_router.load_dataframe(args.input_path, auto_sample=False, sheet=args.sheet, comment=args.comment)
    if target and target not in df.columns:
        raise SystemExit(f"target not found: {target}")
    if time_col and time_col not in df.columns:
        raise SystemExit(f"time_col not found: {time_col}")

    payload: dict[str, Any] = {
        "stage": "describe",
        "source": str(Path(args.input_path).resolve()),
        "target": target,
        "time_col": time_col,
        "shape": [int(df.shape[0]), int(df.shape[1])],
        "columns": [str(c) for c in df.columns],
        "numeric": {str(c): numeric_profile(df[c]) for c in df.columns if pd.api.types.is_numeric_dtype(df[c])},
        "categorical": {
            str(c): [{"value": str(v), "count": int(n), "share": float(n / len(df))}
                     for v, n in df[c].astype(str).value_counts(dropna=False).head(8).items()]
            for c in df.columns if pd.api.types.is_object_dtype(df[c]) or isinstance(df[c].dtype, pd.CategoricalDtype)
        },
        "correlations": correlation_profile(df, target),
        "groups": group_profile(df, target, args.max_categories) if target else [],
        "time_series": time_profile(df, time_col, target) if time_col else None,
        "caveats": [
            "Descriptive statistics describe this dataset only; they do not identify causes.",
            "Correlations are pairwise and not adjusted for confounders or time trends.",
        ],
        "created_at": common.now_utc_iso(),
    }
    write_json(args.output_path, payload)

    if args.markdown_path:
        lines = [f"# Descriptive profile: {Path(args.input_path).name}", "",
                 f"- Rows: {len(df):,}; columns: {df.shape[1]}; target: `{target}`; time: `{time_col}`", ""]
        if payload.get("time_series"):
            ts = payload["time_series"]
            lines += ["## Time series", "", f"- {ts.get('min')} → {ts.get('max')}",
                      f"- target change: {ts.get('target_change_pct')}%"]
            lines += ["", "| month | mean |", "|---|---:|"]
            lines += [f"| {row['month']} | {row['value']} |" for row in ts.get("monthly_mean", [])]
        lines += ["", "## Top correlations", "", "| feature | Pearson | Spearman | n |", "|---|---:|---:|---:|"]
        lines += [f"| {row['feature']} | {row['pearson']} | {row['spearman']} | {row['n']} |"
                  for row in payload.get("correlations", [])[:12]]
        common.write_markdown(args.markdown_path, "\n".join(lines))
    print(f"wrote {args.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
