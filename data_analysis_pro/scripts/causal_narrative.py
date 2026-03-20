#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import parse_json_arg, write_json, write_markdown

TASK_LABELS = {
    "did": "Difference-in-Differences",
    "rd": "Regression Discontinuity",
    "synthetic-control": "Synthetic Control",
    "iv": "Instrumental Variables",
    "dml": "Double Machine Learning",
    "dr": "Doubly Robust Estimation",
    "psm": "Propensity Score Matching",
    "orthogonal": "Orthogonal Learner",
    "uplift": "Uplift Modeling",
    "cate": "Meta-Learner CATE",
    "causal": "Causal Suite",
}


def _fmt_number(value: Any, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) >= 1000:
        return f"{number:,.{digits}f}"
    return f"{number:.{digits}f}"


def _fmt_percent(value: Any, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number * 100:.{digits}f}%"


def _direction_label(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "unclear"
    if number > 0:
        return "positive"
    if number < 0:
        return "negative"
    return "neutral"


def _unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item and item not in seen:
            unique.append(item)
            seen.add(item)
    return unique


def _artifact_names(artifacts: list[str]) -> list[str]:
    return [Path(path).name for path in artifacts]


def _is_significant(p_value: Any, alpha: float = 0.05) -> bool | None:
    if p_value is None:
        return None
    try:
        return bool(float(p_value) < alpha)
    except (TypeError, ValueError):
        return None


def _assumptions_for_task(task: str) -> list[str]:
    assumptions = {
        "did": [
            "Treatment and control groups would have followed parallel trends absent the intervention.",
            "No material spillovers or concurrent shocks affect treatment but not control at the same time.",
            "Group composition is stable enough that the pre/post comparison is meaningful.",
        ],
        "rd": [
            "Units cannot precisely manipulate the running variable around the cutoff.",
            "Potential outcomes evolve smoothly through the cutoff aside from treatment assignment.",
            "The estimate is local to observations near the cutoff rather than the whole population.",
        ],
        "synthetic-control": [
            "The donor pool can reproduce the treated unit well before the intervention.",
            "No major post-treatment shock differentially affects the treated unit outside the intervention.",
            "Donor units are not contaminated by the same treatment during the analysis window.",
        ],
        "iv": [
            "The instrument is relevant for treatment take-up.",
            "The instrument affects the outcome only through the treatment channel.",
            "Monotonicity and stable treatment response are credible for the induced compliers.",
        ],
        "dml": [
            "Conditional ignorability is plausible given the modeled covariates.",
            "Treatment and control overlap sufficiently in covariate space.",
            "Nuisance models are flexible enough that orthogonalization removes most bias.",
        ],
        "dr": [
            "Conditional ignorability is plausible given the modeled covariates.",
            "Treatment and control overlap sufficiently in covariate space.",
            "At least one nuisance model is reasonably well specified.",
        ],
        "psm": [
            "Selection into treatment is captured by observed covariates.",
            "Common support exists so treated users can be matched to similar controls.",
            "Post-match balance is good enough that remaining confounding is limited.",
        ],
        "orthogonal": [
            "Conditional ignorability is plausible given the modeled features.",
            "Nuisance models for baseline outcome and propensity are adequate.",
            "Estimated heterogeneity reflects signal rather than unstable pseudo-outcomes.",
        ],
        "uplift": [
            "Treatment assignment is randomized or ignorable conditional on included features.",
            "Predicted uplift generalizes to the population where targeting decisions will be made.",
            "Observed bucket lift is not driven by leakage or unstable subgroup estimates.",
        ],
        "cate": [
            "Treatment assignment is randomized or ignorable conditional on included features.",
            "Meta-learners are flexible enough to capture treatment heterogeneity.",
            "Agreement across learners is good enough to trust subgroup ranking.",
        ],
        "causal": [
            "Each included method's identifying assumptions must be considered separately.",
            "Consistency across methods strengthens confidence but does not eliminate design risk.",
            "The final recommendation should prioritize methods with the best diagnostics for this dataset.",
        ],
    }
    return assumptions.get(task, ["Review the method-specific identifying assumptions before using the estimate for decisions."])


def _question_for_task(task: str, report: dict[str, Any]) -> str:
    outcome = report.get("outcome_col", "the outcome")
    if task == "did":
        return f"Did the intervention change `{outcome}` for the treated group relative to a comparable control group after rollout?"
    if task == "rd":
        return f"Does crossing the `{report.get('running_col', 'running variable')}` cutoff causally change `{outcome}` near the eligibility threshold?"
    if task == "synthetic-control":
        return f"After the intervention date, did `{report.get('treated_unit', 'the treated unit')}` diverge from a synthetic counterfactual for `{outcome}`?"
    if task == "iv":
        return f"What is the causal effect of `{report.get('treatment_col', 'treatment')}` on `{outcome}` after correcting for endogeneity with `{report.get('instrument_col', 'the instrument')}`?"
    if task in {"dml", "dr", "psm"}:
        return f"What is the average causal effect of `{report.get('treatment_col', 'treatment')}` on `{outcome}` after adjustment for observed confounders?"
    if task == "orthogonal":
        return f"How does the treatment effect on `{outcome}` vary across users after orthogonalizing baseline outcome and propensity patterns?"
    if task == "uplift":
        return f"Which users are most likely to increase `{outcome}` when treated rather than left in control?"
    if task == "cate":
        return f"Which subgroups appear to have larger or smaller causal responses in `{outcome}` across meta-learner CATE models?"
    if task == "causal":
        return "What do the available causal designs jointly suggest about the treatment effect, and which methods are credible enough to inform action?"
    return f"What is the causal effect on `{outcome}`?"


def _design_for_task(task: str, report: dict[str, Any]) -> str:
    if task == "did":
        return (
            f"Compare `{report.get('treatment_value', 'treated')}` vs `{report.get('control_value', 'control')}` across "
            f"pre/post periods and estimate the interaction effect on `{report.get('outcome_col', 'outcome')}`."
        )
    if task == "rd":
        return (
            f"Use a local weighted regression around cutoff `{_fmt_number(report.get('cutoff'))}` on "
            f"`{report.get('running_col', 'running variable')}` to estimate the jump in `{report.get('outcome_col', 'outcome')}`."
        )
    if task == "synthetic-control":
        return (
            f"Build a weighted donor combination for `{report.get('treated_unit', 'the treated unit')}` and compare post-treatment "
            f"`{report.get('outcome_col', 'outcome')}` against that synthetic path."
        )
    if task == "iv":
        return (
            f"Estimate a 2SLS model that instruments `{report.get('treatment_col', 'treatment')}` with "
            f"`{report.get('instrument_col', 'instrument')}` before regressing `{report.get('outcome_col', 'outcome')}`."
        )
    if task == "dml":
        return "Cross-fit nuisance models for outcome and treatment, orthogonalize residuals, and estimate an average treatment effect from the residual-on-residual signal."
    if task == "dr":
        return "Combine outcome and propensity models in a doubly robust score so the estimate remains stable if at least one nuisance model is approximately correct."
    if task == "psm":
        return "Estimate propensity scores, match treated rows to similar controls, then compute the average treatment effect on the treated from the matched sample."
    if task == "orthogonal":
        return "Use cross-fitted baseline outcome and propensity models to construct pseudo-outcomes, then learn heterogeneous treatment effects from those orthogonalized targets."
    if task == "uplift":
        return "Train treatment-aware response models, rank users by predicted uplift, and compare observed lift across uplift-ordered buckets and subgroups."
    if task == "cate":
        return "Estimate conditional treatment effects with multiple meta-learners and compare their distributions, subgroup patterns, and agreement."
    if task == "causal":
        return "Run multiple causal estimators and compare direction, magnitude, and diagnostic quality instead of trusting a single design in isolation."
    return "Use the configured causal design to estimate the effect."


def _key_estimate_for_task(task: str, report: dict[str, Any]) -> dict[str, Any]:
    if task == "did":
        p_value = report.get("regression", {}).get("p_value")
        return {
            "label": "DID interaction effect",
            "value": report.get("did_estimate"),
            "p_value": p_value,
            "confidence_interval": report.get("regression", {}).get("confidence_interval"),
            "direction": _direction_label(report.get("did_estimate")),
            "significant": _is_significant(p_value),
        }
    if task == "rd":
        p_value = report.get("regression", {}).get("p_value")
        return {
            "label": "Local effect at the cutoff",
            "value": report.get("local_effect"),
            "p_value": p_value,
            "confidence_interval": report.get("regression", {}).get("confidence_interval"),
            "direction": _direction_label(report.get("local_effect")),
            "significant": _is_significant(p_value),
        }
    if task == "synthetic-control":
        return {
            "label": "Average post-treatment gap",
            "value": report.get("post_average_gap"),
            "p_value": None,
            "confidence_interval": None,
            "direction": _direction_label(report.get("post_average_gap")),
            "significant": None,
        }
    if task == "iv":
        return {
            "label": "2SLS treatment effect",
            "value": report.get("iv_estimate"),
            "p_value": report.get("p_value"),
            "confidence_interval": report.get("confidence_interval"),
            "direction": _direction_label(report.get("iv_estimate")),
            "significant": _is_significant(report.get("p_value")),
        }
    if task in {"dml", "dr"}:
        return {
            "label": "Average treatment effect",
            "value": report.get("average_treatment_effect"),
            "p_value": report.get("p_value"),
            "confidence_interval": report.get("confidence_interval"),
            "direction": _direction_label(report.get("average_treatment_effect")),
            "significant": _is_significant(report.get("p_value")),
        }
    if task == "psm":
        return {
            "label": "Average treatment effect on treated",
            "value": report.get("average_treatment_effect_on_treated"),
            "p_value": report.get("p_value"),
            "confidence_interval": report.get("confidence_interval"),
            "direction": _direction_label(report.get("average_treatment_effect_on_treated")),
            "significant": _is_significant(report.get("p_value")),
        }
    if task == "orthogonal":
        return {
            "label": "Average predicted treatment effect",
            "value": report.get("average_predicted_effect"),
            "p_value": None,
            "confidence_interval": None,
            "direction": _direction_label(report.get("average_predicted_effect")),
            "significant": None,
        }
    if task == "uplift":
        return {
            "label": "Average predicted uplift",
            "value": report.get("average_predicted_uplift"),
            "p_value": None,
            "confidence_interval": None,
            "direction": _direction_label(report.get("average_predicted_uplift")),
            "significant": None,
        }
    if task == "cate":
        methods = sorted(report.get("methods", {}).keys())
        comparison = report.get("method_comparison", {})
        return {
            "label": "Meta-learner comparison",
            "value": comparison.get("mean_absolute_difference"),
            "p_value": None,
            "confidence_interval": None,
            "direction": "unclear",
            "significant": None,
            "methods": methods,
            "correlation": comparison.get("correlation"),
        }
    return {
        "label": "Effect estimate",
        "value": None,
        "p_value": None,
        "confidence_interval": None,
        "direction": "unclear",
        "significant": None,
    }


def _diagnostics_for_task(task: str, report: dict[str, Any]) -> list[str]:
    diagnostics: list[str] = []
    if task == "did":
        diagnostics.append(f"Estimated DID effect: {_fmt_number(report.get('did_estimate'))}.")
        if report.get("relative_effect_vs_control_pre") is not None:
            diagnostics.append(f"Relative effect vs control pre-period baseline: {_fmt_percent(report.get('relative_effect_vs_control_pre'))}.")
        regression = report.get("regression", {})
        if regression.get("available"):
            diagnostics.append(
                f"Robust interaction p-value: {_fmt_number(regression.get('p_value'))}; CI: {_fmt_number(regression.get('confidence_interval', [None, None])[0])} to {_fmt_number(regression.get('confidence_interval', [None, None])[1])}."
            )
    elif task == "rd":
        counts = report.get("counts", {})
        diagnostics.append(f"Bandwidth: {_fmt_number(report.get('bandwidth'))}; local sample size left/right = {counts.get('left', 0)}/{counts.get('right', 0)}.")
        jump = float(report.get("treated_share", {}).get("right", 0.0)) - float(report.get("treated_share", {}).get("left", 0.0))
        diagnostics.append(f"Treatment assignment jump at cutoff: {_fmt_number(jump)}.")
        regression = report.get("regression", {})
        if regression.get("available"):
            diagnostics.append(f"Local-linear RD p-value: {_fmt_number(regression.get('p_value'))}.")
        for feature, details in report.get("covariate_continuity", {}).items():
            diagnostics.append(f"Covariate continuity for `{feature}`: local effect {_fmt_number(details.get('local_effect'))}, p-value {_fmt_number(details.get('p_value'))}.")
    elif task == "synthetic-control":
        diagnostics.append(f"Pre-treatment RMSPE: {_fmt_number(report.get('pre_rmspe'))}.")
        diagnostics.append(f"Post/pre RMSPE ratio: {_fmt_number(report.get('post_to_pre_rmspe_ratio'))}.")
        top_weights = report.get("donor_weights", [])[:3]
        if top_weights:
            diagnostics.append("Top donor weights: " + ", ".join(f"{row['unit']}={_fmt_number(row['weight'])}" for row in top_weights) + ".")
    elif task == "iv":
        first_stage = report.get("first_stage", {})
        diagnostics.append(f"First-stage coefficient on instrument: {_fmt_number(first_stage.get('instrument_coefficient'))}.")
        diagnostics.append(f"First-stage F-statistic: {_fmt_number(first_stage.get('f_statistic'))}.")
        diagnostics.append(f"Reduced-form coefficient: {_fmt_number(report.get('reduced_form', {}).get('instrument_coefficient'))}.")
    elif task in {"dml", "dr"}:
        diagnostics.append(f"ATE: {_fmt_number(report.get('average_treatment_effect'))}; naive difference: {_fmt_number(report.get('naive_difference'))}.")
        diagnostics.append(f"Overlap share in common support: {_fmt_percent(report.get('propensity_overlap', {}).get('share_in_common_support'))}.")
        diagnostics.append(f"Robust p-value: {_fmt_number(report.get('p_value'))}.")
    elif task == "psm":
        diagnostics.append(f"Matched pairs: {report.get('matched_pairs', 0)}.")
        diagnostics.append(f"Common-support share: {_fmt_percent(report.get('common_support', {}).get('share_in_common_support'))}.")
        diagnostics.append(f"Balance improved: {bool(report.get('balance', {}).get('balance_improved', False))}.")
    elif task == "orthogonal":
        diagnostics.append(f"Average predicted effect: {_fmt_number(report.get('average_predicted_effect'))}.")
        diagnostics.append(f"Overlap share in common support: {_fmt_percent(report.get('propensity_overlap', {}).get('share_in_common_support'))}.")
        subgroup_effects = report.get("subgroup_effects", [])
        if subgroup_effects:
            top_segment = sorted(
                subgroup_effects,
                key=lambda row: abs(_subgroup_effect_value(row, ["orthogonal_mean_effect", "effect"]) or 0.0),
                reverse=True,
            )[0]
            diagnostics.append(
                f"Most pronounced subgroup effect: {top_segment.get('segment')} = {_fmt_number(_subgroup_effect_value(top_segment, ['orthogonal_mean_effect', 'effect']))}."
            )
    elif task == "uplift":
        diagnostics.append(f"Average predicted uplift: {_fmt_number(report.get('average_predicted_uplift'))}.")
        buckets = report.get("uplift_buckets", [])
        if buckets:
            top_bucket = sorted(buckets, key=lambda row: row.get("bucket", 0))[0]
            diagnostics.append(f"Top-ranked uplift bucket observed lift: {_fmt_number(top_bucket.get('observed_lift'))}.")
        heterogeneity = report.get("heterogeneity", [])
        if heterogeneity:
            best_group = sorted(heterogeneity, key=lambda row: float(row.get("average_uplift", 0.0)), reverse=True)[0]
            diagnostics.append(f"Highest-uplift subgroup: {best_group.get('segment')} = {_fmt_number(best_group.get('average_uplift'))}.")
    elif task == "cate":
        comparison = report.get("method_comparison", {})
        diagnostics.append(f"Meta-learner correlation: {_fmt_number(comparison.get('correlation'))}.")
        diagnostics.append(f"Mean absolute CATE gap: {_fmt_number(comparison.get('mean_absolute_difference'))}.")
        subgroup_cate = report.get("subgroup_cate", [])
        if subgroup_cate:
            strongest_group = sorted(
                subgroup_cate,
                key=lambda row: abs(_subgroup_effect_value(row, ["mean_cate"]) or 0.0),
                reverse=True,
            )[0]
            diagnostics.append(
                f"Most differentiated subgroup: {strongest_group.get('segment')} = {_fmt_number(_subgroup_effect_value(strongest_group, ['mean_cate']))}."
            )
    return diagnostics


def _risks_for_task(task: str, report: dict[str, Any]) -> list[str]:
    risks: list[str] = []
    if task == "did":
        regression = report.get("regression", {})
        if regression.get("available") and not _is_significant(regression.get("p_value"), alpha=0.05):
            risks.append("The DID interaction is not statistically distinguishable from zero at the default 5% level.")
    elif task == "rd":
        jump = float(report.get("treated_share", {}).get("right", 0.0)) - float(report.get("treated_share", {}).get("left", 0.0))
        if jump < 0.5:
            risks.append("Treatment take-up does not change sharply enough at the cutoff for a clean sharp-RD story.")
        discontinuous = [
            feature
            for feature, details in report.get("covariate_continuity", {}).items()
            if details.get("p_value") is not None and float(details["p_value"]) < 0.05
        ]
        if discontinuous:
            risks.append("Observed covariates may jump at the cutoff: " + ", ".join(discontinuous[:4]) + ".")
    elif task == "synthetic-control":
        if float(report.get("pre_rmspe", 0.0)) > 5:
            risks.append("Pre-treatment fit is weak, so the post-treatment gap may reflect poor counterfactual construction.")
    elif task == "iv":
        if report.get("first_stage", {}).get("weak_instrument_at_f_lt_10"):
            risks.append("The instrument looks weak by the common first-stage F < 10 rule.")
    elif task in {"dml", "dr"}:
        if float(report.get("propensity_overlap", {}).get("share_in_common_support", 1.0)) < 0.8:
            risks.append("Treatment/control overlap is limited, which makes the adjusted estimate more model-dependent.")
    elif task == "psm":
        if float(report.get("common_support", {}).get("share_in_common_support", 1.0)) < 0.8:
            risks.append("Common support is limited, so many treated rows may not have credible controls.")
        if not bool(report.get("balance", {}).get("balance_improved", True)):
            risks.append("Matching did not improve balance, so residual confounding likely remains.")
    elif task == "orthogonal":
        if float(report.get("propensity_overlap", {}).get("share_in_common_support", 1.0)) < 0.8:
            risks.append("Orthogonalized heterogeneity estimates rely on limited overlap.")
    elif task == "uplift":
        if not report.get("heterogeneity"):
            risks.append("No sufficiently large high-signal subgroup was found, so targeting value is uncertain.")
    elif task == "cate":
        correlation = report.get("method_comparison", {}).get("correlation")
        if correlation is not None and float(correlation) < 0.3:
            risks.append("Meta-learners disagree materially, which signals unstable subgroup treatment effects.")
    return risks


def _business_interpretation_for_task(task: str, report: dict[str, Any], key_estimate: dict[str, Any]) -> list[str]:
    outcome = report.get("outcome_col", "outcome")
    treatment = report.get("treatment_col", "treatment")
    interpretation: list[str] = []
    value = key_estimate.get("value")
    direction = key_estimate.get("direction", "unclear")
    if task == "did":
        interpretation.append(
            f"Relative to control, the post-treatment shift in `{outcome}` is estimated at {_fmt_number(value)} units for `{report.get('treatment_value', 'treated')}`."
        )
    elif task == "rd":
        interpretation.append(
            f"For units near the eligibility threshold, crossing the cutoff changes `{outcome}` by about {_fmt_number(value)} units."
        )
        interpretation.append("This is a local estimate around the cutoff and should not be extrapolated mechanically to the full population.")
    elif task == "synthetic-control":
        interpretation.append(
            f"After intervention, the treated unit sits {_fmt_number(value)} outcome units {direction} relative to its synthetic counterfactual on average."
        )
    elif task == "iv":
        interpretation.append(
            f"Using exogenous variation from the instrument, a one-unit increase in `{treatment}` moves `{outcome}` by roughly {_fmt_number(value)} units for instrument-responsive users."
        )
    elif task in {"dml", "dr"}:
        interpretation.append(
            f"After adjustment for observed confounders, treatment changes `{outcome}` by about {_fmt_number(value)} units on average."
        )
    elif task == "psm":
        interpretation.append(
            f"Among matched treated rows, treatment shifts `{outcome}` by roughly {_fmt_number(value)} units relative to similar controls."
        )
    elif task == "orthogonal":
        interpretation.append("The average effect is useful as a directional benchmark, but the real value here is ranking heterogeneous responses across segments.")
    elif task == "uplift":
        interpretation.append("The model is most useful for prioritization: treat the high-uplift tail first rather than rolling out blindly to everyone.")
    elif task == "cate":
        interpretation.append("Use the subgroup and learner-agreement view to decide where differentiated treatment policy is defensible and where it is not.")
    if direction == "positive":
        interpretation.append(f"The current estimate points to a positive causal impact on `{outcome}`.")
    elif direction == "negative":
        interpretation.append(f"The current estimate points to a negative causal impact on `{outcome}`.")
    elif direction == "neutral":
        interpretation.append(f"The current estimate is effectively neutral for `{outcome}`.")
    return interpretation


def _subgroup_effect_value(row: dict[str, Any], preferred_keys: list[str]) -> float | None:
    for key in preferred_keys:
        if key in row and row[key] is not None:
            return float(row[key])
    dynamic_keys = [key for key in row if key.endswith("_mean_effect") and row[key] is not None]
    if dynamic_keys:
        values = [float(row[key]) for key in dynamic_keys]
        return float(sum(values) / len(values))
    return None


def _recommendation_for_task(task: str, key_estimate: dict[str, Any], risks: list[str]) -> str:
    significant = key_estimate.get("significant")
    direction = key_estimate.get("direction")
    risk_level = "high" if len(risks) >= 2 else "moderate" if len(risks) == 1 else "low"

    if task in {"uplift", "cate", "orthogonal"}:
        if risk_level == "low":
            return "Use this output for targeting or subgroup prioritization, but validate policy impact with an online experiment before broad rollout."
        return "Treat this as directional heterogeneity evidence only; do not use it as the sole basis for irreversible targeting decisions."

    if significant is True and direction == "positive" and risk_level == "low":
        return "The design supports a positive causal effect with manageable diagnostics. This is strong enough to inform rollout sizing or policy continuation."
    if significant is True and direction == "negative" and risk_level == "low":
        return "The design supports a harmful causal effect with manageable diagnostics. Avoid expanding this treatment without redesign."
    if significant is False:
        return "The estimate is too weak to support a confident causal claim. Treat the result as inconclusive and collect stronger evidence."
    if risk_level == "high":
        return "Do not rely on this estimate alone. Diagnostics or assumptions are weak enough that the result should be treated as provisional."
    return "Use the estimate as directional evidence, but keep the documented risks attached when making decisions."


def _headline_for_single(method_label: str, key_estimate: dict[str, Any]) -> str:
    label = key_estimate.get("label", "Effect")
    value = _fmt_number(key_estimate.get("value"))
    p_value = key_estimate.get("p_value")
    significant = key_estimate.get("significant")
    if significant is True:
        return f"{method_label} estimates {label.lower()} at {value} with statistically significant evidence."
    if significant is False:
        return f"{method_label} estimates {label.lower()} at {value}, but the evidence is not statistically decisive."
    return f"{method_label} reports {label.lower()} at {value}; rely on diagnostics because no direct p-value summary is available."


def _build_single_narrative(report: dict[str, Any]) -> dict[str, Any]:
    task = str(report.get("task", "")).strip().lower()
    method_label = TASK_LABELS.get(task, task or "Causal Method")
    key_estimate = _key_estimate_for_task(task, report)
    risks = _risks_for_task(task, report)
    narrative = {
        "task": task,
        "method_label": method_label,
        "question": _question_for_task(task, report),
        "design": _design_for_task(task, report),
        "identification_assumptions": _assumptions_for_task(task),
        "key_estimate": key_estimate,
        "diagnostics": _diagnostics_for_task(task, report),
        "business_interpretation": _business_interpretation_for_task(task, report, key_estimate),
        "risks_and_limits": risks,
        "recommendation": _recommendation_for_task(task, key_estimate, risks),
        "headline": _headline_for_single(method_label, key_estimate),
        "artifacts": report.get("artifacts", []),
        "artifact_names": _artifact_names(report.get("artifacts", [])),
    }
    return narrative


def _suite_overview(sections: list[dict[str, Any]]) -> tuple[str, dict[str, Any], list[str], str]:
    effect_sections = [section for section in sections if section.get("key_estimate", {}).get("direction") in {"positive", "negative", "neutral"}]
    positive_count = sum(section["key_estimate"]["direction"] == "positive" for section in effect_sections)
    negative_count = sum(section["key_estimate"]["direction"] == "negative" for section in effect_sections)
    significant_count = sum(section["key_estimate"].get("significant") is True for section in effect_sections)
    methods = [section["method_label"] for section in sections]

    if positive_count and not negative_count:
        headline = f"The causal methods mostly point to a positive effect across {positive_count} reported estimators."
        direction = "positive"
    elif negative_count and not positive_count:
        headline = f"The causal methods mostly point to a negative effect across {negative_count} reported estimators."
        direction = "negative"
    else:
        headline = "The causal methods provide mixed or method-dependent directional evidence."
        direction = "mixed"

    diagnostics = [
        f"Methods run: {', '.join(methods)}.",
        f"Methods with explicit statistical significance support: {significant_count}.",
    ]
    risks = _unique_keep_order([risk for section in sections for risk in section.get("risks_and_limits", [])])
    if direction == "mixed":
        risks.append("Method disagreement means the final decision should lean on the designs with the strongest diagnostics and assumptions.")
    recommendation = (
        "Use the methods with the strongest design-based credibility as the primary decision anchor, and treat the rest as triangulation."
        if risks
        else "The methods are directionally aligned with limited visible diagnostics risk, so the combined evidence is usable for decision support."
    )
    key_estimate = {
        "label": "Directional agreement across methods",
        "value": {"positive_methods": positive_count, "negative_methods": negative_count, "significant_methods": significant_count},
        "direction": direction,
        "significant": significant_count > 0,
    }
    return headline, key_estimate, diagnostics, recommendation


def build_causal_narrative(report: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    task = str(report.get("task", "")).strip().lower()
    if task != "causal":
        return _build_single_narrative(report)

    reports = report.get("reports", {})
    sections = [_build_single_narrative(subreport) for _, subreport in reports.items()]
    headline, key_estimate, diagnostics, recommendation = _suite_overview(sections)
    narrative = {
        "task": "causal",
        "method_label": TASK_LABELS["causal"],
        "question": _question_for_task("causal", report),
        "design": _design_for_task("causal", report),
        "identification_assumptions": _assumptions_for_task("causal"),
        "key_estimate": key_estimate,
        "diagnostics": diagnostics,
        "business_interpretation": [
            "Read this as a triangulation layer: consistency across credible methods is more useful than any single point estimate.",
            "When methods disagree, default to the design with the clearest identification and strongest diagnostics for the specific dataset.",
        ],
        "risks_and_limits": _unique_keep_order([risk for section in sections for risk in section.get("risks_and_limits", [])]),
        "recommendation": recommendation,
        "headline": headline,
        "artifacts": report.get("artifacts", []),
        "artifact_names": _artifact_names(report.get("artifacts", [])),
        "method_sections": sections,
    }
    return narrative


def _markdown_for_section(section: dict[str, Any], heading_level: int = 2) -> list[str]:
    heading = "#" * heading_level
    lines = [
        f"{heading} {section.get('method_label', 'Method')}",
        "",
        section.get("headline", ""),
        "",
        f"{heading}# Question",
        "",
        section.get("question", ""),
        "",
        f"{heading}# Design",
        "",
        section.get("design", ""),
        "",
        f"{heading}# Identification Assumptions",
        "",
    ]
    lines.extend([f"- {item}" for item in section.get("identification_assumptions", [])] or ["- None recorded."])
    key_estimate = section.get("key_estimate", {})
    lines.extend(
        [
            "",
            f"{heading}# Key Estimate",
            "",
            f"- label: {key_estimate.get('label', 'N/A')}",
            f"- value: {_fmt_number(key_estimate.get('value')) if not isinstance(key_estimate.get('value'), dict) else json.dumps(key_estimate.get('value'), ensure_ascii=False)}",
        ]
    )
    if key_estimate.get("p_value") is not None:
        lines.append(f"- p_value: {_fmt_number(key_estimate.get('p_value'))}")
    if key_estimate.get("confidence_interval") is not None:
        ci = key_estimate.get("confidence_interval")
        lines.append(f"- confidence_interval: {_fmt_number(ci[0])} to {_fmt_number(ci[1])}")
    lines.extend(
        [
            "",
            f"{heading}# Diagnostics",
            "",
        ]
    )
    lines.extend([f"- {item}" for item in section.get("diagnostics", [])] or ["- None recorded."])
    lines.extend(
        [
            "",
            f"{heading}# Business Interpretation",
            "",
        ]
    )
    lines.extend([f"- {item}" for item in section.get("business_interpretation", [])] or ["- None recorded."])
    lines.extend(
        [
            "",
            f"{heading}# Risks And Limits",
            "",
        ]
    )
    lines.extend([f"- {item}" for item in section.get("risks_and_limits", [])] or ["- No major method-specific risk was auto-flagged."])
    lines.extend(
        [
            "",
            f"{heading}# Recommendation",
            "",
            section.get("recommendation", ""),
        ]
    )
    if section.get("artifact_names"):
        lines.extend(
            [
                "",
                f"{heading}# Artifacts",
                "",
            ]
        )
        lines.extend([f"- {item}" for item in section.get("artifact_names", [])])
    return lines


def render_causal_narrative_markdown(narrative: dict[str, Any]) -> str:
    lines = [
        "# Causal Narrative Report",
        "",
        narrative.get("headline", ""),
        "",
        "## Executive Summary",
        "",
        f"- method: {narrative.get('method_label', 'N/A')}",
        f"- recommendation: {narrative.get('recommendation', 'N/A')}",
    ]
    if narrative.get("task") == "causal":
        lines.append(f"- methods_included: {', '.join(section['method_label'] for section in narrative.get('method_sections', []))}")
    lines.extend(["", "## Overview", "", narrative.get("question", ""), "", narrative.get("design", "")])
    lines.extend(["", "## Identification Assumptions", ""])
    lines.extend([f"- {item}" for item in narrative.get("identification_assumptions", [])] or ["- None recorded."])
    lines.extend(["", "## Diagnostics", ""])
    lines.extend([f"- {item}" for item in narrative.get("diagnostics", [])] or ["- None recorded."])
    lines.extend(["", "## Business Interpretation", ""])
    lines.extend([f"- {item}" for item in narrative.get("business_interpretation", [])] or ["- None recorded."])
    lines.extend(["", "## Risks And Limits", ""])
    lines.extend([f"- {item}" for item in narrative.get("risks_and_limits", [])] or ["- No major top-level risk was auto-flagged."])
    if narrative.get("task") == "causal":
        lines.extend(["", "## Method Sections", ""])
        for section in narrative.get("method_sections", []):
            lines.extend(_markdown_for_section(section, heading_level=3))
            lines.append("")
    else:
        lines.extend(["", "## Detail", ""])
        lines.extend(_markdown_for_section(narrative, heading_level=3))
    return "\n".join(lines).rstrip() + "\n"


def write_causal_narrative(output_dir: Path, narrative: dict[str, Any]) -> dict[str, str]:
    json_path = output_dir / "causal_narrative_report.json"
    markdown_path = output_dir / "causal_narrative_report.md"
    write_json(json_path, narrative)
    write_markdown(markdown_path, render_causal_narrative_markdown(narrative))
    return {"json_path": str(json_path), "markdown_path": str(markdown_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a narrative causal report from an existing causal_report.json payload.")
    parser.add_argument("--report-path", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--config-json")
    args = parser.parse_args()

    report = json.loads(Path(args.report_path).read_text())
    config = parse_json_arg(args.config_json)
    narrative = build_causal_narrative(report, config=config)
    if args.output_dir:
        write_causal_narrative(Path(args.output_dir), narrative)
    print(json.dumps(narrative, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
