#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency, kruskal, spearmanr
from sklearn.metrics import roc_auc_score

# Add the scripts directory to sys.path so we can import common and io_router
sys.path.append(str(Path(__file__).parent))
import common
import io_router
import column_profile

def _series_kind(series: pd.Series, *, as_target: bool = False) -> str:
    non_null = series.dropna()
    unique_count = int(non_null.nunique(dropna=True))
    if unique_count <= 1: return "constant"
    if pd.api.types.is_numeric_dtype(series):
        if as_target:
            if unique_count == 2: return "binary"
            if unique_count <= 10: return "categorical"
            return "numeric"
        if unique_count <= 10: return "categorical"
        return "numeric"
    return "binary" if as_target and unique_count == 2 else "categorical"

def _cramers_v(table: pd.DataFrame) -> float:
    if table.empty or table.shape[0] < 2 or table.shape[1] < 2: return 0.0
    chi2, _, _, _ = chi2_contingency(table)
    n = float(table.to_numpy().sum())
    denominator = n * max(1.0, float(min(table.shape[0] - 1, table.shape[1] - 1)))
    return float(np.sqrt(chi2 / denominator)) if denominator > 0 else 0.0

def _eta_squared(grouped_frame: pd.DataFrame, group_col: str, value_col: str) -> float:
    if grouped_frame.empty or grouped_frame[group_col].nunique() < 2: return 0.0
    overall_mean = grouped_frame[value_col].mean()
    total_ss = float(((grouped_frame[value_col] - overall_mean) ** 2).sum())
    if total_ss <= 0: return 0.0
    group_stats = grouped_frame.groupby(group_col)[value_col].agg(["mean", "size"])
    between_ss = float((((group_stats["mean"] - overall_mean) ** 2) * group_stats["size"]).sum())
    return float(max(0.0, min(1.0, between_ss / total_ss)))

def _pairwise_relationship(df: pd.DataFrame, x_name: str, y_name: str, target_kind: str) -> dict[str, Any]:
    x = df[x_name]
    y = df[y_name]
    x_kind = _series_kind(x)
    
    if target_kind in {"binary", "categorical"} and x_kind in {"categorical", "binary"}:
        table = pd.crosstab(x.fillna("NA"), y.fillna("NA"))
        effect_size = _cramers_v(table)
        metric = "cramers_v"
    elif target_kind in {"binary", "categorical"} and x_kind == "numeric":
        frame = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": y}).dropna()
        effect_size = _eta_squared(frame, "y", "x")
        metric = "eta_squared"
    elif target_kind == "numeric" and x_kind in {"categorical", "binary"}:
        frame = pd.DataFrame({"x": x, "y": pd.to_numeric(y, errors="coerce")}).dropna()
        effect_size = _eta_squared(frame, "x", "y")
        metric = "eta_squared"
    else:
        frame = pd.DataFrame({"x": pd.to_numeric(x, errors="coerce"), "y": pd.to_numeric(y, errors="coerce")}).dropna()
        if len(frame) < 3: effect_size = 0.0
        else: effect_size = abs(float(spearmanr(frame["x"], frame["y"]).correlation))
        metric = "spearman_r"

    return {
        "x": x_name, "y": y_name, "x_kind": x_kind, "y_kind": target_kind,
        "effect_size": float(effect_size), "metric": metric
    }

def run_screening(df, target, top_k=20):
    if target not in df.columns: raise ValueError(f"Target {target} not found")
    target_kind = _series_kind(df[target], as_target=True)
    
    candidates = [c for c in df.columns if c != target]
    results = []
    for col in candidates:
        results.append(_pairwise_relationship(df, col, target, target_kind))
    
    results.sort(key=lambda x: x["effect_size"], reverse=True)
    return results[:top_k]

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--top-k", type=int, default=20)
    args = parser.parse_args()

    df = io_router.load_dataframe(args.input_path)
    findings = run_screening(df, args.target, top_k=args.top_k)
    print(json.dumps(findings, indent=2, ensure_ascii=False))
