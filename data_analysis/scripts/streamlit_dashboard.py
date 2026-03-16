#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import _configure_runtime_environment
from report_export import _collect_run_context
from report_index import build_run_index, export_run_index

_configure_runtime_environment()

DEFAULT_OUTPUTS_ROOT = Path(__file__).resolve().parents[1] / "outputs"
APP_TITLE = "Data Analysis Atlas"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--outputs-root", default=str(DEFAULT_OUTPUTS_ROOT))
    parser.add_argument("--refresh-index", action="store_true")
    parser.add_argument("--default-task")
    parser.add_argument("--default-group")
    args, _unknown = parser.parse_known_args(sys.argv[1:])
    return args


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
          --paper: #f6f1e7;
          --paper-2: #efe5d4;
          --ink: #14281d;
          --muted: #5d6b63;
          --accent: #0f766e;
          --accent-2: #c97c2c;
          --line: rgba(20, 40, 29, 0.12);
          --card: rgba(255, 255, 255, 0.72);
        }
        .stApp {
          background:
            radial-gradient(circle at top left, rgba(201,124,44,0.16), transparent 28%),
            radial-gradient(circle at top right, rgba(15,118,110,0.14), transparent 24%),
            linear-gradient(180deg, var(--paper), #fbf8f1 36%, #f2eadc 100%);
          color: var(--ink);
        }
        .block-container {
          padding-top: 1.2rem;
          padding-bottom: 2rem;
          max-width: 1400px;
        }
        h1, h2, h3 {
          font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", Georgia, serif;
          color: var(--ink);
          letter-spacing: -0.02em;
        }
        .atlas-hero {
          background: linear-gradient(135deg, rgba(20,40,29,0.96), rgba(15,118,110,0.92));
          color: #f8f4eb;
          border-radius: 24px;
          padding: 1.5rem 1.4rem 1.35rem 1.4rem;
          border: 1px solid rgba(255,255,255,0.12);
          box-shadow: 0 24px 60px rgba(20,40,29,0.18);
          margin-bottom: 1rem;
        }
        .atlas-kicker {
          text-transform: uppercase;
          letter-spacing: 0.18em;
          font-size: 0.72rem;
          opacity: 0.8;
          margin-bottom: 0.6rem;
        }
        .atlas-sub {
          color: rgba(248,244,235,0.82);
          font-size: 0.98rem;
          max-width: 54rem;
          margin-top: 0.45rem;
        }
        .atlas-card {
          background: var(--card);
          border: 1px solid var(--line);
          border-radius: 18px;
          padding: 1rem 1rem 0.9rem 1rem;
          box-shadow: 0 12px 32px rgba(20,40,29,0.08);
          backdrop-filter: blur(8px);
          min-height: 110px;
        }
        .atlas-card-label {
          color: var(--muted);
          text-transform: uppercase;
          letter-spacing: 0.12em;
          font-size: 0.72rem;
          margin-bottom: 0.42rem;
        }
        .atlas-card-value {
          color: var(--ink);
          font-size: 1.75rem;
          font-weight: 700;
          line-height: 1.05;
        }
        .atlas-card-note {
          color: var(--muted);
          font-size: 0.88rem;
          margin-top: 0.42rem;
        }
        .atlas-chip-row {
          display: flex;
          flex-wrap: wrap;
          gap: 0.45rem;
          margin-top: 0.35rem;
          margin-bottom: 0.65rem;
        }
        .atlas-chip {
          display: inline-block;
          padding: 0.26rem 0.6rem;
          border-radius: 999px;
          background: rgba(15,118,110,0.12);
          border: 1px solid rgba(15,118,110,0.15);
          color: var(--ink);
          font-size: 0.82rem;
        }
        .atlas-panel {
          background: rgba(255,255,255,0.62);
          border: 1px solid var(--line);
          border-radius: 18px;
          padding: 1rem 1rem 0.9rem 1rem;
          box-shadow: 0 14px 34px rgba(20,40,29,0.06);
          margin-bottom: 0.9rem;
        }
        .atlas-small {
          color: var(--muted);
          font-size: 0.88rem;
        }
        .atlas-rule {
          border-top: 1px solid var(--line);
          margin: 0.85rem 0 0.65rem 0;
        }
        [data-testid="stSidebar"] {
          background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(244,236,221,0.96));
          border-right: 1px solid rgba(20,40,29,0.08);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _stringify_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


@st.cache_data(show_spinner=False)
def _load_index(outputs_root_str: str, refresh: bool) -> dict[str, Any]:
    outputs_root = Path(outputs_root_str)
    if refresh or not (outputs_root / "run_index.json").exists():
        export_run_index(outputs_root)
    payload = _safe_read_json(outputs_root / "run_index.json")
    if payload is not None:
        return payload
    return build_run_index(outputs_root)


@st.cache_data(show_spinner=False)
def _load_run_context(run_dir_str: str) -> dict[str, Any]:
    return _collect_run_context(Path(run_dir_str))


def _task_options(index: dict[str, Any]) -> list[str]:
    return sorted({str(run.get("task") or "unknown") for run in index.get("runs", [])})


def _group_options(index: dict[str, Any]) -> list[str]:
    return sorted({str(run.get("group") or "ungrouped") for run in index.get("runs", [])})


def _filter_runs(index: dict[str, Any], tasks: list[str], groups: list[str], query: str) -> list[dict[str, Any]]:
    query = query.strip().lower()
    runs = index.get("runs", [])
    filtered = []
    for run in runs:
        if tasks and run.get("task") not in tasks:
            continue
        if groups and run.get("group") not in groups:
            continue
        haystack = " ".join(
            str(run.get(key) or "")
            for key in ["task", "group", "summary", "headline", "relative_path", "decision_status", "key_metric"]
        ).lower()
        if query and query not in haystack:
            continue
        filtered.append(run)
    filtered.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return filtered


def _render_hero(index: dict[str, Any], filtered_runs: list[dict[str, Any]]) -> None:
    latest = filtered_runs[0] if filtered_runs else None
    latest_text = latest.get("relative_path") if latest else "No run selected"
    st.markdown(
        f"""
        <div class="atlas-hero">
          <div class="atlas-kicker">Interactive Analysis Review</div>
          <h1 style="margin:0;">{APP_TITLE}</h1>
          <div class="atlas-sub">
            Browse historical runs, inspect narratives and artifacts, and compare related analyses without leaving the skill workspace.
            Latest visible run: <strong>{latest_text}</strong>.
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    run_count = len(filtered_runs)
    task_count = len({run.get("task") for run in filtered_runs})
    group_count = len({run.get("group") for run in filtered_runs})
    chart_count = sum(int(run.get("charts") or 0) for run in filtered_runs)
    cards = [
        ("Visible Runs", str(run_count), "Current filter scope"),
        ("Tasks", str(task_count), "Distinct task types"),
        ("Groups", str(group_count), "Output subtrees represented"),
        ("Charts", str(chart_count), "PNG artifacts across visible runs"),
    ]
    cols = st.columns(len(cards))
    for col, (label, value, note) in zip(cols, cards):
        col.markdown(
            f"""
            <div class="atlas-card">
              <div class="atlas-card-label">{label}</div>
              <div class="atlas-card-value">{value}</div>
              <div class="atlas-card-note">{note}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _runs_dataframe(runs: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "timestamp": run.get("timestamp"),
                "task": run.get("task"),
                "group": run.get("group"),
                "rows": run.get("rows"),
                "columns": run.get("columns"),
                "charts": run.get("charts"),
                "decision": run.get("decision_status"),
                "summary": run.get("headline") or run.get("summary"),
                "relative_path": run.get("relative_path"),
            }
            for run in runs
        ]
    )
    return frame


