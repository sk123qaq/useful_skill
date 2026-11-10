#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from typing import Any

import numpy as np
from scipy import stats
from statsmodels.stats.multitest import multipletests  # type: ignore
from statsmodels.stats.power import NormalIndPower, TTestIndPower  # type: ignore

from common import parse_json_arg, write_json
from io_router import load_dataframe


def resolve_variants(df, group_col: str, control: Any | None = None, treatment: Any | None = None) -> tuple[Any, Any]:
    if group_col not in df.columns:
        raise ValueError(f"Unknown group column: {group_col}")

    variants = [value for value in df[group_col].dropna().unique().tolist()]
    if control is not None and treatment is not None:
        return control, treatment
    if "control" in variants and "treatment" in variants:
        return "control", "treatment"
    if len(variants) != 2:
        raise ValueError("Experiment analysis currently supports exactly two variants unless control and treatment are provided.")
    variants = sorted(variants, key=str)
    return variants[0], variants[1]


def infer_metric_type(series, configured_type: str | None = None) -> str:
    if configured_type:
        return configured_type
    cleaned = series.dropna()
    unique_values = set(cleaned.unique().tolist())
    if cleaned.dtype == bool or unique_values.issubset({0, 1, True, False}):
        return "binary"
    if np.issubdtype(cleaned.dtype, np.number):
        return "continuous"
    return "categorical"


def normal_critical_value(alpha: float) -> float:
    return float(stats.norm.ppf(1 - alpha / 2))


def sample_ratio_mismatch(
    df,
    group_col: str,
    control: Any,
    treatment: Any,
    expected_allocation: dict[str, float] | None = None,
    alpha: float = 0.05,
) -> dict[str, Any]:
    counts = df[group_col].value_counts(dropna=False)
    observed = np.array([int(counts.get(control, 0)), int(counts.get(treatment, 0))], dtype=float)
    if expected_allocation:
        expected_ratio = np.array(
            [float(expected_allocation.get(str(control), expected_allocation.get(control, 0.5))), float(expected_allocation.get(str(treatment), expected_allocation.get(treatment, 0.5)))],
            dtype=float,
        )
        expected_ratio = expected_ratio / expected_ratio.sum()
    else:
        expected_ratio = np.array([0.5, 0.5], dtype=float)
    expected = observed.sum() * expected_ratio
    statistic, p_value = stats.chisquare(observed, f_exp=expected)
    return {
        "observed_counts": {str(control): int(observed[0]), str(treatment): int(observed[1])},
        "expected_counts": {str(control): float(expected[0]), str(treatment): float(expected[1])},
        "expected_allocation": {str(control): float(expected_ratio[0]), str(treatment): float(expected_ratio[1])},
        "chi2_statistic": float(statistic),
        "p_value": float(p_value),
        "is_mismatch": bool(p_value < alpha),
    }


def cohen_h(control_rate: float, treatment_rate: float) -> float:
    return float(2 * math.asin(math.sqrt(treatment_rate)) - 2 * math.asin(math.sqrt(control_rate)))


def cohen_d(control_values, treatment_values) -> float | None:
    control_array = np.asarray(control_values, dtype=float)
    treatment_array = np.asarray(treatment_values, dtype=float)
    if len(control_array) < 2 or len(treatment_array) < 2:
        return None
    control_var = control_array.var(ddof=1)
    treatment_var = treatment_array.var(ddof=1)
    pooled = math.sqrt(((len(control_array) - 1) * control_var + (len(treatment_array) - 1) * treatment_var) / (len(control_array) + len(treatment_array) - 2))
    if pooled == 0:
        return None
    return float((treatment_array.mean() - control_array.mean()) / pooled)


def metric_is_significant(metric_result: dict[str, Any]) -> bool:
    multiple_testing = metric_result.get("multiple_testing")
    if multiple_testing and "rejected" in multiple_testing:
        if not bool(multiple_testing["rejected"]):
            return False
    sequential = metric_result.get("sequential_monitoring")
    if sequential and "rejected" in sequential:
        if not bool(sequential["rejected"]):
            return False
    return bool(metric_result.get("statistically_significant", False))


