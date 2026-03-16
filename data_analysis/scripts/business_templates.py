#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from typing import Any


def funnel_from_step_columns(df, steps: list[str]) -> dict[str, Any]:
    counts = []
    base = None
    previous = None
    for step in steps:
        if step not in df.columns:
            raise ValueError(f"Unknown funnel step column: {step}")
        count = int(df[step].fillna(False).astype(bool).sum())
        base = count if base is None else base
        step_conversion = count / previous if previous else 1.0
        total_conversion = count / base if base else 0.0
        counts.append(
            {
                "step": step,
                "users": count,
                "step_conversion": round(step_conversion, 4),
                "total_conversion": round(total_conversion, 4),
            }
        )
        previous = count
    return {"mode": "step_columns", "steps": counts}


def funnel_from_stage_column(df, stage_col: str, ordered_stages: list[str]) -> dict[str, Any]:
    if stage_col not in df.columns:
        raise ValueError(f"Unknown stage column: {stage_col}")
    value_counts = df[stage_col].value_counts(dropna=False)
    base = None
    previous = None
    steps = []
    for stage in ordered_stages:
        count = int(value_counts.get(stage, 0))
        base = count if base is None else base
        step_conversion = count / previous if previous else 1.0
        total_conversion = count / base if base else 0.0
        steps.append(
            {
                "step": stage,
                "users": count,
                "step_conversion": round(step_conversion, 4),
                "total_conversion": round(total_conversion, 4),
            }
        )
        previous = count
    return {"mode": "stage_column", "steps": steps}


def monetization_summary(df, user_col: str, revenue_col: str, order_col: str | None = None) -> dict[str, Any]:
    if user_col not in df.columns or revenue_col not in df.columns:
        raise ValueError("Monetization summary needs both a user column and a revenue column.")
    total_users = int(df[user_col].nunique())
    paying = df[df[revenue_col].fillna(0) > 0]
    paying_users = int(paying[user_col].nunique())
    revenue = float(df[revenue_col].fillna(0).sum())
    report = {
        "active_users": total_users,
        "paying_users": paying_users,
        "pay_rate": round(paying_users / total_users, 4) if total_users else 0.0,
        "revenue": revenue,
        "arpu": round(revenue / total_users, 4) if total_users else 0.0,
        "arppu": round(revenue / paying_users, 4) if paying_users else 0.0,
    }
    if order_col and order_col in df.columns:
        buyers = int(df[df[revenue_col].fillna(0) > 0][user_col].nunique())
        repeat_buyers = int(
            df[df[revenue_col].fillna(0) > 0]
            .groupby(user_col)[order_col]
            .nunique()
            .gt(1)
            .sum()
        )
        report["repeat_purchase_rate"] = round(repeat_buyers / buyers, 4) if buyers else 0.0
    return report


def retention_summary(df, user_col: str, date_col: str, periods: list[int] | None = None, acquisition_col: str | None = None) -> dict[str, Any]:
    import pandas as pd  # type: ignore

    if user_col not in df.columns or date_col not in df.columns:
        raise ValueError("Retention summary needs both user and date columns.")

    frame = df[[user_col, date_col] + ([acquisition_col] if acquisition_col else [])].copy()
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    if acquisition_col:
        frame[acquisition_col] = pd.to_datetime(frame[acquisition_col], errors="coerce")
        acquisition_dates = frame.groupby(user_col)[acquisition_col].min()
    else:
        acquisition_dates = frame.groupby(user_col)[date_col].min()

    frame["acquisition_date"] = frame[user_col].map(acquisition_dates)
    frame["day_offset"] = (frame[date_col] - frame["acquisition_date"]).dt.days
    frame = frame.dropna(subset=["day_offset"])
    periods = periods or [1, 7, 30]
    cohort_size = int(acquisition_dates.shape[0])
    metrics = {}
    for period in periods:
        retained_users = int(frame[frame["day_offset"] == period][user_col].nunique())
        metrics[f"day_{period}_retention"] = round(retained_users / cohort_size, 4) if cohort_size else 0.0
    active_days = (
        frame.groupby("day_offset")[user_col]
        .nunique()
        .sort_index()
        .to_dict()
    )
    return {
        "cohort_size": cohort_size,
        "retention": metrics,
        "active_users_by_day_offset": {int(offset): int(count) for offset, count in active_days.items()},
    }


