#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from analysis_methods import normalize_task as normalize_analysis_task
from analysis_methods import run_analysis_method
from business_templates import build_business_report
from causal_analysis import normalize_task as normalize_causal_task
from causal_analysis import run_causal_analysis
from causal_narrative import build_causal_narrative, write_causal_narrative
from clean_preprocess import build_cleaning_report
from common import (
    availability_report,
    ensure_modules,
    ensure_output_dir,
    friendly_chart_feature_label,
    friendly_chart_target_label,
    parse_json_arg,
    write_json,
    write_markdown,
)
from db_connectors import connection_plan, explain_driver_risks, read_sql_query
from eda_stats import build_eda_report
from experiment_analysis import analyze_experiment
from explain_viz import build_storyline, save_basic_charts, select_chart_plan
from feature_engineering import build_feature_plan
from full_process_report_export import export_process_report
from io_router import build_file_read_plan, load_dataframe
from model_explainability import explain_supervised_model
from model_runner import best_model_name_from_report, run_baseline_model, select_model_candidates
from report_export import export_dashboard
from report_index import export_run_index, infer_outputs_root
from source_research_adapter import execute_web_search_request


MODEL_NAME_LABELS = {
    "hist_gradient_boosting_classifier": "直方梯度提升分类模型",
    "random_forest_classifier": "随机森林分类模型",
    "xgboost_classifier": "XGBoost 分类模型",
    "lightgbm_classifier": "LightGBM 分类模型",
    "hist_gradient_boosting_regressor": "直方梯度提升回归模型",
    "random_forest_regressor": "随机森林回归模型",
    "xgboost_regressor": "XGBoost 回归模型",
    "lightgbm_regressor": "LightGBM 回归模型",
}

MODEL_REASON_TEMPLATES = {
    "hist_gradient_boosting_classifier": "对高维稀疏特征有较强适应性，通常在效果与训练速度之间更平衡。",
    "random_forest_classifier": "作为稳健基线模型，便于和其他集成模型做横向对比，能快速发现过拟合迹象。",
    "xgboost_classifier": "在非线性关系和特征交互较强时常有提升，适合验证是否存在可观的性能增益。",
    "lightgbm_classifier": "在大样本场景训练效率高，适合与 XGBoost 对比验证树模型上限。",
    "hist_gradient_boosting_regressor": "对大样本回归任务收敛较快，适合做回归基线与稳定性参照。",
    "random_forest_regressor": "对异常值和非线性关系较稳健，可用于检查误差分布是否受局部样本影响。",
    "xgboost_regressor": "在复杂非线性回归中通常具备更强拟合能力，适合验证是否能显著降低误差。",
    "lightgbm_regressor": "在大样本回归中训练效率较高，便于快速迭代参数并与 XGBoost 做对比。",
}

WARNING_TRANSLATIONS = {
    "Input path does not exist.": "输入路径不存在。",
    "Supported formats: csv, tsv, xlsx, xlsm, xls, xlsb, parquet, feather, json, jsonl.": "支持格式：csv、tsv、xlsx、xlsm、xls、xlsb、parquet、feather、json、jsonl。",
    "Excel is fragile for large datasets. Consider converting to CSV or Parquet first.": "Excel 处理大数据较脆弱，建议先转为 CSV 或 Parquet。",
    "A worksheet cannot exceed 1,048,576 rows.": "单个工作表不能超过 1,048,576 行。",
    "Archive inputs are read from the selected member only; inspect other members if joins are expected.": "压缩包输入只读取当前选中的成员文件；如果预期需要联表，请检查其他成员文件。",
    "Compressed input detected via": "检测到压缩输入，行数只能基于压缩后的字节大小估计。",
    "Multiple supported files detected. Auto-selected": "检测到多个可用文件，已自动选择",
    "Directory input auto-selected": "目录输入已自动选择",
    "No input source provided.": "未提供输入数据源。",
}

FEATURE_RECOMMENDATION_TRANSLATIONS = {
    "One-hot encode low-cardinality categoricals. Review high-cardinality columns before modeling.": "对低基数类别变量做独热编码；高基数字段在建模前先审查。",
    "Consider scaling only for models sensitive to feature magnitude.": "仅在对特征量纲敏感的模型中考虑做缩放。",
    "Add calendar features and lag features for temporal tasks.": "时间序列任务可补充日历特征和滞后特征。",
    "Check leakage before creating rolling, cumulative, or target-derived features.": "在创建滚动、累计或由目标派生的特征前，先检查数据泄漏。",
}

ANALYSIS_TASK_LABELS = {
    "cluster": "聚类分析",
    "apriori": "关联规则分析",
    "anova": "方差分析",
    "root-cause": "根因分析",
}

CAUSAL_TASK_LABELS = {
    "did": "DID",
    "rd": "RD",
    "synthetic-control": "合成控制",
    "iv": "IV",
    "dml": "DML",
    "dr": "双重稳健",
    "psm": "PSM",
    "orthogonal": "正交学习器",
    "uplift": "uplift",
    "cate": "CATE",
    "causal": "因果方法套件",
}


def infer_task(task: str, target: str | None, time_col: str | None) -> str:
    if task != "auto":
        return task
    if time_col and target:
        return "time-series"
    if target:
        return "regression"
    return "descriptive"


def _log(message: str) -> None:
    print(f"[run_pipeline] {message}", flush=True)


def _write_run_status(run_dir: Path, stage: str, task: str, extra: dict[str, Any] | None = None) -> None:
    payload: dict[str, Any] = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "stage": stage,
        "task": task,
    }
    if extra:
        payload.update(extra)
    write_json(run_dir / "run_status.json", payload)


def _is_probable_classification_target(series: Any) -> bool:
    if series is None:
        return False
    if not hasattr(series, "dropna"):
        return False
    values = series.dropna()
    if hasattr(values, "empty") and values.empty:
        return False
    try:
        unique_count = int(values.nunique(dropna=True))
    except Exception:  # noqa: BLE001
        return False
    if unique_count <= 1:
        return False
    if unique_count == 2:
        return True

    sample = values.head(5000).tolist() if hasattr(values, "head") else list(values)[:5000]
    non_numeric_count = 0
    for item in sample:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            continue
        if isinstance(item, float):
            if item.is_integer():
                continue
            non_numeric_count += 1
            continue
        text = str(item).strip()
        try:
            numeric_value = float(text)
            if numeric_value.is_integer():
                continue
            non_numeric_count += 1
        except Exception:  # noqa: BLE001
            non_numeric_count += 1

    if non_numeric_count > 0 and unique_count <= 100:
        return True
    if non_numeric_count == 0 and unique_count <= 20:
        return True
    return False