def binary_metric_analysis(control_series, treatment_series, success_value: Any = 1, alpha: float = 0.05) -> dict[str, Any]:
    from statsmodels.stats.proportion import proportions_ztest  # type: ignore

    control_binary = (control_series == success_value).astype(int)
    treatment_binary = (treatment_series == success_value).astype(int)
    control_success = int(control_binary.sum())
    treatment_success = int(treatment_binary.sum())
    control_n = int(control_binary.count())
    treatment_n = int(treatment_binary.count())
    control_rate = control_success / control_n if control_n else 0.0
    treatment_rate = treatment_success / treatment_n if treatment_n else 0.0
    statistic, p_value = proportions_ztest([treatment_success, control_success], [treatment_n, control_n])
    absolute_lift = treatment_rate - control_rate
    relative_lift = absolute_lift / control_rate if control_rate else None
    z_critical = normal_critical_value(alpha)
    standard_error = math.sqrt(
        (treatment_rate * (1 - treatment_rate) / treatment_n if treatment_n else 0.0)
        + (control_rate * (1 - control_rate) / control_n if control_n else 0.0)
    )
    ci_low = absolute_lift - z_critical * standard_error
    ci_high = absolute_lift + z_critical * standard_error
    return {
        "metric_type": "binary",
        "test": "two_sample_proportion_z_test",
        "control": {"n": control_n, "successes": control_success, "rate": float(control_rate)},
        "treatment": {"n": treatment_n, "successes": treatment_success, "rate": float(treatment_rate)},
        "absolute_lift": float(absolute_lift),
        "relative_lift": float(relative_lift) if relative_lift is not None else None,
        "confidence_interval": [float(ci_low), float(ci_high)],
        "p_value": float(p_value),
        "statistic": float(statistic),
        "statistically_significant": bool(p_value < alpha),
        "effect_size": {"name": "cohen_h", "value": cohen_h(control_rate, treatment_rate)},
    }


def continuous_metric_analysis(control_series, treatment_series, alpha: float = 0.05) -> dict[str, Any]:
    control_values = control_series.dropna().astype(float)
    treatment_values = treatment_series.dropna().astype(float)
    statistic, p_value = stats.ttest_ind(treatment_values, control_values, equal_var=False, nan_policy="omit")
    control_mean = float(control_values.mean()) if len(control_values) else 0.0
    treatment_mean = float(treatment_values.mean()) if len(treatment_values) else 0.0
    absolute_lift = treatment_mean - control_mean
    relative_lift = absolute_lift / control_mean if control_mean else None
    control_var = float(control_values.var(ddof=1)) if len(control_values) > 1 else 0.0
    treatment_var = float(treatment_values.var(ddof=1)) if len(treatment_values) > 1 else 0.0
    se = math.sqrt((control_var / len(control_values) if len(control_values) else 0.0) + (treatment_var / len(treatment_values) if len(treatment_values) else 0.0))
    numerator = (control_var / len(control_values) + treatment_var / len(treatment_values)) ** 2 if len(control_values) and len(treatment_values) else 0.0
    denominator = (
        ((control_var / len(control_values)) ** 2) / (len(control_values) - 1) if len(control_values) > 1 else 0.0
    ) + (((treatment_var / len(treatment_values)) ** 2) / (len(treatment_values) - 1) if len(treatment_values) > 1 else 0.0)
    degrees_of_freedom = numerator / denominator if denominator else None
    t_critical = float(stats.t.ppf(1 - alpha / 2, degrees_of_freedom)) if degrees_of_freedom else normal_critical_value(alpha)
    ci_low = absolute_lift - t_critical * se
    ci_high = absolute_lift + t_critical * se
    variance_test = stats.levene(control_values, treatment_values) if len(control_values) > 1 and len(treatment_values) > 1 else None
    return {
        "metric_type": "continuous",
        "test": "welch_t_test",
        "control": {"n": int(control_values.count()), "mean": control_mean, "std": float(control_values.std(ddof=1)) if len(control_values) > 1 else 0.0},
        "treatment": {"n": int(treatment_values.count()), "mean": treatment_mean, "std": float(treatment_values.std(ddof=1)) if len(treatment_values) > 1 else 0.0},
        "absolute_lift": float(absolute_lift),
        "relative_lift": float(relative_lift) if relative_lift is not None else None,
        "confidence_interval": [float(ci_low), float(ci_high)],
        "p_value": float(p_value),
        "statistic": float(statistic),
        "degrees_of_freedom": float(degrees_of_freedom) if degrees_of_freedom else None,
        "statistically_significant": bool(p_value < alpha),
        "effect_size": {"name": "cohen_d", "value": cohen_d(control_values, treatment_values)},
        "variance_check": {"test": "levene", "p_value": float(variance_test.pvalue)} if variance_test else None,
    }


