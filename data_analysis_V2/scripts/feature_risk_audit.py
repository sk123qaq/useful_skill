from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from data_analysis_V2.scripts.schemas import validate_feature_risk_report


def _same_value_ratio(left: pd.Series, right: pd.Series) -> float:
    aligned = pd.concat([left.astype(str), right.astype(str)], axis=1).dropna()
    if aligned.empty:
        return 0.0
    return float((aligned.iloc[:, 0] == aligned.iloc[:, 1]).mean())


def classify_feature(series: pd.Series, target_series: pd.Series | None = None, target_name: str | None = None) -> tuple[str, str]:
    name = series.name.lower()
    if any(token in name for token in ("leak", "leakage", "actual", "ground_truth", "final_label", "label_copy", "target_copy")):
        return "hard_leakage", "Feature name suggests direct leakage."
    if target_name and target_name.lower() in name and any(
        token in name for token in ("copy", "clone", "duplicate", "actual", "ground_truth")
    ):
        return "hard_leakage", "Feature name directly references the target as a copy-like field."
    if target_series is not None and _same_value_ratio(series, target_series) >= 0.98:
        return "hard_leakage", "Feature values nearly duplicate the target."
    if any(token in name for token in ("post", "after", "resolved", "settled", "collected", "proxy_after", "converted_after")):
        return "post_outcome", "Feature appears to be recorded after the outcome."
    if any(token in name for token in ("batch", "export", "ingest", "load", "etl", "snapshot", "created_at", "updated_at")):
        return "collection_artifact", "Feature appears to reflect data collection mechanics."
    if any(token in name for token in ("id", "uuid", "session")):
        return "collection_artifact", "Identifier-like field may not generalize."
    if any(token in name for token in ("score", "proxy", "segment", "bucket", "zip", "region")):
        return "soft_proxy", "Feature may be an indirect proxy that needs review."
    return "safe", "No obvious leakage pattern detected."


def audit_feature_risk(df: pd.DataFrame, target: str | None = None) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    target_series = df[target] if target and target in df.columns else None
    for column in df.columns:
        if column == target:
            continue
        label, reason = classify_feature(df[column], target_series=target_series, target_name=target)
        features.append({"feature": column, "label": label, "reason": reason})
    label_counts = Counter(feature["label"] for feature in features)
    report = {
        "features": features,
        "summary": {
            "label_counts": dict(sorted(label_counts.items())),
            "hard_block": label_counts.get("hard_leakage", 0) > 0,
        },
    }
    return validate_feature_risk_report(report)
