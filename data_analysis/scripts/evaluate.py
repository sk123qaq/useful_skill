#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

def choose_cv(is_time_series: bool = False, classification: bool = False, n_splits: int = 5):
    from sklearn.model_selection import KFold, StratifiedKFold, TimeSeriesSplit

    if is_time_series:
        return TimeSeriesSplit(n_splits=n_splits)
    if classification:
        return StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    return KFold(n_splits=n_splits, shuffle=True, random_state=42)


def classification_metrics(y_true, y_pred, y_proba=None) -> dict[str, Any]:
    import numpy as np
    from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score

    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision_weighted": float(precision_score(y_true, y_pred, average="weighted", zero_division=0)),
        "recall_weighted": float(recall_score(y_true, y_pred, average="weighted", zero_division=0)),
        "f1_weighted": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
    }
    if y_proba is not None and len(np.unique(y_true)) == 2:
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_proba))
    return metrics


def regression_metrics(y_true, y_pred) -> dict[str, Any]:
    import numpy as np
    from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, mean_squared_error, r2_score

    return {
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae": float(mean_absolute_error(y_true, y_pred)),
        "mape": float(mean_absolute_percentage_error(y_true, y_pred)),
        "r2": float(r2_score(y_true, y_pred)),
    }


def forecast_metrics(y_true, y_pred) -> dict[str, Any]:
    return regression_metrics(y_true, y_pred)


def sharpe_ratio(returns, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float | None:
    import numpy as np

    array = np.asarray(returns, dtype=float)
    if array.size == 0:
        return None
    excess = array - risk_free_rate / periods_per_year
    volatility = excess.std(ddof=1)
    if volatility == 0:
        return None
    return float(np.sqrt(periods_per_year) * excess.mean() / volatility)


def max_drawdown(equity_curve) -> float | None:
    import numpy as np

    array = np.asarray(equity_curve, dtype=float)
    if array.size == 0:
        return None
    peaks = np.maximum.accumulate(array)
    drawdowns = (array - peaks) / peaks
    return float(drawdowns.min())