def cuped_adjusted_continuous_analysis(frame, metric_name: str, group_col: str, control: Any, treatment: Any, covariate_col: str, alpha: float = 0.05) -> dict[str, Any]:
    if covariate_col not in frame.columns:
        raise ValueError(f"Unknown CUPED covariate column: {covariate_col}")

    subset = frame[[group_col, metric_name, covariate_col]].dropna().copy()
    if subset.empty:
        raise ValueError(f"No complete rows available for CUPED using covariate {covariate_col}.")

    subset[metric_name] = subset[metric_name].astype(float)
    subset[covariate_col] = subset[covariate_col].astype(float)
    covariate_variance = float(subset[covariate_col].var(ddof=1))
    if covariate_variance == 0:
        raise ValueError(f"CUPED covariate {covariate_col} has zero variance.")

    theta = float(np.cov(subset[metric_name], subset[covariate_col], ddof=1)[0, 1] / covariate_variance)
    mean_covariate = float(subset[covariate_col].mean())
    subset["cuped_adjusted"] = subset[metric_name] - theta * (subset[covariate_col] - mean_covariate)

    raw_result = continuous_metric_analysis(
        subset[subset[group_col] == control][metric_name],
        subset[subset[group_col] == treatment][metric_name],
        alpha=alpha,
    )
    adjusted_result = continuous_metric_analysis(
        subset[subset[group_col] == control]["cuped_adjusted"],
        subset[subset[group_col] == treatment]["cuped_adjusted"],
        alpha=alpha,
    )

    raw_variance = float(subset[metric_name].var(ddof=1))
    adjusted_variance = float(subset["cuped_adjusted"].var(ddof=1))
    variance_reduction = None
    if raw_variance > 0:
        variance_reduction = float(1 - adjusted_variance / raw_variance)

    adjusted_result["test"] = "welch_t_test_cuped_adjusted"
    adjusted_result["analysis_basis"] = "cuped_adjusted"
    adjusted_result["raw_estimate"] = {
        "control_mean": raw_result["control"]["mean"],
        "treatment_mean": raw_result["treatment"]["mean"],
        "absolute_lift": raw_result["absolute_lift"],
        "relative_lift": raw_result["relative_lift"],
        "p_value": raw_result["p_value"],
    }
    adjusted_result["cuped"] = {
        "covariate": covariate_col,
        "theta": theta,
        "covariate_mean": mean_covariate,
        "raw_variance": raw_variance,
        "adjusted_variance": adjusted_variance,
        "variance_reduction_pct": float(variance_reduction * 100) if variance_reduction is not None else None,
    }
    return adjusted_result


def categorical_balance_analysis(control_series, treatment_series, alpha: float = 0.05) -> dict[str, Any]:
    contingency = np.array(
        [
            control_series.value_counts(dropna=False).sort_index(),
            treatment_series.value_counts(dropna=False).sort_index(),
        ],
        dtype=object,
    )
    categories = sorted(set(control_series.dropna().unique().tolist()) | set(treatment_series.dropna().unique().tolist()), key=str)
    control_counts = [int((control_series == category).sum()) for category in categories]
    treatment_counts = [int((treatment_series == category).sum()) for category in categories]
    chi2, p_value, _, _ = stats.chi2_contingency([control_counts, treatment_counts])
    return {
        "metric_type": "categorical",
        "test": "chi_square_independence",
        "categories": [str(category) for category in categories],
        "control_counts": dict(zip([str(category) for category in categories], control_counts)),
        "treatment_counts": dict(zip([str(category) for category in categories], treatment_counts)),
        "chi2_statistic": float(chi2),
        "p_value": float(p_value),
        "statistically_significant": bool(p_value < alpha),
    }


