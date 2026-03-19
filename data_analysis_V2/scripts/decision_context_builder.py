from __future__ import annotations

from pathlib import Path
from typing import Any

from data_analysis_V2.scripts.common import write_json, write_markdown
from data_analysis_V2.scripts.schemas import validate_judgment_context


def _missing_columns(scout_report: dict[str, Any]) -> list[tuple[str, float]]:
    return sorted(
        [(column, rate) for column, rate in scout_report["missingness"].items() if rate > 0],
        key=lambda item: item[1],
        reverse=True,
    )


def _soft_proxy_features(feature_risk_report: dict[str, Any]) -> list[str]:
    return [
        feature["feature"]
        for feature in feature_risk_report["features"]
        if feature["label"] == "soft_proxy"
    ]


def _candidate_features(scout_report: dict[str, Any], target: str | None) -> list[str]:
    return [column for column in scout_report["columns"] if column != target]


def build_scout_judgment_context(
    contract: dict[str, Any],
    scout_report: dict[str, Any],
    feature_risk_report: dict[str, Any],
    route_decision: dict[str, Any],
    column_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates = _candidate_features(scout_report, contract.get("target"))
    missing_columns = _missing_columns(scout_report)
    context = {
        "stage": "after_scout",
        "question": contract["question"],
        "task": contract["task"],
        "target": contract["target"],
        "dataset_overview": {
            "row_count": scout_report["row_count"],
            "column_count": scout_report["column_count"],
            "duplicate_rows": scout_report["duplicate_rows"],
            "duplicate_rate": scout_report["duplicate_rate"],
            "missing_columns": missing_columns,
            "target_distribution": scout_report["target_distribution"],
        },
        "feature_summary": {
            "candidate_feature_count": len(candidates),
            "candidate_features": candidates,
            "risk_counts": feature_risk_report["summary"]["label_counts"],
            "soft_proxy_features": _soft_proxy_features(feature_risk_report),
            "high_cardinality_fields": scout_report["high_cardinality_fields"],
            "suspicious_fields": scout_report["suspicious_fields"],
            "profile_flags": (column_profile or {}).get("summary", {}),
        },
        "route_summary": {
            "route": route_decision["route"],
            "reasons": route_decision["reasons"],
            "blockers": route_decision["blockers"],
        },
        "global_assessment": [
            f"Data profile: {scout_report['row_count']} rows and {scout_report['column_count']} columns.",
            (
                f"Missingness check: {len(missing_columns)} columns still have missing values."
                if missing_columns
                else "Missingness check: no columns with missing values."
            ),
            f"Duplicate check: {scout_report['duplicate_rows']} duplicate rows detected; no de-duplication has been applied yet.",
            (
                "Feature risk check: hard leakage not detected."
                if feature_risk_report["summary"]["label_counts"].get("hard_leakage", 0) == 0
                else "Feature risk check: hard leakage detected."
            ),
            f"Candidate features currently include all non-target columns ({len(candidates)} fields); no formal feature selection has been applied yet.",
            "Outlier treatment has not been applied yet; for this dataset the more relevant quality issue may be duplicate handling and category consistency.",
        ],
        "decision_prompt": (
            "Review the whole analysis so far, not only this step. Decide whether to continue to baseline, clean data first, or stop and report."
        ),
    }
    return validate_judgment_context(context)


def build_baseline_judgment_context(
    contract: dict[str, Any],
    scout_report: dict[str, Any],
    feature_risk_report: dict[str, Any],
    route_decision: dict[str, Any],
    baseline_results: dict[str, Any],
) -> dict[str, Any]:
    metric = baseline_results["primary_metric"]
    best_model = next(
        model for model in baseline_results["models"] if model["model_name"] == baseline_results["best_model_name"]
    )
    best_dummy = next(
        model for model in baseline_results["models"] if model["model_name"] == baseline_results["best_dummy_name"]
    )
    improvement = best_model["mean_metrics"][metric] - best_dummy["mean_metrics"][metric]
    context = {
        "stage": "after_baseline",
        "question": contract["question"],
        "task": contract["task"],
        "target": contract["target"],
        "dataset_overview": {
            "row_count": scout_report["row_count"],
            "column_count": scout_report["column_count"],
            "duplicate_rows": scout_report["duplicate_rows"],
            "duplicate_rate": scout_report["duplicate_rate"],
            "target_distribution": scout_report["target_distribution"],
        },
        "feature_summary": {
            "candidate_feature_count": len(_candidate_features(scout_report, contract.get("target"))),
            "risk_counts": feature_risk_report["summary"]["label_counts"],
            "soft_proxy_features": _soft_proxy_features(feature_risk_report),
        },
        "route_summary": {
            "route": route_decision["route"],
            "reasons": route_decision["reasons"],
            "blockers": route_decision["blockers"],
        },
        "model_summary": {
            "primary_metric": metric,
            "best_model_name": best_model["model_name"],
            "best_model_mean": best_model["mean_metrics"][metric],
            "best_model_std": best_model["std_metrics"][metric],
            "best_dummy_name": best_dummy["model_name"],
            "best_dummy_mean": best_dummy["mean_metrics"][metric],
            "absolute_improvement": improvement,
            "model_order": baseline_results["model_order"],
            "all_models": [
                {
                    "model_name": model["model_name"],
                    "family": model["family"],
                    "mean_metrics": model["mean_metrics"],
                    "std_metrics": model["std_metrics"],
                }
                for model in baseline_results["models"]
            ],
        },
        "global_assessment": [
            f"Baseline comparison: best model `{best_model['model_name']}` improved {metric} by {improvement:.4f} over `{best_dummy['model_name']}`.",
            f"Stability snapshot: best model `{metric}` std is {best_model['std_metrics'][metric]:.4f}.",
            f"Duplicate rows are still present ({scout_report['duplicate_rows']}); no de-duplication has been applied before modeling.",
            (
                "Soft proxy fields remain in the candidate set: " + ", ".join(_soft_proxy_features(feature_risk_report))
                if _soft_proxy_features(feature_risk_report)
                else "No soft proxy fields were flagged."
            ),
            "No hyperparameter tuning, threshold optimization, or additional feature selection has been applied yet.",
        ],
        "decision_prompt": (
            "Judge from the whole analysis so far. Decide whether to continue to report, request more modeling/tuning, or stop as not usable."
        ),
    }
    return validate_judgment_context(context)


def render_judgment_context_markdown(context: dict[str, Any]) -> str:
    dataset = context["dataset_overview"]
    feature_summary = context["feature_summary"]
    route_summary = context["route_summary"]
    lines = [
        f"# Agent Judgment Context: {context['stage']}",
        "",
        "## Business Question",
        "",
        context["question"] or "(not provided)",
        "",
        "## Current Route",
        "",
        f"- route: `{route_summary['route']}`",
        f"- task: `{context['task']}`",
        f"- target: `{context['target']}`",
        "",
        "## Data Analysis Findings",
        "",
        f"- rows: {dataset['row_count']}",
        f"- columns: {dataset['column_count']}",
        f"- duplicate_rows: {dataset.get('duplicate_rows', 0)}",
        f"- duplicate_rate: {dataset.get('duplicate_rate', 0)}",
        f"- target_distribution: {dataset.get('target_distribution')}",
        "",
        "## Feature Findings",
        "",
        f"- candidate_feature_count: {feature_summary['candidate_feature_count']}",
        f"- risk_counts: {feature_summary['risk_counts']}",
    ]
    if feature_summary.get("soft_proxy_features"):
        lines.append(f"- soft_proxy_features: {', '.join(feature_summary['soft_proxy_features'])}")
    if feature_summary.get("profile_flags"):
        lines.append(f"- profile_flags: {feature_summary['profile_flags']}")
    if feature_summary.get("high_cardinality_fields"):
        lines.append(f"- high_cardinality_fields: {', '.join(feature_summary['high_cardinality_fields'])}")
    if feature_summary.get("suspicious_fields"):
        lines.append(f"- suspicious_fields: {', '.join(feature_summary['suspicious_fields'])}")
    if context.get("model_summary"):
        model_summary = context["model_summary"]
        lines.extend(
            [
                "",
                "## Modeling Findings",
                "",
                f"- primary_metric: {model_summary['primary_metric']}",
                f"- best_model: {model_summary['best_model_name']} = {model_summary['best_model_mean']:.4f}",
                f"- best_dummy: {model_summary['best_dummy_name']} = {model_summary['best_dummy_mean']:.4f}",
                f"- absolute_improvement: {model_summary['absolute_improvement']:.4f}",
            ]
        )
    lines.extend(["", "## Global Assessment", ""])
    lines.extend([f"- {item}" for item in context["global_assessment"]])
    lines.extend(["", "## Agent Decision Prompt", "", context["decision_prompt"]])
    return "\n".join(lines) + "\n"


def write_judgment_context(run_dir: str | Path, artifact_base: str, context: dict[str, Any]) -> None:
    run_path = Path(run_dir)
    write_json(run_path / f"{artifact_base}.json", context)
    write_markdown(run_path / f"{artifact_base}.md", render_judgment_context_markdown(context))