def _refine_auto_task(task: str, requested_task: str, df: Any, target: str | None) -> str:
    if requested_task != "auto":
        return task
    if task != "regression":
        return task
    if not target or target not in getattr(df, "columns", []):
        return task
    try:
        if _is_probable_classification_target(df[target]):
            return "classification"
    except Exception:  # noqa: BLE001
        return task
    return task


def _friendly_model_name(name: str | None) -> str:
    if not name:
        return "N/A"
    return MODEL_NAME_LABELS.get(name, name.replace("_", " "))


def _localize_warning(text: str) -> str:
    translated = text
    for source, target in WARNING_TRANSLATIONS.items():
        if source in translated:
            translated = translated.replace(source, target)
    return translated


def _localize_feature_recommendation(text: str) -> str:
    return FEATURE_RECOMMENDATION_TRANSLATIONS.get(text, text)


def _localize_read_plan_for_summary(read_plan: dict[str, Any]) -> dict[str, Any]:
    localized = dict(read_plan)
    warnings = localized.get("warnings")
    if isinstance(warnings, list):
        localized["warnings"] = [_localize_warning(str(item)) for item in warnings]
    risks = localized.get("risks")
    if isinstance(risks, list):
        localized["risks"] = [_localize_warning(str(item)) for item in risks]
    return localized


def _load_dataset(args) -> tuple[Any | None, dict[str, Any], dict[str, Any]]:
    sample_rows = None if getattr(args, "use_full_data", False) else args.sample_rows
    if args.input_path:
        full_frame = load_dataframe(args.input_path, sample_rows=None)
        read_plan = build_file_read_plan(args.input_path)
        return _sample_frame(full_frame, read_plan, sample_rows)
    if args.db_url and args.query:
        frame = read_sql_query(args.db_url, args.query, limit=None)
        plan = connection_plan(args.db_url)
        plan["risks"] = explain_driver_risks(args.db_url)
        return _sample_frame(frame, plan, sample_rows)
    return None, {"note": "未提供输入数据源，流水线只能写入环境与任务规划产物。"}, {}


def _sample_frame(frame: Any, read_plan: dict[str, Any], sample_rows: int | None) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    population_rows = int(frame.shape[0]) if hasattr(frame, "shape") and frame.shape else 0
    requested_rows = int(sample_rows) if sample_rows and sample_rows > 0 else None
    sampling_report: dict[str, Any]
    if requested_rows and population_rows and requested_rows < population_rows:
        sampled_frame = frame.sample(n=requested_rows, random_state=42)
        sampling_report = {
            "strategy": "simple_random_sample",
            "sampled": True,
            "random_state": 42,
            "population_rows": population_rows,
            "sample_rows_requested": requested_rows,
            "sample_rows_used": int(sampled_frame.shape[0]),
            "sampling_fraction": round(float(sampled_frame.shape[0]) / float(population_rows), 6),
        }
        read_plan["sample_strategy"] = "simple_random_sample"
        read_plan["rows_total"] = population_rows
        read_plan["rows_used"] = int(sampled_frame.shape[0])
        return sampled_frame, read_plan, sampling_report

    sampling_report = {
        "strategy": "full_population",
        "sampled": False,
        "random_state": None,
        "population_rows": population_rows,
        "sample_rows_requested": requested_rows or population_rows,
        "sample_rows_used": population_rows,
        "sampling_fraction": 1.0,
    }
    read_plan["sample_strategy"] = "full_population"
    read_plan["rows_total"] = population_rows
    read_plan["rows_used"] = population_rows
    return frame, read_plan, sampling_report


def _write_summary(run_dir: Path, task: str, read_plan: dict[str, Any], findings: list[str], risks: list[str], recommendations: list[str]) -> None:
    content = [
        "# 数据分析运行摘要",
        "",
        f"- 任务类型：`{task}`",
        f"- 读取产物：`{run_dir / 'read_plan.json'}`",
        f"- 环境产物：`{run_dir / 'environment.json'}`",
        "",
        build_storyline(findings, risks, recommendations),
        "",
        "## 读取计划",
        f"```json\n{json.dumps(read_plan, ensure_ascii=False, indent=2)}\n```",
    ]
    write_markdown(run_dir / "run_summary.md", "\n".join(content))


def _write_sampling_report(run_dir: Path, sampling_report: dict[str, Any]) -> None:
    write_json(run_dir / "sampling_report.json", sampling_report)


def _estimate_model_runtime(rows: int, model_count: int, sampled: bool) -> str:
    if rows <= 0:
        return "约 5-10 分钟"
    if sampled and rows <= 10000:
        return "约 3-8 分钟"
    if rows <= 50000:
        return "约 8-20 分钟"
    if rows <= 150000:
        return "约 15-30 分钟"
    if rows <= 400000:
        return "约 20-45 分钟"
    return "约 30-60 分钟"


def _build_pre_model_recommendation_plan(
    task: str,
    candidate_models: list[str],
    rows_used: int,
    sampled: bool,
    target_rate: float | None,
) -> dict[str, Any]:
    recommendations: list[dict[str, str]] = []
    for name in candidate_models[:4]:
        recommendations.append(
            {
                "model": name,
                "model_label": _friendly_model_name(name),
                "reason": MODEL_REASON_TEMPLATES.get(name, "作为候选基线模型用于比较稳定性与泛化表现。"),
            }
        )

    focus: list[str] = []
    if task == "classification":
        focus.append("优先看 F1、召回率与 AUC，不只看准确率。")
        if target_rate is not None and (target_rate < 0.4 or target_rate > 0.6):
            focus.append("目标分布不完全平衡，需重点关注少数类召回率与误报成本。")
    elif task == "regression":
        focus.append("优先看 RMSE、MAE、R2，并结合残差分布判断稳定性。")
    if sampled:
        focus.append("当前为抽样结果，建议先做模型排序，再用全量数据复核前2名模型。")
    else:
        focus.append("当前为全量数据，可直接以交叉验证结果作为主要模型排序依据。")

    return {
        "task": task,
        "rows_used": rows_used,
        "candidate_models": candidate_models[:4],
        "recommended_models": recommendations,
        "comparison_focus": focus,
    }


