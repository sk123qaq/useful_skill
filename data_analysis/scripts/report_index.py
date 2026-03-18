#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

from report_export import _best_model_name_from_report, _collect_run_context, _fmt_number, _fmt_percent

CAUSAL_TASKS = {"did", "rd", "synthetic-control", "iv", "dml", "dr", "psm", "orthogonal", "uplift", "cate", "causal"}
SUPERVISED_TASKS = {"regression", "classification"}
BUSINESS_TASKS = {"funnel", "monetization", "retention", "cohort", "ltv", "business"}
ANALYSIS_TASKS = {"cluster", "anova", "apriori", "root-cause"}


def infer_outputs_root(run_dir: Path) -> Path:
    for candidate in [run_dir, *run_dir.parents]:
        if candidate.name == "outputs":
            return candidate
    return run_dir.parent


def discover_run_dirs(outputs_root: Path) -> list[Path]:
    runs = sorted({path.parent for path in outputs_root.rglob("environment.json") if path.parent != outputs_root})
    return [path for path in runs if path.is_dir()]


def _relative_group(outputs_root: Path, run_dir: Path) -> str:
    relative = run_dir.relative_to(outputs_root)
    parts = relative.parts
    if len(parts) >= 2:
        return parts[0]
    return "ungrouped"


def _extract_run_timestamp(run_dir: Path, context: dict[str, Any]) -> str:
    checked_at = (context.get("environment") or {}).get("checked_at")
    if checked_at:
        return str(checked_at)
    name = run_dir.name
    if "-" in name:
        return name.split("-", 1)[-1]
    return name


def _extract_task(context: dict[str, Any]) -> str:
    if (context.get("chart_plan") or {}).get("task"):
        return str(context["chart_plan"]["task"])
    if (context.get("causal_report") or {}).get("task"):
        return str(context["causal_report"]["task"])
    if (context.get("analysis_report") or {}).get("task"):
        return str(context["analysis_report"]["task"])
    if (context.get("model_report") or {}).get("task"):
        return str(context["model_report"]["task"])
    if context.get("experiment_report"):
        return "experiment"
    if context.get("business_report"):
        return "business"
    return "unknown"


def _task_slug(task: str) -> str:
    return task.replace("/", "-").replace("_", "-").strip().lower()


def _compare_family(task: str) -> str:
    if task in CAUSAL_TASKS:
        return "causal"
    if task == "experiment":
        return "experiment"
    if task in SUPERVISED_TASKS:
        return "supervised"
    if task in BUSINESS_TASKS:
        return "business"
    if task in ANALYSIS_TASKS:
        return "analysis"
    return "general"


def _extract_experiment_compare_fields(experiment: dict[str, Any]) -> dict[str, Any]:
    metrics = experiment.get("metrics", {})
    primary_name = None
    primary_metric = None
    for metric_name, metric in metrics.items():
        if metric.get("role") == "primary":
            primary_name = metric_name
            primary_metric = metric
            break
    if primary_metric is None and metrics:
        primary_name, primary_metric = next(iter(metrics.items()))
    underpowered = [
        metric_name
        for metric_name, metric in metrics.items()
        if metric.get("power_analysis", {}).get("underpowered_for_target")
    ]
    return {
        "primary_metric": primary_name,
        "absolute_lift": primary_metric.get("absolute_lift") if primary_metric else None,
        "relative_lift": primary_metric.get("relative_lift") if primary_metric else None,
        "p_value": primary_metric.get("p_value") if primary_metric else None,
        "adjusted_p_value": primary_metric.get("multiple_testing", {}).get("adjusted_p_value") if primary_metric else None,
        "srm_mismatch": experiment.get("sample_ratio_mismatch", {}).get("is_mismatch"),
        "underpowered_metrics": underpowered,
    }


def _direction_from_value(value: Any) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 0:
        return "positive"
    if number < 0:
        return "negative"
    return "neutral"