def analyze_metric(df, group_col: str, control: Any, treatment: Any, metric_config: dict[str, Any], alpha: float) -> dict[str, Any]:
    metric_name = metric_config["name"]
    if metric_name not in df.columns:
        raise ValueError(f"Unknown metric column: {metric_name}")
    control_series = df[df[group_col] == control][metric_name]
    treatment_series = df[df[group_col] == treatment][metric_name]
    metric_type = infer_metric_type(df[metric_name], metric_config.get("type"))

    if metric_type == "binary":
        result = binary_metric_analysis(
            control_series,
            treatment_series,
            success_value=metric_config.get("success_value", 1),
            alpha=alpha,
        )
    elif metric_type == "continuous":
        cuped_covariate = metric_config.get("cuped_covariate")
        if cuped_covariate:
            result = cuped_adjusted_continuous_analysis(
                df[df[group_col].isin([control, treatment])],
                metric_name=metric_name,
                group_col=group_col,
                control=control,
                treatment=treatment,
                covariate_col=cuped_covariate,
                alpha=alpha,
            )
        else:
            result = continuous_metric_analysis(control_series, treatment_series, alpha=alpha)
    else:
        result = categorical_balance_analysis(control_series, treatment_series, alpha=alpha)

    preferred_direction = metric_config.get("preferred_direction", "increase")
    threshold = metric_config.get("practical_significance")
    absolute_lift = result.get("absolute_lift")
    practically_significant = None
    if threshold is not None and absolute_lift is not None:
        practically_significant = abs(float(absolute_lift)) >= float(threshold)

    result.update(
        {
            "role": metric_config.get("role", "secondary"),
            "preferred_direction": preferred_direction,
            "practical_significance_threshold": threshold,
            "practically_significant": practically_significant,
        }
    )
    return result