def _write_pre_model_recommendation(run_dir: Path, plan: dict[str, Any]) -> None:
    write_json(run_dir / "pre_model_recommendation.json", plan)
    lines = [
        "# 建模前模型推荐",
        "",
        f"- 任务类型：`{plan.get('task', 'N/A')}`",
        f"- 数据规模：`{plan.get('rows_used', 0):,}` 行",
        "",
        "## 推荐模型与原因",
    ]
    for item in plan.get("recommended_models", []):
        lines.append(f"- `{item.get('model_label', item.get('model', 'N/A'))}`：{item.get('reason', '')}")
    lines.extend(["", "## 对比测试重点"])
    for point in plan.get("comparison_focus", []):
        lines.append(f"- {point}")
    write_markdown(run_dir / "pre_model_recommendation.md", "\n".join(lines))


def _enforce_pre_model_recommendation_gate(run_dir: Path, task: str, target: str | None, plan: dict[str, Any]) -> None:
    """
    Hard gate: before supervised modeling starts, recommendation content must exist
    and include model reasons.
    """
    if not target or task not in {"classification", "regression"}:
        write_json(
            run_dir / "pre_model_gate.json",
            {
                "passed": True,
                "applied": False,
                "reason": "当前任务不进入监督建模硬门禁。",
            },
        )
        return

    errors: list[str] = []
    recommended_models = plan.get("recommended_models")
    if not isinstance(recommended_models, list) or len(recommended_models) < 2:
        errors.append("recommended_models 至少需要 2 个候选模型，才能支持对比测试。")
    else:
        for idx, item in enumerate(recommended_models, start=1):
            if not isinstance(item, dict):
                errors.append(f"recommended_models[{idx}] 不是对象。")
                continue
            if not str(item.get("model_label", "")).strip():
                errors.append(f"recommended_models[{idx}] 缺少 model_label。")
            reason = str(item.get("reason", "")).strip()
            if len(reason) < 10:
                errors.append(f"recommended_models[{idx}] 的推荐原因过短。")

    payload = {
        "passed": len(errors) == 0,
        "applied": True,
        "task": task,
        "target": target,
        "errors": errors,
        "recommended_model_count": len(recommended_models) if isinstance(recommended_models, list) else 0,
    }
    write_json(run_dir / "pre_model_gate.json", payload)
    if errors:
        raise RuntimeError("Pre-model recommendation gate failed: " + " | ".join(errors))