def _extract_causal_compare_fields(causal: dict[str, Any], raw_report: dict[str, Any]) -> dict[str, Any]:
    estimate = causal.get("key_estimate", {})
    value = estimate.get("value")
    if isinstance(value, dict):
        value = json.dumps(value, ensure_ascii=False)
    compare = {
        "estimate_label": estimate.get("label"),
        "estimate_value": value,
        "direction": estimate.get("direction"),
        "significant": estimate.get("significant"),
        "risk_count": len(causal.get("risks_and_limits", [])),
        "recommendation": causal.get("recommendation"),
    }
    if compare["estimate_value"] is not None or not raw_report:
        return compare

    task = raw_report.get("task")
    if task == "did":
        compare.update(
            {
                "estimate_label": "DID estimate",
                "estimate_value": raw_report.get("did_estimate"),
                "direction": _direction_from_value(raw_report.get("did_estimate")),
                "significant": raw_report.get("regression", {}).get("p_value", 1) < 0.05 if raw_report.get("regression", {}).get("p_value") is not None else None,
            }
        )
    elif task == "rd":
        compare.update(
            {
                "estimate_label": "Local effect",
                "estimate_value": raw_report.get("local_effect"),
                "direction": _direction_from_value(raw_report.get("local_effect")),
                "significant": raw_report.get("regression", {}).get("p_value", 1) < 0.05 if raw_report.get("regression", {}).get("p_value") is not None else None,
            }
        )
    elif task == "synthetic-control":
        compare.update(
            {
                "estimate_label": "Post average gap",
                "estimate_value": raw_report.get("post_average_gap"),
                "direction": _direction_from_value(raw_report.get("post_average_gap")),
            }
        )
    elif task == "iv":
        compare.update(
            {
                "estimate_label": "IV estimate",
                "estimate_value": raw_report.get("iv_estimate"),
                "direction": _direction_from_value(raw_report.get("iv_estimate")),
                "significant": raw_report.get("p_value", 1) < 0.05 if raw_report.get("p_value") is not None else None,
            }
        )
    elif task in {"dml", "dr"}:
        compare.update(
            {
                "estimate_label": "ATE",
                "estimate_value": raw_report.get("average_treatment_effect"),
                "direction": _direction_from_value(raw_report.get("average_treatment_effect")),
                "significant": raw_report.get("p_value", 1) < 0.05 if raw_report.get("p_value") is not None else None,
            }
        )
    elif task == "psm":
        compare.update(
            {
                "estimate_label": "ATT",
                "estimate_value": raw_report.get("average_treatment_effect_on_treated"),
                "direction": _direction_from_value(raw_report.get("average_treatment_effect_on_treated")),
                "significant": raw_report.get("p_value", 1) < 0.05 if raw_report.get("p_value") is not None else None,
            }
        )
    elif task == "orthogonal":
        compare.update(
            {
                "estimate_label": "Predicted effect",
                "estimate_value": raw_report.get("average_predicted_effect"),
                "direction": _direction_from_value(raw_report.get("average_predicted_effect")),
            }
        )
    elif task == "uplift":
        compare.update(
            {
                "estimate_label": "Predicted uplift",
                "estimate_value": raw_report.get("average_predicted_uplift"),
                "direction": _direction_from_value(raw_report.get("average_predicted_uplift")),
            }
        )
    elif task == "cate":
        compare.update(
            {
                "estimate_label": "Mean absolute CATE gap",
                "estimate_value": raw_report.get("method_comparison", {}).get("mean_absolute_difference"),
                "direction": None,
            }
        )
    elif task == "causal":
        reports = raw_report.get("reports", {})
        positive = 0
        negative = 0
        for method, report in reports.items():
            candidate_value = (
                report.get("average_treatment_effect")
                if "average_treatment_effect" in report
                else report.get("average_predicted_effect")
                if "average_predicted_effect" in report
                else report.get("average_predicted_uplift")
                if "average_predicted_uplift" in report
                else report.get("did_estimate")
                if "did_estimate" in report
                else report.get("local_effect")
                if "local_effect" in report
                else report.get("post_average_gap")
                if "post_average_gap" in report
                else report.get("iv_estimate")
            )
            direction = _direction_from_value(candidate_value)
            if direction == "positive":
                positive += 1
            elif direction == "negative":
                negative += 1
        compare.update(
            {
                "estimate_label": "Methods",
                "estimate_value": len(reports),
                "direction": "positive" if positive and not negative else "negative" if negative and not positive else None,
            }
        )
    return compare


def _extract_supervised_compare_fields(model_report: dict[str, Any], explainability: dict[str, Any]) -> dict[str, Any]:
    task = model_report.get("task")
    best_model = _best_model_name_from_report(model_report, task=task)
    score_label = None
    score_value = None
    if best_model:
        metrics = model_report.get("models", {}).get(best_model, {})
        if task == "regression":
            score_label = "R2"
            score_value = metrics.get("test_r2")
        elif task == "classification":
            score_label = "F1"
            score_value = metrics.get("test_f1_weighted")
    top_feature = None
    if explainability.get("permutation_importance"):
        top_feature = explainability["permutation_importance"][0].get("feature")
    return {
        "best_model": best_model,
        "score_label": score_label,
        "score_value": score_value,
        "n_features_used": model_report.get("n_features_used"),
        "top_feature": top_feature,
    }