def _numeric_compare_dataframe(runs: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for run in runs:
        row = {
            "timestamp": run.get("timestamp"),
            "task": run.get("task"),
            "group": run.get("group"),
            "relative_path": run.get("relative_path"),
        }
        for key, value in (run.get("compare_fields") or {}).items():
            row[key] = value
        rows.append(row)
    frame = pd.DataFrame(rows)
    for column in frame.columns:
        if column in {"timestamp", "task", "group", "relative_path"}:
            frame[column] = frame[column].map(_stringify_value)
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.notna().any():
            frame[column] = numeric
        else:
            frame[column] = frame[column].map(_stringify_value)
    return frame


def _render_overview(index: dict[str, Any], filtered_runs: list[dict[str, Any]]) -> None:
    left, right = st.columns([1.1, 0.9])
    with left:
        task_counts = pd.DataFrame(
            [{"task": task, "count": count} for task, count in sorted(index.get("task_counts", {}).items(), key=lambda item: item[1], reverse=True)]
        )
        if not task_counts.empty:
            fig = px.bar(
                task_counts,
                x="count",
                y="task",
                orientation="h",
                color="count",
                color_continuous_scale=["#d8b07c", "#0f766e"],
                title="Run Count by Task",
            )
            fig.update_layout(height=420, margin=dict(l=10, r=10, t=52, b=10), coloraxis_showscale=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig, width="stretch")
    with right:
        frame = _runs_dataframe(filtered_runs)
        if not frame.empty:
            timeline = frame.copy()
            timeline["date"] = pd.to_datetime(timeline["timestamp"], errors="coerce").dt.strftime("%Y-%m-%d")
            daily = timeline.groupby("date", dropna=True).size().reset_index(name="runs")
            if not daily.empty:
                fig = px.area(
                    daily,
                    x="date",
                    y="runs",
                    title="Visible Runs Over Time",
                    color_discrete_sequence=["#c97c2c"],
                )
                fig.update_layout(height=420, margin=dict(l=10, r=10, t=52, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, width="stretch")

    st.markdown('<div class="atlas-panel">', unsafe_allow_html=True)
    st.subheader("Recent Runs")
    for run in filtered_runs[:8]:
        chips = " ".join(
            f'<span class="atlas-chip">{label}</span>'
            for label in [str(run.get("task") or "unknown"), str(run.get("group") or "ungrouped"), str(run.get("decision_status") or "no-decision")]
        )
        st.markdown(
            f"""
            <div style="padding:0.55rem 0 0.7rem 0;">
              <div style="font-weight:700;">{run.get('relative_path')}</div>
              <div class="atlas-chip-row">{chips}</div>
              <div class="atlas-small">{run.get('headline') or run.get('summary') or 'No summary extracted.'}</div>
            </div>
            <div class="atlas-rule"></div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _context_cards(run: dict[str, Any], context: dict[str, Any]) -> list[tuple[str, str, str]]:
    cleaning = context.get("cleaning_report") or {}
    shape = cleaning.get("shape") or {}
    cards = [
        ("Task", str(run.get("task") or "unknown"), "Run task"),
        ("Group", str(run.get("group") or "ungrouped"), "Outputs subtree"),
        ("Rows", str(shape.get("rows") or run.get("rows") or "N/A"), "Detected row count"),
        ("Charts", str(run.get("charts") or 0), "PNG outputs"),
    ]
    return cards


def _render_run_detail(run: dict[str, Any]) -> None:
    context = _load_run_context(str(run["run_dir"]))
    cards = _context_cards(run, context)
    cols = st.columns(len(cards))
    for col, (label, value, note) in zip(cols, cards):
        col.markdown(
            f"""
            <div class="atlas-card">
              <div class="atlas-card-label">{label}</div>
              <div class="atlas-card-value" style="font-size:1.3rem;">{value}</div>
              <div class="atlas-card-note">{note}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown('<div class="atlas-panel">', unsafe_allow_html=True)
    st.subheader("Run Metadata")
    st.caption(run["run_dir"])
    chip_labels = [str(run.get("task") or "unknown"), str(run.get("group") or "ungrouped")]
    if run.get("decision_status"):
        chip_labels.append(str(run["decision_status"]))
    if run.get("headline"):
        st.markdown(f"**Headline**: {run['headline']}")
    st.markdown(
        "".join(f'<span class="atlas-chip">{label}</span>' for label in chip_labels),
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    summary_tab, details_tab, artifacts_tab = st.tabs(["Narrative", "Task Details", "Artifacts"])
    with summary_tab:
        if context.get("run_summary_markdown"):
            st.markdown(context["run_summary_markdown"])
        if context.get("causal_narrative_markdown"):
            st.markdown("---")
            st.markdown(context["causal_narrative_markdown"])
        research = context.get("research_report") or {}
        if research:
            st.markdown("---")
            st.subheader("External Research")
            c1, c2, c3 = st.columns(3)
            c1.metric("Requests", research.get("request_count", 0))
            c2.metric("Deduped Records", research.get("record_count_total", 0))
            c3.metric("Conflicts", research.get("conflict_count_total", 0))
    with details_tab:
        for label, key in [
            ("Business", "business_report"),
            ("Experiment", "experiment_report"),
            ("Analysis", "analysis_report"),
            ("Causal", "causal_report"),
            ("Causal Narrative", "causal_narrative_report"),
            ("Model", "model_report"),
            ("Explainability", "explainability_report"),
            ("Research", "research_report"),
        ]:
            payload = context.get(key) or {}
            if not payload:
                continue
            with st.expander(label, expanded=label in {"Experiment", "Causal"}):
                st.json(payload)
        png_files = context.get("png_files") or []
        if png_files:
            st.subheader("Chart Gallery")
            image_cols = st.columns(2)
            for index, image_name in enumerate(png_files):
                image_cols[index % 2].image(str(Path(run["run_dir"]) / image_name), caption=image_name, width="stretch")
    with artifacts_tab:
        st.markdown("**Markdown artifacts**")
        for name in context.get("markdown_files") or []:
            path = Path(run["run_dir"]) / name
            with st.expander(name):
                st.code(path.read_text()[:12000], language="markdown")
        st.markdown("**JSON artifacts**")
        for name in context.get("json_files") or []:
            path = Path(run["run_dir"]) / name
            with st.expander(name):
                payload = _safe_read_json(path)
                if payload is not None:
                    st.json(payload)
                else:
                    st.code(path.read_text()[:12000], language="json")
        csv_files = context.get("csv_files") or []
        if csv_files:
            st.markdown("**CSV artifacts**")
            for name in csv_files:
                path = Path(run["run_dir"]) / name
                with st.expander(name):
                    try:
                        st.dataframe(pd.read_csv(path).head(100), width="stretch")
                    except Exception as exc:
                        st.error(str(exc))


def _render_comparison(filtered_runs: list[dict[str, Any]]) -> None:
    if not filtered_runs:
        st.info("No runs match the current filters.")
        return
    frame = _numeric_compare_dataframe(filtered_runs)
    if frame.empty:
        st.info("No comparison fields are available for the current run selection.")
        return
    st.dataframe(frame, width="stretch", hide_index=True)

    numeric_columns = [
        column
        for column in frame.columns
        if column not in {"timestamp", "task", "group", "relative_path"} and pd.api.types.is_numeric_dtype(frame[column])
    ]
    if not numeric_columns:
        return
    metric = st.selectbox("Comparison metric", numeric_columns, index=0, key="comparison_metric")
    chart_frame = frame[["relative_path", "task", metric]].dropna(subset=[metric]).sort_values(metric, ascending=False)
    if chart_frame.empty:
        st.info("Selected metric has no numeric values in the current filter scope.")
        return
    fig = px.bar(
        chart_frame.head(20),
        x=metric,
        y="relative_path",
        color="task",
        orientation="h",
        title=f"Top runs by {metric}",
        color_discrete_sequence=["#0f766e", "#c97c2c", "#355070", "#6d597a", "#bc4749"],
    )
    fig.update_layout(height=max(360, 34 * min(len(chart_frame), 20)), margin=dict(l=10, r=10, t=52, b=10), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch")


def main() -> None:
    args = _parse_args()
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    _inject_styles()

    outputs_root = Path(args.outputs_root)
    st.sidebar.title("Atlas Controls")
    st.sidebar.caption("Interactive browser for data-analysis outputs.")
    refresh_index = st.sidebar.button("Refresh Index Now") or args.refresh_index
    outputs_root_value = st.sidebar.text_input("Outputs Root", value=str(outputs_root))
    index = _load_index(outputs_root_value, refresh=refresh_index)

    tasks = _task_options(index)
    groups = _group_options(index)
    selected_tasks = st.sidebar.multiselect("Tasks", options=tasks, default=[args.default_task] if args.default_task in tasks else [])
    selected_groups = st.sidebar.multiselect("Groups", options=groups, default=[args.default_group] if args.default_group in groups else [])
    search_text = st.sidebar.text_input("Search", placeholder="task, group, summary, headline")

    filtered_runs = _filter_runs(index, tasks=selected_tasks, groups=selected_groups, query=search_text)
    _render_hero(index, filtered_runs)

    overview_tab, runs_tab, detail_tab, compare_tab = st.tabs(["Overview", "Runs", "Selected Run", "Compare"])

    with overview_tab:
        _render_overview(index, filtered_runs)

    with runs_tab:
        st.subheader("Filtered Run Table")
        frame = _runs_dataframe(filtered_runs)
        if frame.empty:
            st.info("No runs match the current filters.")
        else:
            st.dataframe(frame, width="stretch", hide_index=True)

    with detail_tab:
        if not filtered_runs:
            st.info("No runs available to inspect.")
        else:
            labels = [f"{run['timestamp']} | {run['task']} | {run['relative_path']}" for run in filtered_runs]
            selected_label = st.selectbox("Run", options=labels, index=0)
            selected_run = filtered_runs[labels.index(selected_label)]
            _render_run_detail(selected_run)

    with compare_tab:
        st.subheader("Task-Aware Comparison")
        _render_comparison(filtered_runs)


if __name__ == "__main__":
    main()
