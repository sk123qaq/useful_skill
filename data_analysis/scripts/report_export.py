#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

KNOWN_JSON_ARTIFACTS = {
    "environment": "environment.json",
    "read_plan": "read_plan.json",
    "semantic_schema": "semantic_schema.json",
    "feature_lineage": "feature_lineage.json",
    "chart_plan": "chart_plan.json",
    "chart_candidates": "chart_candidates.json",
    "report_chart_decision": "report_chart_decision.json",
    "cleaning_report": "cleaning_report.json",
    "stats_report": "stats_report.json",
    "feature_plan": "feature_plan.json",
    "model_report": "model_report.json",
    "explainability_report": "explainability_report.json",
    "business_report": "business_report.json",
    "experiment_report": "experiment_report.json",
    "analysis_report": "analysis_report.json",
    "causal_report": "causal_report.json",
    "causal_narrative_report": "causal_narrative_report.json",
    "research_report": "research_report.json",
}


def _best_model_name_from_report(model_report: dict[str, Any], task: str | None) -> str | None:
    models = model_report.get("models", {})
    if not models or task not in {"classification", "regression"}:
        return None
    ranking_metric = "test_f1_weighted" if task == "classification" else "test_r2"
    candidates = []
    for model_name, metrics in models.items():
        if "error" in metrics or ranking_metric not in metrics:
            continue
        candidates.append((float(metrics[ranking_metric]), model_name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _load_optional_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text()


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


def _escape(value: Any) -> str:
    return html.escape(str(value))


def _collect_run_context(run_dir: Path) -> dict[str, Any]:
    payload = {name: _load_optional_json(run_dir / filename) for name, filename in KNOWN_JSON_ARTIFACTS.items()}
    payload["run_summary_markdown"] = _load_optional_text(run_dir / "run_summary.md")
    payload["causal_narrative_markdown"] = _load_optional_text(run_dir / "causal_narrative_report.md")
    payload["png_files"] = sorted(path.name for path in run_dir.glob("*.png"))
    payload["csv_files"] = sorted(path.name for path in run_dir.glob("*.csv"))
    payload["markdown_files"] = sorted(path.name for path in run_dir.glob("*.md"))
    payload["json_files"] = sorted(path.name for path in run_dir.glob("*.json"))
    payload["research_dirs"] = sorted(path.name for path in run_dir.glob("research*") if path.is_dir())
    payload["run_dir"] = str(run_dir)
    return payload


def _summary_cards(context: dict[str, Any]) -> list[dict[str, str]]:
    cleaning = context.get("cleaning_report") or {}
    chart_plan = context.get("chart_plan") or {}
    chart_candidates = context.get("chart_candidates") or {}
    report_chart_decision = context.get("report_chart_decision") or {}
    environment = context.get("environment") or {}
    cards = [
        {"label": "Task", "value": chart_plan.get("task", "unknown")},
    ]
    shape = cleaning.get("shape", {})
    if shape:
        cards.append({"label": "Rows", "value": str(shape.get("rows", "N/A"))})
        cards.append({"label": "Columns", "value": str(shape.get("columns", "N/A"))})
    missing = cleaning.get("missing_values", {})
    if missing:
        cards.append({"label": "Missing Columns", "value": str(missing.get("columns_with_missing_values", 0))})
    duplicates = cleaning.get("duplicates", {})
    if duplicates:
        cards.append({"label": "Duplicate Ratio", "value": _fmt_percent(duplicates.get("duplicate_ratio", 0.0))})
    cards.append({"label": "Charts", "value": str(len(context.get("png_files", [])))})
    if chart_candidates:
        candidates = chart_candidates.get("candidates", []) if isinstance(chart_candidates.get("candidates", []), list) else []
        eligible = [item for item in candidates if isinstance(item, dict) and bool(item.get("allow_in_formal_body")) and not bool(item.get("diagnostic_only"))]
        cards.append({"label": "Report Audience", "value": str(chart_candidates.get("report_audience", "management"))})
        cards.append({"label": "Body Chart Candidates", "value": str(len(eligible))})
    if report_chart_decision:
        selected = report_chart_decision.get("selected_charts", []) if isinstance(report_chart_decision.get("selected_charts", []), list) else []
        cards.append({"label": "Body Chart Decision", "value": str(report_chart_decision.get("status", "draft"))})
        cards.append({"label": "Body Charts Selected", "value": str(len(selected))})
    modules = environment.get("modules", {})
    if modules:
        available = sum(bool(value) for value in modules.values())
        cards.append({"label": "Deps Available", "value": f"{available}/{len(modules)}"})
    return cards


def _render_formal_report_governance(context: dict[str, Any]) -> str:
    chart_candidates = context.get("chart_candidates") or {}
    report_chart_decision = context.get("report_chart_decision") or {}
    if not chart_candidates and not report_chart_decision:
        return ""
    candidates = chart_candidates.get("candidates", []) if isinstance(chart_candidates.get("candidates", []), list) else []
    eligible = [item for item in candidates if isinstance(item, dict) and bool(item.get("allow_in_formal_body")) and not bool(item.get("diagnostic_only"))]
    diagnostic = [item for item in candidates if isinstance(item, dict) and bool(item.get("diagnostic_only"))]
    selected = report_chart_decision.get("selected_charts", []) if isinstance(report_chart_decision.get("selected_charts", []), list) else []
    selected_html = "".join(
        f"<li>{_escape(item.get('title') or item.get('file') or 'chart')} ({_escape(item.get('file') or 'N/A')})</li>"
        for item in selected
        if isinstance(item, dict)
    )
    rows = [
        ("Report Audience", chart_candidates.get("report_audience") or report_chart_decision.get("report_audience") or "N/A"),
        ("Governed Candidates", len(candidates)),
        ("Eligible Body Charts", len(eligible)),
        ("Diagnostic-only Charts", len(diagnostic)),
        ("Decision Status", report_chart_decision.get("status", "not recorded")),
        ("Selected Body Charts", len(selected)),
    ]
    return f"""
    <section class="panel">
      <h2>Formal Report Governance</h2>
      <p class="lead">This dashboard stays read-only. It shows the formal-report governance metadata, but it does not replace `report_chart_decision.json` or the second-pass chart review workflow.</p>
      <table class="kv-table">{''.join(f"<tr><th>{_escape(label)}</th><td>{_escape(value)}</td></tr>" for label, value in rows)}</table>
      <ul class="bullet-list subtle">
        <li>Formal-report body charts should come from governed candidates, not arbitrary PNG discovery.</li>
        <li>Diagnostic-only or body-ineligible charts may still appear in the gallery because the dashboard keeps a full-run review view.</li>
      </ul>
      <h3>Current Body Chart Selection</h3>
      <ul class="bullet-list">{selected_html or '<li>No explicit body-chart decision recorded yet.</li>'}</ul>
    </section>
    """


def _render_cards(cards: list[dict[str, str]]) -> str:
    if not cards:
        return ""
    items = []
    for card in cards:
        items.append(
            f"""
            <div class="metric-card">
              <div class="metric-label">{_escape(card['label'])}</div>
              <div class="metric-value">{_escape(card['value'])}</div>
            </div>
            """
        )
    return f'<section class="metric-grid">{"".join(items)}</section>'


def _render_key_findings(context: dict[str, Any]) -> str:
    items: list[str] = []
    causal_narrative = context.get("causal_narrative_report") or {}
    experiment = context.get("experiment_report") or {}
    business = context.get("business_report") or {}
    analysis = context.get("analysis_report") or {}
    model_report = context.get("model_report") or {}
    explainability = context.get("explainability_report") or {}

    if causal_narrative:
        items.append(causal_narrative.get("headline", ""))
        items.append(causal_narrative.get("recommendation", ""))
    if experiment:
        decision = experiment.get("decision", {})
        items.append(f"Experiment decision: {decision.get('status', 'unknown')}.")
        if decision.get("summary"):
            items.append(decision["summary"])
    if business:
        for key in ["ltv", "pay_rate", "total_revenue", "retention"]:
            if key in business:
                items.append(f"{key}: {business[key]}")
    if analysis:
        task = analysis.get("task", "analysis")
        if task == "cluster":
            items.append(f"Selected {analysis.get('n_clusters', 'N/A')} clusters.")
        elif task == "anova":
            result = analysis.get("result", {})
            items.append(f"{result.get('test', 'ANOVA')} p-value: {_fmt_number(result.get('p_value'))}.")
        elif task == "root-cause":
            drivers = analysis.get("top_positive_drivers", [])
            if drivers:
                items.append(f"Top root-cause driver: {drivers[0].get('segment', 'N/A')}.")
    if model_report:
        task = model_report.get("task")
        best_model = _best_model_name_from_report(model_report, task=task)
        if best_model:
            items.append(f"Best baseline model: {best_model}.")
    if explainability:
        top_features = explainability.get("permutation_importance", [])
        if top_features:
            items.append(f"Top explainability feature: {top_features[0].get('feature', 'N/A')}.")

    if not items:
        items.append("No high-level findings were auto-detected from the current artifact set.")
    list_items = "".join(f"<li>{_escape(item)}</li>" for item in items if item)
    return f"""
    <section class="panel">
      <h2>Key Findings</h2>
      <ul class="bullet-list">{list_items}</ul>
    </section>
    """


def _render_data_quality(context: dict[str, Any]) -> str:
    cleaning = context.get("cleaning_report") or {}
    if not cleaning:
        return ""
    rows = [
        ("Rows", cleaning.get("shape", {}).get("rows")),
        ("Columns", cleaning.get("shape", {}).get("columns")),
        ("Missing Cells", cleaning.get("missing_values", {}).get("total_missing_cells")),
        ("Missing Columns", cleaning.get("missing_values", {}).get("columns_with_missing_values")),
        ("Duplicate Rows", cleaning.get("duplicates", {}).get("duplicate_rows")),
        ("Duplicate Ratio", _fmt_percent(cleaning.get("duplicates", {}).get("duplicate_ratio", 0.0))),
        ("Isolation Forest Outlier Ratio", _fmt_percent(cleaning.get("outliers_isolation_forest", {}).get("outlier_ratio"))),
    ]
    body = "".join(
        f"<tr><th>{_escape(label)}</th><td>{_escape(value)}</td></tr>"
        for label, value in rows
        if value is not None
    )
    preprocessing = cleaning.get("preprocessing_plan", [])
    preprocess_html = "".join(f"<li>{_escape(item)}</li>" for item in preprocessing[:8]) or "<li>No preprocessing suggestions recorded.</li>"
    return f"""
    <section class="panel two-col">
      <div>
        <h2>Data Quality</h2>
        <table class="kv-table">{body}</table>
      </div>
      <div>
        <h2>Preprocessing Plan</h2>
        <ul class="bullet-list">{preprocess_html}</ul>
      </div>
    </section>
    """


def _render_model_section(context: dict[str, Any]) -> str:
    model_report = context.get("model_report") or {}
    explainability = context.get("explainability_report") or {}
    if not model_report and not explainability:
        return ""
    best_model = None
    metrics_rows = ""
    if model_report:
        task = model_report.get("task")
        best_model = _best_model_name_from_report(model_report, task=task)
        if best_model:
            metrics = model_report.get("models", {}).get(best_model, {})
            metrics_rows = "".join(
                f"<tr><th>{_escape(key)}</th><td>{_escape(_fmt_number(value) if isinstance(value, (int, float)) else value)}</td></tr>"
                for key, value in metrics.items()
                if key.startswith("test_") and "error" not in key
            )
    top_features = explainability.get("permutation_importance", [])[:8]
    feature_html = "".join(
        f"<tr><th>{_escape(item.get('feature', 'N/A'))}</th><td>{_escape(_fmt_number(item.get('importance_mean')))}</td></tr>"
        for item in top_features
    )
    return f"""
    <section class="panel two-col">
      <div>
        <h2>Model Summary</h2>
        <p class="lead">{_escape(best_model or 'No supervised model summary available.')}</p>
        <table class="kv-table">{metrics_rows or '<tr><td colspan=\"2\">No ranking metrics found.</td></tr>'}</table>
      </div>
      <div>
        <h2>Explainability</h2>
        <table class="kv-table">{feature_html or '<tr><td colspan=\"2\">No permutation-importance output found.</td></tr>'}</table>
      </div>
    </section>
    """


def _render_business_section(context: dict[str, Any]) -> str:
    business = context.get("business_report") or {}
    if not business:
        return ""
    cards = []
    for key in ["users", "paying_users", "pay_rate", "total_revenue", "ltv", "cohort_size", "retention"]:
        if key in business:
            value = _fmt_percent(business[key]) if "rate" in key or key == "retention" else business[key]
            cards.append({"label": key.replace("_", " ").title(), "value": str(value)})
    extra = []
    if "steps" in business:
        extra.extend(
            f"{step.get('step', 'N/A')}: {step.get('count', 'N/A')} ({_fmt_percent(step.get('conversion_rate'))})"
            for step in business["steps"][:10]
        )
    if "cohorts" in business:
        extra.extend(
            f"{cohort}: LTV {values.get('ltv', 'N/A')}"
            for cohort, values in list(business["cohorts"].items())[:8]
        )
    if "cohort_sizes" in business:
        extra.extend(
            f"{cohort}: size {size}"
            for cohort, size in list(business["cohort_sizes"].items())[:8]
        )
    if "active_users_by_day_offset" in business:
        extra.extend(
            f"Day {offset}: {count} active users"
            for offset, count in list(business["active_users_by_day_offset"].items())[:8]
        )
    return f"""
    <section class="panel">
      <h2>Business KPIs</h2>
      {_render_cards(cards)}
      <ul class="bullet-list">{"".join(f"<li>{_escape(item)}</li>" for item in extra) or "<li>No additional KPI drilldown found.</li>"}</ul>
    </section>
    """


def _render_experiment_section(context: dict[str, Any]) -> str:
    report = context.get("experiment_report") or {}
    if not report:
        return ""
    decision = report.get("decision", {})
    variant_counts = report.get("variant_counts", {})
    variant_html = "".join(f"<tr><th>{_escape(name)}</th><td>{_escape(count)}</td></tr>" for name, count in variant_counts.items())
    metric_rows = []
    for metric_name, metric in list(report.get("metrics", {}).items())[:8]:
        adjusted_p = metric.get("multiple_testing", {}).get("adjusted_p_value")
        metric_rows.append(
            f"""
            <tr>
              <th>{_escape(metric_name)}</th>
              <td>{_escape(metric.get('role', 'N/A'))}</td>
              <td>{_escape(_fmt_number(metric.get('absolute_lift')))}</td>
              <td>{_escape(_fmt_number(metric.get('relative_lift')))}</td>
              <td>{_escape(_fmt_number(metric.get('p_value')))}</td>
              <td>{_escape(_fmt_number(adjusted_p) if adjusted_p is not None else 'N/A')}</td>
            </tr>
            """
        )
    return f"""
    <section class="panel two-col">
      <div>
        <h2>Experiment Decision</h2>
        <p class="headline">{_escape(decision.get('status', 'unknown'))}</p>
        <p>{_escape(decision.get('summary', ''))}</p>
        <table class="kv-table">{variant_html}</table>
      </div>
      <div>
        <h2>Metric Review</h2>
        <table class="wide-table">
          <thead><tr><th>Metric</th><th>Role</th><th>Abs Lift</th><th>Rel Lift</th><th>p-value</th><th>Adj p-value</th></tr></thead>
          <tbody>{''.join(metric_rows)}</tbody>
        </table>
      </div>
    </section>
    """


def _render_research_section(context: dict[str, Any]) -> str:
    report = context.get("research_report") or {}
    if not report:
        return ""
    lines = [
        f"Requests executed: {report.get('request_count', 0)}.",
        f"Deduplicated source candidates: {report.get('record_count_total', 0)}.",
        f"Conflicts flagged: {report.get('conflict_count_total', 0)}.",
    ]
    for directory in context.get("research_dirs", []):
        lines.append(f"Research artifact directory: {directory}/")
    return f"""
    <section class="panel">
      <h2>External Research</h2>
      <ul class="bullet-list">{''.join(f"<li>{_escape(item)}</li>" for item in lines)}</ul>
      <details><summary>Raw research report</summary><pre>{_escape(json.dumps(report, ensure_ascii=False, indent=2))}</pre></details>
    </section>
    """


def _render_analysis_section(context: dict[str, Any]) -> str:
    report = context.get("analysis_report") or {}
    if not report:
        return ""
    task = report.get("task", "analysis")
    bullets = [f"Task: {task}."]
    if task == "cluster":
        bullets.append(f"Selected {report.get('n_clusters', 'N/A')} clusters.")
    if task == "apriori":
        bullets.append(f"Generated {len(report.get('rules', []))} association rules.")
    if task == "anova":
        result = report.get("result", {})
        bullets.append(f"{result.get('test', 'test')} p-value: {_fmt_number(result.get('p_value'))}.")
    if task == "root-cause":
        top = report.get("top_positive_drivers", [])
        if top:
            bullets.append(f"Top positive driver: {top[0].get('segment', 'N/A')}.")
    return f"""
    <section class="panel">
      <h2>Analysis Method Output</h2>
      <ul class="bullet-list">{''.join(f'<li>{_escape(item)}</li>' for item in bullets)}</ul>
      <details><summary>Raw analysis report</summary><pre>{_escape(json.dumps(report, ensure_ascii=False, indent=2))}</pre></details>
    </section>
    """


def _render_causal_section(context: dict[str, Any]) -> str:
    narrative = context.get("causal_narrative_report") or {}
    report = context.get("causal_report") or {}
    if not narrative and not report:
        return ""
    if narrative:
        method_sections = narrative.get("method_sections", [])
        section_html = "".join(
            f"""
            <details class="method-detail">
              <summary>{_escape(section.get('method_label', 'Method'))}</summary>
              <p class="lead">{_escape(section.get('headline', ''))}</p>
              <p><strong>Recommendation:</strong> {_escape(section.get('recommendation', ''))}</p>
              <ul class="bullet-list">{''.join(f"<li>{_escape(item)}</li>" for item in section.get('diagnostics', []))}</ul>
              <ul class="bullet-list subtle">{''.join(f"<li>{_escape(item)}</li>" for item in section.get('risks_and_limits', [])) or '<li>No major method-specific risk was auto-flagged.</li>'}</ul>
            </details>
            """
            for section in method_sections
        )
        if not section_html:
            section_html = f"""
            <p class="lead">{_escape(narrative.get('headline', ''))}</p>
            <p><strong>Recommendation:</strong> {_escape(narrative.get('recommendation', ''))}</p>
            <ul class="bullet-list">{''.join(f"<li>{_escape(item)}</li>" for item in narrative.get('diagnostics', []))}</ul>
            """
        return f"""
        <section class="panel">
          <h2>Causal Narrative</h2>
          <p class="headline">{_escape(narrative.get('headline', ''))}</p>
          <p>{_escape(narrative.get('question', ''))}</p>
          <p><strong>Recommendation:</strong> {_escape(narrative.get('recommendation', ''))}</p>
          <ul class="bullet-list subtle">{''.join(f"<li>{_escape(item)}</li>" for item in narrative.get('risks_and_limits', [])) or '<li>No major top-level risk was auto-flagged.</li>'}</ul>
          {section_html}
        </section>
        """
    return f"""
    <section class="panel">
      <h2>Causal Report</h2>
      <details open><summary>Raw causal report</summary><pre>{_escape(json.dumps(report, ensure_ascii=False, indent=2))}</pre></details>
    </section>
    """


def _render_gallery(context: dict[str, Any]) -> str:
    images = context.get("png_files", [])
    if not images:
        return ""
    image_html = "".join(
        f"""
        <figure class="gallery-item">
          <img src="{_escape(image)}" alt="{_escape(image)}" loading="lazy" />
          <figcaption>{_escape(image)}</figcaption>
        </figure>
        """
        for image in images
    )
    return f"""
    <section class="panel">
      <h2>Chart Gallery</h2>
      <div class="gallery">{image_html}</div>
    </section>
    """


def _render_artifact_index(context: dict[str, Any]) -> str:
    files = context.get("json_files", []) + context.get("markdown_files", []) + context.get("csv_files", [])
    file_list = "".join(f"<li>{_escape(name)}</li>" for name in files)
    read_plan = context.get("read_plan")
    read_plan_html = _escape(json.dumps(read_plan, ensure_ascii=False, indent=2)) if read_plan else "N/A"
    return f"""
    <section class="panel two-col">
      <div>
        <h2>Artifact Index</h2>
        <ul class="bullet-list">{file_list}</ul>
      </div>
      <div>
        <h2>Read Plan</h2>
        <pre>{read_plan_html}</pre>
      </div>
    </section>
    """


def _build_html(context: dict[str, Any], title: str | None = None) -> str:
    task = (context.get("chart_plan") or {}).get("task", "analysis")
    heading = title or f"Data Analysis Dashboard: {task}"
    checked_at = ((context.get("environment") or {}).get("checked_at")) or "N/A"
    run_dir = context.get("run_dir", "")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_escape(heading)}</title>
  <style>
    :root {{
      --bg: #f7f3eb;
      --panel: #fffaf3;
      --ink: #182028;
      --muted: #6b7280;
      --accent: #0f766e;
      --accent-2: #b45309;
      --line: #e7dccd;
      --shadow: 0 10px 30px rgba(24, 32, 40, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, rgba(15,118,110,0.12), transparent 28%),
        radial-gradient(circle at left 20%, rgba(180,83,9,0.10), transparent 24%),
        var(--bg);
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    .hero {{
      padding: 28px 30px;
      border: 1px solid var(--line);
      border-radius: 24px;
      background: linear-gradient(135deg, rgba(255,250,243,0.96), rgba(246,240,228,0.98));
      box-shadow: var(--shadow);
      margin-bottom: 22px;
    }}
    .eyebrow {{
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent);
      font-size: 12px;
      margin-bottom: 10px;
      font-weight: 700;
    }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    h1 {{ font-size: 34px; line-height: 1.1; }}
    h2 {{ font-size: 22px; }}
    p {{ margin: 0 0 12px; line-height: 1.6; }}
    .meta {{
      display: flex;
      gap: 18px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 14px;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 14px;
      margin: 18px 0 0;
    }}
    .metric-card, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      box-shadow: var(--shadow);
    }}
    .metric-card {{
      padding: 16px 18px;
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      margin-bottom: 8px;
    }}
    .metric-value {{
      font-size: 24px;
      font-weight: 700;
    }}
    .panel {{
      padding: 22px 24px;
      margin-top: 18px;
    }}
    .two-col {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 20px;
    }}
    .bullet-list {{
      margin: 0;
      padding-left: 20px;
      line-height: 1.7;
    }}
    .bullet-list.subtle {{
      color: var(--muted);
    }}
    .headline {{
      font-size: 18px;
      font-weight: 700;
      color: var(--accent-2);
    }}
    .lead {{
      font-size: 16px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .kv-table th, .kv-table td, .wide-table th, .wide-table td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    .kv-table th {{
      width: 42%;
      color: var(--muted);
      font-weight: 600;
    }}
    .wide-table th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    details {{
      border-top: 1px solid var(--line);
      padding-top: 10px;
      margin-top: 10px;
    }}
    summary {{
      cursor: pointer;
      font-weight: 700;
      color: var(--accent);
    }}
    pre {{
      overflow-x: auto;
      padding: 12px;
      border-radius: 14px;
      background: #f4efe6;
      border: 1px solid var(--line);
      font-size: 12px;
      line-height: 1.5;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .gallery {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }}
    .gallery-item {{
      margin: 0;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: #fffdf8;
    }}
    .gallery-item img {{
      width: 100%;
      height: auto;
      border-radius: 12px;
      display: block;
    }}
    .gallery-item figcaption {{
      margin-top: 8px;
      font-size: 12px;
      color: var(--muted);
    }}
    @media (max-width: 720px) {{
      .wrap {{ padding: 18px 14px 34px; }}
      .hero {{ padding: 22px 18px; border-radius: 18px; }}
      h1 {{ font-size: 28px; }}
      .panel {{ padding: 18px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="eyebrow">Data Analysis Report</div>
      <h1>{_escape(heading)}</h1>
      <p>Static dashboard exported from the run directory so agents and humans can review one artifact instead of many raw JSON files.</p>
      <div class="meta">
        <span>Task: {_escape(task)}</span>
        <span>Checked at: {_escape(checked_at)}</span>
        <span>Run dir: {_escape(run_dir)}</span>
      </div>
      {_render_cards(_summary_cards(context))}
    </section>
    {_render_key_findings(context)}
    {_render_data_quality(context)}
    {_render_business_section(context)}
    {_render_experiment_section(context)}
    {_render_research_section(context)}
    {_render_analysis_section(context)}
    {_render_model_section(context)}
    {_render_formal_report_governance(context)}
    {_render_causal_section(context)}
    {_render_gallery(context)}
    {_render_artifact_index(context)}
  </div>
</body>
</html>
"""


def export_dashboard(run_dir: Path, output_path: Path | None = None, title: str | None = None) -> Path:
    context = _collect_run_context(run_dir)
    path = output_path or (run_dir / "report_dashboard.html")
    path.write_text(_build_html(context, title=title))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a static HTML dashboard from a data-analysis run directory.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output-path")
    parser.add_argument("--title")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    output_path = Path(args.output_path) if args.output_path else None
    path = export_dashboard(run_dir, output_path=output_path, title=args.title)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