def _extract_business_compare_fields(task: str, business: dict[str, Any]) -> dict[str, Any]:
    if task == "ltv":
        return {"primary_label": "LTV", "primary_value": business.get("ltv"), "secondary_label": "Pay Rate", "secondary_value": business.get("pay_rate")}
    if task == "monetization":
        return {"primary_label": "Revenue", "primary_value": business.get("total_revenue"), "secondary_label": "Pay Rate", "secondary_value": business.get("pay_rate")}
    if task == "retention":
        return {"primary_label": "Retention", "primary_value": business.get("retention"), "secondary_label": "Cohort Size", "secondary_value": business.get("cohort_size")}
    if task == "cohort":
        return {"primary_label": "Cohorts", "primary_value": len(business.get("cohort_sizes", {})), "secondary_label": "Matrix Rows", "secondary_value": len(business.get("retention_matrix", {}))}
    if task == "funnel":
        steps = business.get("steps", [])
        final_rate = steps[-1].get("conversion_rate") if steps else None
        return {"primary_label": "Steps", "primary_value": len(steps), "secondary_label": "Final Conversion", "secondary_value": final_rate}
    return {"primary_label": "Key Metric", "primary_value": None, "secondary_label": None, "secondary_value": None}


def _extract_analysis_compare_fields(analysis: dict[str, Any]) -> dict[str, Any]:
    task = analysis.get("task")
    if task == "cluster":
        return {"detail_label": "Clusters", "detail_value": analysis.get("n_clusters"), "secondary_label": "Selection Metric", "secondary_value": analysis.get("selection_metric")}
    if task == "anova":
        result = analysis.get("result", {})
        return {"detail_label": result.get("test", "p-value"), "detail_value": result.get("p_value"), "secondary_label": "Significant", "secondary_value": result.get("significant_at_alpha")}
    if task == "apriori":
        return {"detail_label": "Rules", "detail_value": len(analysis.get("rules", [])), "secondary_label": "Min Support", "secondary_value": analysis.get("min_support")}
    if task == "root-cause":
        top = analysis.get("top_positive_drivers", [])
        return {"detail_label": "Top Driver", "detail_value": top[0].get("segment") if top else None, "secondary_label": "Drivers", "secondary_value": len(top)}
    return {"detail_label": None, "detail_value": None, "secondary_label": None, "secondary_value": None}


def _extract_compare_fields(task: str, context: dict[str, Any]) -> dict[str, Any]:
    if task in CAUSAL_TASKS:
        return _extract_causal_compare_fields(context.get("causal_narrative_report") or {}, context.get("causal_report") or {})
    if task == "experiment":
        return _extract_experiment_compare_fields(context.get("experiment_report") or {})
    if task in SUPERVISED_TASKS:
        return _extract_supervised_compare_fields(context.get("model_report") or {}, context.get("explainability_report") or {})
    if task in BUSINESS_TASKS:
        return _extract_business_compare_fields(task, context.get("business_report") or {})
    if task in ANALYSIS_TASKS:
        return _extract_analysis_compare_fields(context.get("analysis_report") or {})
    return {}


def _primary_summary(context: dict[str, Any]) -> str:
    if (context.get("causal_narrative_report") or {}).get("headline"):
        return str(context["causal_narrative_report"]["headline"])
    experiment = context.get("experiment_report") or {}
    if experiment.get("decision", {}).get("summary"):
        return str(experiment["decision"]["summary"])
    if experiment.get("decision", {}).get("status"):
        return f"Experiment decision: {experiment['decision']['status']}."
    analysis = context.get("analysis_report") or {}
    if analysis.get("task") == "cluster":
        return f"Selected {analysis.get('n_clusters', 'N/A')} clusters."
    if analysis.get("task") == "anova":
        result = analysis.get("result", {})
        return f"{result.get('test', 'ANOVA')} p-value {_fmt_number(result.get('p_value'))}."
    business = context.get("business_report") or {}
    if "ltv" in business:
        return f"LTV {_fmt_number(business.get('ltv'))} with pay rate {_fmt_percent(business.get('pay_rate'))}."
    if "retention" in business:
        return f"Retention {_fmt_percent(business.get('retention'))}."
    model_report = context.get("model_report") or {}
    task = model_report.get("task")
    best_model = _best_model_name_from_report(model_report, task=task)
    if best_model:
        metrics = model_report.get("models", {}).get(best_model, {})
        ranking = metrics.get("test_r2") if task == "regression" else metrics.get("test_f1_weighted") if task == "classification" else None
        return f"Best model {best_model} with score {_fmt_number(ranking)}."
    return "No high-level summary was auto-extracted."


