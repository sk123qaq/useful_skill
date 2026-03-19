from __future__ import annotations

from typing import Any

import pandas as pd


def _target_distribution(series: pd.Series | None) -> dict[str, Any]:
    if series is None:
        return {"available": False}
    counts = series.value_counts(dropna=False).head(10)
    return {
        "available": True,
        "unique_values": int(series.nunique(dropna=False)),
        "top_counts": {str(key): int(value) for key, value in counts.items()},
    }


def run_scout_audit(
    df: pd.DataFrame,
    target: str | None = None,
    time_col: str | None = None,
) -> dict[str, Any]:
    row_count = int(len(df))
    missingness = {
        column: round(float(df[column].isna().mean()), 6)
        for column in df.columns
    }
    suspicious_fields = [
        column
        for column in df.columns
        if any(token in column.lower() for token in ("id", "uuid", "batch", "post", "after", "label", "target"))
    ]
    high_cardinality_fields = [
        column
        for column in df.columns
        if df[column].nunique(dropna=False) > max(20, int(row_count * 0.8))
    ]
    target_series = df[target] if target and target in df.columns else None
    report = {
        "row_count": row_count,
        "column_count": int(len(df.columns)),
        "columns": list(df.columns),
        "duplicate_rows": int(df.duplicated().sum()),
        "duplicate_rate": round(float(df.duplicated().mean()), 6),
        "missingness": missingness,
        "high_cardinality_fields": high_cardinality_fields,
        "suspicious_fields": suspicious_fields,
        "target_distribution": _target_distribution(target_series),
        "time_column_present": bool(time_col and time_col in df.columns),
    }
    return report
