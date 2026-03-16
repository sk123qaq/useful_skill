#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from common import configure_matplotlib_defaults, friendly_chart_target_label, module_available, write_json


def select_chart_plan(df, task: str, target: str | None = None, time_col: str | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    numeric_columns = list(df.select_dtypes(include=["number", "bool"]).columns)
    chart_plan = []
    if time_col and time_col in df.columns and target and target in df.columns:
        chart_plan.append({"chart": "line", "x": time_col, "y": target, "reason": "Show trend, seasonality, and anomalies over time."})
    if target and target in numeric_columns:
        chart_plan.append({"chart": "histogram", "x": target, "reason": "Show target distribution and skew."})
    if len(numeric_columns) >= 2:
        chart_plan.append({"chart": "correlation_heatmap", "columns": numeric_columns[:10], "reason": "Summarize linear relationships across numeric variables."})
    if task in {"classification", "regression"} and target:
        chart_plan.append({"chart": "feature_importance", "reason": "Show the most influential features for the selected supervised model."})
        chart_plan.append({"chart": "partial_dependence", "reason": "Show directional response for the most important features."})
    if task == "funnel":
        chart_plan.append({"chart": "horizontal_bar", "reason": "Show ordered step counts and drop-offs."})
    if task == "retention":
        chart_plan.append({"chart": "retention_curve", "reason": "Show active user retention by day or period offset."})
    if task == "cohort":
        chart_plan.append({"chart": "cohort_heatmap", "reason": "Show retention by acquisition cohort and elapsed period."})
    if task == "ltv":
        chart_plan.append({"chart": "cohort_ltv_bar", "reason": "Compare cohort-level lifetime value or revenue per user."})
    if task in {"cluster", "clustering"}:
        chart_plan.append({"chart": "cluster_size_bar", "reason": "Show the size of each discovered cluster."})
        chart_plan.append({"chart": "cluster_projection", "reason": "Show a 2D projection of cluster separation."})
    if task in {"apriori", "association", "association-rules"}:
        chart_plan.append({"chart": "association_rule_bar", "reason": "Show top association rules ranked by lift."})
    if task == "anova":
        chart_plan.append({"chart": "boxplot", "reason": "Compare the target distribution across groups."})
    if task in {"root-cause", "root_cause"}:
        chart_plan.append({"chart": "driver_bar", "reason": "Show the segments with the largest contribution to the KPI delta."})
    if task in {"did", "difference-in-differences", "difference_in_differences"}:
        chart_plan.append({"chart": "did_trend", "reason": "Show pre/post outcome movement for treatment and control."})
    if task in {"rd", "regression-discontinuity", "regression_discontinuity", "rdd"}:
        chart_plan.append({"chart": "rd_scatter", "reason": "Show the local jump around the running-variable cutoff."})
        chart_plan.append({"chart": "rd_binned_means", "reason": "Show binned means around the cutoff."})
    if task in {"synthetic-control", "synthetic_control", "synth-control", "synthetic"}:
        chart_plan.append({"chart": "synthetic_path", "reason": "Show treated and synthetic trajectories over time."})
        chart_plan.append({"chart": "synthetic_gap", "reason": "Show the treated-minus-synthetic gap over time."})
    if task in {"iv", "instrumental-variables", "instrumental_variables"}:
        chart_plan.append({"chart": "iv_first_stage", "reason": "Show the first-stage relationship between instrument and treatment."})
        chart_plan.append({"chart": "iv_reduced_form", "reason": "Show reduced-form movement in the outcome by instrument."})
    if task in {"dml", "double-machine-learning", "double_machine_learning"}:
        chart_plan.append({"chart": "dml_residual_fit", "reason": "Show the residual-on-residual orthogonal regression fit."})
        chart_plan.append({"chart": "dml_score_distribution", "reason": "Show the distribution of DML orthogonal scores."})
    if task in {"dr", "doubly-robust", "doubly_robust"}:
        chart_plan.append({"chart": "propensity_overlap", "reason": "Show overlap for the doubly robust nuisance propensity model."})
        chart_plan.append({"chart": "dr_score_distribution", "reason": "Show the distribution of doubly robust scores."})
    if task in {"psm", "propensity-score-matching", "propensity_score_matching"}:
        chart_plan.append({"chart": "propensity_overlap", "reason": "Show common-support overlap between treatment and control."})
        chart_plan.append({"chart": "balance_smd", "reason": "Show covariate balance before and after matching."})
    if task in {"orthogonal", "orthogonal-learner", "orthogonal_learner"}:
        chart_plan.append({"chart": "orthogonal_effect_distribution", "reason": "Show the fitted orthogonal-learner effect distribution."})
        chart_plan.append({"chart": "orthogonal_pseudo_outcome", "reason": "Show the pseudo-outcome distribution used by the orthogonal learner."})
    if task in {"uplift", "heterogeneity"}:
        chart_plan.append({"chart": "uplift_distribution", "reason": "Show the distribution of predicted treatment effects."})
        chart_plan.append({"chart": "uplift_bucket_lift", "reason": "Show observed lift by uplift-ranked bucket."})
    if task in {"cate", "meta-learner", "meta_learner"}:
        chart_plan.append({"chart": "cate_distribution", "reason": "Show predicted treatment-effect distributions by meta-learner."})
        chart_plan.append({"chart": "cate_method_scatter", "reason": "Show agreement between meta-learner CATE estimates."})
    if task == "causal":
        chart_plan.append({"chart": "causal_method_bundle", "reason": "Show the method-specific artifacts for DID, RD, synthetic control, IV, DML, DR, PSM, orthogonal learners, uplift, and CATE."})
    if task in {"experiment", "ab-test"} and config:
        group_col = config.get("group_col")
        metrics = config.get("metrics", [])
        primary_metric = None
        for metric in metrics:
            if isinstance(metric, dict) and metric.get("role") == "primary":
                primary_metric = metric.get("name")
                break
        if primary_metric is None and metrics:
            first_metric = metrics[0]
            primary_metric = first_metric.get("name") if isinstance(first_metric, dict) else first_metric
        if group_col and primary_metric:
            chart_plan.append({"chart": "variant_comparison_bar", "x": group_col, "y": primary_metric, "reason": "Compare the primary metric between control and treatment."})
    return {"task": task, "charts": chart_plan}


def _configure_chinese_font():
    preferred_fonts = [
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "PingFang SC",
        "Hiragino Sans GB",
        "Songti SC",
        "Microsoft YaHei",
        "SimHei",
        "Arial Unicode MS",
    ]
    return configure_matplotlib_defaults(preferred_fonts)


def save_basic_charts(df, output_dir: Path, task: str, target: str | None = None, time_col: str | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = select_chart_plan(df, task=task, target=target, time_col=time_col, config=config)
    if not module_available("matplotlib"):
        chart_plan_path = output_dir / "chart_plan.json"
        write_json(chart_plan_path, {"rendered": False, **plan})
        return {"rendered": False, "chart_plan_path": str(chart_plan_path)}

    import matplotlib.pyplot as plt  # type: ignore

    font_name = _configure_chinese_font()
    artifacts: list[str] = []

    if time_col and target and time_col in df.columns and target in df.columns:
        frame = df.sort_values(time_col)
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(frame[time_col], frame[target])
        ax.set_title(f"{target} over time")
        ax.set_xlabel(time_col)
        ax.set_ylabel(target)
        path = output_dir / "time_series.png"
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        artifacts.append(str(path))

    if target and target in df.columns:
        fig, ax = plt.subplots(figsize=(8, 5))
        target_label = friendly_chart_target_label(target)
        target_series = df[target].dropna()
        unique_values = sorted(target_series.unique().tolist()) if hasattr(target_series, "unique") else []
        if set(unique_values).issubset({0, 1}) and len(unique_values) <= 2:
            counts = target_series.astype(int).value_counts().sort_index()
            x_positions = [0, 1]
            y_values = [int(counts.get(0, 0)), int(counts.get(1, 0))]
            ax.bar(x_positions, y_values, color=["#8FB9A8", "#D67C6D"])
            ax.set_xticks(x_positions)
            ax.set_xticklabels(["否", "是"])
            ax.set_title(f"{target_label}分布")
        else:
            target_series.hist(ax=ax, bins=30)
            ax.set_title(f"{target_label}分布")
        ax.set_xlabel(target_label)
        ax.set_ylabel("样本量")
        path = output_dir / "target_distribution.png"
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        artifacts.append(str(path))

    if task == "retention" and config:
        from business_templates import retention_summary

        user_col = config.get("user_col")
        date_col = config.get("date_col")
        if user_col and date_col and user_col in df.columns and date_col in df.columns:
            report = retention_summary(df, user_col=user_col, date_col=date_col, periods=config.get("periods"), acquisition_col=config.get("acquisition_col"))
            series = report.get("active_users_by_day_offset", {})
            if series:
                fig, ax = plt.subplots(figsize=(8, 5))
                x_values = list(series.keys())
                y_values = list(series.values())
                ax.plot(x_values, y_values, marker="o")
                ax.set_title("Retention curve")
                ax.set_xlabel("Day offset")
                ax.set_ylabel("Active users")
                path = output_dir / "retention_curve.png"
                fig.tight_layout()
                fig.savefig(path, dpi=150)
                plt.close(fig)
                artifacts.append(str(path))

    if task == "ltv" and config:
        from business_templates import ltv_summary

        required = {"user_col", "revenue_col", "date_col"}
        if required.issubset(config):
            report = ltv_summary(
                df,
                user_col=config["user_col"],
                revenue_col=config["revenue_col"],
                date_col=config["date_col"],
                acquisition_col=config.get("acquisition_col"),
                cohort_freq=config.get("cohort_freq", "M"),
            )
            cohorts = report.get("cohorts", {})
            if cohorts:
                fig, ax = plt.subplots(figsize=(8, 5))
                cohort_names = list(cohorts.keys())
                ltv_values = [cohorts[name]["ltv"] for name in cohort_names]
                ax.bar(cohort_names, ltv_values)
                ax.set_title("Cohort LTV")
                ax.set_xlabel("Cohort")
                ax.set_ylabel("LTV")
                path = output_dir / "cohort_ltv.png"
                fig.tight_layout()
                fig.savefig(path, dpi=150)
                plt.close(fig)
                artifacts.append(str(path))

    if task == "cohort" and config:
        from business_templates import cohort_retention_matrix

        if "user_col" in config and "date_col" in config:
            report = cohort_retention_matrix(
                df,
                user_col=config["user_col"],
                date_col=config["date_col"],
                acquisition_col=config.get("acquisition_col"),
                cohort_freq=config.get("cohort_freq", "M"),
                max_periods=int(config.get("max_periods", 12)),
            )
            matrix = report.get("retention_matrix", {})
            if matrix:
                cohort_names = list(matrix.keys())
                period_labels = sorted({int(period) for cohort_values in matrix.values() for period in cohort_values.keys()})
                values = [[matrix[cohort].get(str(period), float("nan")) for period in period_labels] for cohort in cohort_names]
                fig, ax = plt.subplots(figsize=(8, 5))
                image = ax.imshow(values, aspect="auto", cmap="Blues")
                ax.set_title("Cohort retention heatmap")
                ax.set_xlabel("Period index")
                ax.set_ylabel("Cohort")
                ax.set_xticks(range(len(period_labels)))
                ax.set_xticklabels(period_labels)
                ax.set_yticks(range(len(cohort_names)))
                ax.set_yticklabels(cohort_names)
                fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
                path = output_dir / "cohort_heatmap.png"
                fig.tight_layout()
                fig.savefig(path, dpi=150)
                plt.close(fig)
                artifacts.append(str(path))

    if task in {"experiment", "ab-test"} and config:
        group_col = config.get("group_col")
        metrics = config.get("metrics", [])
        primary_metric = None
        for metric in metrics:
            if isinstance(metric, dict) and metric.get("role") == "primary":
                primary_metric = metric.get("name")
                break
        if primary_metric is None and metrics:
            first_metric = metrics[0]
            primary_metric = first_metric.get("name") if isinstance(first_metric, dict) else first_metric
        if group_col and primary_metric and group_col in df.columns and primary_metric in df.columns:
            fig, ax = plt.subplots(figsize=(7, 5))
            grouped = df.groupby(group_col)[primary_metric].mean().sort_index()
            grouped.plot(kind="bar", ax=ax)
            ax.set_title(f"{primary_metric} by {group_col}")
            ax.set_xlabel(group_col)
            ax.set_ylabel(primary_metric)
            path = output_dir / "experiment_primary_metric.png"
            fig.tight_layout()
            fig.savefig(path, dpi=150)
            plt.close(fig)
            artifacts.append(str(path))

    write_json(output_dir / "chart_plan.json", {"rendered": True, "font": font_name, **plan})
    return {"rendered": True, "font": font_name, "artifacts": artifacts}


def build_storyline(findings: list[str], risks: list[str], recommendations: list[str]) -> str:
    lines = ["## Context", "- Explain why the question matters.", "", "## Insight"]
    lines.extend(f"- {item}" for item in findings or ["No findings were generated."])
    lines.append("")
    lines.append("## Recommendation")
    lines.extend(f"- {item}" for item in recommendations or ["No recommendation generated yet."])
    lines.append("")
    lines.append("## Risk")
    lines.extend(f"- {item}" for item in risks or ["State data quality, causality, or generalization limits here."])
    return "\n".join(lines)