def _build_pre_model_summary(
    task: str,
    df: Any,
    sampling_report: dict[str, Any],
    cleaning_report: dict[str, Any],
    eda_report: dict[str, Any],
    feature_plan: dict[str, Any],
    chart_plan: dict[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    shape = cleaning_report.get("shape", {})
    rows_used = int(shape.get("rows", getattr(df, "shape", [0])[0]))
    cols_used = int(shape.get("columns", getattr(df, "shape", [0, 0])[1]))
    target_rate = None
    target_summary = (eda_report.get("summary_statistics") or {}).get("obese")
    if isinstance(target_summary, dict) and target_summary.get("mean") is not None:
        target_rate = float(target_summary["mean"])
    candidate_models = select_model_candidates(task, is_time_series=False).get("models", []) if task in {"classification", "regression"} else []
    recommendation_plan = _build_pre_model_recommendation_plan(
        task=task,
        candidate_models=candidate_models,
        rows_used=rows_used,
        sampled=bool(sampling_report.get("sampled")),
        target_rate=target_rate,
    )
    recommendations = [item["model_label"] for item in recommendation_plan.get("recommended_models", [])]
    findings = [
        f"已完成数据读取、清洗、EDA、特征规划和基础图表，当前分析规模为 {rows_used} 行 × {cols_used} 列。",
    ]
    if sampling_report.get("sampled"):
        findings.append(
            f"当前采用简单随机抽样（simple random sample），从 {sampling_report.get('population_rows', rows_used):,} 行中随机抽取 {sampling_report.get('sample_rows_used', rows_used):,} 行，随机种子为 {sampling_report.get('random_state', 42)}。"
        )
    else:
        findings.append(f"当前采用全量数据，共 {sampling_report.get('population_rows', rows_used):,} 行。")
    if target_rate is not None:
        findings.append(f"目标发生率约为 {target_rate:.2%}，说明类别并不完全平衡，后续模型更适合看 F1 和召回率。")
    duplicate_rows = (cleaning_report.get("duplicates") or {}).get("duplicate_rows")
    missing_cells = (cleaning_report.get("missing_values") or {}).get("total_missing_cells")
    findings.append(f"缺失单元格 {missing_cells or 0} 个，重复行 {duplicate_rows or 0} 行。")

    if recommendations:
        recommendations_text = [f"建议优先比较：{'、'.join(recommendations)}。"]
        for item in recommendation_plan.get("recommended_models", []):
            recommendations_text.append(f"推荐理由 - {item['model_label']}：{item['reason']}")
    else:
        recommendations_text = ["建议先使用最轻量的基线模型做初筛，再决定是否上更重的集成模型。"]
    for point in recommendation_plan.get("comparison_focus", []):
        recommendations_text.append(f"对比重点：{point}")
    estimated = _estimate_model_runtime(rows_used, max(len(candidate_models), 1), bool(sampling_report.get("sampled")))
    recommendations_text.append(f"预计还需要约 {estimated} 才能完成模型比较、解释和正式报告导出。")
    recommendations_text.append("如果现在继续，请重新运行并加上 `--continue-after-checkpoint`；如果不继续，当前产物已经可以导出为预建模阶段报告。")

    risks = [
        "这一步还没有进入模型训练，因此当前结论只适合做下一步决策，不应直接当作最终模型结果。",
    ]
    if feature_plan.get("recommendations"):
        risks.append("特征工程建议已经生成，但是否采纳仍需结合模型结果复核。")
    if chart_plan.get("charts"):
        risks.append(f"当前基础图表已生成 {len(chart_plan.get('charts', []))} 个计划项，适合先做确认再决定是否继续建模。")
    return findings, risks, recommendations_text


def _build_chart_review(context: dict[str, Any]) -> dict[str, Any]:
    chart_plan = context.get("chart_plan") or {}
    explainability = context.get("explainability_report") or {}
    stats = context.get("stats_report") or {}
    sampling = context.get("sampling_report") or {}
    charts = []
    positive_rate = None
    target_summary = (stats.get("summary_statistics") or {}).get("obese")
    if isinstance(target_summary, dict) and target_summary.get("mean") is not None:
        positive_rate = float(target_summary["mean"])

    plan_charts = chart_plan.get("charts", []) if isinstance(chart_plan.get("charts", []), list) else []
    png_names = {item.get("file") for item in plan_charts if isinstance(item, dict) and item.get("file")}
    if "target_distribution.png" in png_names or positive_rate is not None:
        charts.append(
            {
                "index": len(charts) + 1,
                "file": "target_distribution.png",
                "title": f"{friendly_chart_target_label('obese')}分布图",
                "interpretation": f"样本中目标发生率约为 {positive_rate:.2%}，正负样本并不完全平衡，这意味着后续模型不能只看准确率。",
                "implication": "如果继续建模，应把召回率、F1 和类别不平衡一起放进判断标准。",
                "caption_note": "类别不平衡（正类占比）",
            }
        )

    shap_report = explainability.get("shap") or {}
    top_features = shap_report.get("top_features") or []
    if isinstance(top_features, list) and top_features and "shap_bar.png" in png_names:
        top_feature_names = "、".join(friendly_chart_feature_label(item.get("feature")) for item in top_features[:3] if item.get("feature"))
        charts.append(
            {
                "index": len(charts) + 1,
                "file": "shap_bar.png",
                "title": "SHAP 特征重要性图",
                "interpretation": f"SHAP 排名前几位的变量主要是 {top_feature_names}，说明模型主要依赖这些健康状态和行为变量来区分肥胖风险。",
                "implication": "这类结果更适合用来解释模型为什么这样判断，不应直接当作因果关系。",
                "caption_note": "SHAP（衡量变量对模型预测影响强弱的解释方法）",
            }
        )

    pdp_features = explainability.get("partial_dependence_features") or []
    for feature in pdp_features:
        file_name = f"pdp_{feature}.png"
        if file_name not in png_names:
            continue
        friendly_feature = friendly_chart_feature_label(feature)
        charts.append(
            {
                "index": len(charts) + 1,
                "file": file_name,
                "title": f"{friendly_feature}部分依赖图",
                "interpretation": f"这张图展示了 {friendly_feature} 变化时，模型预测的边际变化方向，适合和 SHAP 一起理解该变量的作用。",
                "implication": f"如果 {friendly_feature} 位于重要性靠前的位置，它更值得在后续解释里单独复核。",
                "caption_note": "PDP（部分依赖图，用来观察单个变量变化时模型预测如何变化）",
            }
        )

    if not charts and png_names:
        for file_name in sorted(png_names):
            charts.append(
                {
                    "index": len(charts) + 1,
                    "file": file_name,
                    "title": file_name.replace("_", " ").replace(".png", ""),
                    "interpretation": "该图展示了当前分析阶段已生成的可视化结果。",
                    "implication": "建议结合对应 JSON 结果一起阅读。",
                    "caption_note": "",
                }
            )

    overall = "这组图把目标分布、特征重要性和局部边际影响串起来看，可以先判断类别是否失衡，再判断模型主要依赖哪些变量，最后看这些变量在边际上的方向性变化。"
    if sampling.get("sampled"):
        overall = f"这组图基于简单随机抽样（simple random sample）生成，适合先做预览判断；抽样规模为 {sampling.get('sample_rows_used', 0):,} 行。 " + overall
    return {
        "generated_at": "auto",
        "status": "provided",
        "source": "contextual-auto-review",
        "overall_summary": overall,
        "charts": charts,
    }


def _write_chart_review(run_dir: Path, context: dict[str, Any]) -> dict[str, Any]:
    review = _build_chart_review(context)
    write_json(run_dir / "chart_review.json", review)
    return review


def _run_research_workflows(research_config: Any, run_dir: Path) -> dict[str, Any]:
    if not research_config:
        return {}
    requests = research_config if isinstance(research_config, list) else [research_config]
    reports = []
    for index, request_config in enumerate(requests, start=1):
        subdir = run_dir / ("research" if len(requests) == 1 else f"research-{index}")
        subdir.mkdir(parents=True, exist_ok=True)
        reports.append(execute_web_search_request(request_config, output_dir=subdir))
    aggregated = {
        "request_count": len(reports),
        "reports": reports,
        "record_count_total": sum(report["normalized_package"]["record_count_deduplicated"] for report in reports),
        "conflict_count_total": sum(len(report["normalized_package"]["conflicts"]) for report in reports),
    }
    write_json(run_dir / "research_report.json", aggregated)
    return aggregated


def _maybe_export_formal_report(run_dir: Path, enabled: bool, title: str | None) -> None:
    if not enabled:
        return
    ensure_modules(["docx", "reportlab"], "formal report export")
    from formal_report_export import export_formal_report

    export_formal_report(run_dir, title=title)


def _maybe_export_process_report(run_dir: Path, enabled: bool, title: str | None) -> None:
    if not enabled:
        return
    export_process_report(run_dir, title=title)


def _finish_run(
    run_dir: Path,
    formal_report: bool,
    report_title: str | None,
    process_report: bool,
    process_report_title: str | None,
) -> None:
    export_dashboard(run_dir)
    _maybe_export_process_report(run_dir, process_report, process_report_title)
    _maybe_export_formal_report(run_dir, formal_report, report_title)
    export_run_index(infer_outputs_root(run_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the data-analysis skill pipeline.")
    parser.add_argument("--dataset", choices=["wdi"])
    parser.add_argument("--input-path")
    parser.add_argument("--db-url")
    parser.add_argument("--query")
    parser.add_argument("--task", default="auto")
    parser.add_argument("--target")
    parser.add_argument("--time-col")
    parser.add_argument("--output-dir")
    parser.add_argument("--config-json")
    parser.add_argument("--sample-rows", type=int, default=5000)
    parser.add_argument("--use-full-data", action="store_true", help="Use the full input population without sampling.")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument(
        "--pre-model-checkpoint",
        action="store_true",
        help="Stop after read/clean/EDA/feature/basic chart generation and emit a checkpoint summary.",
    )
    parser.add_argument(
        "--continue-after-checkpoint",
        action="store_true",
        help="Continue from the pre-model checkpoint into full model training.",
    )
    parser.add_argument("--formal-report", action="store_true")
    parser.add_argument("--report-title")
    parser.add_argument(
        "--process-report",
        dest="process_report",
        action="store_true",
        help="Export a full process report (report_process.html).",
    )
    parser.add_argument(
        "--no-process-report",
        dest="process_report",
        action="store_false",
        help="Disable full process report export.",
    )
    parser.add_argument("--process-report-title")
    parser.set_defaults(process_report=True)
    args = parser.parse_args()

    config = parse_json_arg(args.config_json)

    if args.dataset == "wdi":
        if not args.input_path:
            parser.error("--dataset wdi requires --input-path pointing to WDI_csv.zip")
        from wdi_analysis_report import build_artifacts as build_wdi_artifacts

        outputs_root = Path(args.output_dir) if args.output_dir else (Path.cwd() / "outputs")
        run_dir = build_wdi_artifacts(Path(args.input_path), outputs_root)
        _finish_run(run_dir, args.formal_report, args.report_title, args.process_report, args.process_report_title)
        print(run_dir, flush=True)
        return 0

    run_dir = ensure_output_dir(args.output_dir, prefix="data-analysis")
    _log(f"Run directory: {run_dir}")
    environment = availability_report()
    write_json(run_dir / "environment.json", environment)
    research_config = config.get("research")

    task = infer_task(args.task, args.target, args.time_col)
    _write_run_status(
        run_dir,
        stage="initialized",
        task=task,
        extra={"requested_task": args.task, "target": args.target, "time_col": args.time_col},
    )

    if args.input_path:
        read_plan = build_file_read_plan(args.input_path)
    elif args.db_url:
        read_plan = connection_plan(args.db_url)
        read_plan["risks"] = explain_driver_risks(args.db_url)
    else:
        read_plan = {"note": "No input source provided."}
    write_json(run_dir / "read_plan.json", read_plan)

    if args.plan_only or (not args.input_path and not (args.db_url and args.query) and not research_config):
        chart_plan = {"task": task, "charts": []}
        write_json(run_dir / "chart_plan.json", chart_plan)
        _write_summary(
            run_dir,
            task,
            read_plan,
            findings=["已请求仅做规划运行，因此未加载数据集。"],
            risks=["后续执行仍依赖缺失依赖安装完成，并且需要提供数据源。"],
            recommendations=["可先根据已保存的读取计划准备运行环境，再进入分析。"],
        )
        _finish_run(run_dir, args.formal_report, args.report_title, args.process_report, args.process_report_title)
        _write_run_status(run_dir, stage="completed", task=task, extra={"mode": "plan-only"})
        print(run_dir, flush=True)
        return 0

    if not args.input_path and not (args.db_url and args.query) and research_config:
        chart_plan = {"task": task, "charts": []}
        write_json(run_dir / "chart_plan.json", chart_plan)
        research_report = _run_research_workflows(research_config, run_dir)
        _write_summary(
            run_dir,
            task,
            read_plan,
            findings=[
                f"已执行 {research_report['request_count']} 个外部研究请求。",
                f"已收集 {research_report['record_count_total']} 条去重后的来源候选。",
            ],
            risks=["外部研究输出带有启发式性质，在作为最终指标依据前需要复核。"],
            recommendations=["建议先查看 research_report.json 和 research_sources.md，再把外部基准与本地数据混合使用。"],
        )
        _finish_run(run_dir, args.formal_report, args.report_title, args.process_report, args.process_report_title)
        _write_run_status(run_dir, stage="completed", task=task, extra={"mode": "research-only"})
        print(run_dir, flush=True)
        return 0

    _write_run_status(run_dir, stage="loading-data", task=task)
    _log("Loading dataset...")
    df, read_artifact, sampling_report = _load_dataset(args)
    original_task = task
    task = _refine_auto_task(task, args.task, df, args.target)
    if task != original_task:
        _log(f"Auto task refined from `{original_task}` to `{task}` based on target distribution.")
    _write_run_status(
        run_dir,
        stage="data-loaded",
        task=task,
        extra={"rows": int(df.shape[0]), "columns": int(df.shape[1]), "sampled": bool(sampling_report.get("sampled"))},
    )
    write_json(run_dir / "read_plan.json", read_artifact)
    _write_sampling_report(run_dir, sampling_report)

    _log("Running cleaning / EDA / feature planning...")
    _write_run_status(run_dir, stage="eda-and-features", task=task)
    cleaning_report = build_cleaning_report(df, time_col=args.time_col, target=args.target)
    eda_report = build_eda_report(df, time_col=args.time_col, target=args.target)
    feature_plan = build_feature_plan(df, target=args.target, time_col=args.time_col)
    if isinstance(feature_plan.get("recommendations"), list):
        feature_plan["recommendations"] = [_localize_feature_recommendation(str(item)) for item in feature_plan["recommendations"]]
    chart_plan = select_chart_plan(df, task=task, target=args.target, time_col=args.time_col, config=config)
    write_json(run_dir / "cleaning_report.json", cleaning_report)
    write_json(run_dir / "stats_report.json", eda_report)
    write_json(run_dir / "feature_plan.json", feature_plan)
    write_json(run_dir / "chart_plan.json", chart_plan)

    viz_result = save_basic_charts(df, run_dir, task=task, target=args.target, time_col=args.time_col, config=config)
    rendered_chart_plan = chart_plan
    chart_plan_path = run_dir / "chart_plan.json"
    if chart_plan_path.exists():
        try:
            rendered_chart_plan = json.loads(chart_plan_path.read_text())
        except Exception:  # noqa: BLE001
            rendered_chart_plan = chart_plan

    _write_chart_review(
        run_dir,
        {
            "chart_plan": rendered_chart_plan,
            "explainability_report": {},
            "stats_report": eda_report,
            "sampling_report": sampling_report,
        },
    )

    rows_used_for_plan = int(getattr(df, "shape", [0])[0]) if hasattr(df, "shape") else 0
    target_rate_for_plan = None
    target_summary = (eda_report.get("summary_statistics") or {}).get("obese")
    if isinstance(target_summary, dict) and target_summary.get("mean") is not None:
        target_rate_for_plan = float(target_summary["mean"])
    pre_model_candidates = select_model_candidates(task, is_time_series=False).get("models", []) if task in {"classification", "regression"} else []
    pre_model_plan = _build_pre_model_recommendation_plan(
        task=task,
        candidate_models=pre_model_candidates,
        rows_used=rows_used_for_plan,
        sampled=bool(sampling_report.get("sampled")),
        target_rate=target_rate_for_plan,
    )
    _write_pre_model_recommendation(run_dir, pre_model_plan)
    if pre_model_plan.get("recommended_models"):
        labels = "、".join(item["model_label"] for item in pre_model_plan["recommended_models"])
        _log(f"Pre-model recommendation: {labels}")
        for item in pre_model_plan["recommended_models"]:
            _log(f"  - {item['model_label']}: {item['reason']}")

    if args.pre_model_checkpoint and not args.continue_after_checkpoint:
        checkpoint_findings, checkpoint_risks, checkpoint_recommendations = _build_pre_model_summary(
            task,
            df,
            sampling_report,
            cleaning_report,
            eda_report,
            feature_plan,
            rendered_chart_plan,
        )
        _write_summary(run_dir, task, _localize_read_plan_for_summary(read_artifact), checkpoint_findings, checkpoint_risks, checkpoint_recommendations)
        _finish_run(run_dir, args.formal_report, args.report_title, args.process_report, args.process_report_title)
        _write_run_status(run_dir, stage="completed", task=task, extra={"mode": "checkpoint"})
        print(run_dir, flush=True)
        return 0

    _enforce_pre_model_recommendation_gate(run_dir, task, args.target, pre_model_plan)
    _log("Running model training / evaluation...")
    _write_run_status(run_dir, stage="modeling", task=task)
    model_report: dict[str, Any] = {}
    explainability_report: dict[str, Any] = {}
    if args.target and task in {"classification", "regression"}:
        model_report = run_baseline_model(df, target=args.target, task=task, time_col=args.time_col)
        explainability_config = config.get("explainability", {})
        if explainability_config is not False:
            selected_model = explainability_config.get("model_name") if isinstance(explainability_config, dict) else None
            if not selected_model:
                selected_model = best_model_name_from_report(model_report, task=task)
            if selected_model:
                explainability_report = explain_supervised_model(
                    df,
                    target=args.target,
                    task=task,
                    output_dir=run_dir,
                    model_name=selected_model,
                    top_n=int(explainability_config.get("top_n", 10)) if isinstance(explainability_config, dict) else 10,
                )
                write_json(run_dir / "explainability_report.json", explainability_report)
    elif args.target and task == "time-series":
        model_report = select_model_candidates(task, is_time_series=bool(args.time_col))
    elif args.target and task not in {"funnel", "monetization", "retention", "cohort", "ltv", "experiment", "ab-test"}:
        model_report = select_model_candidates(task, is_time_series=bool(args.time_col))
    if model_report:
        write_json(run_dir / "model_report.json", model_report)

    business_report: dict[str, Any] = {}
    if task in {"funnel", "monetization", "retention", "cohort", "ltv"}:
        business_report = build_business_report(df, task=task, config=config)
        write_json(run_dir / "business_report.json", business_report)

    experiment_report: dict[str, Any] = {}
    if task in {"experiment", "ab-test"}:
        experiment_report = analyze_experiment(df, config)
        write_json(run_dir / "experiment_report.json", experiment_report)

    analysis_report: dict[str, Any] = {}
    if task in {"cluster", "clustering", "apriori", "association", "association-rules", "anova", "root-cause", "root_cause"}:
        analysis_report = run_analysis_method(df, task=task, config=config, output_dir=run_dir)
        write_json(run_dir / "analysis_report.json", analysis_report)

    causal_report: dict[str, Any] = {}
    causal_narrative: dict[str, Any] = {}
    research_report: dict[str, Any] = {}
    if task in {
        "did",
        "difference-in-differences",
        "difference_in_differences",
        "rd",
        "regression-discontinuity",
        "regression_discontinuity",
        "rdd",
        "synthetic-control",
        "synthetic_control",
        "synth-control",
        "synthetic",
        "iv",
        "instrumental-variables",
        "instrumental_variables",
        "dml",
        "double-machine-learning",
        "double_machine_learning",
        "dr",
        "doubly-robust",
        "doubly_robust",
        "psm",
        "propensity-score-matching",
        "propensity_score_matching",
        "orthogonal",
        "orthogonal-learner",
        "orthogonal_learner",
        "uplift",
        "heterogeneity",
        "cate",
        "meta-learner",
        "meta_learner",
        "causal",
    }:
        causal_report = run_causal_analysis(df, task=task, config=config, output_dir=run_dir)
        write_json(run_dir / "causal_report.json", causal_report)
        causal_narrative = build_causal_narrative(causal_report, config=config)
        write_causal_narrative(run_dir, causal_narrative)

    if research_config:
        research_report = _run_research_workflows(research_config, run_dir)

    _log("Rendering charts and writing summaries...")
    _write_run_status(run_dir, stage="summarizing", task=task)
    viz_result = save_basic_charts(df, run_dir, task=task, target=args.target, time_col=args.time_col, config=config)
    if chart_plan_path.exists():
        try:
            rendered_chart_plan = json.loads(chart_plan_path.read_text())
        except Exception:  # noqa: BLE001
            rendered_chart_plan = chart_plan

    findings = [
        f"已加载 {int(df.shape[0])} 行、{int(df.shape[1])} 列数据。",
        f"发现 {cleaning_report['missing_values']['columns_with_missing_values']} 个字段存在缺失值。",
    ]
    risks = [_localize_warning(item) for item in list(read_artifact.get("warnings", []))] if isinstance(read_artifact, dict) else []
    if not viz_result.get("rendered", False):
        risks.append("当前环境缺少 matplotlib，基础图表未能渲染。")
    recommendations = feature_plan.get("recommendations", [])[:3]
    if explainability_report:
        findings.append(f"已为模型 {_friendly_model_name(explainability_report['model_name'])} 生成解释性分析。")
        if explainability_report.get("permutation_importance"):
            top_feature = explainability_report["permutation_importance"][0]["feature"]
            findings.append(f"置换重要性最高的特征为 {friendly_chart_feature_label(top_feature)}。")
        recommendations.append("建议在解释模型行为前，先核对特征重要性、PDP 和 SHAP 产物。")
    if task in {"funnel", "monetization", "retention", "cohort", "ltv"} and business_report:
        recommendations.append("建议结合业务分析报告中的 KPI 结果再做解释。")
    if task in {"experiment", "ab-test"} and experiment_report:
        findings.append(f"实验决策状态：{experiment_report['decision']['status']}。")
        recommendations.append("建议检查实验报告中的 SRM、提升幅度、p 值和护栏指标。")
        if experiment_report["sample_ratio_mismatch"]["is_mismatch"]:
            risks.append("检测到样本比例失衡，实验结果可能无效。")
        if experiment_report.get("multiple_testing", {}).get("applied"):
            findings.append(f"已应用多重检验校正，方法为 {experiment_report['multiple_testing']['method']}。")
        if experiment_report.get("sequential_monitoring", {}).get("applied"):
            findings.append(
                f"已应用序贯监测，方法为 {experiment_report['sequential_monitoring']['method']}，调整后的 alpha 为 {experiment_report['sequential_monitoring']['adjusted_alpha']:.4f}。"
            )
        underpowered = [
            metric_name
            for metric_name, result in experiment_report.get("metrics", {}).items()
            if result.get("power_analysis", {}).get("underpowered_for_target")
        ]
        if underpowered:
            risks.append(f"以下指标在当前目标功效下可能不足：{', '.join(underpowered)}。")
    if analysis_report:
        normalized_analysis_task = normalize_analysis_task(task)
        findings.append(f"已生成 {ANALYSIS_TASK_LABELS.get(normalized_analysis_task, normalized_analysis_task)}。")
        recommendations.append("建议查看 analysis_report 中的方法级结果和图表。")
        if normalized_analysis_task == "cluster":
            selection_label = "轮廓系数" if analysis_report["selection_metric"] == "silhouette" else "用户指定"
            findings.append(f"已选择 {analysis_report['n_clusters']} 个簇，依据为 {selection_label}。")
        elif normalized_analysis_task == "apriori":
            findings.append(f"已生成 {len(analysis_report.get('rules', []))} 条关联规则。")
            if not analysis_report.get("rules"):
                risks.append("没有关联规则通过当前支持度/置信度阈值。")
        elif normalized_analysis_task == "anova":
            findings.append(f"{analysis_report['result']['test']} 的 p 值为 {analysis_report['result']['p_value']:.4f}。")
            if not analysis_report["result"]["significant_at_alpha"]:
                risks.append("在当前显著性水平下，组间差异未达到统计显著。")
        elif normalized_analysis_task == "root-cause":
            top_drivers = analysis_report.get("top_positive_drivers", [])
            if top_drivers:
                findings.append(f"首要根因驱动项为 {top_drivers[0]['segment']}。")
    if causal_report:
        normalized_causal_task = normalize_causal_task(task)
        findings.append(f"已生成 {CAUSAL_TASK_LABELS.get(normalized_causal_task, normalized_causal_task)} 因果分析报告。")
        if causal_narrative:
            findings.append(causal_narrative["headline"])
        recommendations.append("建议先看 causal_narrative_report，再查看 causal_report.json 中的技术细节和图表。")
        if normalized_causal_task == "did":
            findings.append(f"DID 估计值为 {causal_report['did_estimate']:.4f}。")
            regression = causal_report.get("regression", {})
            if regression.get("available"):
                findings.append(f"DID 交互项 p 值为 {regression['p_value']:.4f}。")
        elif normalized_causal_task == "rd":
            findings.append(f"RD 局部效应为 {causal_report['local_effect']:.4f}。")
            regression = causal_report.get("regression", {})
            if regression.get("available"):
                findings.append(f"RD 局部 p 值为 {regression['p_value']:.4f}。")
            if causal_report.get("treated_share", {}).get("right", 1.0) - causal_report.get("treated_share", {}).get("left", 0.0) < 0.5:
                risks.append("断点处的处理跃迁不够明显，sharp RD 解释可能不够稳健。")
            discontinuous_covariates = [
                feature
                for feature, details in causal_report.get("covariate_continuity", {}).items()
                if details.get("p_value") is not None and float(details["p_value"]) < 0.05
            ]
            if discontinuous_covariates:
                risks.append("以下协变量在断点附近可能存在连续性问题：" + ", ".join(discontinuous_covariates[:4]) + "。")
        elif normalized_causal_task == "synthetic-control":
            findings.append(f"合成控制法后期平均差距为 {causal_report['post_average_gap']:.4f}。")
            ratio = causal_report.get("post_to_pre_rmspe_ratio")
            if ratio is not None:
                findings.append(f"合成控制法后/前 RMSPE 比值为 {ratio:.4f}。")
            if causal_report.get("pre_rmspe", 0.0) > 5:
                risks.append("合成控制法在处理前拟合误差偏大。")
        elif normalized_causal_task == "iv":
            findings.append(f"IV 估计值为 {causal_report['iv_estimate']:.4f}。")
            first_stage = causal_report.get("first_stage", {})
            findings.append(f"IV 一阶段 F 统计量为 {first_stage.get('f_statistic', 0.0):.4f}。")
            if first_stage.get("weak_instrument_at_f_lt_10"):
                risks.append("按常用的一阶段 F < 10 经验规则看，该工具变量可能偏弱。")
        elif normalized_causal_task == "dml":
            findings.append(f"DML 平均处理效应为 {causal_report['average_treatment_effect']:.4f}。")
            if causal_report.get("propensity_overlap", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("DML 残差化后共同支持区间仍偏窄。")
        elif normalized_causal_task == "dr":
            findings.append(f"双重稳健 ATE 为 {causal_report['average_treatment_effect']:.4f}。")
            if causal_report.get("propensity_overlap", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("双重稳健估计的共同支持区间仍偏窄。")
        elif normalized_causal_task == "psm":
            findings.append(
                f"PSM ATT 为 {causal_report['average_treatment_effect_on_treated']:.4f}，基于 {causal_report['matched_pairs']} 对匹配样本。"
            )
            if causal_report.get("common_support", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("共同支持区间有限，PSM 估计可能不稳定。")
            balance = causal_report.get("balance", {})
            if balance and not balance.get("balance_improved", True):
                risks.append("匹配并未改善协变量平衡，因此 PSM 结果不宜直接视为可靠。")
        elif normalized_causal_task == "orthogonal":
            findings.append(f"正交学习器的平均预测效应为 {causal_report['average_predicted_effect']:.4f}。")
            if causal_report.get("propensity_overlap", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("正交学习器在倾向得分模型上的共同支持区间仍偏窄。")
        elif normalized_causal_task == "uplift":
            findings.append(f"平均预测 uplift 为 {causal_report['average_predicted_uplift']:.4f}。")
            if not causal_report.get("heterogeneity"):
                risks.append("在当前最小分组规模下，没有找到足够的异质性分段。")
        elif normalized_causal_task == "cate":
            findings.append(f"CATE 元学习器方法包括：{', '.join(causal_report.get('methods', {}).keys())}。")
            comparison = causal_report.get("method_comparison", {})
            if "mean_absolute_difference" in comparison:
                findings.append(f"元学习器的 CATE 平均绝对差为 {comparison['mean_absolute_difference']:.4f}。")
            if comparison.get("correlation") is not None and float(comparison["correlation"]) < 0.3:
                risks.append("元学习器的 CATE 结果一致性较低，说明模型不确定性仍然存在。")
        elif normalized_causal_task == "causal":
            findings.append(f"因果方法套件执行的方法包括：{', '.join(causal_report.get('methods', []))}。")
            rd_report = causal_report.get("reports", {}).get("rd", {})
            if rd_report and rd_report.get("treated_share", {}).get("right", 1.0) - rd_report.get("treated_share", {}).get("left", 0.0) < 0.5:
                risks.append("因果套件中的 RD 运行没有显示足够强的断点跃迁。")
            if rd_report:
                discontinuous_covariates = [
                    feature
                    for feature, details in rd_report.get("covariate_continuity", {}).items()
                    if details.get("p_value") is not None and float(details["p_value"]) < 0.05
                ]
                if discontinuous_covariates:
                    risks.append("因果套件中的 RD 运行在断点附近存在潜在协变量不连续：" + ", ".join(discontinuous_covariates[:4]) + "。")
            synth_report = causal_report.get("reports", {}).get("synthetic-control", {})
            if synth_report and synth_report.get("pre_rmspe", 0.0) > 5:
                risks.append("因果套件中的合成控制法处理前拟合误差偏大。")
            iv_report = causal_report.get("reports", {}).get("iv", {})
            if iv_report and iv_report.get("first_stage", {}).get("weak_instrument_at_f_lt_10"):
                risks.append("因果套件中的 IV 运行显示一阶段偏弱。")
            dml_report = causal_report.get("reports", {}).get("dml", {})
            if dml_report and dml_report.get("propensity_overlap", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("因果套件中的 DML 运行共同支持区间偏窄。")
            dr_report = causal_report.get("reports", {}).get("dr", {})
            if dr_report and dr_report.get("propensity_overlap", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("因果套件中的双重稳健运行共同支持区间偏窄。")
            orthogonal_report = causal_report.get("reports", {}).get("orthogonal", {})
            if orthogonal_report and orthogonal_report.get("propensity_overlap", {}).get("share_in_common_support", 1.0) < 0.8:
                risks.append("因果套件中的正交学习器共同支持区间偏窄。")
            if dml_report and orthogonal_report:
                dml_effect = float(dml_report.get("average_treatment_effect", 0.0))
                orthogonal_effect = float(orthogonal_report.get("average_predicted_effect", 0.0))
                denominator = max(abs(dml_effect), 1.0)
                if abs(dml_effect - orthogonal_effect) / denominator > 0.2:
                    risks.append("因果套件中的 DML 与正交学习器估计存在明显分歧。")
            cate_report = causal_report.get("reports", {}).get("cate", {})
            cate_comparison = cate_report.get("method_comparison", {})
            if cate_comparison.get("correlation") is not None and float(cate_comparison["correlation"]) < 0.3:
                risks.append("因果套件中的元学习器 CATE 结果一致性较低。")
            psm_report = causal_report.get("reports", {}).get("psm", {})
            if psm_report:
                if psm_report.get("common_support", {}).get("share_in_common_support", 1.0) < 0.8:
                    risks.append("因果套件中的 PSM 运行共同支持区间偏窄。")
                if not psm_report.get("balance", {}).get("balance_improved", True):
                    risks.append("因果套件中的 PSM 运行未改善协变量平衡。")
    if business_report:
        findings.append("已生成业务分析报告。")
        recommendations.append("建议查看 business_report.json 中的 KPI 定义、分层和业务图表。")
    if research_report:
        findings.append(f"外部研究共收集到 {research_report['record_count_total']} 条去重后的来源候选。")
        recommendations.append("在最终分析前，建议先检查 research_sources 的说明和冲突标记。")
        if research_report["conflict_count_total"] > 0:
            risks.append(f"外部研究发现 {research_report['conflict_count_total']} 处来源定义或单位冲突。")
    if not findings:
        findings.append("当前未生成实质性分析结果。")
    if not recommendations:
        recommendations.append("建议补充领域指标或特征选择配置，以获得更完整的分析结果。")
    if not risks:
        risks.append("当前运行未发现明显阻断性问题。")

    _write_chart_review(
        run_dir,
        {
            "chart_plan": rendered_chart_plan,
            "explainability_report": explainability_report,
            "stats_report": eda_report,
            "sampling_report": sampling_report,
        },
    )
    _write_summary(run_dir, task, _localize_read_plan_for_summary(read_artifact), findings, risks, recommendations)
    _log("Exporting dashboard / process report / formal report...")
    _write_run_status(run_dir, stage="exporting", task=task)
    _finish_run(run_dir, args.formal_report, args.report_title, args.process_report, args.process_report_title)
    _write_run_status(run_dir, stage="completed", task=task)
    print(run_dir, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
