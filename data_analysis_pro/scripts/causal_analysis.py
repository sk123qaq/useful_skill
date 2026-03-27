#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from causal_narrative import build_causal_narrative, write_causal_narrative
from common import configure_matplotlib_defaults, ensure_output_dir, module_available, parse_json_arg, write_json
from io_router import load_dataframe

try:
    from report_export import export_dashboard
except ImportError:
    def export_dashboard(*args: Any, **kwargs: Any) -> None:
        return None


try:
    from report_index import export_run_index, infer_outputs_root
except ImportError:
    def export_run_index(*args: Any, **kwargs: Any) -> None:
        return None

    def infer_outputs_root(output_dir: Path) -> Path:
        return output_dir

TASK_ALIASES = {
    "did": "did",
    "difference-in-differences": "did",
    "difference_in_differences": "did",
    "rd": "rd",
    "regression-discontinuity": "rd",
    "regression_discontinuity": "rd",
    "rdd": "rd",
    "synthetic-control": "synthetic-control",
    "synthetic_control": "synthetic-control",
    "synth-control": "synthetic-control",
    "synthetic": "synthetic-control",
    "iv": "iv",
    "instrumental-variables": "iv",
    "instrumental_variables": "iv",
    "dml": "dml",
    "double-machine-learning": "dml",
    "double_machine_learning": "dml",
    "dr": "dr",
    "doubly-robust": "dr",
    "doubly_robust": "dr",
    "psm": "psm",
    "propensity-score-matching": "psm",
    "propensity_score_matching": "psm",
    "orthogonal": "orthogonal",
    "orthogonal-learner": "orthogonal",
    "orthogonal_learner": "orthogonal",
    "uplift": "uplift",
    "heterogeneity": "uplift",
    "cate": "cate",
    "meta-learner": "cate",
    "meta_learner": "cate",
    "causal": "causal",
    "dml_lite": "dml_lite",
    "dml-lite": "dml_lite",
    "dml_simple": "dml_lite",
}


def normalize_task(task: str) -> str:
    normalized = task.strip().lower()
    if normalized not in TASK_ALIASES:
        raise ValueError(f"Unsupported causal task: {task}")
    return TASK_ALIASES[normalized]


def _dedupe_columns(columns: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for column in columns:
        if column not in seen:
            deduped.append(column)
            seen.add(column)
    return deduped


def _configure_plotting() -> None:
    if not module_available("matplotlib"):
        return
    configure_matplotlib_defaults()


def _coerce_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _prepare_feature_frame(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    frame = df[_dedupe_columns(feature_cols)].copy()
    categorical_columns = list(frame.select_dtypes(exclude=["number", "bool"]).columns)
    numeric_columns = list(frame.select_dtypes(include=["number", "bool"]).columns)
    if numeric_columns:
        frame[numeric_columns] = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    if categorical_columns:
        frame[categorical_columns] = frame[categorical_columns].fillna("__MISSING__").astype("string")
        frame = pd.get_dummies(frame, columns=categorical_columns, dummy_na=False)
    frame = frame.fillna(frame.median(numeric_only=True)).fillna(0.0)
    return frame.astype(float)


def _resolve_binary_values(df: pd.DataFrame, treatment_col: str, treatment_value: Any | None, control_value: Any | None) -> tuple[Any, Any]:
    variants = [value for value in df[treatment_col].dropna().unique().tolist()]
    if treatment_value is not None and control_value is not None:
        return treatment_value, control_value
    if "treatment" in variants and "control" in variants:
        return "treatment", "control"
    if True in variants and False in variants:
        return True, False
    if 1 in variants and 0 in variants:
        return 1, 0
    if len(variants) == 2:
        ordered = sorted(variants, key=str)
        return ordered[1], ordered[0]
    
    # Auto binarize by median if not specified and > 2 values
    median = df[treatment_col].median()
    return f"__GT_MEDIAN_{median}__", median


def _set_treatment_indicator(df: pd.DataFrame, treatment_col: str, treatment_value: Any, control_value: Any) -> pd.DataFrame:
    df = df.copy()
    if isinstance(treatment_value, str) and treatment_value.startswith("__GT_MEDIAN_"):
        median = float(control_value)
        df["__treated__"] = (df[treatment_col] > median).astype(int)
    else:
        df["__treated__"] = (df[treatment_col] == treatment_value).astype(int)
    return df


def _std_mean_diff(treated: pd.Series, control: pd.Series) -> float:
    treated_values = treated.astype(float).to_numpy()
    control_values = control.astype(float).to_numpy()
    treated_var = float(np.var(treated_values, ddof=1)) if len(treated_values) > 1 else 0.0
    control_var = float(np.var(control_values, ddof=1)) if len(control_values) > 1 else 0.0
    pooled = math.sqrt((treated_var + control_var) / 2) if (treated_var + control_var) > 0 else 0.0
    if pooled == 0:
        return 0.0
    return float((treated_values.mean() - control_values.mean()) / pooled)


def _predict_positive_probability(model, X: pd.DataFrame) -> np.ndarray:
    if not hasattr(model, "predict_proba"):
        return np.asarray(model.predict(X), dtype=float)
    probabilities = model.predict_proba(X)
    classes = getattr(model, "classes_", None)
    if classes is None or len(classes) == 0:
        return np.asarray(probabilities, dtype=float).reshape(-1)
    if len(classes) == 1:
        return np.full(len(X), float(classes[0]), dtype=float)
    positive_index = int(np.where(np.asarray(classes) == 1)[0][0]) if 1 in set(classes) else len(classes) - 1
    return np.asarray(probabilities[:, positive_index], dtype=float)


def _is_binary_outcome(series: pd.Series) -> bool:
    values = set(series.dropna().unique().tolist())
    return values.issubset({0, 1, 0.0, 1.0, True, False})


def _build_outcome_model(binary_outcome: bool):
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

    if binary_outcome:
        return RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=1)
    return RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=1)


def _build_propensity_model():
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression(max_iter=1000)


def _build_effect_model():
    from sklearn.ensemble import RandomForestRegressor

    return RandomForestRegressor(n_estimators=200, random_state=42, n_jobs=1)


def _predict_outcome(model, X: pd.DataFrame, binary_outcome: bool) -> np.ndarray:
    if binary_outcome:
        return _predict_positive_probability(model, X)
    return np.asarray(model.predict(X), dtype=float)


def _safe_cv_splits(indicator: pd.Series, desired_splits: int) -> int:
    value_counts = indicator.value_counts()
    if value_counts.empty:
        raise ValueError("Unable to determine cross-fitting splits from an empty indicator.")
    min_count = int(value_counts.min())
    if min_count < 2:
        raise ValueError("Need at least two observations in each treatment arm for cross-fitting.")
    return max(2, min(int(desired_splits), min_count))


def _crossfit_main_effect_and_propensity(
    encoded_features: pd.DataFrame,
    treatment_indicator: pd.Series,
    outcome: pd.Series,
    n_splits: int,
    random_state: int,
) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.model_selection import StratifiedKFold

    m_hat = np.zeros(len(encoded_features), dtype=float)
    e_hat = np.zeros(len(encoded_features), dtype=float)
    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    for train_idx, valid_idx in splitter.split(encoded_features, treatment_indicator):
        X_train = encoded_features.iloc[train_idx]
        X_valid = encoded_features.iloc[valid_idx]
        w_train = treatment_indicator.iloc[train_idx]
        y_train = outcome.iloc[train_idx]

        propensity_model = _build_propensity_model()
        propensity_model.fit(X_train, w_train)
        e_hat[valid_idx] = propensity_model.predict_proba(X_valid)[:, 1]

        outcome_model = _build_outcome_model(binary_outcome=False)
        outcome_model.fit(X_train, y_train)
        m_hat[valid_idx] = _predict_outcome(outcome_model, X_valid, binary_outcome=False)
    return m_hat, e_hat


def _propensity_overlap_summary(propensity: np.ndarray, treatment: pd.Series) -> dict[str, Any]:
    treated_scores = propensity[treatment.to_numpy() == 1]
    control_scores = propensity[treatment.to_numpy() == 0]
    overlap_low = max(float(np.min(treated_scores)), float(np.min(control_scores)))
    overlap_high = min(float(np.max(treated_scores)), float(np.max(control_scores)))
    in_support = (propensity >= overlap_low) & (propensity <= overlap_high)
    return {
        "lower": overlap_low,
        "upper": overlap_high,
        "share_in_common_support": float(np.mean(in_support)),
    }


def _ordered_index(frame: pd.DataFrame, index_name: str) -> pd.DataFrame:
    ordered = frame.copy()
    if index_name not in ordered.columns:
        return ordered
    datetime_values = pd.to_datetime(ordered[index_name], errors="coerce")
    if datetime_values.notna().all():
        ordered["__sort_key__"] = datetime_values
    else:
        numeric_values = pd.to_numeric(ordered[index_name], errors="coerce")
        if numeric_values.notna().all():
            ordered["__sort_key__"] = numeric_values
        else:
            ordered["__sort_key__"] = ordered[index_name].astype(str)
    ordered = ordered.sort_values("__sort_key__").drop(columns="__sort_key__")
    return ordered