def _key_metric(context: dict[str, Any]) -> str:
    causal = context.get("causal_narrative_report") or {}
    estimate = causal.get("key_estimate", {})
    if estimate.get("value") is not None and not isinstance(estimate.get("value"), dict):
        return f"{estimate.get('label', 'Estimate')}: {_fmt_number(estimate.get('value'))}"
    experiment = context.get("experiment_report") or {}
    if experiment.get("decision", {}).get("status"):
        return str(experiment["decision"]["status"])
    business = context.get("business_report") or {}
    for key in ["ltv", "pay_rate", "total_revenue", "retention"]:
        if key in business:
            value = _fmt_percent(business[key]) if key in {"pay_rate", "retention"} else _fmt_number(business[key])
            return f"{key}: {value}"
    analysis = context.get("analysis_report") or {}
    if analysis.get("result", {}).get("p_value") is not None:
        return f"p-value: {_fmt_number(analysis['result']['p_value'])}"
    model = context.get("model_report") or {}
    task = model.get("task")
    best_model = _best_model_name_from_report(model, task=task)
    if best_model:
        metrics = model.get("models", {}).get(best_model, {})
        if task == "regression" and metrics.get("test_r2") is not None:
            return f"R2: {_fmt_number(metrics['test_r2'])}"
        if task == "classification" and metrics.get("test_f1_weighted") is not None:
            return f"F1: {_fmt_number(metrics['test_f1_weighted'])}"
    return "N/A"


def summarize_run(outputs_root: Path, run_dir: Path) -> dict[str, Any]:
    context = _collect_run_context(run_dir)
    cleaning = context.get("cleaning_report") or {}
    shape = cleaning.get("shape", {})
    causal = context.get("causal_narrative_report") or {}
    experiment = context.get("experiment_report") or {}
    task = _extract_task(context)
    summary = {
        "group": _relative_group(outputs_root, run_dir),
        "run_dir": str(run_dir),
        "relative_path": str(run_dir.relative_to(outputs_root)),
        "task": task,
        "compare_family": _compare_family(task),
        "task_page_path": f"comparisons/{_task_slug(task)}.html",
        "timestamp": _extract_run_timestamp(run_dir, context),
        "rows": shape.get("rows"),
        "columns": shape.get("columns"),
        "charts": len(context.get("png_files", [])),
        "summary": _primary_summary(context),
        "key_metric": _key_metric(context),
        "compare_fields": _extract_compare_fields(task, context),
        "dashboard_path": str((run_dir / "report_dashboard.html").relative_to(outputs_root)) if (run_dir / "report_dashboard.html").exists() else None,
        "process_report_path": str((run_dir / "report_process.html").relative_to(outputs_root)) if (run_dir / "report_process.html").exists() else None,
        "run_summary_path": str((run_dir / "run_summary.md").relative_to(outputs_root)) if (run_dir / "run_summary.md").exists() else None,
        "causal_narrative_path": str((run_dir / "causal_narrative_report.md").relative_to(outputs_root)) if (run_dir / "causal_narrative_report.md").exists() else None,
        "decision_status": experiment.get("decision", {}).get("status"),
        "headline": causal.get("headline"),
    }
    return summary


def build_run_index(outputs_root: Path) -> dict[str, Any]:
    run_dirs = discover_run_dirs(outputs_root)
    runs = [summarize_run(outputs_root, run_dir) for run_dir in run_dirs]
    runs.sort(key=lambda run: str(run.get("timestamp", "")), reverse=True)
    task_counts = Counter(run["task"] for run in runs)
    group_counts = Counter(run["group"] for run in runs)
    task_pages = [
        {
            "task": task,
            "count": count,
            "path": f"comparisons/{_task_slug(task)}.html",
        }
        for task, count in sorted(task_counts.items())
    ]
    return {
        "outputs_root": str(outputs_root),
        "run_count": len(runs),
        "task_counts": dict(sorted(task_counts.items())),
        "group_counts": dict(sorted(group_counts.items())),
        "task_pages": task_pages,
        "runs": runs,
    }


def _escape(value: Any) -> str:
    return html.escape(str(value))


def _render_top_cards(index: dict[str, Any]) -> str:
    cards = [
        ("Total Runs", str(index.get("run_count", 0))),
        ("Tasks", str(len(index.get("task_counts", {})))),
        ("Groups", str(len(index.get("group_counts", {})))),
    ]
    cards.extend((f"Task: {task}", str(count)) for task, count in list(index.get("task_counts", {}).items())[:4])
    return "".join(
        f"""
        <div class="metric-card">
          <div class="metric-label">{_escape(label)}</div>
          <div class="metric-value">{_escape(value)}</div>
        </div>
        """
        for label, value in cards
    )