def cohort_retention_matrix(
    df,
    user_col: str,
    date_col: str,
    acquisition_col: str | None = None,
    cohort_freq: str = "M",
    max_periods: int = 12,
) -> dict[str, Any]:
    import pandas as pd  # type: ignore

    frame = df[[user_col, date_col] + ([acquisition_col] if acquisition_col else [])].copy()
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    if acquisition_col:
        frame[acquisition_col] = pd.to_datetime(frame[acquisition_col], errors="coerce")
        acquisition_dates = frame.groupby(user_col)[acquisition_col].min()
    else:
        acquisition_dates = frame.groupby(user_col)[date_col].min()

    frame["acquisition_date"] = frame[user_col].map(acquisition_dates)
    frame["cohort_period"] = frame["acquisition_date"].dt.to_period(cohort_freq)
    frame["activity_period"] = frame[date_col].dt.to_period(cohort_freq)
    frame["period_index"] = (frame["activity_period"] - frame["cohort_period"]).apply(lambda value: int(value.n) if value is not pd.NaT else None)
    frame = frame.dropna(subset=["period_index"])
    frame = frame[(frame["period_index"] >= 0) & (frame["period_index"] <= max_periods)]

    cohort_sizes = frame.groupby("cohort_period")[user_col].nunique()
    matrix: dict[str, dict[str, float]] = defaultdict(dict)
    for (cohort_period, period_index), users in frame.groupby(["cohort_period", "period_index"])[user_col].nunique().items():
        cohort_size = int(cohort_sizes.get(cohort_period, 0))
        matrix[str(cohort_period)][str(int(period_index))] = round(users / cohort_size, 4) if cohort_size else 0.0

    return {
        "cohort_freq": cohort_freq,
        "cohort_sizes": {str(period): int(size) for period, size in cohort_sizes.items()},
        "retention_matrix": matrix,
    }


def ltv_summary(
    df,
    user_col: str,
    revenue_col: str,
    date_col: str,
    acquisition_col: str | None = None,
    cohort_freq: str = "M",
) -> dict[str, Any]:
    import pandas as pd  # type: ignore

    if any(column not in df.columns for column in [user_col, revenue_col, date_col]):
        raise ValueError("LTV summary needs user, revenue, and date columns.")

    frame = df[[user_col, revenue_col, date_col] + ([acquisition_col] if acquisition_col else [])].copy()
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame[revenue_col] = frame[revenue_col].fillna(0).astype(float)
    if acquisition_col:
        frame[acquisition_col] = pd.to_datetime(frame[acquisition_col], errors="coerce")
        acquisition_dates = frame.groupby(user_col)[acquisition_col].min()
    else:
        acquisition_dates = frame.groupby(user_col)[date_col].min()

    frame["acquisition_date"] = frame[user_col].map(acquisition_dates)
    frame["cohort_period"] = frame["acquisition_date"].dt.to_period(cohort_freq)
    total_users = int(frame[user_col].nunique())
    revenue_by_user = frame.groupby(user_col)[revenue_col].sum()
    paying_users = int(revenue_by_user.gt(0).sum())
    summary = {
        "users": total_users,
        "paying_users": paying_users,
        "pay_rate": round(paying_users / total_users, 4) if total_users else 0.0,
        "total_revenue": float(frame[revenue_col].sum()),
        "ltv": round(float(frame[revenue_col].sum()) / total_users, 4) if total_users else 0.0,
    }

    cohort_summary = {}
    for cohort_period, cohort_frame in frame.groupby("cohort_period"):
        cohort_users = int(cohort_frame[user_col].nunique())
        cohort_revenue = float(cohort_frame[revenue_col].sum())
        cohort_summary[str(cohort_period)] = {
            "users": cohort_users,
            "revenue": cohort_revenue,
            "ltv": round(cohort_revenue / cohort_users, 4) if cohort_users else 0.0,
        }
    summary["cohorts"] = cohort_summary
    return summary


def build_business_report(df, task: str, config: dict[str, Any]) -> dict[str, Any]:
    if task == "funnel":
        if "steps" in config:
            return funnel_from_step_columns(df, config["steps"])
        if "stage_col" in config and "ordered_stages" in config:
            return funnel_from_stage_column(df, config["stage_col"], config["ordered_stages"])
        return {"task": task, "error": "Provide either steps or stage_col + ordered_stages."}
    if task == "monetization":
        return monetization_summary(
            df,
            user_col=config["user_col"],
            revenue_col=config["revenue_col"],
            order_col=config.get("order_col"),
        )
    if task == "retention":
        return retention_summary(
            df,
            user_col=config["user_col"],
            date_col=config["date_col"],
            periods=config.get("periods"),
            acquisition_col=config.get("acquisition_col"),
        )
    if task == "cohort":
        return cohort_retention_matrix(
            df,
            user_col=config["user_col"],
            date_col=config["date_col"],
            acquisition_col=config.get("acquisition_col"),
            cohort_freq=config.get("cohort_freq", "M"),
            max_periods=int(config.get("max_periods", 12)),
        )
    if task == "ltv":
        return ltv_summary(
            df,
            user_col=config["user_col"],
            revenue_col=config["revenue_col"],
            date_col=config["date_col"],
            acquisition_col=config.get("acquisition_col"),
            cohort_freq=config.get("cohort_freq", "M"),
        )
    return {"task": task, "note": "No business template matched the requested task."}
