#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from common import ensure_modules, module_available


def encode_categoricals(df, columns: list[str] | None = None, dummy_na: bool = True):
    ensure_modules(["pandas"], "categorical encoding")
    import pandas as pd  # type: ignore

    frame = df.copy()
    target_columns = columns or list(frame.select_dtypes(exclude=["number", "bool"]).columns)
    if not target_columns:
        return frame
    frame[target_columns] = frame[target_columns].fillna("__MISSING__").astype("string")
    encoded = pd.get_dummies(frame, columns=target_columns, dummy_na=dummy_na)
    encoded.columns = [str(col).replace("<", "_").replace(">", "_") for col in encoded.columns]
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
    plan: dict[str, Any] = {
        "numeric_columns": numeric_columns,
        "categorical_columns": categorical_columns,
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