def _render_task_pages(index: dict[str, Any]) -> str:
    pages = index.get("task_pages", [])
    if not pages:
        return ""
    links = "".join(
        f"""
        <a class="task-link" href="{_escape(page['path'])}">
          <span>{_escape(page['task'])}</span>
          <strong>{_escape(page['count'])}</strong>
        </a>
        """
        for page in pages
    )
    return f"""
    <section class="panel">
      <h2>Task Comparison Pages</h2>
      <div class="task-link-grid">{links}</div>
    </section>
    """


def _render_recent_runs(index: dict[str, Any]) -> str:
    recent = index.get("runs", [])[:8]
    if not recent:
        return "<p>No runs found.</p>"
    items = []
    for run in recent:
        link = f'<a href="{_escape(run["dashboard_path"])}">Open dashboard</a>' if run.get("dashboard_path") else _escape(run["relative_path"])
        items.append(
            f"""
            <article class="run-card" data-task="{_escape(run['task'])}" data-group="{_escape(run['group'])}">
              <div class="run-meta">{_escape(run['group'])} · {_escape(run['timestamp'])}</div>
              <h3>{_escape(run['task'])}</h3>
              <p>{_escape(run['summary'])}</p>
              <p class="subtle">{_escape(run['key_metric'])}</p>
              <div class="run-links">{link}</div>
            </article>
            """
        )
    return "".join(items)


def _render_runs_table(index: dict[str, Any]) -> str:
    rows = []
    for run in index.get("runs", []):
        dashboard_link = (
            f'<a href="{_escape(run["dashboard_path"])}">dashboard</a>'
            if run.get("dashboard_path")
            else "-"
        )
        process_link = (
            f'<a href="{_escape(run["process_report_path"])}">process</a>'
            if run.get("process_report_path")
            else "-"
        )
        narrative_link = (
            f'<a href="{_escape(run["causal_narrative_path"])}">narrative</a>'
            if run.get("causal_narrative_path")
            else "-"
        )
        summary_link = (
            f'<a href="{_escape(run["run_summary_path"])}">summary</a>'
            if run.get("run_summary_path")
            else "-"
        )
        rows.append(
            f"""
            <tr data-task="{_escape(run['task'])}" data-group="{_escape(run['group'])}">
              <td>{_escape(run['group'])}</td>
              <td>{_escape(run['task'])}</td>
              <td>{_escape(run['timestamp'])}</td>
              <td>{_escape(run['rows'] if run['rows'] is not None else 'N/A')}</td>
              <td>{_escape(run['charts'])}</td>
              <td>{_escape(run['key_metric'])}</td>
              <td>{_escape(run['summary'])}</td>
              <td>{dashboard_link} · {process_link} · {narrative_link} · {summary_link}</td>
            </tr>
            """
        )
    return "".join(rows)


def _comparison_columns_for_family(family: str) -> list[tuple[str, str]]:
    if family == "causal":
        return [
            ("Estimate", "estimate"),
            ("Direction", "direction"),
            ("Significant", "significant"),
            ("Risks", "risk_count"),
            ("Recommendation", "recommendation"),
        ]
    if family == "experiment":
        return [
            ("Primary Metric", "primary_metric"),
            ("Abs Lift", "absolute_lift"),
            ("Adj p", "adjusted_p_value"),
            ("SRM", "srm_mismatch"),
            ("Underpowered", "underpowered_metrics"),
        ]
    if family == "supervised":
        return [
            ("Best Model", "best_model"),
            ("Score", "score"),
            ("Features", "n_features_used"),
            ("Top Feature", "top_feature"),
        ]
    if family == "business":
        return [
            ("Primary", "primary"),
            ("Secondary", "secondary"),
        ]
    if family == "analysis":
        return [
            ("Detail", "detail"),
            ("Secondary", "secondary"),
        ]
    return [("Key Metric", "key_metric")]


