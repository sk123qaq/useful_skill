from __future__ import annotations

from typing import Any

import pandas as pd


def _target_as_numeric(target: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(target):
        return target.astype(float)
    encoded, _ = pd.factorize(target.astype(str))
    return pd.Series(encoded, index=target.index, dtype="float64")


def _score_feature(series: pd.Series, target: pd.Series) -> float:
    target_numeric = _target_as_numeric(target)
    if pd.api.types.is_numeric_dtype(series):
        numeric_series = series.astype(float)
        if numeric_series.nunique(dropna=True) <= 1 or target_numeric.nunique(dropna=True) <= 1:
            return 0.0
        correlation = numeric_series.fillna(numeric_series.mean()).corr(target_numeric)
        return abs(float(correlation)) if correlation == correlation else 0.0
    grouped = pd.DataFrame({"feature": series.astype(str), "target": target_numeric}).groupby("feature")["target"].mean()
    return float(grouped.std()) if len(grouped) > 1 else 0.0


def build_guarded_explainability(
    df: pd.DataFrame,
    target: str,
    feature_risk_report: dict[str, Any],
    top_n: int = 5,
) -> dict[str, Any]:
    risk_by_feature = {entry["feature"]: entry for entry in feature_risk_report["features"]}
    scores = []
    for column in df.columns:
        if column == target:
            continue
        scores.append((column, _score_feature(df[column], df[target])))
    ranked = sorted(scores, key=lambda item: item[1], reverse=True)[:top_n]
    top_features = []
    warnings = []
    for feature_name, score in ranked:
        risk_entry = risk_by_feature[feature_name]
        if risk_entry["label"] in {"hard_leakage", "post_outcome"}:
            warnings.append(f"{feature_name} is risky for narrative use.")
        top_features.append(
            {
                "feature": feature_name,
                "importance_score": float(score),
                "lineage": {"raw_field": feature_name},
                "risk_label": risk_entry["label"],
                "risk_reason": risk_entry["reason"],
            }
        )
    return {
        "top_features": top_features,
        "predictive_reliance_statement": "These feature rankings describe predictive reliance, not causal leverage.",
        "not_a_causal_claim": True,
        "warnings": warnings,
    }