def _bucket_lift_rows(scored: pd.DataFrame, score_col: str, outcome_col: str, bucket_count: int) -> list[dict[str, Any]]:
    if len(scored) < 4:
        return []
    bucket_count = min(bucket_count, max(2, len(scored) // 4 or 2))
    ranked = scored.copy()
    ranked["__bucket__"] = pd.qcut(
        ranked[score_col].rank(method="first"),
        q=bucket_count,
        labels=False,
        duplicates="drop",
    )
    ranked["__bucket__"] = ranked["__bucket__"].astype(int)
    rows = []
    for bucket, bucket_frame in ranked.groupby("__bucket__"):
        treated_frame = bucket_frame.loc[bucket_frame["__treated__"] == 1, outcome_col]
        control_frame = bucket_frame.loc[bucket_frame["__treated__"] == 0, outcome_col]
        observed_lift = float(treated_frame.mean() - control_frame.mean()) if len(treated_frame) and len(control_frame) else None
        rows.append(
            {
                "bucket": int(bucket),
                "n_rows": int(len(bucket_frame)),
                "predicted_effect_mean": float(bucket_frame[score_col].mean()),
                "treated_rows": int((bucket_frame["__treated__"] == 1).sum()),
                "control_rows": int((bucket_frame["__treated__"] == 0).sum()),
                "observed_lift": observed_lift,
            }
        )
    rows.sort(key=lambda item: item["bucket"], reverse=True)
    return rows


def _subgroup_effect_rows(
    working: pd.DataFrame,
    score_columns: dict[str, str],
    outcome_col: str,
    heterogeneity_cols: list[str],
    min_group_size: int,
) -> list[dict[str, Any]]:
    subgroup_rows: list[dict[str, Any]] = []
    for column in heterogeneity_cols:
        for subgroup, subgroup_frame in working.groupby(column):
            treated_frame = subgroup_frame.loc[subgroup_frame["__treated__"] == 1, outcome_col]
            control_frame = subgroup_frame.loc[subgroup_frame["__treated__"] == 0, outcome_col]
            if len(treated_frame) < min_group_size or len(control_frame) < min_group_size:
                continue
            row: dict[str, Any] = {
                "dimension": column,
                "segment": str(subgroup),
                "treated_mean": float(treated_frame.mean()),
                "control_mean": float(control_frame.mean()),
                "observed_lift": float(treated_frame.mean() - control_frame.mean()),
                "treated_n": int(len(treated_frame)),
                "control_n": int(len(control_frame)),
            }
            for method_name, score_col in score_columns.items():
                row[f"{method_name}_mean_effect"] = float(subgroup_frame[score_col].mean())
            subgroup_rows.append(row)
    subgroup_rows.sort(key=lambda item: abs(item["observed_lift"]), reverse=True)
    return subgroup_rows


def _balance_table(encoded: pd.DataFrame, treatment_indicator: pd.Series, top_n: int = 12) -> dict[str, Any]:
    treated_mask = treatment_indicator.astype(bool)
    rows = []
    for column in encoded.columns:
        treated = encoded.loc[treated_mask, column]
        control = encoded.loc[~treated_mask, column]
        rows.append(
            {
                "feature": column,
                "treated_mean": float(treated.mean()),
                "control_mean": float(control.mean()),
                "smd": _std_mean_diff(treated, control),
            }
        )
    rows.sort(key=lambda item: abs(item["smd"]), reverse=True)
    return {
        "mean_absolute_smd": float(np.mean([abs(item["smd"]) for item in rows])) if rows else 0.0,
        "top_imbalanced_features": rows[:top_n],
        "all_features": rows,
    }


def difference_in_differences_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    outcome_col = config.get("outcome_col")
    treatment_col = config.get("treatment_col") or config.get("group_col")
    post_col = config.get("post_col")
    time_col = config.get("time_col")
    unit_col = config.get("unit_col")
    if not outcome_col or not treatment_col:
        raise ValueError("DID requires `outcome_col` and `treatment_col`/`group_col`.")

    working = df.copy()
    working[outcome_col] = _coerce_numeric(working[outcome_col])
    working = working.dropna(subset=[outcome_col, treatment_col])
    treatment_value, control_value = _resolve_binary_values(
        working, treatment_col, config.get("treatment_value"), config.get("control_value")
    )
    working = _set_treatment_indicator(working, treatment_col, treatment_value, control_value)
    if isinstance(treatment_value, str) and treatment_value.startswith("__GT_MEDIAN_"):
        median = float(control_value)
        treatment_value, control_value = f"> {median}", f"<= {median}"

    if post_col:
        working = working.dropna(subset=[post_col])
        post_value = config.get("post_value", 1)
        working["__post__"] = (working[post_col] == post_value).astype(int)
    else:
        period_col = config.get("period_col")
        if not period_col:
            raise ValueError("DID requires `post_col` or `period_col`.")
        working = working.dropna(subset=[period_col])
        pre_value = config.get("pre_value")
        post_value = config.get("post_value")
        if pre_value is None or post_value is None:
            values = sorted(working[period_col].astype(str).unique().tolist())
            if len(values) != 2:
                raise ValueError("DID period_col mode requires exactly two period values or explicit pre/post values.")
            pre_value, post_value = values[0], values[1]
        working["__post__"] = (working[period_col].astype(str) == str(post_value)).astype(int)
        post_col = period_col

    subset = working.loc[working["__treated__"].isin([0, 1])].copy()
    group_period_means = (
        subset.groupby(["__treated__", "__post__"])[outcome_col].mean().rename("mean_outcome").reset_index()
    )
    if group_period_means.shape[0] < 4:
        raise ValueError("DID requires observations in all four treatment/control x pre/post cells.")

    mean_map = {
        (int(row["__treated__"]), int(row["__post__"])): float(row["mean_outcome"])
        for _, row in group_period_means.iterrows()
    }
    control_pre = mean_map[(0, 0)]
    control_post = mean_map[(0, 1)]
    treated_pre = mean_map[(1, 0)]
    treated_post = mean_map[(1, 1)]
    did_estimate = (treated_post - treated_pre) - (control_post - control_pre)
    relative_effect = did_estimate / control_pre if control_pre else None

    regression = {"available": False}
    if module_available("statsmodels"):
        import statsmodels.api as sm  # type: ignore

        regressors = pd.DataFrame(
            {
                "treated": subset["__treated__"].astype(float),
                "post": subset["__post__"].astype(float),
            },
            index=subset.index,
        )
        regressors["interaction"] = regressors["treated"] * regressors["post"]
        regressors = sm.add_constant(regressors, has_constant="add")
        model = sm.OLS(subset[outcome_col].astype(float), regressors).fit(cov_type="HC1")
        confidence_interval = model.conf_int().loc["interaction"].tolist()
        regression = {
            "available": True,
            "coefficient": float(model.params["interaction"]),
            "standard_error": float(model.bse["interaction"]),
            "p_value": float(model.pvalues["interaction"]),
            "confidence_interval": [float(confidence_interval[0]), float(confidence_interval[1])],
            "n_obs": int(model.nobs),
            "cov_type": "HC1",
        }

    report: dict[str, Any] = {
        "task": "did",
        "outcome_col": outcome_col,
        "treatment_col": treatment_col,
        "treatment_value": treatment_value,
        "control_value": control_value,
        "post_col": post_col,
        "did_estimate": float(did_estimate),
        "relative_effect_vs_control_pre": float(relative_effect) if relative_effect is not None else None,
        "cell_means": {
            "control_pre": control_pre,
            "control_post": control_post,
            "treated_pre": treated_pre,
            "treated_post": treated_post,
        },
        "regression": regression,
        "assumptions": {
            "parallel_trends_not_verified": True,
            "stable_unit_treatment_value_assumption": True,
            "time_varying_confounding_not_removed": True,
        },
        "artifacts": [],
    }

    if output_dir is not None:
        summary_table = subset.groupby([treatment_col, "__post__"])[outcome_col].agg(["mean", "count"]).reset_index()
        table_path = output_dir / "did_cell_summary.csv"
        summary_table.to_csv(table_path, index=False)
        report["artifacts"].append(str(table_path))

        if module_available("matplotlib"):
            import matplotlib.pyplot as plt  # type: ignore

            _configure_plotting()
            fig, ax = plt.subplots(figsize=(7, 5))
            ax.plot(["pre", "post"], [control_pre, control_post], marker="o", label=str(control_value))
            ax.plot(["pre", "post"], [treated_pre, treated_post], marker="o", label=str(treatment_value))
            ax.set_title("Difference-in-differences group means")
            ax.set_xlabel("Period")
            ax.set_ylabel(outcome_col)
            ax.legend()
            path = output_dir / "did_group_means.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

            if time_col and time_col in subset.columns:
                trend = subset.groupby([time_col, treatment_col])[outcome_col].mean().reset_index()
                fig, ax = plt.subplots(figsize=(8, 5))
                for group_name, group_frame in trend.groupby(treatment_col):
                    ordered = group_frame.sort_values(time_col)
                    ax.plot(ordered[time_col].astype(str), ordered[outcome_col], marker="o", label=str(group_name))
                ax.set_title("Outcome trend by group")
                ax.set_xlabel(time_col)
                ax.set_ylabel(outcome_col)
                ax.legend()
                path = output_dir / "did_trend.png"
                fig.tight_layout()
                fig.savefig(path, dpi=150)
                plt.close(fig)
                report["artifacts"].append(str(path))

    if unit_col and unit_col in subset.columns:
        report["n_units"] = int(subset[unit_col].nunique())
    return report


def regression_discontinuity_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    outcome_col = config.get("outcome_col")
    running_col = config.get("running_col")
    cutoff = config.get("cutoff")
    if outcome_col is None or running_col is None or cutoff is None:
        raise ValueError("RD requires `outcome_col`, `running_col`, and `cutoff`.")

    working = df.copy()
    working[outcome_col] = _coerce_numeric(working[outcome_col])
    working[running_col] = _coerce_numeric(working[running_col])
    working = working.dropna(subset=[outcome_col, running_col])
    working["running_centered"] = working[running_col] - float(cutoff)

    bandwidth = config.get("bandwidth")
    if bandwidth is None:
        bandwidth = float(np.quantile(np.abs(working["running_centered"]), 0.4))
        if bandwidth <= 0:
            bandwidth = float(np.max(np.abs(working["running_centered"])))
    bandwidth = float(bandwidth)
    local = working.loc[working["running_centered"].abs() <= bandwidth].copy()
    if local.empty:
        raise ValueError("No observations fall within the requested RD bandwidth.")

    treatment_col = config.get("treatment_col")
    if treatment_col and treatment_col in local.columns:
        treatment_value, control_value = _resolve_binary_values(
            local,
            treatment_col,
            config.get("treatment_value"),
            config.get("control_value"),
        )
        local = _set_treatment_indicator(local, treatment_col, treatment_value, control_value)
        if isinstance(treatment_value, str) and treatment_value.startswith("__GT_MEDIAN_"):
            median = float(control_value)
            treatment_value, control_value = f"> {median}", f"<= {median}"
    else:
        local["__treated__"] = (local["running_centered"] >= 0).astype(int)
        treatment_value, control_value = 1, 0

    left = local.loc[local["running_centered"] < 0]
    right = local.loc[local["running_centered"] >= 0]
    if len(left) < 3 or len(right) < 3:
        raise ValueError("RD needs at least 3 observations on each side of the cutoff within the selected bandwidth.")

    degree = int(config.get("degree", 1))
    kernel = str(config.get("kernel", "triangular"))
    if kernel == "triangular":
        weights = np.clip(1 - np.abs(local["running_centered"]) / bandwidth, 0.0, None)
    else:
        weights = np.ones(len(local), dtype=float)

    estimate = float(right[outcome_col].mean() - left[outcome_col].mean())
    regression: dict[str, Any] = {"available": False}
    rd_regressors: pd.DataFrame | None = None
    weight_series = pd.Series(weights, index=local.index, dtype=float)
    if module_available("statsmodels"):
        import statsmodels.api as sm  # type: ignore

        rd_regressors = pd.DataFrame(
            {
                "treated": local["__treated__"].astype(float),
                "running_centered": local["running_centered"].astype(float),
            },
            index=local.index,
        )
        rd_regressors["treated_x_running"] = rd_regressors["treated"] * rd_regressors["running_centered"]
        if degree >= 2:
            rd_regressors["running_centered_sq"] = rd_regressors["running_centered"] ** 2
            rd_regressors["treated_x_running_sq"] = rd_regressors["treated"] * rd_regressors["running_centered_sq"]
        rd_regressors = sm.add_constant(rd_regressors, has_constant="add")
        model = sm.WLS(local[outcome_col].astype(float), rd_regressors, weights=weights).fit(cov_type="HC1")
        confidence_interval = model.conf_int().loc["treated"].tolist()
        estimate = float(model.params["treated"])
        regression = {
            "available": True,
            "coefficient": estimate,
            "standard_error": float(model.bse["treated"]),
            "p_value": float(model.pvalues["treated"]),
            "confidence_interval": [float(confidence_interval[0]), float(confidence_interval[1])],
            "n_obs": int(model.nobs),
            "cov_type": "HC1",
            "kernel": kernel,
            "degree": degree,
        }

    continuity_checks = {}
    for covariate in config.get("covariate_cols", []):
        if covariate not in local.columns:
            continue
        covariate_series = _coerce_numeric(local[covariate])
        covariate_local = local.assign(__covariate__=covariate_series).dropna(subset=["__covariate__"])
        left_cov = covariate_local.loc[covariate_local["running_centered"] < 0, "__covariate__"]
        right_cov = covariate_local.loc[covariate_local["running_centered"] >= 0, "__covariate__"]
        if len(left_cov) < 2 or len(right_cov) < 2:
            continue
        continuity_result = {
            "left_mean": float(left_cov.mean()),
            "right_mean": float(right_cov.mean()),
            "difference": float(right_cov.mean() - left_cov.mean()),
            "method": "welch_t_test",
        }
        if rd_regressors is not None:
            import statsmodels.api as sm  # type: ignore

            covariate_regressors = rd_regressors.loc[covariate_local.index]
            covariate_model = sm.WLS(
                covariate_local["__covariate__"].astype(float),
                covariate_regressors,
                weights=weight_series.loc[covariate_local.index],
            ).fit(cov_type="HC1")
            confidence_interval = covariate_model.conf_int().loc["treated"].tolist()
            continuity_result.update(
                {
                    "method": "local_linear_rd",
                    "local_effect": float(covariate_model.params["treated"]),
                    "standard_error": float(covariate_model.bse["treated"]),
                    "p_value": float(covariate_model.pvalues["treated"]),
                    "confidence_interval": [float(confidence_interval[0]), float(confidence_interval[1])],
                }
            )
        else:
            statistic, p_value = stats.ttest_ind(right_cov, left_cov, equal_var=False)
            continuity_result.update(
                {
                    "p_value": float(p_value),
                    "statistic": float(statistic),
                }
            )
        continuity_checks[covariate] = continuity_result

    report: dict[str, Any] = {
        "task": "rd",
        "outcome_col": outcome_col,
        "running_col": running_col,
        "cutoff": float(cutoff),
        "bandwidth": bandwidth,
        "kernel": kernel,
        "degree": degree,
        "treatment_col": treatment_col or "__threshold_rule__",
        "treatment_value": treatment_value,
        "control_value": control_value,
        "local_effect": estimate,
        "left_mean": float(left[outcome_col].mean()),
        "right_mean": float(right[outcome_col].mean()),
        "counts": {"left": int(len(left)), "right": int(len(right))},
        "treated_share": {
            "left": float(left["__treated__"].mean()),
            "right": float(right["__treated__"].mean()),
        },
        "regression": regression,
        "covariate_continuity": continuity_checks,
        "artifacts": [],
    }

    if output_dir is not None and module_available("matplotlib"):
        import matplotlib.pyplot as plt  # type: ignore

        _configure_plotting()
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.scatter(local[running_col], local[outcome_col], alpha=0.65)
        ax.axvline(float(cutoff), color="tab:red", linestyle="--")
        ax.set_title("Regression discontinuity around cutoff")
        ax.set_xlabel(running_col)
        ax.set_ylabel(outcome_col)
        path = output_dir / "rd_scatter.png"
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        report["artifacts"].append(str(path))

        bins = int(config.get("n_bins", 12))
        binned = local.assign(
            __bin__=pd.cut(local["running_centered"], bins=bins, duplicates="drop")
        ).dropna(subset=["__bin__"])
        if not binned.empty:
            grouped = (
                binned.groupby("__bin__", observed=False)
                .agg(running_mean=(running_col, "mean"), outcome_mean=(outcome_col, "mean"))
                .reset_index(drop=True)
            )
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.plot(grouped["running_mean"], grouped["outcome_mean"], marker="o")
            ax.axvline(float(cutoff), color="tab:red", linestyle="--")
            ax.set_title("RD binned means")
            ax.set_xlabel(running_col)
            ax.set_ylabel(outcome_col)
            path = output_dir / "rd_binned_means.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

    return report


def double_machine_learning_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    treatment_col = config.get("treatment_col")
    outcome_col = config.get("outcome_col")
    covariate_cols = config.get("covariate_cols") or config.get("feature_cols")
    heterogeneity_cols = list(config.get("heterogeneity_cols", []))
    if not treatment_col or not outcome_col or not covariate_cols:
        raise ValueError("DML requires `treatment_col`, `outcome_col`, and `covariate_cols`.")

    selected_columns = _dedupe_columns([treatment_col, outcome_col, *covariate_cols, *heterogeneity_cols])
    working = df[selected_columns].copy()
    working[outcome_col] = _coerce_numeric(working[outcome_col])
    working = working.dropna(subset=[treatment_col, outcome_col])
    if _is_binary_outcome(working[outcome_col]):
        raise ValueError("Current DML implementation is restricted to continuous outcomes.")

    treatment_value, control_value = _resolve_binary_values(
        working, treatment_col, config.get("treatment_value"), config.get("control_value")
    )
    if isinstance(treatment_value, str) and treatment_value.startswith("__GT_MEDIAN_"):
        median = float(control_value)
        working["__treated__"] = (working[treatment_col] > median).astype(int)
        treatment_value, control_value = f"> {median}", f"<= {median}"
    else:
        working = working.loc[working[treatment_col].isin([treatment_value, control_value])].copy()
        working["__treated__"] = (working[treatment_col] == treatment_value).astype(int)

    encoded_features = _prepare_feature_frame(working, list(covariate_cols))
    treatment_indicator = working["__treated__"].astype(int)
    outcome = working[outcome_col].astype(float)
    n_splits = _safe_cv_splits(treatment_indicator, int(config.get("n_splits", 3)))
    random_state = int(config.get("random_state", 42))
    clip = float(config.get("propensity_clip", 0.02))

    m_hat, e_hat = _crossfit_main_effect_and_propensity(
        encoded_features,
        treatment_indicator,
        outcome,
        n_splits=n_splits,
        random_state=random_state,
    )
    e_hat = np.clip(e_hat, clip, 1 - clip)

    y_res = outcome.to_numpy(dtype=float) - m_hat
    w_res = treatment_indicator.to_numpy(dtype=float) - e_hat
    denominator = float(np.sum(w_res**2))
    if denominator <= 1e-8:
        raise ValueError("Residualized treatment variance is too small for DML.")

    theta = float(np.sum(w_res * y_res) / denominator)
    regression_error = y_res - theta * w_res
    orthogonal_scores = w_res * regression_error
    n_obs = len(working)
    mean_w_sq = float(np.mean(w_res**2))
    score_variance = float(np.mean(orthogonal_scores**2))
    standard_error = math.sqrt(score_variance / (mean_w_sq**2 * n_obs)) if mean_w_sq > 0 and n_obs > 1 else 0.0
    z_score = theta / standard_error if standard_error else 0.0
    p_value = float(2 * (1 - stats.norm.cdf(abs(z_score)))) if standard_error else 1.0
    confidence_interval = [float(theta - 1.96 * standard_error), float(theta + 1.96 * standard_error)]
    naive_difference = float(outcome.loc[treatment_indicator == 1].mean() - outcome.loc[treatment_indicator == 0].mean())

    working["dml_main_effect_hat"] = m_hat
    working["dml_propensity_hat"] = e_hat
    working["dml_outcome_residual"] = y_res
    working["dml_treatment_residual"] = w_res

    subgroup_rows: list[dict[str, Any]] = []
    min_group_size = int(config.get("min_group_size", 3))
    min_group_residual_var = float(config.get("min_group_residual_variance", 1e-6))
    for column in heterogeneity_cols:
        for subgroup, subgroup_frame in working.groupby(column):
            treated_count = int(subgroup_frame["__treated__"].sum())
            control_count = int(len(subgroup_frame) - treated_count)
            if treated_count < min_group_size or control_count < min_group_size:
                continue
            subgroup_w_res = subgroup_frame["dml_treatment_residual"].to_numpy(dtype=float)
            subgroup_y_res = subgroup_frame["dml_outcome_residual"].to_numpy(dtype=float)
            subgroup_denominator = float(np.sum(subgroup_w_res**2))
            if subgroup_denominator <= min_group_residual_var:
                continue
            subgroup_theta = float(np.sum(subgroup_w_res * subgroup_y_res) / subgroup_denominator)
            subgroup_rows.append(
                {
                    "dimension": column,
                    "segment": str(subgroup),
                    "treated_mean": float(subgroup_frame.loc[subgroup_frame["__treated__"] == 1, outcome_col].mean()),
                    "control_mean": float(subgroup_frame.loc[subgroup_frame["__treated__"] == 0, outcome_col].mean()),
                    "observed_lift": float(
                        subgroup_frame.loc[subgroup_frame["__treated__"] == 1, outcome_col].mean()
                        - subgroup_frame.loc[subgroup_frame["__treated__"] == 0, outcome_col].mean()
                    ),
                    "treated_n": treated_count,
                    "control_n": control_count,
                    "dml_effect": subgroup_theta,
                }
            )
    subgroup_rows.sort(key=lambda item: abs(item["observed_lift"]), reverse=True)

    report: dict[str, Any] = {
        "task": "dml",
        "treatment_col": treatment_col,
        "outcome_col": outcome_col,
        "covariate_cols": list(covariate_cols),
        "treatment_value": treatment_value,
        "control_value": control_value,
        "n_rows_used": int(len(working)),
        "n_splits": int(n_splits),
        "average_treatment_effect": theta,
        "naive_difference": naive_difference,
        "standard_error": float(standard_error),
        "z_score": float(z_score),
        "p_value": p_value,
        "confidence_interval": confidence_interval,
        "propensity_overlap": _propensity_overlap_summary(e_hat, treatment_indicator),
        "effective_treatment_variance": mean_w_sq,
        "score_distribution": {
            "min": float(np.min(orthogonal_scores)),
            "p25": float(np.percentile(orthogonal_scores, 25)),
            "median": float(np.median(orthogonal_scores)),
            "p75": float(np.percentile(orthogonal_scores, 75)),
            "max": float(np.max(orthogonal_scores)),
        },
        "subgroup_effects": subgroup_rows[:12],
        "artifacts": [],
    }

    if output_dir is not None:
        score_path = output_dir / "dml_residuals.csv"
        working.to_csv(score_path, index=False)
        report["artifacts"].append(str(score_path))

        if module_available("matplotlib"):
            import matplotlib.pyplot as plt  # type: ignore

            _configure_plotting()
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.scatter(w_res, y_res, alpha=0.75)
            x_line = np.linspace(float(np.min(w_res)), float(np.max(w_res)), 100)
            ax.plot(x_line, theta * x_line, color="tab:red", linewidth=2)
            ax.set_title("DML residual-on-residual fit")
            ax.set_xlabel("Treatment residual")
            ax.set_ylabel("Outcome residual")
            path = output_dir / "dml_residual_fit.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

            fig, ax = plt.subplots(figsize=(8, 5))
            ax.hist(orthogonal_scores, bins=12, alpha=0.85)
            ax.set_title("Orthogonal score distribution")
            ax.set_xlabel("Orthogonal score")
            ax.set_ylabel("Count")
            path = output_dir / "dml_score_distribution.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

    return report


def propensity_score_matching_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    from sklearn.linear_model import LogisticRegression

    treatment_col = config.get("treatment_col")
    outcome_col = config.get("outcome_col")
    covariate_cols = config.get("covariate_cols")
    id_col = config.get("id_col")
    if not treatment_col or not outcome_col or not covariate_cols:
        raise ValueError("PSM requires `treatment_col`, `outcome_col`, and `covariate_cols`.")

    working = df[[*( [id_col] if id_col else [] ), treatment_col, outcome_col, *covariate_cols]].copy()
    working[outcome_col] = _coerce_numeric(working[outcome_col])
    working = working.dropna(subset=[treatment_col, outcome_col])
    treatment_value, control_value = _resolve_binary_values(
        working, treatment_col, config.get("treatment_value"), config.get("control_value")
    )
    if isinstance(treatment_value, str) and treatment_value.startswith("__GT_MEDIAN_"):
        median = float(control_value)
        working["__treated__"] = (working[treatment_col] > median).astype(int)
        treatment_value, control_value = f"> {median}", f"<= {median}"
    else:
        working = working.loc[working[treatment_col].isin([treatment_value, control_value])].copy()
        working["__treated__"] = (working[treatment_col] == treatment_value).astype(int)

    feature_frame = _prepare_feature_frame(working, list(covariate_cols))
    model = LogisticRegression(max_iter=1000)
    model.fit(feature_frame, working["__treated__"])
    propensity = model.predict_proba(feature_frame)[:, 1]
    working["propensity_score"] = propensity

    overlap_low = max(
        float(working.loc[working["__treated__"] == 1, "propensity_score"].min()),
        float(working.loc[working["__treated__"] == 0, "propensity_score"].min()),
    )
    overlap_high = min(
        float(working.loc[working["__treated__"] == 1, "propensity_score"].max()),
        float(working.loc[working["__treated__"] == 0, "propensity_score"].max()),
    )
    common_support_mask = working["propensity_score"].between(overlap_low, overlap_high, inclusive="both")

    caliper = config.get("caliper")
    caliper_value = float(caliper) if caliper is not None else None
    with_replacement = bool(config.get("with_replacement", False))
    treated = working.loc[working["__treated__"] == 1].sort_values("propensity_score")
    control = working.loc[working["__treated__"] == 0].sort_values("propensity_score")
    available_controls = list(control.index)
    pairs: list[tuple[Any, Any, float]] = []
    for treated_index, treated_row in treated.iterrows():
        if not available_controls:
            break
        candidate_scores = control.loc[available_controls, "propensity_score"]
        distances = (candidate_scores - float(treated_row["propensity_score"])).abs()
        best_index = distances.idxmin()
        best_distance = float(distances.loc[best_index])
        if caliper_value is not None and best_distance > caliper_value:
            continue
        pairs.append((treated_index, best_index, best_distance))
        if not with_replacement:
            available_controls.remove(best_index)

    if not pairs:
        raise ValueError("No matches found under the current caliper/overlap constraints.")

    matched_rows = []
    pair_differences = []
    for pair_id, (treated_index, control_index, distance) in enumerate(pairs, start=1):
        treated_row = working.loc[treated_index]
        control_row = working.loc[control_index]
        diff = float(treated_row[outcome_col] - control_row[outcome_col])
        pair_differences.append(diff)
        matched_rows.append(
            {
                "pair_id": pair_id,
                "treated_index": str(treated_index),
                "control_index": str(control_index),
                "treated_id": str(treated_row[id_col]) if id_col else str(treated_index),
                "control_id": str(control_row[id_col]) if id_col else str(control_index),
                "treated_outcome": float(treated_row[outcome_col]),
                "control_outcome": float(control_row[outcome_col]),
                "treated_propensity": float(treated_row["propensity_score"]),
                "control_propensity": float(control_row["propensity_score"]),
                "distance": distance,
                "outcome_difference": diff,
            }
        )

    pair_diff_array = np.asarray(pair_differences, dtype=float)
    att = float(pair_diff_array.mean())
    statistic, p_value = stats.ttest_1samp(pair_diff_array, 0.0) if len(pair_diff_array) > 1 else (0.0, 1.0)
    se = float(pair_diff_array.std(ddof=1) / math.sqrt(len(pair_diff_array))) if len(pair_diff_array) > 1 else 0.0
    critical = float(stats.t.ppf(0.975, len(pair_diff_array) - 1)) if len(pair_diff_array) > 1 else 0.0
    confidence_interval = [float(att - critical * se), float(att + critical * se)] if len(pair_diff_array) > 1 else [att, att]

    pre_balance = _balance_table(feature_frame, working["__treated__"])
    matched_indices = [index for pair in pairs for index in pair[:2]]
    matched_feature_frame = feature_frame.loc[matched_indices]
    matched_treatment = working.loc[matched_indices, "__treated__"]
    post_balance = _balance_table(matched_feature_frame, matched_treatment)

    coefficient_rows = [
        {"feature": feature, "coefficient": float(coef)}
        for feature, coef in sorted(
            zip(feature_frame.columns.tolist(), model.coef_[0].tolist()),
            key=lambda item: abs(item[1]),
            reverse=True,
        )[:10]
    ]

    report: dict[str, Any] = {
        "task": "psm",
        "treatment_col": treatment_col,
        "outcome_col": outcome_col,
        "covariate_cols": list(covariate_cols),
        "treatment_value": treatment_value,
        "control_value": control_value,
        "n_rows_used": int(len(working)),
        "n_treated": int(int(working["__treated__"].sum())),
        "n_control": int(int((1 - working["__treated__"]).sum())),
        "matched_pairs": int(len(pairs)),
        "average_treatment_effect_on_treated": att,
        "confidence_interval": confidence_interval,
        "p_value": float(p_value),
        "common_support": {
            "lower": overlap_low,
            "upper": overlap_high,
            "share_in_common_support": float(common_support_mask.mean()),
        },
        "balance": {
            "before_matching": pre_balance,
            "after_matching": post_balance,
            "balance_improved": bool(post_balance["mean_absolute_smd"] <= pre_balance["mean_absolute_smd"]),
        },
        "propensity_model_top_coefficients": coefficient_rows,
        "artifacts": [],
    }

    if output_dir is not None:
        matched_path = output_dir / "psm_matched_pairs.csv"
        pd.DataFrame(matched_rows).to_csv(matched_path, index=False)
        report["artifacts"].append(str(matched_path))

        if module_available("matplotlib"):
            import matplotlib.pyplot as plt  # type: ignore

            _configure_plotting()
            fig, ax = plt.subplots(figsize=(8, 5))
            treated_scores = working.loc[working["__treated__"] == 1, "propensity_score"]
            control_scores = working.loc[working["__treated__"] == 0, "propensity_score"]
            ax.hist(control_scores, bins=10, alpha=0.6, label=str(control_value))
            ax.hist(treated_scores, bins=10, alpha=0.6, label=str(treatment_value))
            ax.set_title("Propensity score overlap")
            ax.set_xlabel("Propensity score")
            ax.set_ylabel("Count")
            ax.legend()
            path = output_dir / "psm_propensity_overlap.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

            top_before = pre_balance["top_imbalanced_features"][:8]
            top_after_lookup = {row["feature"]: row["smd"] for row in post_balance["all_features"]}
            labels = [row["feature"] for row in top_before][::-1]
            before_values = [row["smd"] for row in top_before][::-1]
            after_values = [top_after_lookup.get(label, 0.0) for label in labels]
            y = np.arange(len(labels))
            fig, ax = plt.subplots(figsize=(9, 5))
            ax.barh(y - 0.18, before_values, height=0.35, label="before")
            ax.barh(y + 0.18, after_values, height=0.35, label="after")
            ax.set_yticks(y)
            ax.set_yticklabels(labels)
            ax.set_title("Standardized mean difference before/after matching")
            ax.set_xlabel("SMD")
            ax.legend()
            path = output_dir / "psm_balance_smd.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

    return report


def synthetic_control_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    from scipy.optimize import minimize

    unit_col = config.get("unit_col")
    time_col = config.get("time_col")
    outcome_col = config.get("outcome_col")
    treated_unit = config.get("treated_unit")
    intervention_time = config.get("intervention_time")
    post_col = config.get("post_col")
    if not unit_col or not time_col or not outcome_col or treated_unit is None:
        raise ValueError("Synthetic control requires `unit_col`, `time_col`, `outcome_col`, and `treated_unit`.")
    if intervention_time is None and post_col is None:
        raise ValueError("Synthetic control requires `intervention_time` or `post_col`.")

    working = df[[unit_col, time_col, outcome_col] + ([post_col] if post_col else [])].copy()
    working[outcome_col] = _coerce_numeric(working[outcome_col])
    working = working.dropna(subset=[unit_col, time_col, outcome_col])
    working = _ordered_index(working, time_col)

    if post_col:
        period_lookup = (
            working[[time_col, post_col]]
            .drop_duplicates(subset=[time_col])
            .sort_values(time_col)
            .set_index(time_col)[post_col]
        )
        pre_periods = period_lookup.loc[period_lookup.astype(int) == 0].index.tolist()
        post_periods = period_lookup.loc[period_lookup.astype(int) == 1].index.tolist()
    else:
        time_values = working[time_col].drop_duplicates().tolist()
        parsed = pd.to_datetime(pd.Series(time_values), errors="coerce")
        if parsed.notna().all():
            pre_periods = [value for value in time_values if pd.to_datetime(value) < pd.to_datetime(intervention_time)]
            post_periods = [value for value in time_values if pd.to_datetime(value) >= pd.to_datetime(intervention_time)]
        else:
            pre_periods = [value for value in time_values if str(value) < str(intervention_time)]
            post_periods = [value for value in time_values if str(value) >= str(intervention_time)]

    pivot = working.pivot_table(index=time_col, columns=unit_col, values=outcome_col, aggfunc="mean")
    pivot = pivot.dropna(axis=0, how="any")
    donor_units = config.get("donor_units") or [column for column in pivot.columns.tolist() if column != treated_unit]
    if treated_unit not in pivot.columns:
        raise ValueError(f"Treated unit {treated_unit} is not present in the data.")
    missing_donors = [unit for unit in donor_units if unit not in pivot.columns]
    if missing_donors:
        raise ValueError(f"Missing donor units: {', '.join(map(str, missing_donors))}")

    pre_periods = [period for period in pre_periods if period in pivot.index]
    post_periods = [period for period in post_periods if period in pivot.index]
    if len(pre_periods) < 3 or len(post_periods) < 1:
        raise ValueError("Synthetic control needs at least 3 pre-treatment periods and 1 post-treatment period.")

    treated_pre = pivot.loc[pre_periods, treated_unit].to_numpy(dtype=float)
    donor_pre = pivot.loc[pre_periods, donor_units].to_numpy(dtype=float)

    def objective(weights: np.ndarray) -> float:
        synthetic_pre = donor_pre @ weights
        residual = treated_pre - synthetic_pre
        return float(np.mean(residual**2))

    initial = np.full(len(donor_units), 1.0 / len(donor_units), dtype=float)
    bounds = [(0.0, 1.0)] * len(donor_units)
    constraints = [{"type": "eq", "fun": lambda weights: np.sum(weights) - 1.0}]
    result = minimize(objective, initial, bounds=bounds, constraints=constraints, method="SLSQP")
    if not result.success:
        raise ValueError(f"Synthetic control optimization failed: {result.message}")

    weights = np.asarray(result.x, dtype=float)
    synthetic_series = pivot[donor_units].to_numpy(dtype=float) @ weights
    treated_series = pivot[treated_unit].to_numpy(dtype=float)
    gap = treated_series - synthetic_series
    pre_mask = pivot.index.isin(pre_periods)
    post_mask = pivot.index.isin(post_periods)
    pre_rmspe = float(np.sqrt(np.mean(gap[pre_mask] ** 2)))
    post_rmspe = float(np.sqrt(np.mean(gap[post_mask] ** 2)))
    rmspe_ratio = float(post_rmspe / pre_rmspe) if pre_rmspe > 0 else None
    post_average_gap = float(np.mean(gap[post_mask]))

    report: dict[str, Any] = {
        "task": "synthetic-control",
        "unit_col": unit_col,
        "time_col": time_col,
        "outcome_col": outcome_col,
        "treated_unit": treated_unit,
        "donor_units": donor_units,
        "intervention_time": intervention_time if intervention_time is not None else "__post_col__",
        "donor_weights": [
            {"unit": str(unit), "weight": float(weight)}
            for unit, weight in sorted(zip(donor_units, weights.tolist()), key=lambda item: item[1], reverse=True)
        ],
        "pre_rmspe": pre_rmspe,
        "post_rmspe": post_rmspe,
        "post_to_pre_rmspe_ratio": rmspe_ratio,
        "post_average_gap": post_average_gap,
        "post_period_gaps": [
            {"period": str(period), "gap": float(gap_value)}
            for period, gap_value in zip(pivot.index[post_mask].tolist(), gap[post_mask].tolist())
        ],
        "artifacts": [],
    }

    if output_dir is not None:
        path_frame = pd.DataFrame(
            {
                time_col: pivot.index.tolist(),
                "treated": treated_series,
                "synthetic_control": synthetic_series,
                "gap": gap,
                "is_post": pivot.index.isin(post_periods).astype(int),
            }
        )
        path_csv = output_dir / "synthetic_control_path.csv"
        path_frame.to_csv(path_csv, index=False)
        report["artifacts"].append(str(path_csv))

        if module_available("matplotlib"):
            import matplotlib.pyplot as plt  # type: ignore

            _configure_plotting()
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.plot(path_frame[time_col].astype(str), path_frame["treated"], marker="o", label=str(treated_unit))
            ax.plot(path_frame[time_col].astype(str), path_frame["synthetic_control"], marker="o", label="synthetic")
            if intervention_time is not None:
                ax.axvline(str(intervention_time), color="tab:red", linestyle="--")
            ax.set_title("Synthetic control path")
            ax.set_xlabel(time_col)
            ax.set_ylabel(outcome_col)
            ax.legend()
            figure_path = output_dir / "synthetic_control_path.png"
            fig.tight_layout()
            fig.savefig(figure_path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(figure_path))

            fig, ax = plt.subplots(figsize=(8, 5))
            ax.plot(path_frame[time_col].astype(str), path_frame["gap"], marker="o")
            ax.axhline(0.0, color="black", linewidth=1)
            if intervention_time is not None:
                ax.axvline(str(intervention_time), color="tab:red", linestyle="--")
            ax.set_title("Synthetic control gap")
            ax.set_xlabel(time_col)
            ax.set_ylabel("Gap")
            figure_path = output_dir / "synthetic_control_gap.png"
            fig.tight_layout()
            fig.savefig(figure_path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(figure_path))

            fig, ax = plt.subplots(figsize=(8, 5))
            positive_weights = [(unit, weight) for unit, weight in zip(donor_units, weights.tolist()) if weight > 1e-6]
            ax.bar([str(unit) for unit, _ in positive_weights], [weight for _, weight in positive_weights])
            ax.set_title("Synthetic control donor weights")
            ax.set_xlabel("Donor unit")
            ax.set_ylabel("Weight")
            figure_path = output_dir / "synthetic_control_weights.png"
            fig.tight_layout()
            fig.savefig(figure_path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(figure_path))

    return report


def instrumental_variables_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    if not module_available("statsmodels"):
        raise ValueError("IV analysis requires statsmodels.")

    import statsmodels.api as sm  # type: ignore
    from statsmodels.sandbox.regression.gmm import IV2SLS  # type: ignore

    outcome_col = config.get("outcome_col")
    treatment_col = config.get("treatment_col")
    instrument_col = config.get("instrument_col")
    covariate_cols = list(config.get("covariate_cols", []))
    if not outcome_col or not treatment_col or not instrument_col:
        raise ValueError("IV requires `outcome_col`, `treatment_col`, and `instrument_col`.")

    selected_columns = _dedupe_columns([outcome_col, treatment_col, instrument_col, *covariate_cols])
    working = df[selected_columns].copy()
    working[outcome_col] = _coerce_numeric(working[outcome_col])
    working[treatment_col] = _coerce_numeric(working[treatment_col])
    working[instrument_col] = _coerce_numeric(working[instrument_col])
    working = working.dropna(subset=[outcome_col, treatment_col, instrument_col])

    control_frame = _prepare_feature_frame(working, covariate_cols) if covariate_cols else pd.DataFrame(index=working.index)
    y = working[outcome_col].astype(float)
    d = working[treatment_col].astype(float)
    z = working[instrument_col].astype(float)

    first_stage_exog = sm.add_constant(pd.concat([z.rename(instrument_col), control_frame], axis=1), has_constant="add")
    first_stage = sm.OLS(d, first_stage_exog).fit(cov_type="HC1")
    instrument_t = float(first_stage.tvalues[instrument_col])
    first_stage_f = instrument_t**2

    reduced_form = sm.OLS(y, first_stage_exog).fit(cov_type="HC1")

    ols_exog = sm.add_constant(pd.concat([d.rename(treatment_col), control_frame], axis=1), has_constant="add")
    ols_result = sm.OLS(y, ols_exog).fit(cov_type="HC1")

    iv_exog = sm.add_constant(pd.concat([d.rename(treatment_col), control_frame], axis=1), has_constant="add")
    iv_instruments = sm.add_constant(pd.concat([z.rename(instrument_col), control_frame], axis=1), has_constant="add")
    iv_result = IV2SLS(y, iv_exog, iv_instruments).fit()
    try:
        iv_result = iv_result.get_robustcov_results(cov_type="HC1")
    except Exception:
        pass

    confidence_interval = iv_result.conf_int()
    if hasattr(confidence_interval, "loc"):
        treatment_ci = confidence_interval.loc[treatment_col].tolist()
    else:
        parameter_names = list(iv_result.model.exog_names)
        treatment_index = parameter_names.index(treatment_col)
        treatment_ci = confidence_interval[treatment_index].tolist()

    treatment_parameter_index = list(iv_result.model.exog_names).index(treatment_col)
    iv_coefficient = float(iv_result.params[treatment_parameter_index] if not hasattr(iv_result.params, "get") else iv_result.params[treatment_col])
    iv_bse = float(iv_result.bse[treatment_parameter_index] if not hasattr(iv_result.bse, "get") else iv_result.bse[treatment_col])
    iv_p_value = float(iv_result.pvalues[treatment_parameter_index] if not hasattr(iv_result.pvalues, "get") else iv_result.pvalues[treatment_col])

    first_stage_residuals = d - first_stage.fittedvalues
    hausman_exog = sm.add_constant(
        pd.concat(
            [
                d.rename(treatment_col),
                first_stage_residuals.rename("first_stage_residual"),
                control_frame,
            ],
            axis=1,
        ),
        has_constant="add",
    )
    hausman_result = sm.OLS(y, hausman_exog).fit(cov_type="HC1")

    report: dict[str, Any] = {
        "task": "iv",
        "outcome_col": outcome_col,
        "treatment_col": treatment_col,
        "instrument_col": instrument_col,
        "covariate_cols": covariate_cols,
        "n_rows_used": int(len(working)),
        "iv_estimate": iv_coefficient,
        "standard_error": iv_bse,
        "p_value": iv_p_value,
        "confidence_interval": [float(treatment_ci[0]), float(treatment_ci[1])],
        "first_stage": {
            "instrument_coefficient": float(first_stage.params[instrument_col]),
            "instrument_p_value": float(first_stage.pvalues[instrument_col]),
            "f_statistic": float(first_stage_f),
            "r_squared": float(first_stage.rsquared),
            "weak_instrument_at_f_lt_10": bool(first_stage_f < 10),
        },
        "reduced_form": {
            "instrument_coefficient": float(reduced_form.params[instrument_col]),
            "instrument_p_value": float(reduced_form.pvalues[instrument_col]),
        },
        "comparison": {
            "ols_estimate": float(ols_result.params[treatment_col]),
            "ols_p_value": float(ols_result.pvalues[treatment_col]),
            "iv_minus_ols": float(iv_coefficient - float(ols_result.params[treatment_col])),
        },
        "hausman": {
            "residual_coefficient": float(hausman_result.params["first_stage_residual"]),
            "p_value": float(hausman_result.pvalues["first_stage_residual"]),
        },
        "artifacts": [],
    }

    if output_dir is not None and module_available("matplotlib"):
        import matplotlib.pyplot as plt  # type: ignore

        _configure_plotting()
        if z.nunique() <= 4:
            grouped = working.groupby(instrument_col).agg(
                treatment_mean=(treatment_col, "mean"),
                outcome_mean=(outcome_col, "mean"),
            ).reset_index()
            fig, ax = plt.subplots(figsize=(7, 5))
            ax.bar(grouped[instrument_col].astype(str), grouped["treatment_mean"])
            ax.set_title("First-stage by instrument")
            ax.set_xlabel(instrument_col)
            ax.set_ylabel(treatment_col)
            path = output_dir / "iv_first_stage.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

            fig, ax = plt.subplots(figsize=(7, 5))
            ax.bar(grouped[instrument_col].astype(str), grouped["outcome_mean"])
            ax.set_title("Reduced-form by instrument")
            ax.set_xlabel(instrument_col)
            ax.set_ylabel(outcome_col)
            path = output_dir / "iv_reduced_form.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))
        else:
            fig, ax = plt.subplots(figsize=(7, 5))
            ax.scatter(z, d, alpha=0.75)
            ax.set_title("Instrument vs treatment")
            ax.set_xlabel(instrument_col)
            ax.set_ylabel(treatment_col)
            path = output_dir / "iv_first_stage.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

    return report


def doubly_robust_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold

    treatment_col = config.get("treatment_col")
    outcome_col = config.get("outcome_col")
    covariate_cols = config.get("covariate_cols") or config.get("feature_cols")
    heterogeneity_cols = list(config.get("heterogeneity_cols", []))
    if not treatment_col or not outcome_col or not covariate_cols:
        raise ValueError("Doubly robust analysis requires `treatment_col`, `outcome_col`, and `covariate_cols`.")

    selected_columns = _dedupe_columns([treatment_col, outcome_col, *covariate_cols, *heterogeneity_cols])
    working = df[selected_columns].copy()
    working[outcome_col] = _coerce_numeric(working[outcome_col])
    working = working.dropna(subset=[treatment_col, outcome_col])
    treatment_value, control_value = _resolve_binary_values(
        working, treatment_col, config.get("treatment_value"), config.get("control_value")
    )
    if isinstance(treatment_value, str) and treatment_value.startswith("__GT_MEDIAN_"):
        median = float(control_value)
        working["__treated__"] = (working[treatment_col] > median).astype(int)
        treatment_value, control_value = f"> {median}", f"<= {median}"
    else:
        working = working.loc[working[treatment_col].isin([treatment_value, control_value])].copy()
        working["__treated__"] = (working[treatment_col] == treatment_value).astype(int)

    encoded_features = _prepare_feature_frame(working, list(covariate_cols))
    treatment_indicator = working["__treated__"].astype(int)
    outcome = working[outcome_col].astype(float)
    binary_outcome = _is_binary_outcome(outcome)
    clip = float(config.get("propensity_clip", 0.02))
    n_splits = _safe_cv_splits(treatment_indicator, int(config.get("n_splits", 3)))

    mu0_hat = np.zeros(len(working), dtype=float)
    mu1_hat = np.zeros(len(working), dtype=float)
    e_hat = np.zeros(len(working), dtype=float)

    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=int(config.get("random_state", 42)))
    for train_idx, valid_idx in splitter.split(encoded_features, treatment_indicator):
        X_train = encoded_features.iloc[train_idx]
        X_valid = encoded_features.iloc[valid_idx]
        w_train = treatment_indicator.iloc[train_idx]
        y_train = outcome.iloc[train_idx]

        propensity_model = LogisticRegression(max_iter=1000)
        propensity_model.fit(X_train, w_train)
        fold_propensity = propensity_model.predict_proba(X_valid)[:, 1]
        e_hat[valid_idx] = np.clip(fold_propensity, clip, 1 - clip)

        treated_model = _build_outcome_model(binary_outcome)
        control_model = _build_outcome_model(binary_outcome)
        treated_model.fit(X_train.loc[w_train == 1], y_train.loc[w_train == 1])
        control_model.fit(X_train.loc[w_train == 0], y_train.loc[w_train == 0])
        mu1_hat[valid_idx] = _predict_outcome(treated_model, X_valid, binary_outcome)
        mu0_hat[valid_idx] = _predict_outcome(control_model, X_valid, binary_outcome)

    treatment_array = treatment_indicator.to_numpy(dtype=float)
    outcome_array = outcome.to_numpy(dtype=float)
    aipw_scores = (
        mu1_hat
        - mu0_hat
        + treatment_array * (outcome_array - mu1_hat) / e_hat
        - (1 - treatment_array) * (outcome_array - mu0_hat) / (1 - e_hat)
    )
    ate = float(np.mean(aipw_scores))
    ate_se = float(np.std(aipw_scores, ddof=1) / math.sqrt(len(aipw_scores))) if len(aipw_scores) > 1 else 0.0
    z_score = ate / ate_se if ate_se else 0.0
    p_value = float(2 * (1 - stats.norm.cdf(abs(z_score)))) if ate_se else 1.0
    confidence_interval = [float(ate - 1.96 * ate_se), float(ate + 1.96 * ate_se)]
    naive_difference = float(outcome.loc[treatment_indicator == 1].mean() - outcome.loc[treatment_indicator == 0].mean())

    working["dr_score"] = aipw_scores
    working["mu1_hat"] = mu1_hat
    working["mu0_hat"] = mu0_hat
    working["propensity_score"] = e_hat

    subgroup_rows = _subgroup_effect_rows(
        working,
        score_columns={"dr": "dr_score"},
        outcome_col=outcome_col,
        heterogeneity_cols=heterogeneity_cols,
        min_group_size=int(config.get("min_group_size", 3)),
    )

    propensity_full = LogisticRegression(max_iter=1000).fit(encoded_features, treatment_indicator)
    coefficient_rows = [
        {"feature": feature, "coefficient": float(coef)}
        for feature, coef in sorted(
            zip(encoded_features.columns.tolist(), propensity_full.coef_[0].tolist()),
            key=lambda item: abs(item[1]),
            reverse=True,
        )[:10]
    ]

    report: dict[str, Any] = {
        "task": "dr",
        "treatment_col": treatment_col,
        "outcome_col": outcome_col,
        "covariate_cols": list(covariate_cols),
        "treatment_value": treatment_value,
        "control_value": control_value,
        "binary_outcome": bool(binary_outcome),
        "n_rows_used": int(len(working)),
        "n_splits": int(n_splits),
        "average_treatment_effect": ate,
        "naive_difference": naive_difference,
        "standard_error": ate_se,
        "z_score": float(z_score),
        "p_value": p_value,
        "confidence_interval": confidence_interval,
        "propensity_overlap": _propensity_overlap_summary(e_hat, treatment_indicator),
        "score_distribution": {
            "min": float(np.min(aipw_scores)),
            "p25": float(np.percentile(aipw_scores, 25)),
            "median": float(np.median(aipw_scores)),
            "p75": float(np.percentile(aipw_scores, 75)),
            "max": float(np.max(aipw_scores)),
        },
        "subgroup_effects": subgroup_rows[:12],
        "propensity_model_top_coefficients": coefficient_rows,
        "artifacts": [],
    }

    if output_dir is not None:
        score_path = output_dir / "dr_scores.csv"
        working.to_csv(score_path, index=False)
        report["artifacts"].append(str(score_path))

        if module_available("matplotlib"):
            import matplotlib.pyplot as plt  # type: ignore

            _configure_plotting()
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.hist(working.loc[treatment_indicator == 0, "propensity_score"], bins=10, alpha=0.6, label=str(control_value))
            ax.hist(working.loc[treatment_indicator == 1, "propensity_score"], bins=10, alpha=0.6, label=str(treatment_value))
            ax.set_title("Cross-fitted propensity overlap")
            ax.set_xlabel("Propensity score")
            ax.set_ylabel("Count")
            ax.legend()
            path = output_dir / "dr_propensity_overlap.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

            fig, ax = plt.subplots(figsize=(8, 5))
            ax.hist(aipw_scores, bins=12, alpha=0.85)
            ax.set_title("Doubly robust score distribution")
            ax.set_xlabel("AIPW score")
            ax.set_ylabel("Count")
            path = output_dir / "dr_score_distribution.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

    return report


def uplift_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    from sklearn.model_selection import train_test_split

    treatment_col = config.get("treatment_col")
    outcome_col = config.get("outcome_col")
    feature_cols = config.get("feature_cols") or config.get("covariate_cols")
    heterogeneity_cols = config.get("heterogeneity_cols", [])
    if not treatment_col or not outcome_col or not feature_cols:
        raise ValueError("Uplift requires `treatment_col`, `outcome_col`, and `feature_cols`/`covariate_cols`.")

    selected_columns = _dedupe_columns([treatment_col, outcome_col, *feature_cols, *heterogeneity_cols])
    working = df[selected_columns].copy()
    working[outcome_col] = _coerce_numeric(working[outcome_col])
    working = working.dropna(subset=[treatment_col, outcome_col])
    treatment_value, control_value = _resolve_binary_values(
        working, treatment_col, config.get("treatment_value"), config.get("control_value")
    )
    if isinstance(treatment_value, str) and treatment_value.startswith("__GT_MEDIAN_"):
        median = float(control_value)
        working["__treated__"] = (working[treatment_col] > median).astype(int)
        treatment_value, control_value = f"> {median}", f"<= {median}"
    else:
        working = working.loc[working[treatment_col].isin([treatment_value, control_value])].copy()
        working["__treated__"] = (working[treatment_col] == treatment_value).astype(int)

    encoded_features = _prepare_feature_frame(working, list(feature_cols))
    binary_outcome = _is_binary_outcome(working[outcome_col])
    train_index, test_index = train_test_split(
        working.index,
        test_size=float(config.get("test_size", 0.3)),
        random_state=int(config.get("random_state", 42)),
        stratify=working["__treated__"],
    )
    train = working.loc[train_index]
    test = working.loc[test_index]
    X_train = encoded_features.loc[train_index]
    X_test = encoded_features.loc[test_index]

    treated_train_mask = train["__treated__"] == 1
    control_train_mask = train["__treated__"] == 0
    treated_model = _build_outcome_model(binary_outcome)
    control_model = _build_outcome_model(binary_outcome)

    treated_model.fit(X_train.loc[treated_train_mask], train.loc[treated_train_mask, outcome_col])
    control_model.fit(X_train.loc[control_train_mask], train.loc[control_train_mask, outcome_col])

    if binary_outcome:
        predicted_treated = _predict_positive_probability(treated_model, X_test)
        predicted_control = _predict_positive_probability(control_model, X_test)
    else:
        predicted_treated = treated_model.predict(X_test)
        predicted_control = control_model.predict(X_test)
    uplift_scores = np.asarray(predicted_treated) - np.asarray(predicted_control)

    scored = test.copy()
    scored["predicted_treated_outcome"] = predicted_treated
    scored["predicted_control_outcome"] = predicted_control
    scored["predicted_uplift"] = uplift_scores
    bucket_rows = _bucket_lift_rows(scored, score_col="predicted_uplift", outcome_col=outcome_col, bucket_count=int(config.get("n_buckets", 5)))

    working["predicted_uplift"] = np.nan
    working.loc[test_index, "predicted_uplift"] = uplift_scores
    subgroup_rows = _subgroup_effect_rows(
        working.dropna(subset=["predicted_uplift"]),
        score_columns={"t_learner": "predicted_uplift"},
        outcome_col=outcome_col,
        heterogeneity_cols=heterogeneity_cols,
        min_group_size=int(config.get("min_group_size", 3)),
    )

    importance = []
    if hasattr(treated_model, "feature_importances_") and hasattr(control_model, "feature_importances_"):
        values = (treated_model.feature_importances_ + control_model.feature_importances_) / 2
        importance = [
            {"feature": feature, "importance": float(value)}
            for feature, value in sorted(zip(X_train.columns.tolist(), values.tolist()), key=lambda item: item[1], reverse=True)[:10]
        ]

    report: dict[str, Any] = {
        "task": "uplift",
        "treatment_col": treatment_col,
        "outcome_col": outcome_col,
        "feature_cols": list(feature_cols),
        "treatment_value": treatment_value,
        "control_value": control_value,
        "binary_outcome": bool(binary_outcome),
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "average_predicted_uplift": float(np.mean(uplift_scores)),
        "uplift_distribution": {
            "min": float(np.min(uplift_scores)),
            "p25": float(np.percentile(uplift_scores, 25)),
            "median": float(np.median(uplift_scores)),
            "p75": float(np.percentile(uplift_scores, 75)),
            "max": float(np.max(uplift_scores)),
        },
        "uplift_buckets": bucket_rows,
        "heterogeneity": subgroup_rows[:12],
        "model_feature_importance": importance,
        "artifacts": [],
    }

    if output_dir is not None:
        score_path = output_dir / "uplift_scores.csv"
        scored.to_csv(score_path, index=False)
        report["artifacts"].append(str(score_path))

        if module_available("matplotlib"):
            import matplotlib.pyplot as plt  # type: ignore

            _configure_plotting()
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.hist(scored["predicted_uplift"], bins=12, alpha=0.8)
            ax.set_title("Predicted uplift distribution")
            ax.set_xlabel("Predicted uplift")
            ax.set_ylabel("Count")
            path = output_dir / "uplift_distribution.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

            fig, ax = plt.subplots(figsize=(8, 5))
            bucket_labels = [str(row["bucket"]) for row in bucket_rows][::-1]
            bucket_values = [row["observed_lift"] if row["observed_lift"] is not None else 0.0 for row in bucket_rows][::-1]
            ax.bar(bucket_labels, bucket_values)
            ax.set_title("Observed lift by uplift bucket")
            ax.set_xlabel("Uplift bucket (high to low)")
            ax.set_ylabel("Observed lift")
            path = output_dir / "uplift_bucket_lift.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

    return report


def orthogonal_learner_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    treatment_col = config.get("treatment_col")
    outcome_col = config.get("outcome_col")
    feature_cols = config.get("feature_cols") or config.get("covariate_cols")
    heterogeneity_cols = list(config.get("heterogeneity_cols", []))
    if not treatment_col or not outcome_col or not feature_cols:
        raise ValueError("Orthogonal learner requires `treatment_col`, `outcome_col`, and `feature_cols`/`covariate_cols`.")

    selected_columns = _dedupe_columns([treatment_col, outcome_col, *feature_cols, *heterogeneity_cols])
    working = df[selected_columns].copy()
    working[outcome_col] = _coerce_numeric(working[outcome_col])
    working = working.dropna(subset=[treatment_col, outcome_col])
    treatment_value, control_value = _resolve_binary_values(
        working, treatment_col, config.get("treatment_value"), config.get("control_value")
    )
    if isinstance(treatment_value, str) and treatment_value.startswith("__GT_MEDIAN_"):
        median = float(control_value)
        working["__treated__"] = (working[treatment_col] > median).astype(int)
        treatment_value, control_value = f"> {median}", f"<= {median}"
    else:
        working = working.loc[working[treatment_col].isin([treatment_value, control_value])].copy()
        working["__treated__"] = (working[treatment_col] == treatment_value).astype(int)

    encoded_features = _prepare_feature_frame(working, list(feature_cols))
    treatment_indicator = working["__treated__"].astype(int)
    outcome = working[outcome_col].astype(float)
    n_splits = _safe_cv_splits(treatment_indicator, int(config.get("n_splits", 3)))
    random_state = int(config.get("random_state", 42))
    clip = float(config.get("propensity_clip", 0.02))
    min_denominator = float(config.get("min_denominator", 0.05))

    m_hat, e_hat = _crossfit_main_effect_and_propensity(
        encoded_features,
        treatment_indicator,
        outcome,
        n_splits=n_splits,
        random_state=random_state,
    )
    e_hat = np.clip(e_hat, clip, 1 - clip)

    treatment_residual = treatment_indicator.to_numpy(dtype=float) - e_hat
    outcome_residual = outcome.to_numpy(dtype=float) - m_hat
    signed_residual = np.where(treatment_residual >= 0, 1.0, -1.0)
    stabilized_residual = np.where(np.abs(treatment_residual) < min_denominator, signed_residual * min_denominator, treatment_residual)
    pseudo_outcome = outcome_residual / stabilized_residual
    sample_weight = treatment_residual**2

    tau_model = _build_effect_model()
    tau_model.fit(encoded_features, pseudo_outcome, sample_weight=sample_weight)
    tau_hat = np.asarray(tau_model.predict(encoded_features), dtype=float)

    working["orthogonal_effect"] = tau_hat
    working["orthogonal_propensity_hat"] = e_hat
    working["orthogonal_main_effect_hat"] = m_hat
    working["orthogonal_pseudo_outcome"] = pseudo_outcome
    working["orthogonal_weight"] = sample_weight

    bucket_rows = _bucket_lift_rows(
        working,
        score_col="orthogonal_effect",
        outcome_col=outcome_col,
        bucket_count=int(config.get("n_buckets", 5)),
    )
    subgroup_rows = _subgroup_effect_rows(
        working,
        score_columns={"orthogonal": "orthogonal_effect"},
        outcome_col=outcome_col,
        heterogeneity_cols=heterogeneity_cols,
        min_group_size=int(config.get("min_group_size", 3)),
    )
    feature_importance = []
    if hasattr(tau_model, "feature_importances_"):
        feature_importance = [
            {"feature": feature, "importance": float(value)}
            for feature, value in sorted(
                zip(encoded_features.columns.tolist(), tau_model.feature_importances_.tolist()),
                key=lambda item: item[1],
                reverse=True,
            )[:10]
        ]

    report: dict[str, Any] = {
        "task": "orthogonal",
        "treatment_col": treatment_col,
        "outcome_col": outcome_col,
        "feature_cols": list(feature_cols),
        "treatment_value": treatment_value,
        "control_value": control_value,
        "n_rows_used": int(len(working)),
        "n_splits": int(n_splits),
        "average_predicted_effect": float(np.mean(tau_hat)),
        "naive_difference": float(outcome.loc[treatment_indicator == 1].mean() - outcome.loc[treatment_indicator == 0].mean()),
        "propensity_overlap": _propensity_overlap_summary(e_hat, treatment_indicator),
        "pseudo_outcome_distribution": {
            "min": float(np.min(pseudo_outcome)),
            "p25": float(np.percentile(pseudo_outcome, 25)),
            "median": float(np.median(pseudo_outcome)),
            "p75": float(np.percentile(pseudo_outcome, 75)),
            "max": float(np.max(pseudo_outcome)),
        },
        "predicted_effect_distribution": {
            "min": float(np.min(tau_hat)),
            "p25": float(np.percentile(tau_hat, 25)),
            "median": float(np.median(tau_hat)),
            "p75": float(np.percentile(tau_hat, 75)),
            "max": float(np.max(tau_hat)),
        },
        "bucket_lifts": bucket_rows,
        "subgroup_effects": subgroup_rows[:12],
        "model_feature_importance": feature_importance,
        "artifacts": [],
    }

    if output_dir is not None:
        score_path = output_dir / "orthogonal_scores.csv"
        working.to_csv(score_path, index=False)
        report["artifacts"].append(str(score_path))

        if module_available("matplotlib"):
            import matplotlib.pyplot as plt  # type: ignore

            _configure_plotting()
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.hist(tau_hat, bins=12, alpha=0.85)
            ax.set_title("Orthogonal learner effect distribution")
            ax.set_xlabel("Predicted effect")
            ax.set_ylabel("Count")
            path = output_dir / "orthogonal_effect_distribution.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

            fig, ax = plt.subplots(figsize=(8, 5))
            ax.hist(pseudo_outcome, bins=12, alpha=0.85)
            ax.set_title("Orthogonal pseudo-outcome distribution")
            ax.set_xlabel("Pseudo-outcome")
            ax.set_ylabel("Count")
            path = output_dir / "orthogonal_pseudo_outcome.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

    return report


def cate_meta_learner_analysis(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    from sklearn.model_selection import StratifiedKFold

    treatment_col = config.get("treatment_col")
    outcome_col = config.get("outcome_col")
    feature_cols = config.get("feature_cols") or config.get("covariate_cols")
    heterogeneity_cols = list(config.get("heterogeneity_cols", []))
    if not treatment_col or not outcome_col or not feature_cols:
        raise ValueError("CATE analysis requires `treatment_col`, `outcome_col`, and `feature_cols`/`covariate_cols`.")

    selected_columns = _dedupe_columns([treatment_col, outcome_col, *feature_cols, *heterogeneity_cols])
    working = df[selected_columns].copy()
    working[outcome_col] = _coerce_numeric(working[outcome_col])
    working = working.dropna(subset=[treatment_col, outcome_col])
    treatment_value, control_value = _resolve_binary_values(
        working, treatment_col, config.get("treatment_value"), config.get("control_value")
    )
    if isinstance(treatment_value, str) and treatment_value.startswith("__GT_MEDIAN_"):
        median = float(control_value)
        working["__treated__"] = (working[treatment_col] > median).astype(int)
        treatment_value, control_value = f"> {median}", f"<= {median}"
    else:
        working = working.loc[working[treatment_col].isin([treatment_value, control_value])].copy()
        working["__treated__"] = (working[treatment_col] == treatment_value).astype(int)

    encoded_features = _prepare_feature_frame(working, list(feature_cols))
    treatment_indicator = working["__treated__"].astype(int)
    outcome = working[outcome_col].astype(float)
    binary_outcome = _is_binary_outcome(outcome)
    methods = list(config.get("methods", ["s_learner", "t_learner"]))
    valid_methods = [method for method in methods if method in {"s_learner", "t_learner"}]
    if not valid_methods:
        raise ValueError("CATE methods must include `s_learner` and/or `t_learner`.")

    n_splits = _safe_cv_splits(treatment_indicator, int(config.get("n_splits", 3)))
    splitter = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=int(config.get("random_state", 42)))
    method_predictions = {method: np.full(len(working), np.nan, dtype=float) for method in valid_methods}

    for train_idx, valid_idx in splitter.split(encoded_features, treatment_indicator):
        X_train = encoded_features.iloc[train_idx]
        X_valid = encoded_features.iloc[valid_idx]
        w_train = treatment_indicator.iloc[train_idx]
        y_train = outcome.iloc[train_idx]

        if "s_learner" in valid_methods:
            s_model = _build_outcome_model(binary_outcome)
            X_train_s = X_train.copy()
            X_train_s["__treated__"] = w_train.to_numpy(dtype=float)
            s_model.fit(X_train_s, y_train)

            X_valid_treated = X_valid.copy()
            X_valid_treated["__treated__"] = 1.0
            X_valid_control = X_valid.copy()
            X_valid_control["__treated__"] = 0.0
            method_predictions["s_learner"][valid_idx] = _predict_outcome(s_model, X_valid_treated, binary_outcome) - _predict_outcome(
                s_model,
                X_valid_control,
                binary_outcome,
            )

        if "t_learner" in valid_methods:
            treated_model = _build_outcome_model(binary_outcome)
            control_model = _build_outcome_model(binary_outcome)
            treated_model.fit(X_train.loc[w_train == 1], y_train.loc[w_train == 1])
            control_model.fit(X_train.loc[w_train == 0], y_train.loc[w_train == 0])
            method_predictions["t_learner"][valid_idx] = _predict_outcome(treated_model, X_valid, binary_outcome) - _predict_outcome(
                control_model,
                X_valid,
                binary_outcome,
            )

    for method_name, predictions in method_predictions.items():
        working[f"{method_name}_cate"] = predictions

    method_reports: dict[str, Any] = {}
    bucket_reports: dict[str, Any] = {}
    for method_name in valid_methods:
        predictions = working[f"{method_name}_cate"].dropna().to_numpy(dtype=float)
        method_reports[method_name] = {
            "average_predicted_effect": float(np.mean(predictions)),
            "distribution": {
                "min": float(np.min(predictions)),
                "p25": float(np.percentile(predictions, 25)),
                "median": float(np.median(predictions)),
                "p75": float(np.percentile(predictions, 75)),
                "max": float(np.max(predictions)),
            },
        }
        bucket_reports[method_name] = _bucket_lift_rows(
            working.dropna(subset=[f"{method_name}_cate"]),
            score_col=f"{method_name}_cate",
            outcome_col=outcome_col,
            bucket_count=int(config.get("n_buckets", 5)),
        )

    comparison: dict[str, Any] = {"methods": valid_methods}
    if len(valid_methods) >= 2:
        base = working[f"{valid_methods[0]}_cate"].astype(float)
        other = working[f"{valid_methods[1]}_cate"].astype(float)
        comparison.update(
            {
                "correlation": float(base.corr(other)),
                "mean_absolute_difference": float(np.mean(np.abs(base - other))),
            }
        )

    subgroup_rows = _subgroup_effect_rows(
        working,
        score_columns={method: f"{method}_cate" for method in valid_methods},
        outcome_col=outcome_col,
        heterogeneity_cols=heterogeneity_cols,
        min_group_size=int(config.get("min_group_size", 3)),
    )

    report: dict[str, Any] = {
        "task": "cate",
        "treatment_col": treatment_col,
        "outcome_col": outcome_col,
        "feature_cols": list(feature_cols),
        "treatment_value": treatment_value,
        "control_value": control_value,
        "binary_outcome": bool(binary_outcome),
        "n_rows_used": int(len(working)),
        "n_splits": int(n_splits),
        "methods": method_reports,
        "bucket_lifts": bucket_reports,
        "method_comparison": comparison,
        "subgroup_cate": subgroup_rows[:12],
        "artifacts": [],
    }

    if output_dir is not None:
        score_path = output_dir / "cate_scores.csv"
        working.to_csv(score_path, index=False)
        report["artifacts"].append(str(score_path))

        if module_available("matplotlib"):
            import matplotlib.pyplot as plt  # type: ignore

            _configure_plotting()
            fig, ax = plt.subplots(figsize=(8, 5))
            for method_name in valid_methods:
                ax.hist(working[f"{method_name}_cate"], bins=12, alpha=0.55, label=method_name)
            ax.set_title("CATE distribution by meta-learner")
            ax.set_xlabel("Predicted treatment effect")
            ax.set_ylabel("Count")
            ax.legend()
            path = output_dir / "cate_distribution.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            report["artifacts"].append(str(path))

            if len(valid_methods) >= 2:
                fig, ax = plt.subplots(figsize=(7, 5))
                ax.scatter(working[f"{valid_methods[0]}_cate"], working[f"{valid_methods[1]}_cate"], alpha=0.75)
                ax.set_title("Meta-learner CATE comparison")
                ax.set_xlabel(valid_methods[0])
                ax.set_ylabel(valid_methods[1])
                path = output_dir / "cate_method_scatter.png"
                fig.tight_layout()
                fig.savefig(path, dpi=150)
                plt.close(fig)
                report["artifacts"].append(str(path))

    return report


def causal_suite(df: pd.DataFrame, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    methods = config.get("methods") or [method for method in ["did", "rd", "synthetic-control", "iv", "dml", "dr", "psm", "orthogonal", "uplift", "cate"] if method in config]
    if not methods:
        raise ValueError("Causal suite requires `methods` or method-specific sections such as `did`, `rd`, `synthetic-control`, `iv`, `dml`, `dr`, `psm`, `orthogonal`, `uplift`, or `cate`.")

    reports: dict[str, Any] = {}
    artifacts: list[str] = []
    for raw_method in methods:
        method = normalize_task(raw_method)
        method_config = config.get(method, config if method != "causal" else {})
        if method == "did":
            report = difference_in_differences_analysis(df, method_config, output_dir=output_dir)
        elif method == "rd":
            report = regression_discontinuity_analysis(df, method_config, output_dir=output_dir)
        elif method == "synthetic-control":
            report = synthetic_control_analysis(df, method_config, output_dir=output_dir)
        elif method == "iv":
            report = instrumental_variables_analysis(df, method_config, output_dir=output_dir)
        elif method == "dml":
            report = double_machine_learning_analysis(df, method_config, output_dir=output_dir)
        elif method == "psm":
            report = propensity_score_matching_analysis(df, method_config, output_dir=output_dir)
        elif method == "dr":
            report = doubly_robust_analysis(df, method_config, output_dir=output_dir)
        elif method == "orthogonal":
            report = orthogonal_learner_analysis(df, method_config, output_dir=output_dir)
        elif method == "uplift":
            report = uplift_analysis(df, method_config, output_dir=output_dir)
        elif method == "cate":
            report = cate_meta_learner_analysis(df, method_config, output_dir=output_dir)
        else:
            raise ValueError(f"Unsupported causal suite method: {raw_method}")
        reports[method] = report
        artifacts.extend(report.get("artifacts", []))
    return {
        "task": "causal",
        "methods": list(reports.keys()),
        "reports": reports,
        "artifacts": sorted(set(artifacts)),
    }


def suggest_confounders(df: pd.DataFrame, treatment_col: str, outcome_col: str, threshold: float = 0.1) -> list[str]:
    # Ensure treatment and outcome are numeric for correlation
    temp_df = df.copy()
    temp_df[treatment_col] = pd.to_numeric(temp_df[treatment_col], errors="coerce")
    temp_df[outcome_col] = pd.to_numeric(temp_df[outcome_col], errors="coerce")
    
    # Select numeric columns only
    numeric_df = temp_df.select_dtypes(include=[np.number])
    if treatment_col not in numeric_df.columns or outcome_col not in numeric_df.columns:
        return []
        
    corrs = numeric_df.corr()
    if treatment_col not in corrs.columns or outcome_col not in corrs.columns:
        return []
        
    t_corr = corrs[treatment_col].abs()
    y_corr = corrs[outcome_col].abs()
    
    candidates = []
    for col in numeric_df.columns:
        if col in [treatment_col, outcome_col]:
            continue
        if t_corr[col] > threshold and y_corr[col] > threshold:
            candidates.append(col)
            
    return candidates


def dml_lite_analysis(df: pd.DataFrame, outcome_col: str, treatment_col: str, covariate_cols: list[str], output_dir: Path | None = None) -> dict[str, Any]:
    from sklearn.linear_model import LinearRegression
    
    working = df.copy()
    working[outcome_col] = pd.to_numeric(working[outcome_col], errors="coerce")
    working[treatment_col] = pd.to_numeric(working[treatment_col], errors="coerce")
    working = working.dropna(subset=[outcome_col, treatment_col])
    
    if not covariate_cols:
        X = working[[treatment_col]]
    else:
        encoded_covariates = _prepare_feature_frame(working, list(covariate_cols))
        X = pd.concat([working[[treatment_col]], encoded_covariates], axis=1)
        
    y = working[outcome_col]
    
    model = LinearRegression()
    model.fit(X, y)
    
    # The first coefficient is for treatment_col
    ate = float(model.coef_[0])
    
    # For std_error, we'll try to use statsmodels if available
    std_error = 0.0
    p_value = 1.0
    if module_available("statsmodels"):
        import statsmodels.api as sm
        X_sm = sm.add_constant(X)
        res = sm.OLS(y, X_sm).fit()
        if treatment_col in res.params:
            ate = float(res.params[treatment_col])
            std_error = float(res.bse[treatment_col])
            p_value = float(res.pvalues[treatment_col])
            
    interpretation = f"The estimated Average Treatment Effect (ATE) is {ate:.4f}. "
    if std_error > 0:
        interpretation += f"Standard error: {std_error:.4f}, p-value: {p_value:.4f}."
    else:
        interpretation += "Standard error not available."
        
    return {
        "task": "dml_lite",
        "ate": ate,
        "std_error": std_error,
        "p_value": p_value,
        "interpretation": interpretation,
        "outcome_col": outcome_col,
        "treatment_col": treatment_col,
        "covariate_cols": list(covariate_cols),
        "artifacts": []
    }


def run_causal_analysis(df: pd.DataFrame, task: str, config: dict[str, Any], output_dir: Path | None = None) -> dict[str, Any]:
    normalized = normalize_task(task)
    if normalized == "dml_lite":
        outcome_col = config.get("outcome_col")
        treatment_col = config.get("treatment_col")
        covariate_cols = config.get("covariate_cols") or config.get("feature_cols", [])
        
        # Call suggest_confounders
        suggested = suggest_confounders(df, treatment_col, outcome_col)
        # Merge suggested with existing covariates
        all_covariates = _dedupe_columns(list(covariate_cols) + suggested)
        
        report = dml_lite_analysis(df, outcome_col, treatment_col, all_covariates, output_dir=output_dir)
        report["suggested_confounders"] = suggested
        return report

    if normalized == "did":
        return difference_in_differences_analysis(df, config, output_dir=output_dir)
    if normalized == "rd":
        return regression_discontinuity_analysis(df, config, output_dir=output_dir)
    if normalized == "synthetic-control":
        return synthetic_control_analysis(df, config, output_dir=output_dir)
    if normalized == "iv":
        return instrumental_variables_analysis(df, config, output_dir=output_dir)
    if normalized == "dml":
        return double_machine_learning_analysis(df, config, output_dir=output_dir)
    if normalized == "psm":
        return propensity_score_matching_analysis(df, config, output_dir=output_dir)
    if normalized == "dr":
        return doubly_robust_analysis(df, config, output_dir=output_dir)
    if normalized == "orthogonal":
        return orthogonal_learner_analysis(df, config, output_dir=output_dir)
    if normalized == "uplift":
        return uplift_analysis(df, config, output_dir=output_dir)
    if normalized == "cate":
        return cate_meta_learner_analysis(df, config, output_dir=output_dir)
    if normalized == "causal":
        return causal_suite(df, config, output_dir=output_dir)
    raise ValueError(f"Unsupported causal task: {task}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DID, PSM, uplift, or a combined causal-analysis suite.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--task", required=True, choices=sorted(TASK_ALIASES.keys()))
    parser.add_argument("--output-dir")
    parser.add_argument("--config-json")
    args = parser.parse_args()

    output_dir = ensure_output_dir(args.output_dir, prefix="causal-analysis") if args.output_dir else None
    config = parse_json_arg(args.config_json)
    df = load_dataframe(args.input_path)
    report = run_causal_analysis(df, task=args.task, config=config, output_dir=output_dir)
    if output_dir is not None:
        write_json(output_dir / "causal_report.json", report)
        write_causal_narrative(output_dir, build_causal_narrative(report, config=config))
        export_dashboard(output_dir, title=f"Causal Analysis Dashboard: {normalize_task(args.task)}")
        export_run_index(infer_outputs_root(output_dir))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
