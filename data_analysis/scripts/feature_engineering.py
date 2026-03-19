#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from common import REPORT_AUDIENCES, ensure_modules, friendly_field_label, module_available, sanitize_feature_name


ORDERED_FIELD_HINTS = {
    "age",
    "grade",
    "level",
    "stage",
    "bucket",
    "band",
    "rank",
    "score",
}

ORDERED_VALUE_SEQUENCES = [
    ["poor", "fair", "good", "very_good", "excellent"],
    ["very_poor", "poor", "fair", "good", "very_good", "excellent"],
    ["low", "medium", "high"],
    ["no", "prediabetes", "yes"],
]


def _non_null_unique_values(series, limit: int = 50) -> list[str]:
    if not hasattr(series, "dropna"):
        return []
    values = series.dropna()
    if hasattr(values, "empty") and values.empty:
        return []
    try:
        unique = values.astype("string").unique().tolist()
    except Exception:  # noqa: BLE001
        unique = [str(item) for item in values.unique().tolist()] if hasattr(values, "unique") else []
    return [str(item).strip() for item in unique[:limit] if str(item).strip()]


def _matches_ordered_sequence(unique_values: list[str]) -> bool:
    normalized = {value.lower().replace(" ", "_").replace("-", "_") for value in unique_values}
    if len(normalized) < 2:
        return False
    for sequence in ORDERED_VALUE_SEQUENCES:
        sequence_set = set(sequence)
        if normalized.issubset(sequence_set):
            return True
    return False


def infer_semantic_type(series, field_name: str | None = None) -> str:
    field_key = str(field_name or "").lower()
    if getattr(series, "dtype", None) is not None and str(series.dtype) == "bool":
        return "binary"

    unique_values = _non_null_unique_values(series)
    unique_count = len(unique_values)
    if unique_count <= 2 and unique_count > 0:
        return "binary"

    if "datetime" in str(getattr(series, "dtype", "")).lower() or field_key.endswith("_date") or field_key.endswith("_time"):
        return "time"

    if str(getattr(series, "dtype", "")).lower() in {"int64", "int32", "float64", "float32", "int", "float"}:
        return "continuous"

    if any(hint in field_key for hint in ORDERED_FIELD_HINTS):
        return "ordered_category"

    if _matches_ordered_sequence(unique_values):
        return "ordered_category"

    return "nominal_category"


def build_semantic_schema(df, target: str | None = None, time_col: str | None = None) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    for column in df.columns:
        semantic_type = "time" if time_col and column == time_col else infer_semantic_type(df[column], field_name=column)
        role = "target" if target and column == target else "time" if time_col and column == time_col else "measure" if semantic_type == "continuous" else "dimension"
        unique_count = None
        try:
            unique_count = int(df[column].nunique(dropna=True))
        except Exception:  # noqa: BLE001
            unique_count = None
        missing_ratio = None
        try:
            missing_ratio = float(df[column].isna().mean())
        except Exception:  # noqa: BLE001
            missing_ratio = None
        allowed_chart_intents = {
            "binary": ["comparison", "ranking", "risk_boundary"],
            "ordered_category": ["comparison", "ranking", "trend_proxy"],
            "nominal_category": ["comparison", "ranking", "composition"],
            "continuous": ["distribution", "relationship", "marginal_effect"],
            "time": ["trend", "seasonality", "anomaly"],
        }.get(semantic_type, ["comparison"])
        report_priority = "high" if role in {"target", "time"} else "medium" if unique_count is not None and unique_count <= 20 else "low"
        fields.append(
            {
                "field_name": str(column),
                "business_label": friendly_field_label(str(column)),
                "role": role,
                "semantic_type": semantic_type,
                "report_priority": report_priority,
                "allowed_chart_intents": allowed_chart_intents,
                "preferred_audiences": list(REPORT_AUDIENCES),
                "unique_count": unique_count,
                "missing_ratio": missing_ratio,
            }
        )
    return {
        "version": 1,
        "target_field": target,
        "time_field": time_col,
        "fields": fields,
    }


def build_raw_feature_lineage(df, target: str | None = None) -> dict[str, Any]:
    features = []
    for column in df.columns:
        if target and column == target:
            continue
        features.append(
            {
                "feature_name": sanitize_feature_name(column),
                "source_field": str(column),
                "derivation": "raw_passthrough",
                "category_value": None,
                "is_model_internal": False,
            }
        )
    return {
        "version": 1,
        "target_field": target,
        "features": features,
    }