def _comparison_cell(run: dict[str, Any], key: str) -> str:
    compare = run.get("compare_fields", {})
    if key == "estimate":
        label = compare.get("estimate_label")
        value = compare.get("estimate_value")
        if value is None:
            return "N/A"
        rendered = _fmt_number(value) if isinstance(value, (int, float)) else str(value)
        return f"{label}: {rendered}" if label else rendered
    if key == "direction":
        value = compare.get("direction")
        return str(value) if value not in {None, ""} else "N/A"
    if key == "significant":
        value = compare.get("significant")
        return "yes" if value is True else "no" if value is False else "N/A"
    if key == "risk_count":
        return str(compare.get("risk_count", 0))
    if key == "recommendation":
        value = compare.get("recommendation")
        return str(value) if value not in {None, ""} else "N/A"
    if key == "primary_metric":
        return str(compare.get("primary_metric", "N/A"))
    if key == "absolute_lift":
        value = compare.get("absolute_lift")
        return _fmt_number(value) if value is not None else "N/A"
    if key == "adjusted_p_value":
        value = compare.get("adjusted_p_value")
        return _fmt_number(value) if value is not None else "N/A"
    if key == "srm_mismatch":
        value = compare.get("srm_mismatch")
        return "yes" if value is True else "no" if value is False else "N/A"
    if key == "underpowered_metrics":
        values = compare.get("underpowered_metrics") or []
        return ", ".join(values) if values else "none"
    if key == "best_model":
        value = compare.get("best_model")
        return str(value) if value not in {None, ""} else "N/A"
    if key == "score":
        label = compare.get("score_label")
        value = compare.get("score_value")
        return f"{label}: {_fmt_number(value)}" if label and value is not None else "N/A"
    if key == "n_features_used":
        value = compare.get("n_features_used")
        return str(value) if value is not None else "N/A"
    if key == "top_feature":
        value = compare.get("top_feature")
        return str(value) if value not in {None, ""} else "N/A"
    if key == "primary":
        label = compare.get("primary_label")
        value = compare.get("primary_value")
        rendered = _fmt_percent(value) if label in {"Pay Rate", "Retention", "Final Conversion"} else _fmt_number(value) if isinstance(value, (int, float)) else value
        return f"{label}: {rendered}" if label else "N/A"
    if key == "secondary":
        label = compare.get("secondary_label")
        value = compare.get("secondary_value")
        if isinstance(value, bool):
            rendered = "yes" if value else "no"
        elif label in {"Pay Rate", "Retention", "Final Conversion"}:
            rendered = _fmt_percent(value)
        elif isinstance(value, (int, float)):
            rendered = _fmt_number(value)
        else:
            rendered = value
        return f"{label}: {rendered}" if label else "N/A"
    if key == "detail":
        label = compare.get("detail_label")
        value = compare.get("detail_value")
        rendered = _fmt_number(value) if isinstance(value, (int, float)) else value
        return f"{label}: {rendered}" if label else "N/A"
    if key == "key_metric":
        return str(run.get("key_metric", "N/A"))
    return "N/A"


