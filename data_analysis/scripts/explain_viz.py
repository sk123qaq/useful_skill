#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from typing import Any

from common import (
    REPORT_AUDIENCES,
    configure_matplotlib_defaults,
    friendly_field_label,
    friendly_chart_feature_label,
    friendly_chart_target_label,
    module_available,
    sanitize_feature_name,
    write_json,
)


def _zh_reason(text: str) -> str:
    replacements = {
        "Show trend, seasonality, and anomalies over time.": "展示时间变化、季节性和异常波动。",
        "Show target distribution and skew.": "展示目标分布及其偏斜程度。",
        "Summarize linear relationships across numeric variables.": "汇总数值变量之间的线性关系。",
        "Show the most influential features for the selected supervised model.": "展示所选监督模型最重要的影响变量。",
        "Show directional response for the most important features.": "展示重要变量变化时模型预测的方向性响应。",
        "Show ordered step counts and drop-offs.": "展示各步骤的数量与流失情况。",
        "Show active user retention by day or period offset.": "展示按天或周期偏移的留存走势。",
        "Show retention by acquisition cohort and elapsed period.": "展示按获客 cohort 和经过周期的留存情况。",
        "Compare cohort-level lifetime value or revenue per user.": "比较 cohort 维度的生命周期价值或人均收入。",
        "Show the size of each discovered cluster.": "展示每个发现的簇规模。",
        "Show a 2D projection of cluster separation.": "展示簇在二维投影中的分离情况。",
        "Show top association rules ranked by lift.": "展示按 lift 排序的高价值关联规则。",
        "Compare the target distribution across groups.": "比较不同组的目标分布。",
        "Show the segments with the largest contribution to the KPI delta.": "展示对 KPI 差异贡献最大的细分对象。",
        "Show pre/post outcome movement for treatment and control.": "展示处理组与对照组在前后期的变化。",
        "Show the local jump around the running-variable cutoff.": "展示运行变量断点附近的局部跳跃。",
        "Show binned means around the cutoff.": "展示断点附近的分箱均值。",
        "Show treated and synthetic trajectories over time.": "展示处理组与合成对照组的时间轨迹。",
        "Show the treated-minus-synthetic gap over time.": "展示处理组减去合成对照组后的差值轨迹。",
        "Show the first-stage relationship between instrument and treatment.": "展示工具变量与处理变量之间的一阶段关系。",
        "Show reduced-form movement in the outcome by instrument.": "展示工具变量对结果变量的简化形式变化。",
        "Show the residual-on-residual orthogonal regression fit.": "展示残差对残差的正交回归拟合。",
        "Show the distribution of DML orthogonal scores.": "展示 DML 正交得分的分布。",
        "Show overlap for the doubly robust nuisance propensity model.": "展示双重稳健模型中的倾向得分重叠情况。",
        "Show the distribution of doubly robust scores.": "展示双重稳健得分的分布。",
        "Show common-support overlap between treatment and control.": "展示处理组与对照组的共同支持区间。",
        "Show covariate balance before and after matching.": "展示匹配前后协变量平衡情况。",
        "Show the fitted orthogonal-learner effect distribution.": "展示正交学习器估计效应的分布。",
        "Show the pseudo-outcome distribution used by the orthogonal learner.": "展示正交学习器使用的伪结果分布。",
        "Show the distribution of predicted treatment effects.": "展示预测处理效应的分布。",
        "Show observed lift by uplift-ranked bucket.": "展示按 uplift 分桶后的实际提升。",
        "Show predicted treatment-effect distributions by meta-learner.": "展示元学习器预测的处理效应分布。",
        "Show agreement between meta-learner CATE estimates.": "展示不同元学习器 CATE 估计的一致性。",
        "Show the method-specific artifacts for DID, RD, synthetic control, IV, DML, DR, PSM, orthogonal learners, uplift, and CATE.": "展示 DID、RD、合成控制、IV、DML、DR、PSM、正交学习器、uplift 和 CATE 的方法级产物。",
        "Compare the primary metric between control and treatment.": "比较对照组与实验组的主指标表现。",
    }
    return replacements.get(text, text)