def encode_categoricals(df, columns: list[str] | None = None, dummy_na: bool = True, return_lineage: bool = False):
    ensure_modules(["pandas"], "categorical encoding")
    import pandas as pd  # type: ignore

    frame = df.copy()
    target_columns = columns or list(frame.select_dtypes(exclude=["number", "bool"]).columns)
    if not target_columns:
        if return_lineage:
            return frame, build_raw_feature_lineage(frame).get("features", [])
        return frame
    frame[target_columns] = frame[target_columns].fillna("__MISSING__").astype("string")
    passthrough = frame.drop(columns=target_columns)
    lineage: list[dict[str, Any]] = [
        {
            "feature_name": sanitize_feature_name(column),
            "source_field": str(column),
            "derivation": "raw_passthrough",
            "category_value": None,
            "is_model_internal": False,
        }
        for column in passthrough.columns
    ]
    encoded_parts = [passthrough]
    for column in target_columns:
        dummies = pd.get_dummies(frame[column], prefix=column, dummy_na=dummy_na)
        encoded_parts.append(dummies)
        prefix = f"{column}_"
        for dummy_column in dummies.columns:
            raw_name = str(dummy_column)
            category_value = raw_name[len(prefix) :] if raw_name.startswith(prefix) else raw_name
            lineage.append(
                {
                    "feature_name": sanitize_feature_name(raw_name),
                    "source_field": str(column),
                    "derivation": "one_hot",
                    "category_value": category_value,
                    "is_model_internal": False,
                }
            )
    encoded = pd.concat(encoded_parts, axis=1)
    encoded.columns = [sanitize_feature_name(col) for col in encoded.columns]
    if return_lineage:
        sanitized_map = {entry["feature_name"]: entry for entry in lineage}
        ordered_lineage = [sanitized_map.get(str(column), {"feature_name": str(column), "source_field": str(column), "derivation": "unknown", "category_value": None, "is_model_internal": False}) for column in encoded.columns]
        return encoded, ordered_lineage
    return encoded


def add_calendar_features(df, time_col: str):
    if time_col not in df.columns:
        raise ValueError(f"Unknown time column: {time_col}")
    if not module_available("pandas"):
        raise RuntimeError("pandas is required for calendar feature engineering.")

    import pandas as pd  # type: ignore

    frame = df.copy()
    frame[time_col] = pd.to_datetime(frame[time_col], errors="coerce")
    frame[f"{time_col}_year"] = frame[time_col].dt.year
    frame[f"{time_col}_quarter"] = frame[time_col].dt.quarter
    frame[f"{time_col}_month"] = frame[time_col].dt.month
    frame[f"{time_col}_dayofweek"] = frame[time_col].dt.dayofweek
    frame[f"{time_col}_is_month_end"] = frame[time_col].dt.is_month_end.astype("Int64")
    return frame


def compute_macd(series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    histogram = macd - signal_line
    return {"macd": macd, "signal": signal_line, "histogram": histogram}


def compute_rsi(series, window: int = 14):
    delta = series.diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)
    average_gain = gains.rolling(window=window).mean()
    average_loss = losses.rolling(window=window).mean()
    relative_strength = average_gain / average_loss.replace(0, float("nan"))
    return 100 - (100 / (1 + relative_strength))


def add_technical_indicators(df, price_col: str, time_col: str | None = None):
    ensure_modules(["pandas"], "technical indicators")
    frame = df.copy()
    if price_col not in frame.columns:
        raise ValueError(f"Unknown price column: {price_col}")
    if time_col and time_col in frame.columns:
        frame = frame.sort_values(time_col)
    macd_bundle = compute_macd(frame[price_col])
    frame[f"{price_col}_macd"] = macd_bundle["macd"]
    frame[f"{price_col}_macd_signal"] = macd_bundle["signal"]
    frame[f"{price_col}_macd_hist"] = macd_bundle["histogram"]
    frame[f"{price_col}_rsi_14"] = compute_rsi(frame[price_col])
    return frame


def add_pca_features(df, columns: list[str], n_components: int = 2):
    ensure_modules(["pandas", "sklearn"], "PCA feature engineering")
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    frame = df.copy()
    missing = [col for col in columns if col not in frame.columns]
    if missing:
        raise ValueError(f"Unknown PCA columns: {', '.join(missing)}")
    usable = frame[columns].dropna()
    if usable.empty:
        raise ValueError("PCA columns contain no complete rows.")

    scaler = StandardScaler()
    scaled = scaler.fit_transform(usable)
    pca = PCA(n_components=n_components, random_state=42)
    components = pca.fit_transform(scaled)
    component_columns = [f"pca_component_{index + 1}" for index in range(components.shape[1])]

    for index, component_name in enumerate(component_columns):
        frame[component_name] = None
        frame.loc[usable.index, component_name] = components[:, index]

    return frame, {
        "columns": columns,
        "n_components": int(components.shape[1]),
        "explained_variance_ratio": [float(value) for value in pca.explained_variance_ratio_],
        "component_columns": component_columns,
    }


def build_feature_plan(df, target: str | None = None, time_col: str | None = None) -> dict[str, Any]:
    numeric_columns = list(df.select_dtypes(include=["number", "bool"]).columns)
    categorical_columns = [col for col in df.columns if col not in numeric_columns]
    semantic_schema = build_semantic_schema(df, target=target, time_col=time_col)
    plan: dict[str, Any] = {
        "numeric_columns": numeric_columns,
        "categorical_columns": categorical_columns,
        "field_catalog": semantic_schema.get("fields", []),
        "recommendations": [],
        "available_advanced_features": {
            "calendar_features": bool(time_col and time_col in df.columns),
            "technical_indicators": len(numeric_columns) > 0,
            "pca": len(numeric_columns) >= 5 and module_available("sklearn"),
        },
    }
    if categorical_columns:
        plan["recommendations"].append("One-hot encode low-cardinality categoricals. Review high-cardinality columns before modeling.")
    if numeric_columns:
        plan["recommendations"].append("Consider scaling only for models sensitive to feature magnitude.")
    if time_col and time_col in df.columns:
        plan["recommendations"].append("Add calendar features and lag features for temporal tasks.")
    if target and target in df.columns:
        plan["recommendations"].append("Check leakage before creating rolling, cumulative, or target-derived features.")
    plan["pca_ready"] = len(numeric_columns) >= 5
    return plan