def apply_multiple_testing_correction(report: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    correction_config = config.get("multiple_testing")
    if not correction_config:
        return {}

    if isinstance(correction_config, str):
        method = correction_config
        metric_names = [name for name, result in report["metrics"].items() if "p_value" in result]
    else:
        method = correction_config.get("method", "holm")
        metric_names = correction_config.get("metric_names") or [name for name, result in report["metrics"].items() if "p_value" in result]

    metric_names = [name for name in metric_names if name in report["metrics"] and "p_value" in report["metrics"][name]]
    if len(metric_names) < 2:
        return {"applied": False, "reason": "Need at least two tested metrics for multiple-testing correction."}

    raw_p_values = [float(report["metrics"][name]["p_value"]) for name in metric_names]
    rejected, adjusted_p_values, _, _ = multipletests(raw_p_values, alpha=report["alpha"], method=method)
    for metric_name, adjusted_p_value, reject in zip(metric_names, adjusted_p_values, rejected):
        report["metrics"][metric_name]["multiple_testing"] = {
            "method": method,
            "raw_p_value": float(report["metrics"][metric_name]["p_value"]),
            "adjusted_p_value": float(adjusted_p_value),
            "rejected": bool(reject),
        }
    return {
        "applied": True,
        "method": method,
        "metric_names": metric_names,
        "alpha": float(report["alpha"]),
    }


def cumulative_alpha_spent(alpha: float, info_fraction: float, method: str) -> float:
    info_fraction = min(max(float(info_fraction), 1e-6), 1.0)
    method = method.lower()
    if method == "bonferroni":
        return float(alpha * info_fraction)
    if method in {"obrien_fleming", "obf"}:
        z_alpha_over_2 = stats.norm.ppf(1 - alpha / 2)
        spent = 2 - 2 * stats.norm.cdf(z_alpha_over_2 / math.sqrt(info_fraction))
        return float(min(max(spent, 0.0), alpha))
    if method == "pocock":
        spent = alpha * math.log(1 + (math.e - 1) * info_fraction)
        return float(min(max(spent, 0.0), alpha))
    raise ValueError(f"Unsupported sequential monitoring method: {method}")


def apply_sequential_monitoring(report: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    sequential_config = config.get("sequential_monitoring")
    if not sequential_config:
        return {}

    if isinstance(sequential_config, str):
        sequential_config = {"method": sequential_config}

    method = sequential_config.get("method", "obrien_fleming")
    info_fraction = sequential_config.get("information_fraction")
    current_look = sequential_config.get("current_look")
    total_looks = sequential_config.get("total_looks")
    if info_fraction is None:
        if current_look is None or total_looks is None:
            return {"applied": False, "reason": "Provide information_fraction or current_look + total_looks."}
        info_fraction = float(current_look) / float(total_looks)

    spent_alpha = cumulative_alpha_spent(report["alpha"], info_fraction, method)
    metric_names = sequential_config.get("metric_names") or [name for name, result in report["metrics"].items() if "p_value" in result]
    metric_names = [name for name in metric_names if name in report["metrics"] and "p_value" in report["metrics"][name]]
    for metric_name in metric_names:
        p_value = float(report["metrics"][metric_name]["p_value"])
        report["metrics"][metric_name]["sequential_monitoring"] = {
            "method": method,
            "information_fraction": float(info_fraction),
            "current_look": int(current_look) if current_look is not None else None,
            "total_looks": int(total_looks) if total_looks is not None else None,
            "adjusted_alpha": float(spent_alpha),
            "rejected": bool(p_value < spent_alpha),
            "raw_p_value": p_value,
        }
    return {
        "applied": True,
        "method": method,
        "metric_names": metric_names,
        "information_fraction": float(info_fraction),
        "current_look": int(current_look) if current_look is not None else None,
        "total_looks": int(total_looks) if total_looks is not None else None,
        "adjusted_alpha": float(spent_alpha),
    }


def _binary_required_sample_size(control_rate: float, mde: float, alpha: float, power: float, preferred_direction: str) -> float | None:
    target_rate = control_rate + mde if preferred_direction != "decrease" else control_rate - mde
    target_rate = min(max(target_rate, 1e-6), 1 - 1e-6)
    if abs(target_rate - control_rate) < 1e-12:
        return None
    effect_size = abs(cohen_h(control_rate, target_rate))
    if effect_size == 0:
        return None
    return float(NormalIndPower().solve_power(effect_size=effect_size, power=power, alpha=alpha, ratio=1.0, alternative="two-sided"))


def _continuous_required_sample_size(control_std: float, treatment_std: float, mde: float, alpha: float, power: float) -> float | None:
    pooled_std = math.sqrt((control_std**2 + treatment_std**2) / 2) if control_std or treatment_std else 0.0
    if pooled_std == 0 or mde == 0:
        return None
    effect_size = abs(mde / pooled_std)
    if effect_size == 0:
        return None
    return float(TTestIndPower().solve_power(effect_size=effect_size, power=power, alpha=alpha, ratio=1.0, alternative="two-sided"))


def estimate_metric_power(metric_name: str, metric_result: dict[str, Any], config: dict[str, Any], alpha: float) -> dict[str, Any]:
    power_config = config.get("power_analysis")
    if not power_config:
        return {}
    if isinstance(power_config, (int, float)):
        power_config = {"power": float(power_config)}

    metric_names = power_config.get("metric_names")
    if metric_names and metric_name not in metric_names:
        return {}

    target_power = float(power_config.get("power", 0.8))
    preferred_direction = metric_result.get("preferred_direction", "increase")
    metric_type = metric_result.get("metric_type")
    mde_map = power_config.get("mde", {})
    configured_mde = None
    if isinstance(mde_map, dict):
        configured_mde = mde_map.get(metric_name)
    elif isinstance(mde_map, (int, float)):
        configured_mde = float(mde_map)

    required_n = None
    observed_power = None

    if metric_type == "binary":
        control_rate = float(metric_result["control"]["rate"])
        treatment_rate = float(metric_result["treatment"]["rate"])
        control_n = int(metric_result["control"]["n"])
        effect_size = abs(cohen_h(control_rate, treatment_rate))
        if effect_size > 0 and control_n > 1:
            observed_power = float(NormalIndPower().solve_power(effect_size=effect_size, nobs1=control_n, alpha=alpha, ratio=1.0, alternative="two-sided"))
        mde = configured_mde if configured_mde is not None else metric_result.get("practical_significance_threshold")
        if mde is not None:
            required_n = _binary_required_sample_size(control_rate, float(mde), alpha, target_power, preferred_direction)
    elif metric_type == "continuous":
        control_n = int(metric_result["control"]["n"])
        control_std = float(metric_result["control"]["std"])
        treatment_std = float(metric_result["treatment"]["std"])
        effect_size_value = metric_result.get("effect_size", {}).get("value")
        if effect_size_value not in {None, 0} and control_n > 1:
            observed_power = float(TTestIndPower().solve_power(effect_size=abs(float(effect_size_value)), nobs1=control_n, alpha=alpha, ratio=1.0, alternative="two-sided"))
        mde = configured_mde if configured_mde is not None else metric_result.get("practical_significance_threshold")
        if mde is not None:
            required_n = _continuous_required_sample_size(control_std, treatment_std, float(mde), alpha, target_power)

    if observed_power is None and required_n is None:
        return {}

    current_n = int(metric_result["control"]["n"]) if "control" in metric_result and isinstance(metric_result["control"], dict) and "n" in metric_result["control"] else None
    return {
        "target_power": target_power,
        "alpha": alpha,
        "observed_power": float(observed_power) if observed_power is not None else None,
        "required_n_per_group": float(required_n) if required_n is not None else None,
        "current_n_per_group": current_n,
        "underpowered_for_target": bool(required_n is not None and current_n is not None and current_n < required_n),
    }


def apply_power_analysis(report: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    power_config = config.get("power_analysis")
    if not power_config:
        return {}
    analyzed_metrics = []
    for metric_name, metric_result in report["metrics"].items():
        power_result = estimate_metric_power(metric_name, metric_result, config, alpha=report["alpha"])
        if power_result:
            report["metrics"][metric_name]["power_analysis"] = power_result
            analyzed_metrics.append(metric_name)
    return {
        "applied": bool(analyzed_metrics),
        "metric_names": analyzed_metrics,
        "target_power": float(power_config.get("power", 0.8)) if isinstance(power_config, dict) else float(power_config),
    }


def analyze_balance(df, group_col: str, control: Any, treatment: Any, covariates: list[str], alpha: float) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for covariate in covariates:
        if covariate not in df.columns:
            checks[covariate] = {"error": "Unknown covariate."}
            continue
        metric_type = infer_metric_type(df[covariate])
        if metric_type == "binary":
            checks[covariate] = binary_metric_analysis(df[df[group_col] == control][covariate], df[df[group_col] == treatment][covariate], alpha=alpha)
        elif metric_type == "continuous":
            checks[covariate] = continuous_metric_analysis(df[df[group_col] == control][covariate], df[df[group_col] == treatment][covariate], alpha=alpha)
        else:
            checks[covariate] = categorical_balance_analysis(df[df[group_col] == control][covariate], df[df[group_col] == treatment][covariate], alpha=alpha)
    return checks


def _metric_improved(metric_result: dict[str, Any]) -> bool | None:
    if "absolute_lift" not in metric_result or metric_result["absolute_lift"] is None:
        return None
    preferred_direction = metric_result.get("preferred_direction", "increase")
    absolute_lift = float(metric_result["absolute_lift"])
    if preferred_direction == "decrease":
        return absolute_lift < 0
    return absolute_lift > 0


def summarize_decision(report: dict[str, Any]) -> dict[str, Any]:
    if report["sample_ratio_mismatch"]["is_mismatch"]:
        return {
            "status": "invalid_due_to_srm",
            "summary": "Sample ratio mismatch suggests the experiment allocation may be broken.",
        }

    primary_wins = []
    primary_losses = []
    guardrail_regressions = []
    inconclusive_primary = []

    for metric_name, result in report["metrics"].items():
        improved = _metric_improved(result)
        significant = metric_is_significant(result)
        role = result.get("role", "secondary")
        practically_significant = result.get("practically_significant")

        if role == "primary":
            if significant and improved:
                if practically_significant is False:
                    inconclusive_primary.append(metric_name)
                else:
                    primary_wins.append(metric_name)
            elif significant and improved is False:
                primary_losses.append(metric_name)
            else:
                inconclusive_primary.append(metric_name)

        if role == "guardrail" and significant and improved is False:
            guardrail_regressions.append(metric_name)

    if primary_losses or guardrail_regressions:
        return {
            "status": "do_not_ship_treatment",
            "primary_losses": primary_losses,
            "guardrail_regressions": guardrail_regressions,
            "summary": "Treatment shows statistically significant regressions on a primary or guardrail metric.",
        }
    if primary_wins and not guardrail_regressions:
        return {
            "status": "treatment_looks_promising",
            "primary_wins": primary_wins,
            "summary": "Treatment improves the primary metric without a detected guardrail regression.",
        }
    return {
        "status": "inconclusive",
        "inconclusive_primary": inconclusive_primary,
        "summary": "The experiment does not provide decisive evidence to ship treatment yet.",
    }


def analyze_experiment(df, config: dict[str, Any]) -> dict[str, Any]:
    group_col = config["group_col"]
    alpha = float(config.get("alpha", 0.05))
    control, treatment = resolve_variants(df, group_col, config.get("control"), config.get("treatment"))

    metric_configs = config.get("metrics")
    if not metric_configs:
        raise ValueError("Experiment analysis requires config.metrics.")
    normalized_metrics = [metric if isinstance(metric, dict) else {"name": metric} for metric in metric_configs]
    if not any(metric.get("role") == "primary" for metric in normalized_metrics):
        normalized_metrics[0]["role"] = "primary"

    report = {
        "group_col": group_col,
        "control": control,
        "treatment": treatment,
        "alpha": alpha,
        "variant_counts": {
            str(control): int((df[group_col] == control).sum()),
            str(treatment): int((df[group_col] == treatment).sum()),
        },
        "sample_ratio_mismatch": sample_ratio_mismatch(
            df,
            group_col=group_col,
            control=control,
            treatment=treatment,
            expected_allocation=config.get("expected_allocation"),
            alpha=alpha,
        ),
        "metrics": {},
        "balance_checks": {},
        "multiple_testing": {},
        "sequential_monitoring": {},
        "power_analysis": {},
    }

    for metric_config in normalized_metrics:
        report["metrics"][metric_config["name"]] = analyze_metric(df, group_col, control, treatment, metric_config, alpha)

    covariates = config.get("covariates", [])
    if covariates:
        report["balance_checks"] = analyze_balance(df, group_col, control, treatment, covariates, alpha)

    report["srm_p_value"] = report["sample_ratio_mismatch"].get("p_value")
    if covariates:
        p_values = {
            name: item.get("p_value")
            for name, item in report["balance_checks"].items()
            if isinstance(item, dict) and item.get("p_value") is not None
        }
        threshold = alpha / max(1, len(p_values))
        failures = {name: p for name, p in p_values.items() if float(p) <= threshold}
        marginal = {name: p for name, p in p_values.items() if float(p) <= alpha}
        report["balance_test"] = {
            "alpha": alpha,
            "bonferroni_threshold": threshold,
            "p_values": p_values,
            "failures": failures,
            "marginal": marginal,
            "passed": not failures,
        }
        report["balance_passed"] = not failures
    else:
        report["balance_passed"] = None

    primary_names = [m["name"] for m in normalized_metrics if m.get("role") == "primary"]
    if primary_names:
        primary_name = primary_names[0]
        primary = report["metrics"].get(primary_name, {})
        report["primary_metric"] = primary_name
        report["effect"] = primary.get("absolute_lift")
        report["p_value"] = primary.get("p_value")
        report["primary_metrics"] = primary_names

    report["multiple_testing"] = apply_multiple_testing_correction(report, config)
    report["sequential_monitoring"] = apply_sequential_monitoring(report, config)
    report["power_analysis"] = apply_power_analysis(report, config)
    report["decision"] = summarize_decision(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a two-arm A/B experiment.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--config-json", required=True)
    parser.add_argument("--output-path", default=None)
    args = parser.parse_args()

    df = load_dataframe(args.input_path)
    config = parse_json_arg(args.config_json)
    report = analyze_experiment(df, config)
    if args.output_path:
        write_json(args.output_path, report)
        print(json.dumps({"output_path": str(args.output_path)}, ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