def select_chart_plan(df, task: str, target: str | None = None, time_col: str | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    numeric_columns = list(df.select_dtypes(include=["number", "bool"]).columns)
    chart_plan = []
    if time_col and time_col in df.columns and target and target in df.columns:
        chart_plan.append({"chart": "line", "x": time_col, "y": target, "reason": _zh_reason("Show trend, seasonality, and anomalies over time.")})
    if target and target in numeric_columns:
        chart_plan.append({"chart": "histogram", "x": target, "reason": _zh_reason("Show target distribution and skew.")})
    if len(numeric_columns) >= 2:
        chart_plan.append({"chart": "correlation_heatmap", "columns": numeric_columns[:10], "reason": _zh_reason("Summarize linear relationships across numeric variables.")})
    if task in {"classification", "regression"} and target:
        chart_plan.append({"chart": "feature_importance", "reason": _zh_reason("Show the most influential features for the selected supervised model.")})
        chart_plan.append({"chart": "partial_dependence", "reason": _zh_reason("Show directional response for the most important features.")})
    if task == "funnel":
        chart_plan.append({"chart": "horizontal_bar", "reason": _zh_reason("Show ordered step counts and drop-offs.")})
    if task == "retention":
        chart_plan.append({"chart": "retention_curve", "reason": _zh_reason("Show active user retention by day or period offset.")})
    if task == "cohort":
        chart_plan.append({"chart": "cohort_heatmap", "reason": _zh_reason("Show retention by acquisition cohort and elapsed period.")})
    if task == "ltv":
        chart_plan.append({"chart": "cohort_ltv_bar", "reason": _zh_reason("Compare cohort-level lifetime value or revenue per user.")})
    if task in {"cluster", "clustering"}:
        chart_plan.append({"chart": "cluster_size_bar", "reason": _zh_reason("Show the size of each discovered cluster.")})
        chart_plan.append({"chart": "cluster_projection", "reason": _zh_reason("Show a 2D projection of cluster separation.")})
    if task in {"apriori", "association", "association-rules"}:
        chart_plan.append({"chart": "association_rule_bar", "reason": _zh_reason("Show top association rules ranked by lift.")})
    if task == "anova":
        chart_plan.append({"chart": "boxplot", "reason": _zh_reason("Compare the target distribution across groups.")})
    if task in {"root-cause", "root_cause"}:
        chart_plan.append({"chart": "driver_bar", "reason": _zh_reason("Show the segments with the largest contribution to the KPI delta.")})
    if task in {"did", "difference-in-differences", "difference_in_differences"}:
        chart_plan.append({"chart": "did_trend", "reason": _zh_reason("Show pre/post outcome movement for treatment and control.")})
    if task in {"rd", "regression-discontinuity", "regression_discontinuity", "rdd"}:
        chart_plan.append({"chart": "rd_scatter", "reason": _zh_reason("Show the local jump around the running-variable cutoff.")})
        chart_plan.append({"chart": "rd_binned_means", "reason": _zh_reason("Show binned means around the cutoff.")})
    if task in {"synthetic-control", "synthetic_control", "synth-control", "synthetic"}:
        chart_plan.append({"chart": "synthetic_path", "reason": _zh_reason("Show treated and synthetic trajectories over time.")})
        chart_plan.append({"chart": "synthetic_gap", "reason": _zh_reason("Show the treated-minus-synthetic gap over time.")})
    if task in {"iv", "instrumental-variables", "instrumental_variables"}:
        chart_plan.append({"chart": "iv_first_stage", "reason": _zh_reason("Show the first-stage relationship between instrument and treatment.")})
        chart_plan.append({"chart": "iv_reduced_form", "reason": _zh_reason("Show reduced-form movement in the outcome by instrument.")})
    if task in {"dml", "double-machine-learning", "double_machine_learning"}:
        chart_plan.append({"chart": "dml_residual_fit", "reason": _zh_reason("Show the residual-on-residual orthogonal regression fit.")})
        chart_plan.append({"chart": "dml_score_distribution", "reason": _zh_reason("Show the distribution of DML orthogonal scores.")})
    if task in {"dr", "doubly-robust", "doubly_robust"}:
        chart_plan.append({"chart": "propensity_overlap", "reason": _zh_reason("Show overlap for the doubly robust nuisance propensity model.")})
        chart_plan.append({"chart": "dr_score_distribution", "reason": _zh_reason("Show the distribution of doubly robust scores.")})
    if task in {"psm", "propensity-score-matching", "propensity_score_matching"}:
        chart_plan.append({"chart": "propensity_overlap", "reason": _zh_reason("Show common-support overlap between treatment and control.")})
        chart_plan.append({"chart": "balance_smd", "reason": _zh_reason("Show covariate balance before and after matching.")})
    if task in {"orthogonal", "orthogonal-learner", "orthogonal_learner"}:
        chart_plan.append({"chart": "orthogonal_effect_distribution", "reason": _zh_reason("Show the fitted orthogonal-learner effect distribution.")})
        chart_plan.append({"chart": "orthogonal_pseudo_outcome", "reason": _zh_reason("Show the pseudo-outcome distribution used by the orthogonal learner.")})
    if task in {"uplift", "heterogeneity"}:
        chart_plan.append({"chart": "uplift_distribution", "reason": _zh_reason("Show the distribution of predicted treatment effects.")})
        chart_plan.append({"chart": "uplift_bucket_lift", "reason": _zh_reason("Show observed lift by uplift-ranked bucket.")})
    if task in {"cate", "meta-learner", "meta_learner"}:
        chart_plan.append({"chart": "cate_distribution", "reason": _zh_reason("Show predicted treatment-effect distributions by meta-learner.")})
        chart_plan.append({"chart": "cate_method_scatter", "reason": _zh_reason("Show agreement between meta-learner CATE estimates.")})
    if task == "causal":
        chart_plan.append({"chart": "causal_method_bundle", "reason": _zh_reason("Show the method-specific artifacts for DID, RD, synthetic control, IV, DML, DR, PSM, orthogonal learners, uplift, and CATE.")})
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
            chart_plan.append({"chart": "variant_comparison_bar", "x": group_col, "y": primary_metric, "reason": _zh_reason("Compare the primary metric between control and treatment.")})
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


def _semantic_field_map(semantic_schema: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    fields = (semantic_schema or {}).get("fields", [])
    return {str(item.get("field_name")): item for item in fields if isinstance(item, dict) and item.get("field_name")}


def _lineage_map(feature_lineage: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    features = (feature_lineage or {}).get("features", [])
    return {str(item.get("feature_name")): item for item in features if isinstance(item, dict) and item.get("feature_name")}


def _candidate_audience_fit(section_role: str, diagnostic_only: bool) -> dict[str, str]:
    if diagnostic_only:
        return {"management": "low", "operator": "low", "analyst": "high"}
    if section_role in {"core_evidence", "decision_support"}:
        return {"management": "high", "operator": "high", "analyst": "medium"}
    if section_role in {"context", "risk_boundary"}:
        return {"management": "high", "operator": "medium", "analyst": "medium"}
    if section_role == "mechanism":
        return {"management": "medium", "operator": "medium", "analyst": "high"}
    return {audience: "medium" for audience in REPORT_AUDIENCES}


def _candidate_policy(chart_type: str, file_name: str | None = None) -> dict[str, Any]:
    if chart_type == "partial_dependence":
        return {"section_role": "mechanism", "diagnostic_only": True, "allow_in_formal_body": False, "business_value_score": 45, "suitability_score": 50}
    if chart_type == "feature_importance":
        return {"section_role": "mechanism", "diagnostic_only": False, "allow_in_formal_body": True, "business_value_score": 70, "suitability_score": 72}
    if chart_type in {"line", "retention_curve", "did_trend", "synthetic_path", "synthetic_gap"}:
        return {"section_role": "core_evidence", "diagnostic_only": False, "allow_in_formal_body": True, "business_value_score": 88, "suitability_score": 86}
    if chart_type in {"histogram"}:
        return {"section_role": "context", "diagnostic_only": False, "allow_in_formal_body": True, "business_value_score": 68, "suitability_score": 72}
    if chart_type in {"heatmap", "cohort_heatmap"}:
        return {"section_role": "core_evidence", "diagnostic_only": False, "allow_in_formal_body": True, "business_value_score": 82, "suitability_score": 80}
    if chart_type in {"correlation_heatmap", "scatter"}:
        return {"section_role": "diagnostic", "diagnostic_only": True, "allow_in_formal_body": False, "business_value_score": 40, "suitability_score": 45}
    if chart_type in {"bar", "horizontal_bar", "driver_bar", "cluster_size_bar", "uplift_bucket_lift", "association_rule_bar", "variant_comparison_bar"}:
        return {"section_role": "decision_support", "diagnostic_only": False, "allow_in_formal_body": True, "business_value_score": 84, "suitability_score": 82}
    if file_name == "target_distribution.png":
        return {"section_role": "context", "diagnostic_only": False, "allow_in_formal_body": True, "business_value_score": 70, "suitability_score": 74}
    return {"section_role": "diagnostic", "diagnostic_only": True, "allow_in_formal_body": False, "business_value_score": 35, "suitability_score": 40}


def _candidate_evidence_links(chart_type: str, file_name: str | None, target: str | None = None) -> list[str]:
    if file_name == "target_distribution.png":
        return [f"stats_report.json#summary_statistics.{target}" if target else "stats_report.json#summary_statistics"]
    if file_name == "shap_bar.png" or chart_type == "feature_importance":
        return ["explainability_report.json#shap.top_features", "model_report.json#models"]
    if chart_type == "partial_dependence":
        return ["explainability_report.json#partial_dependence_features"]
    if chart_type in {"line", "retention_curve"}:
        return ["chart_plan.json", "stats_report.json"]
    if chart_type in {"variant_comparison_bar"}:
        return ["experiment_report.json#metrics"]
    return ["chart_plan.json"]


def _candidate_source_fields(
    item: dict[str, Any],
    target: str | None,
    time_col: str | None,
    lineage_by_feature: dict[str, dict[str, Any]],
    semantic_fields: dict[str, dict[str, Any]],
    explainability_report: dict[str, Any] | None = None,
) -> list[str]:
    file_name = str(item.get("file") or "")
    chart_type = str(item.get("chart") or "chart")
    if file_name == "target_distribution.png" and target:
        return [target]
    if file_name == "time_series.png":
        return [field for field in [time_col, target] if field]
    if file_name.startswith("pdp_") and file_name.endswith(".png"):
        feature_name = sanitize_feature_name(file_name.removeprefix("pdp_").removesuffix(".png"))
        source_field = (lineage_by_feature.get(feature_name) or {}).get("source_field")
        return [str(source_field)] if source_field else [feature_name]
    if file_name == "shap_bar.png" and explainability_report:
        fields: list[str] = []
        shap_rows = ((explainability_report.get("shap") or {}).get("top_features") or [])[:5]
        for row in shap_rows:
            feature_name = sanitize_feature_name(row.get("feature"))
            source_field = (lineage_by_feature.get(feature_name) or {}).get("source_field")
            if source_field and source_field not in fields:
                fields.append(str(source_field))
        return fields
    for key in ("x", "y"):
        value = item.get(key)
        if value and str(value) in semantic_fields:
            return [str(value)]
    return []


def build_chart_candidates(
    chart_plan: dict[str, Any],
    *,
    target: str | None = None,
    time_col: str | None = None,
    semantic_schema: dict[str, Any] | None = None,
    feature_lineage: dict[str, Any] | None = None,
    explainability_report: dict[str, Any] | None = None,
    report_audience: str = "management",
) -> dict[str, Any]:
    semantic_fields = _semantic_field_map(semantic_schema)
    lineage_by_feature = _lineage_map(feature_lineage)
    chart_items = chart_plan.get("charts") or []
    candidates: list[dict[str, Any]] = []
    for index, item in enumerate(chart_items, start=1):
        if not isinstance(item, dict):
            continue
        chart_type = str(item.get("chart") or "chart")
        file_name = item.get("file")
        source_fields = _candidate_source_fields(
            item,
            target=target,
            time_col=time_col,
            lineage_by_feature=lineage_by_feature,
            semantic_fields=semantic_fields,
            explainability_report=explainability_report,
        )
        derived_features: list[str] = []
        if file_name and str(file_name).startswith("pdp_"):
            derived_features.append(sanitize_feature_name(str(file_name).removeprefix("pdp_").removesuffix(".png")))
        policy = _candidate_policy(chart_type, file_name=str(file_name) if file_name else None)
        audience_fit = _candidate_audience_fit(policy["section_role"], bool(policy["diagnostic_only"]))
        if report_audience in audience_fit and audience_fit[report_audience] == "low":
            policy["suitability_score"] = max(int(policy["suitability_score"]) - 10, 0)
        source_labels = [friendly_field_label(field) for field in source_fields if field]
        candidates.append(
            {
                "chart_id": f"{index:02d}_{sanitize_feature_name(file_name or chart_type)}",
                "file": file_name,
                "title": item.get("title") or file_name or chart_type,
                "chart_type": chart_type,
                "chart_intent": policy["section_role"],
                "section_role": policy["section_role"],
                "source_fields": source_fields,
                "source_field_labels": source_labels,
                "derived_features": derived_features,
                "audience_fit": audience_fit,
                "diagnostic_only": bool(policy["diagnostic_only"]),
                "allow_in_formal_body": bool(policy["allow_in_formal_body"]),
                "report_audience": report_audience,
                "evidence_links": _candidate_evidence_links(chart_type, str(file_name) if file_name else None, target=target),
                "business_value_score": int(policy["business_value_score"]),
                "suitability_score": int(policy["suitability_score"]),
                "how_to_read": item.get("how_to_read"),
                "meaning": item.get("meaning") or item.get("reason"),
                "rendered": bool(file_name),
            }
        )
    return {
        "version": 1,
        "task": chart_plan.get("task"),
        "report_audience": report_audience,
        "rendered": bool(chart_plan.get("rendered", False)),
        "candidates": candidates,
    }


def _chart_entry_for_file(file_name: str, task: str, target: str | None = None, time_col: str | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    if file_name == "time_series.png":
        return {
            "file": file_name,
            "chart": "line",
            "title": "时间趋势图",
            "how_to_read": "先看整体趋势方向，再看拐点、波动和异常。",
            "meaning": "帮助识别目标变量在时间维度上的变化节奏与异常波动。",
        }
    if file_name == "target_distribution.png":
        label = friendly_chart_target_label(target)
        return {
            "file": file_name,
            "chart": "histogram",
            "title": f"{label}分布图",
            "how_to_read": "先看正负样本或各取值是否失衡，再看分布是否偏斜。",
            "meaning": "帮助判断目标变量的分布形态，以及后续模型是否需要重点关注类别不平衡。",
        }
    if file_name == "shap_bar.png":
        return {
            "file": file_name,
            "chart": "feature_importance",
            "title": "SHAP 特征重要性图",
            "how_to_read": "条形越长，表示该变量对模型预测的平均影响越强。",
            "meaning": "说明模型最依赖哪些变量，但不代表这些变量具有因果作用。",
        }
    if file_name.startswith("pdp_") and file_name.endswith(".png"):
        feature_name = file_name.removeprefix("pdp_").removesuffix(".png")
        return {
            "file": file_name,
            "chart": "partial_dependence",
            "title": f"{friendly_chart_feature_label(feature_name)}部分依赖图",
            "how_to_read": "观察特征变化时模型预测均值如何变化，以及变化是否平缓或突然。",
            "meaning": f"帮助理解 {friendly_chart_feature_label(feature_name)} 在模型中的边际影响。",
        }
    if file_name == "experiment_primary_metric.png":
        return {
            "file": file_name,
            "chart": "bar",
            "title": "实验主指标对比图",
            "how_to_read": "比较对照组和实验组在主指标上的平均值差异。",
            "meaning": "帮助判断实验组是否在核心指标上形成了可见提升。",
        }
    if file_name == "cohort_heatmap.png":
        return {
            "file": file_name,
            "chart": "heatmap",
            "title": "留存热力图",
            "how_to_read": "先看每一行 cohort 的衰减速度，再看不同 cohort 之间的差异。",
            "meaning": "帮助判断不同 cohort 的留存质量与衰减节奏。",
        }
    if file_name == "cohort_ltv.png":
        return {
            "file": file_name,
            "chart": "bar",
            "title": "Cohort LTV 对比图",
            "how_to_read": "比较不同 cohort 的生命周期价值高低。",
            "meaning": "帮助识别哪些 cohort 的长期价值更高。",
        }
    if file_name == "retention_curve.png":
        return {
            "file": file_name,
            "chart": "line",
            "title": "留存曲线图",
            "how_to_read": "看留存随时间的衰减斜率和拐点。",
            "meaning": "帮助理解用户留存的持续性和流失节奏。",
        }
    if file_name == "correlation_heatmap.png":
        return {
            "file": file_name,
            "chart": "heatmap",
            "title": "相关性热力图",
            "how_to_read": "先看颜色最深的格子，再看变量之间是否存在明显同向或反向关系。",
            "meaning": "帮助快速识别数值变量之间的线性关系。",
        }
    title = file_name.replace("_", " ").replace(".png", "")
    return {
        "file": file_name,
        "chart": "chart",
        "title": title,
        "how_to_read": "先看整体结构，再结合对应指标理解差异来源。",
        "meaning": "帮助补充展示本次分析产物。",
    }


def _render_chart_plan(output_dir: Path, plan: dict[str, Any], target: str | None = None, time_col: str | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    png_files = sorted(path.name for path in output_dir.glob("*.png"))
    rendered_charts = []
    for file_name in png_files:
        rendered_charts.append(_chart_entry_for_file(file_name, task=plan.get("task", "analysis"), target=target, time_col=time_col, config=config))
    return {
        "rendered": True,
        "task": plan.get("task"),
        "charts": rendered_charts,
        "planned_charts": plan.get("charts", []),
        "artifacts": png_files,
    }


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

    write_json(output_dir / "chart_plan.json", {"rendered": True, "font": font_name, **_render_chart_plan(output_dir, plan, target=target, time_col=time_col, config=config)})
    return {"rendered": True, "font": font_name, "artifacts": artifacts}


def build_storyline(findings: list[str], risks: list[str], recommendations: list[str]) -> str:
    lines = ["## 背景", "- 说明这次分析要回答什么问题，以及为什么它重要。", "", "## 发现"]
    lines.extend(f"- {item}" for item in findings or ["当前没有生成可用发现。"])
    lines.append("")
    lines.append("## 建议")
    lines.extend(f"- {item}" for item in recommendations or ["当前还没有生成可执行建议。"])
    lines.append("")
    lines.append("## 风险")
    lines.extend(f"- {item}" for item in risks or ["请说明数据质量、因果识别或泛化范围上的限制。"])
    return "\n".join(lines)