def _comparison_page_html(task: str, runs: list[dict[str, Any]], outputs_root: Path) -> str:
    family = runs[0].get("compare_family", "general") if runs else "general"
    columns = _comparison_columns_for_family(family)
    latest = runs[0]["timestamp"] if runs else "N/A"
    groups = sorted({run["group"] for run in runs})
    rows_html = []
    for run in runs:
        dashboard_link = (
            f'<a href="../{_escape(run["dashboard_path"])}">dashboard</a>'
            if run.get("dashboard_path")
            else "-"
        )
        process_link = (
            f'<a href="../{_escape(run["process_report_path"])}">process</a>'
            if run.get("process_report_path")
            else "-"
        )
        narrative_link = (
            f'<a href="../{_escape(run["causal_narrative_path"])}">narrative</a>'
            if run.get("causal_narrative_path")
            else "-"
        )
        summary_link = (
            f'<a href="../{_escape(run["run_summary_path"])}">summary</a>'
            if run.get("run_summary_path")
            else "-"
        )
        dynamic_cells = "".join(f"<td>{_escape(_comparison_cell(run, key))}</td>" for _, key in columns)
        rows_html.append(
            f"""
            <tr>
              <td>{_escape(run['timestamp'])}</td>
              <td>{_escape(run['group'])}</td>
              <td>{_escape(run['rows'] if run['rows'] is not None else 'N/A')}</td>
              {dynamic_cells}
              <td>{_escape(run['summary'])}</td>
              <td>{dashboard_link} · {process_link} · {narrative_link} · {summary_link}</td>
            </tr>
            """
        )
    header_dynamic = "".join(f"<th>{_escape(label)}</th>" for label, _ in columns)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_escape(task)} comparison</title>
  <style>
    body {{
      margin: 0;
      font-family: "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC", "Segoe UI", sans-serif;
      background: #f4f0e8;
      color: #1b2430;
    }}
    .wrap {{ max-width: 1280px; margin: 0 auto; padding: 28px 18px 48px; }}
    .hero, .panel {{ background: #fffaf2; border: 1px solid #e4d8c8; border-radius: 22px; padding: 22px; box-shadow: 0 12px 34px rgba(27, 36, 48, 0.08); }}
    .panel {{ margin-top: 18px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    p {{ margin: 0 0 10px; line-height: 1.6; }}
    .meta {{ color: #69717d; display: flex; flex-wrap: wrap; gap: 16px; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; margin-top: 18px; }}
    .metric-card {{ background: #fffdf8; border: 1px solid #e4d8c8; border-radius: 16px; padding: 14px 16px; }}
    .metric-label {{ color: #69717d; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }}
    .metric-value {{ font-size: 24px; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 14px; font-size: 14px; }}
    th, td {{ text-align: left; vertical-align: top; padding: 10px 12px; border-bottom: 1px solid #e4d8c8; }}
    th {{ color: #69717d; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; }}
    a {{ color: #075985; }}
    @media (max-width: 760px) {{
      .wrap {{ padding: 16px 12px 28px; }}
      .hero, .panel {{ padding: 16px; border-radius: 16px; }}
      table {{ display: block; overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <p><a href="../run_index.html">Back to run index</a></p>
      <h1>{_escape(task)} comparison</h1>
      <p>Task-aware comparison view across historical `{_escape(task)}` runs. Use this page when the top-level index is too broad and you need to compare similar analyses side by side.</p>
      <div class="meta">
        <span>Runs: {_escape(len(runs))}</span>
        <span>Groups: {_escape(len(groups))}</span>
        <span>Latest: {_escape(latest)}</span>
        <span>Family: {_escape(family)}</span>
      </div>
      <div class="metric-grid">
        <div class="metric-card"><div class="metric-label">Run Count</div><div class="metric-value">{_escape(len(runs))}</div></div>
        <div class="metric-card"><div class="metric-label">Groups</div><div class="metric-value">{_escape(len(groups))}</div></div>
        <div class="metric-card"><div class="metric-label">Latest Run</div><div class="metric-value">{_escape(latest.replace('T', ' '))}</div></div>
      </div>
    </section>

    <section class="panel">
      <h2>Runs</h2>
      <table>
        <thead>
          <tr>
            <th>Timestamp</th>
            <th>Group</th>
            <th>Rows</th>
            {header_dynamic}
            <th>Summary</th>
            <th>Links</th>
          </tr>
        </thead>
        <tbody>
          {''.join(rows_html)}
        </tbody>
      </table>
    </section>
  </div>
</body>
</html>
"""


def _write_task_pages(index: dict[str, Any], outputs_root: Path) -> list[dict[str, Any]]:
    comparison_dir = outputs_root / "comparisons"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    written = []
    runs_by_task: dict[str, list[dict[str, Any]]] = {}
    for run in index.get("runs", []):
        runs_by_task.setdefault(run["task"], []).append(run)
    for task, runs in runs_by_task.items():
        path = comparison_dir / f"{_task_slug(task)}.html"
        path.write_text(_comparison_page_html(task, runs, outputs_root))
        written.append({"task": task, "path": str(path.relative_to(outputs_root)), "count": len(runs)})
    return sorted(written, key=lambda item: item["task"])


def _build_html(index: dict[str, Any]) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Data Analysis Run Index</title>
  <style>
    :root {{
      --bg: #f4f0e8;
      --panel: #fffaf2;
      --ink: #1b2430;
      --muted: #69717d;
      --accent: #075985;
      --accent-2: #9a3412;
      --line: #e4d8c8;
      --shadow: 0 12px 34px rgba(27, 36, 48, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(7,89,133,0.10), transparent 28%),
        radial-gradient(circle at 80% 10%, rgba(154,52,18,0.10), transparent 22%),
        var(--bg);
    }}
    .wrap {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 28px 18px 50px;
    }}
    .hero, .panel, .metric-card, .run-card {{
      background: var(--panel);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }}
    .hero {{
      padding: 28px;
      border-radius: 24px;
    }}
    .eyebrow {{
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 10px;
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    h1 {{ font-size: 34px; line-height: 1.08; }}
    h2 {{ font-size: 22px; }}
    p {{ margin: 0 0 10px; line-height: 1.6; }}
    .subtle {{ color: var(--muted); }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 14px;
      margin-top: 18px;
    }}
    .metric-card {{
      border-radius: 18px;
      padding: 14px 16px;
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      margin-bottom: 8px;
    }}
    .metric-value {{
      font-size: 24px;
      font-weight: 700;
    }}
    .panel {{
      margin-top: 18px;
      border-radius: 20px;
      padding: 20px 22px;
    }}
    .toolbar {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    input, select {{
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #fffdf9;
      font: inherit;
    }}
    .run-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
      margin-top: 14px;
    }}
    .task-link-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .task-link {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: #fffdf8;
      text-decoration: none;
      color: var(--ink);
      font-weight: 600;
    }}
    .task-link strong {{
      color: var(--accent);
    }}
    .run-card {{
      border-radius: 18px;
      padding: 16px;
    }}
    .run-meta {{
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 8px;
    }}
    .run-links a {{
      color: var(--accent);
      text-decoration: none;
      font-weight: 600;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 14px;
      font-size: 14px;
    }}
    th, td {{
      text-align: left;
      vertical-align: top;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    a {{
      color: var(--accent);
    }}
    @media (max-width: 760px) {{
      .wrap {{ padding: 16px 12px 28px; }}
      .hero {{ padding: 20px; border-radius: 18px; }}
      h1 {{ font-size: 28px; }}
      .panel {{ padding: 16px; }}
      table {{ display: block; overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="eyebrow">Run Index</div>
      <h1>Data Analysis Multi-Run Dashboard</h1>
      <p>Browse completed runs, filter by task or group, and jump into the right dashboard or narrative artifact without manually opening each run directory.</p>
      <div class="metric-grid">{_render_top_cards(index)}</div>
    </section>

    {_render_task_pages(index)}

    <section class="panel">
      <h2>Filters</h2>
      <div class="toolbar">
        <input id="searchBox" type="search" placeholder="Search summary text, task, or group" />
        <select id="taskFilter">
          <option value="">All tasks</option>
          {''.join(f'<option value="{_escape(task)}">{_escape(task)}</option>' for task in sorted(index.get('task_counts', {}).keys()))}
        </select>
        <select id="groupFilter">
          <option value="">All groups</option>
          {''.join(f'<option value="{_escape(group)}">{_escape(group)}</option>' for group in sorted(index.get('group_counts', {}).keys()))}
        </select>
      </div>
    </section>

    <section class="panel">
      <h2>Recent Runs</h2>
      <div class="run-grid" id="runCards">
        {_render_recent_runs(index)}
      </div>
    </section>

    <section class="panel">
      <h2>All Runs</h2>
      <table id="runsTable">
        <thead>
          <tr>
            <th>Group</th>
            <th>Task</th>
            <th>Timestamp</th>
            <th>Rows</th>
            <th>Charts</th>
            <th>Key Metric</th>
            <th>Summary</th>
            <th>Links</th>
          </tr>
        </thead>
        <tbody>
          {_render_runs_table(index)}
        </tbody>
      </table>
    </section>
  </div>
  <script>
    const searchBox = document.getElementById('searchBox');
    const taskFilter = document.getElementById('taskFilter');
    const groupFilter = document.getElementById('groupFilter');
    const rows = Array.from(document.querySelectorAll('#runsTable tbody tr'));
    const cards = Array.from(document.querySelectorAll('#runCards .run-card'));

    function matches(el) {{
      const task = el.dataset.task || '';
      const group = el.dataset.group || '';
      const text = (el.textContent || '').toLowerCase();
      const search = (searchBox.value || '').trim().toLowerCase();
      const taskOk = !taskFilter.value || task === taskFilter.value;
      const groupOk = !groupFilter.value || group === groupFilter.value;
      const textOk = !search || text.includes(search);
      return taskOk && groupOk && textOk;
    }}

    function applyFilters() {{
      rows.forEach(row => {{
        row.style.display = matches(row) ? '' : 'none';
      }});
      cards.forEach(card => {{
        card.style.display = matches(card) ? '' : 'none';
      }});
    }}

    [searchBox, taskFilter, groupFilter].forEach(el => el.addEventListener('input', applyFilters));
    [taskFilter, groupFilter].forEach(el => el.addEventListener('change', applyFilters));
  </script>
</body>
</html>
"""


def export_run_index(outputs_root: Path, output_path: Path | None = None) -> dict[str, Path]:
    index = build_run_index(outputs_root)
    index["task_pages"] = _write_task_pages(index, outputs_root)
    json_path = output_path.with_suffix(".json") if output_path else outputs_root / "run_index.json"
    html_path = output_path if output_path else outputs_root / "run_index.html"
    json_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    html_path.write_text(_build_html(index))
    return {"json_path": json_path, "html_path": html_path}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a static multi-run index and comparison dashboard for data-analysis outputs.")
    parser.add_argument("--outputs-root", required=True)
    parser.add_argument("--output-path")
    args = parser.parse_args()

    outputs_root = Path(args.outputs_root)
    output_path = Path(args.output_path) if args.output_path else None
    result = export_run_index(outputs_root, output_path=output_path)
    print(result["html_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
