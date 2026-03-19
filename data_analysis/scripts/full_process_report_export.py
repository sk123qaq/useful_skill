#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

KNOWN_JSON_ARTIFACTS = {
    "environment": "environment.json",
    "read_plan": "read_plan.json",
    "sampling_report": "sampling_report.json",
    "semantic_schema": "semantic_schema.json",
    "feature_lineage": "feature_lineage.json",
    "chart_plan": "chart_plan.json",
    "chart_candidates": "chart_candidates.json",
    "report_chart_decision": "report_chart_decision.json",
    "chart_review": "chart_review.json",
    "chart_vision_review": "chart_vision_review.json",
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

TASK_LABELS = {
    "analysis": "通用分析",
    "clustering": "聚类分析",
    "cluster": "聚类分析",
    "classification": "分类建模",
    "regression": "回归建模",
    "experiment": "实验分析",
    "ab-test": "实验分析",
    "did": "因果分析（DID）",
    "rd": "因果分析（RD）",
    "causal": "因果分析",
}


def _escape(value: Any) -> str:
    return html.escape(str(value))


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


def _read_json_with_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "data": None, "message": "artifact not found"}
    try:
        content = json.loads(path.read_text())
    except Exception as exc:  # noqa: BLE001
        return {"status": "parse_error", "data": None, "message": str(exc)}
    if content in ({}, [], ""):
        return {"status": "empty", "data": content, "message": "artifact is empty"}
    return {"status": "ok", "data": content, "message": "ok"}


def _read_text_with_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "data": None, "message": "artifact not found"}
    try:
        content = path.read_text()
    except Exception as exc:  # noqa: BLE001
        return {"status": "parse_error", "data": None, "message": str(exc)}
    if not content.strip():
        return {"status": "empty", "data": content, "message": "artifact is empty"}
    return {"status": "ok", "data": content, "message": "ok"}


def _canonical_heading(text: str) -> str:
    normalized = text.strip().lower()
    aliases = {
        "background": "background",
        "背景": "background",
        "insight": "findings",
        "findings": "findings",
        "发现": "findings",
        "recommendation": "recommendation",
        "recommendations": "recommendation",
        "建议": "recommendation",
        "risk": "risk",
        "risks": "risk",
        "风险": "risk",
    }
    return aliases.get(normalized, normalized)


def _collect_run_context(run_dir: Path) -> dict[str, Any]:
    context: dict[str, Any] = {
        "run_dir": str(run_dir),
        "json_files": sorted(path.name for path in run_dir.glob("*.json")),
        "markdown_files": sorted(path.name for path in run_dir.glob("*.md")),
        "csv_files": sorted(path.name for path in run_dir.glob("*.csv")),
        "png_files": sorted(path.name for path in run_dir.glob("*.png")),
        "artifact_status": {},
    }

    for key, file_name in KNOWN_JSON_ARTIFACTS.items():
        record = _read_json_with_status(run_dir / file_name)
        context[key] = record["data"]
        context["artifact_status"][key] = {
            "status": record["status"],
            "message": record["message"],
            "file": file_name,
        }

    run_summary_record = _read_text_with_status(run_dir / "run_summary.md")
    context["run_summary_markdown"] = run_summary_record["data"]
    context["artifact_status"]["run_summary_markdown"] = {
        "status": run_summary_record["status"],
        "message": run_summary_record["message"],
        "file": "run_summary.md",
    }
    return context


def _extract_markdown_bullets(text: str | None, headings: set[str]) -> list[str]:
    if not text:
        return []
    current = None
    wanted = {_canonical_heading(item) for item in headings}
    output: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current = _canonical_heading(line[3:].strip())
            continue
        if current in wanted and line.startswith("- "):
            output.append(line[2:].strip())
    return output


def _localize_warning(text: str) -> str:
    replacements = {
        "No input source provided.": "未提供输入数据源。",
        "Input path does not exist.": "输入路径不存在。",
        "Supported formats: csv, tsv, xlsx, xlsm, xls, xlsb, parquet, feather, json, jsonl.": "支持格式：csv、tsv、xlsx、xlsm、xls、xlsb、parquet、feather、json、jsonl。",
        "Excel is fragile for large datasets. Consider converting to CSV or Parquet first.": "Excel 处理大数据较脆弱，建议先转为 CSV 或 Parquet。",
        "A worksheet cannot exceed 1,048,576 rows.": "单个工作表不能超过 1,048,576 行。",
        "Archive inputs are read from the selected member only; inspect other members if joins are expected.": "压缩包输入只读取当前选中的成员文件；如果预期需要联表，请检查其他成员文件。",
        "Compressed input detected via": "检测到压缩输入，行数只能基于压缩后的字节大小估计。",
        "Multiple supported files detected. Auto-selected": "检测到多个可用文件，已自动选择",
        "Directory input auto-selected": "目录输入已自动选择",
    }
    translated = text
    for source, target in replacements.items():
        if source in translated:
            translated = translated.replace(source, target)
    return translated


def _as_missing_mapping(missing_by_column: dict[str, Any], total_rows: int | None) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for col, value in missing_by_column.items():
        if isinstance(value, dict):
            count = value.get("missing_count")
            ratio = value.get("missing_ratio")
        else:
            count = value
            try:
                ratio = (float(value) / float(total_rows)) if total_rows else None
            except (TypeError, ValueError):
                ratio = None
        mapping[str(col)] = {"missing_count": count, "missing_ratio": ratio}
    return mapping


def _top_correlation_pairs(correlation_matrix: dict[str, Any], limit: int = 5) -> list[tuple[str, str, float]]:
    pairs: list[tuple[str, str, float]] = []
    seen: set[tuple[str, str]] = set()
    for left, row in correlation_matrix.items():
        if not isinstance(row, dict):
            continue
        for right, value in row.items():
            if left == right:
                continue
            key = tuple(sorted((str(left), str(right))))
            if key in seen:
                continue
            seen.add(key)
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            pairs.append((str(left), str(right), number))
    pairs.sort(key=lambda item: abs(item[2]), reverse=True)
    return pairs[:limit]


def _cluster_signal_bundle(analysis_report: dict[str, Any]) -> dict[str, Any]:
    cluster_sizes = analysis_report.get("cluster_sizes", []) if isinstance(analysis_report.get("cluster_sizes", []), list) else []
    profiles = analysis_report.get("cluster_profiles", []) if isinstance(analysis_report.get("cluster_profiles", []), list) else []

    total = sum(int(item.get("country_count", 0)) for item in cluster_sizes) if cluster_sizes else 0
    smallest_share = None
    if total > 0 and cluster_sizes:
        shares = [float(item.get("country_count", 0)) / float(total) for item in cluster_sizes]
        smallest_share = min(shares)

    def _range_of(key: str) -> float | None:
        values = []
        for item in profiles:
            try:
                values.append(float(item.get(key)))
            except (TypeError, ValueError):
                continue
        if len(values) < 2:
            return None
        return max(values) - min(values)

    return {
        "cluster_count": analysis_report.get("n_clusters"),
        "silhouette": analysis_report.get("silhouette_score"),
        "smallest_share": smallest_share,
        "internet_gap": _range_of("IT.NET.USER.ZS"),
        "electricity_gap": _range_of("EG.ELC.ACCS.ZS"),
    }


def _normalize_chart_review(review: dict[str, Any] | None) -> tuple[dict[str, dict[str, Any]], str | None]:
    if not review or not isinstance(review, dict):
        return {}, None
    rows = review.get("charts", [])
    if not isinstance(rows, list):
        rows = review.get("selected_charts", [])
    if not isinstance(rows, list):
        rows = []
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        file_name = row.get("file")
        title = row.get("title")
        if file_name:
            mapping[str(file_name)] = row
        if title:
            mapping[f"title::{title}"] = row
    overall = review.get("overall_summary")
    return mapping, str(overall) if overall else None


def _chart_candidate_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    payload = context.get("chart_candidates") or {}
    rows = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _selected_body_chart_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    payload = context.get("report_chart_decision") or {}
    rows = payload.get("selected_charts") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _chart_governance_summary(context: dict[str, Any]) -> dict[str, Any]:
    candidates = _chart_candidate_rows(context)
    selected = _selected_body_chart_rows(context)
    candidate_by_file = {str(item.get("file")): item for item in candidates if item.get("file")}
    eligible = [item for item in candidates if bool(item.get("allow_in_formal_body")) and not bool(item.get("diagnostic_only"))]
    diagnostic = [item for item in candidates if bool(item.get("diagnostic_only"))]
    report_chart_decision = context.get("report_chart_decision") or {}
    chart_review = context.get("chart_review") or {}
    audience = (
        report_chart_decision.get("report_audience")
        or (context.get("chart_candidates") or {}).get("report_audience")
        or "management"
    )
    if selected:
        status = "正式正文图已决策" if str(report_chart_decision.get("status") or "").strip().lower() == "final" else "已生成正文图草稿决策"
    elif candidates:
        status = "已生成候选池，待回填正文图决策"
    else:
        status = "当前 run 未生成正文图治理元数据"
    notes: list[str] = []
    if candidates:
        notes.append("正式报告正文图应从 chart_candidates 约束的候选池中选择，而不是从任意 PNG 任取。")
        notes.append("diagnostic_only=true 或 allow_in_formal_body=false 的图默认不进入正文。")
    if str(chart_review.get("status") or "").strip().lower() == "final":
        notes.append("chart_review 已完成逐图自然语言复核，可直接支撑正式报告定稿。")
    elif selected:
        notes.append("当前已有正文图选择结果，但图表自然语言解读仍可能处于草稿阶段。")
    selected_files = [str(item.get("file")) for item in selected if item.get("file")]
    return {
        "status": status,
        "report_audience": str(audience),
        "candidate_count": len(candidates),
        "eligible_count": len(eligible),
        "diagnostic_count": len(diagnostic),
        "selected_count": len(selected),
        "selected_files": selected_files,
        "candidate_by_file": candidate_by_file,
        "selected_files_set": set(selected_files),
        "notes": notes,
    }


def _split_sentences(text: str | None) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[。！？!?]+", str(text).replace("\n", " "))
    cleaned = [part.strip(" ;；，,。") for part in parts if part and part.strip(" ;；，,。")]
    return cleaned


def _first_sentence_with_digit(text: str | None) -> str | None:
    for sentence in _split_sentences(text):
        if any(ch.isdigit() for ch in sentence):
            return sentence
    return None


def _merge_sentences(text: str | None, limit: int = 2) -> str:
    sentences = _split_sentences(text)
    if not sentences:
        return ""
    return "。".join(sentences[:limit]) + "。"


def _dedupe_sentences_text(text: str | None, limit: int = 4) -> str:
    unique: list[str] = []
    seen: set[str] = set()
    for sentence in _split_sentences(text):
        if sentence in seen:
            continue
        seen.add(sentence)
        unique.append(sentence)
    if not unique:
        return ""
    return "。".join(unique[:limit]) + "。"


def _strip_chart_template_openers(text: str | None) -> str:
    sentences = _split_sentences(text)
    if not sentences:
        return ""
    filtered: list[str] = []
    openers = ("这张图围绕", "该图围绕", "本图围绕", "这张图用于", "该图用于", "本图用于")
    for idx, sentence in enumerate(sentences):
        if idx == 0 and sentence.startswith(openers) and len(sentences) > 1:
            continue
        filtered.append(sentence)
    if not filtered:
        filtered = sentences
    return "。".join(filtered) + "。"


def _default_read_method(title: str, file_name: str | None) -> str:
    text = f"{title} {file_name or ''}".lower()
    if "trend" in text or "趋势" in text or "line" in text:
        return "先看整体趋势方向，再看拐点与国家间增速差异。"
    if "scatter" in text or "散点" in text:
        return "先看点云整体方向，再看离群点与重点对象位置。"
    if "bar" in text or "柱" in text:
        return "先做同组对比，再做跨组对比，关注差距是否稳定。"
    if "heatmap" in text or "热力" in text:
        return "先按行看群组轮廓，再按列看关键指标的高低分化。"
    return "先看整体结构，再聚焦差异最大的对象和区间。"


def _diagnostic_chart_reason(candidate_meta: dict[str, Any] | None, meaning: str, read_tip: str) -> str:
    reasons: list[str] = []
    if candidate_meta:
        if bool(candidate_meta.get("diagnostic_only")):
            reasons.append("该图被治理层标记为诊断图，默认用于过程审阅或附录，不直接进入正式报告正文。")
        elif not bool(candidate_meta.get("allow_in_formal_body", True)):
            reasons.append("该图当前不满足正式报告正文准入条件，因此保留在过程报告中供复核。")
        audience_fit = candidate_meta.get("audience_fit") or {}
        if audience_fit.get("management") == "low":
            reasons.append("按当前 management 受众口径，它更适合分析复核而不是管理层正文。")
    normalized_meaning = meaning.strip()
    if normalized_meaning.startswith("帮助理解") and "边际影响" in normalized_meaning:
        focus = normalized_meaning.removeprefix("帮助理解").strip(" 。")
        reasons.append(f"保留这张图是为了核对 {focus} 是否稳定，而不是直接把它当成正式结论。")
    elif normalized_meaning:
        reasons.append(_merge_sentences(normalized_meaning, limit=1))
    elif read_tip:
        reasons.append(f"保留这张图主要用于过程复核：{_merge_sentences(read_tip, limit=1)}")
    return " ".join(part for part in reasons if part).strip() or "该图保留用于过程审阅，帮助确认模型或分析路径中的局部信号。"


def _derive_report_brain(context: dict[str, Any]) -> dict[str, Any]:
    read_plan = context.get("read_plan") or {}
    sampling_report = context.get("sampling_report") or {}
    cleaning = context.get("cleaning_report") or {}
    stats = context.get("stats_report") or {}
    analysis = context.get("analysis_report") or {}
    chart_plan = context.get("chart_plan") or {}
    run_summary = context.get("run_summary_markdown")

    shape = cleaning.get("shape", {})
    rows = int(shape.get("rows", 0)) if shape.get("rows") is not None else 0
    cols = int(shape.get("columns", 0)) if shape.get("columns") is not None else 0

    missing = cleaning.get("missing_values", {})
    missing_total = missing.get("total_missing_cells")
    missing_ratio = None
    if rows > 0 and cols > 0 and missing_total is not None:
        missing_ratio = float(missing_total) / float(rows * cols)

    missing_map = _as_missing_mapping(missing.get("by_column", {}), rows)
    top_missing = sorted(
        missing_map.items(),
        key=lambda item: float(item[1].get("missing_ratio") or 0.0),
        reverse=True,
    )[:5]

    correlations = _top_correlation_pairs(stats.get("correlation_matrix", {}), limit=5)
    cluster_signals = _cluster_signal_bundle(analysis)

    task = str(chart_plan.get("task") or analysis.get("task") or "analysis")
    task_label = TASK_LABELS.get(task, TASK_LABELS["analysis"])

    insight_lines = _extract_markdown_bullets(run_summary, {"insight", "findings"})
    recommendation_lines = _extract_markdown_bullets(run_summary, {"recommendation"})
    risk_lines = _extract_markdown_bullets(run_summary, {"risk"})

    key_findings: list[str] = []
    evidence_map: list[str] = []

    if task in {"cluster", "clustering"} and cluster_signals.get("cluster_count"):
        key_findings.append(
            "分群结果具备策略分层价值："
            + f"K={cluster_signals['cluster_count']}，轮廓系数={_fmt_number(cluster_signals.get('silhouette'), 3)}。"
        )
        evidence_map.append("analysis_report.silhouette_score")

        if cluster_signals.get("internet_gap") is not None and cluster_signals.get("electricity_gap") is not None:
            key_findings.append(
                "基础能力分化明显："
                + f"互联网使用率组间差约 {_fmt_number(cluster_signals['internet_gap'], 2)}pct，"
                + f"电力可及率组间差约 {_fmt_number(cluster_signals['electricity_gap'], 2)}pct。"
            )
            evidence_map.append("analysis_report.cluster_profiles")

        if cluster_signals.get("smallest_share") is not None:
            key_findings.append(
                "分群结构有尾部小样本："
                + f"最小簇占比 {_fmt_percent(cluster_signals['smallest_share'])}，"
                + "不宜直接外推为普遍规律。"
            )
            evidence_map.append("analysis_report.cluster_sizes")

    if not key_findings:
        key_findings.extend(insight_lines[:3])
    if len(key_findings) < 3:
        key_findings.append(
            f"本次分析覆盖 {rows} 行、{cols} 列；总体缺失占比 {_fmt_percent(missing_ratio)}。"
        )
    if sampling_report.get("sampled"):
        key_findings.append(
            f"当前使用简单随机抽样（simple random sample），抽样 {sampling_report.get('sample_rows_used', rows):,} 行，占总体 {sampling_report.get('sampling_fraction', 0.0):.2%}。"
        )
    elif sampling_report.get("population_rows"):
        key_findings.append(f"当前使用全量数据，共 {sampling_report.get('population_rows', rows):,} 行。")

    if top_missing:
        col, payload = top_missing[0]
        key_findings.append(
            "数据完备性主要受少数字段影响："
            + f"{col} 缺失率 {_fmt_percent(payload.get('missing_ratio'))}。"
        )
        evidence_map.append("cleaning_report.missing_values.by_column")

    top_corr_texts = [f"{left} vs {right}（相关系数={_fmt_number(value, 3)}）" for left, right, value in correlations[:3]]

    derived_risks = list(risk_lines)
    if cluster_signals.get("smallest_share") is not None and float(cluster_signals["smallest_share"]) < 0.05:
        derived_risks.append("最小簇占比低于 5%，分群稳定性存在风险。")
    if missing_ratio is not None and missing_ratio > 0.03:
        derived_risks.append("总体缺失率超过 3%，可能影响结果稳健性。")
    if not derived_risks:
        derived_risks.append("当前未发现显著阻断风险，但仍需做后续有效性复核。")

    decision_score = 85.0
    if missing_ratio is not None and missing_ratio > 0.03:
        decision_score -= 12
    if cluster_signals.get("smallest_share") is not None and float(cluster_signals["smallest_share"]) < 0.05:
        decision_score -= 15
    silhouette = cluster_signals.get("silhouette")
    if silhouette is not None:
        try:
            sil = float(silhouette)
            if sil < 0.25:
                decision_score -= 20
            elif sil < 0.4:
                decision_score -= 8
        except (TypeError, ValueError):
            pass

    confidence = "高" if decision_score >= 80 else "中" if decision_score >= 65 else "低"

    if task in {"cluster", "clustering"}:
        decision_call = "建议把本次分群结果作为分层参考，但先处理小样本簇稳定性后再做大范围推广。"
    else:
        decision_call = "建议将当前结论作为决策输入，并在补齐关键数据后开展下一轮分析。"

    direction_suggestions = []
    if recommendation_lines:
        direction_suggestions.extend(recommendation_lines[:3])
    if not direction_suggestions:
        direction_suggestions = [
            "优先把当前结果整理成分层观察清单，避免只依赖单一排名做判断。",
            "针对高缺失字段先做口径清理与补齐，再开展更细颗粒度建模。",
            "对小样本簇做稳定性复核，确认是否需要调整簇数或拆分策略。",
        ]

    governance = _chart_governance_summary(context)
    review_source = context.get("chart_review") or context.get("report_chart_decision") or context.get("chart_vision_review")
    review_map, overall_chart_summary = _normalize_chart_review(review_source)

    chart_cards = []
    for item in chart_plan.get("charts", []) if isinstance(chart_plan.get("charts", []), list) else []:
        if not isinstance(item, dict):
            continue
        file_name = item.get("file")
        title = item.get("title") or item.get("chart") or "图表"
        review_item = None
        if file_name and str(file_name) in review_map:
            review_item = review_map[str(file_name)]
        elif f"title::{title}" in review_map:
            review_item = review_map[f"title::{title}"]
        if not file_name and isinstance(review_item, dict):
            review_file = review_item.get("file")
            if review_file:
                file_name = str(review_file)
        candidate_meta = governance["candidate_by_file"].get(str(file_name)) if file_name else None

        meaning = str(item.get("meaning") or "").strip()
        read_tip = str(item.get("how_to_read") or "").strip()
        interpretation = meaning or "图中展示了与当前分析问题直接相关的结构变化。"
        implication = "建议结合图中相对位置和变化幅度判断业务含义。"
        caption_note = ""

        if isinstance(review_item, dict):
            interpretation = review_item.get("interpretation") or interpretation
            implication = review_item.get("implication") or implication
            caption_note = review_item.get("caption_note") or ""

        review_status = str((context.get("chart_review") or {}).get("status") or "").strip().lower()
        if review_status != "final":
            review_status = str((context.get("report_chart_decision") or {}).get("status") or "").strip().lower()
        has_final_review = bool(
            isinstance(review_item, dict)
            and review_status == "final"
            and review_item.get("interpretation")
            and review_item.get("implication")
        )
        is_body_selected = bool(file_name and file_name in governance["selected_files_set"])

        interpretation_text = _strip_chart_template_openers(
            _dedupe_sentences_text(str(interpretation), limit=5) or str(interpretation)
        )
        if not interpretation_text:
            interpretation_text = "图中展示了与当前分析问题直接相关的结构变化。"

        implication_text = _strip_chart_template_openers(
            _dedupe_sentences_text(str(implication), limit=4) or str(implication)
        )
        if not implication_text:
            implication_text = _dedupe_sentences_text(read_tip, limit=2) or "建议结合图中差异与趋势判断业务含义。"

        evidence_point = _first_sentence_with_digit(interpretation_text) or _merge_sentences(interpretation_text, limit=1)
        read_method = _merge_sentences(read_tip, limit=1) if read_tip else ""
        if not read_method:
            read_method = _default_read_method(title=title, file_name=str(file_name) if file_name else None)

        chart_cards.append(
            {
                "file": file_name,
                "title": title,
                "interpretation": str(interpretation_text) if has_final_review and is_body_selected else "",
                "evidence_point": str(evidence_point) if has_final_review and is_body_selected else "",
                "read_method": str(read_method) if has_final_review and is_body_selected else "",
                "implication": str(implication_text) if has_final_review and is_body_selected else "",
                "caption_note": str(caption_note),
                "body_selected": is_body_selected,
                "has_final_review": has_final_review,
                "card_kind": "reviewed_body" if has_final_review and is_body_selected else "diagnostic_review",
                "process_note": _diagnostic_chart_reason(candidate_meta, meaning=meaning, read_tip=read_tip),
                "section_role": (candidate_meta or {}).get("section_role"),
                "diagnostic_only": bool((candidate_meta or {}).get("diagnostic_only")),
                "allow_in_formal_body": bool((candidate_meta or {}).get("allow_in_formal_body", True)),
            }
        )

    if not overall_chart_summary:
        overall_chart_summary = "图表共同表明：当前任务中的差异不是单一指标差异，而是多个关键变量联动形成的结构性差异。"
    overall_chart_summary = _dedupe_sentences_text(overall_chart_summary, limit=5) or overall_chart_summary

    quality_checks = [
        ("先给结论再讲过程", True),
        ("关键发现有优先级", len(key_findings) >= 3),
        ("关键发现量化", sum(any(ch.isdigit() for ch in line) for line in key_findings[:3]) >= 2),
        ("风险披露明确", len(derived_risks) >= 1),
        ("图表有深入解读", len(chart_cards) >= 1),
        ("证据可追溯", len(evidence_map) >= 2),
    ]

    return {
        "task": task,
        "task_label": task_label,
        "rows": rows,
        "cols": cols,
        "missing_ratio": missing_ratio,
        "top_missing": top_missing,
        "top_correlations": top_corr_texts,
        "key_findings": key_findings[:5],
        "derived_risks": derived_risks[:5],
        "direction_suggestions": direction_suggestions[:3],
        "decision_call": decision_call,
        "confidence": confidence,
        "confidence_score": round(decision_score, 1),
        "evidence_map": evidence_map,
        "chart_governance": governance,
        "chart_cards": chart_cards,
        "overall_chart_summary": overall_chart_summary,
        "quality_checks": quality_checks,
    }


def _render_kv_table(rows: list[tuple[str, Any]]) -> str:
    body = "".join(f"<tr><th>{_escape(k)}</th><td>{_escape(v)}</td></tr>" for k, v in rows)
    return f"<table class=\"kv-table\">{body}</table>"


def _section_executive_summary(brain: dict[str, Any]) -> str:
    findings = "".join(f"<li>{_escape(item)}</li>" for item in brain["key_findings"][:3])
    top_risk = brain["derived_risks"][0] if brain["derived_risks"] else "暂无显著风险。"
    evidence = "".join(f"<li>{_escape(item)}</li>" for item in brain["evidence_map"])
    return f"""
    <section class="panel highlight">
      <h2>执行摘要（先结论）</h2>
      <p class="decision"><strong>决策建议：</strong>{_escape(brain['decision_call'])}</p>
      <div class="meta-grid">
        <div><span class="meta-label">任务类型</span><span class="meta-value">{_escape(brain['task_label'])}</span></div>
        <div><span class="meta-label">决策置信度</span><span class="meta-value">{_escape(brain['confidence'])}（{_escape(brain['confidence_score'])}/100）</span></div>
        <div><span class="meta-label">样本规模</span><span class="meta-value">{_escape(brain['rows'])} 行 × {_escape(brain['cols'])} 列</span></div>
      </div>
      <h3>前三个关键发现</h3>
      <ol>{findings}</ol>
      <h3>最大风险</h3>
      <p>{_escape(top_risk)}</p>
      <h3>证据锚点</h3>
      <ul class="bullet-list">{evidence or '<li>暂无证据锚点。</li>'}</ul>
    </section>
    """


def _section_problem_scope(context: dict[str, Any], brain: dict[str, Any]) -> str:
    read_plan = context.get("read_plan") or {}
    sampling_report = context.get("sampling_report") or {}
    warnings = read_plan.get("warnings", []) if isinstance(read_plan.get("warnings", []), list) else []
    strategy = sampling_report.get("strategy", "full_population")
    if strategy == "simple_random_sample":
        strategy = "简单随机抽样"
    elif strategy == "full_population":
        strategy = "全量数据"
    rows = [
        ("业务问题", f"围绕 {brain['task_label']} 形成可解释、可复核的分析结论"),
        ("本次口径", "以当前任务的主分析样本为主，并结合基础图表和统计摘要进行复核"),
        ("输入数据", read_plan.get("path", "N/A")),
        ("读取策略", read_plan.get("recommended_backend", "N/A")),
        ("抽样策略", strategy),
        ("使用行数", f"{sampling_report.get('sample_rows_used', brain['rows'])} / {sampling_report.get('population_rows', brain['rows'])}"),
    ]
    warning_html = "".join(f"<li>{_escape(_localize_warning(w))}</li>" for w in warnings)
    return f"""
    <section class="panel">
      <h2>业务问题与分析边界</h2>
      {_render_kv_table(rows)}
      <h3>边界与前提</h3>
      <ul class="bullet-list">{warning_html or '<li>未记录额外边界说明。</li>'}</ul>
      <p class="hint">说明：本报告强调“可解释分析”，不是因果识别报告。</p>
    </section>
    """


def _section_key_findings(brain: dict[str, Any]) -> str:
    items = "".join(f"<li>{_escape(item)}</li>" for item in brain["key_findings"])
    support = "".join(f"<li>{_escape(item)}</li>" for item in brain["top_correlations"])
    return f"""
    <section class="panel">
      <h2>关键发现（按优先级）</h2>
      <ol>{items}</ol>
      <h3>支持性统计信号</h3>
      <ul class="bullet-list">{support or '<li>暂无可用相关性摘要。</li>'}</ul>
    </section>
    """


def _section_suggestion_directions(brain: dict[str, Any]) -> str:
    items = "".join(f"<li>{_escape(item)}</li>" for item in brain["direction_suggestions"])
    return f"""
    <section class="panel">
      <h2>建议方向</h2>
      <ul class="bullet-list">{items}</ul>
      <p class="hint">本节仅提供方向性判断，不包含动作拆解或执行安排。</p>
    </section>
    """


def _section_data_quality(context: dict[str, Any], brain: dict[str, Any]) -> str:
    cleaning = context.get("cleaning_report") or {}
    missing = cleaning.get("missing_values", {})
    duplicates = cleaning.get("duplicates", {})
    roles = cleaning.get("roles", {})

    top_missing_rows = []
    for col, payload in brain["top_missing"]:
        top_missing_rows.append((col, f"缺失数={payload.get('missing_count')} 缺失率={_fmt_percent(payload.get('missing_ratio'))}"))
    if not top_missing_rows:
        top_missing_rows.append(("N/A", "暂无缺失字段。"))

    quality_rows = [
        ("总缺失单元格", missing.get("total_missing_cells", "N/A")),
        ("缺失字段数", missing.get("columns_with_missing_values", "N/A")),
        ("总体缺失率", _fmt_percent(brain.get("missing_ratio"))),
        ("重复行", duplicates.get("duplicate_rows", "N/A")),
        ("重复率", _fmt_percent(duplicates.get("duplicate_ratio"))),
        ("数值字段数", len(roles.get("numeric", []))),
        ("类别字段数", len(roles.get("categorical", []))),
    ]

    return f"""
    <section class="panel">
      <h2>数据质量与可信度</h2>
      {_render_kv_table(quality_rows)}
      <h3>高缺失字段（前 5 项）</h3>
      {_render_kv_table(top_missing_rows)}
      <p class="hint">解释：缺失率高的字段会影响分群稳定性，建议先做口径治理再扩大外推。</p>
    </section>
    """


def _section_method_evidence(context: dict[str, Any], brain: dict[str, Any]) -> str:
    analysis = context.get("analysis_report") or {}
    feature_plan = context.get("feature_plan") or {}
    roles = (context.get("cleaning_report") or {}).get("roles", {})

    numeric_count = len(feature_plan.get("numeric_columns", []) or roles.get("numeric", []))
    categorical_count = len(feature_plan.get("categorical_columns", []) or roles.get("categorical", []))

    selection_metric = analysis.get("selection_metric", "N/A")
    if selection_metric == "silhouette":
        selection_metric = "轮廓系数"
    elif selection_metric == "user_supplied":
        selection_metric = "用户指定"

    method_label = analysis.get("method_name") or brain["task_label"]

    rows = [
        ("方法", method_label),
        ("分群数", analysis.get("n_clusters", "N/A")),
        ("选择依据", selection_metric),
        ("轮廓系数", _fmt_number(analysis.get("silhouette_score"), 3)),
        ("特征规模", f"数值字段={numeric_count}，类别字段={categorical_count}"),
    ]

    return f"""
    <section class="panel">
      <h2>方法说明与证据链</h2>
      {_render_kv_table(rows)}
      <p class="hint">术语解释：轮廓系数用于衡量分群可分性，越高通常代表簇内更紧、簇间更分离。</p>
    </section>
    """


def _section_chart_governance(brain: dict[str, Any]) -> str:
    governance = brain.get("chart_governance") or {}
    rows = [
        ("治理状态", governance.get("status", "N/A")),
        ("报告受众", governance.get("report_audience", "N/A")),
        ("候选图数量", governance.get("candidate_count", 0)),
        ("可进正文候选", governance.get("eligible_count", 0)),
        ("诊断/附录倾向", governance.get("diagnostic_count", 0)),
        ("已选正文图", governance.get("selected_count", 0)),
    ]
    selected_files = governance.get("selected_files") or []
    selected_html = "".join(f"<li>{_escape(item)}</li>" for item in selected_files)
    notes_html = "".join(f"<li>{_escape(item)}</li>" for item in governance.get("notes", []))
    return f"""
    <section class="panel">
      <h2>正式报告正文图治理状态</h2>
      {_render_kv_table(rows)}
      <h3>当前入选正文的图</h3>
      <ul class="bullet-list">{selected_html or '<li>当前尚未回填正文图决策，formal report 会使用治理层默认草稿选择。</li>'}</ul>
      <h3>治理约束说明</h3>
      <ul class="bullet-list">{notes_html or '<li>当前未检测到 chart_candidates / report_chart_decision artifact。</li>'}</ul>
      <p class="hint">说明：过程报告仍保留全量 chart plan / PNG 的审计视角；正式报告正文图则受治理层约束，不应与这里的全量图审阅视角混淆。</p>
    </section>
    """


def _section_charts(brain: dict[str, Any], png_files: list[str]) -> str:
    reviewed_cards: list[str] = []
    diagnostic_cards: list[str] = []
    available_png = set(png_files)
    for idx, card in enumerate(brain["chart_cards"], start=1):
        file_name = card.get("file")
        image_html = ""
        if file_name and file_name in available_png:
            image_html = f'<img src="{_escape(file_name)}" alt="{_escape(file_name)}" loading="lazy" />'

        caption = ""
        if card.get("caption_note"):
            caption = f"<p class=\"hint\"><strong>注释：</strong>{_escape(card['caption_note'])}</p>"

        if card.get("card_kind") == "reviewed_body":
            evidence_html = f"<p><strong>证据点：</strong>{_escape(card['evidence_point'])}</p>" if card.get("evidence_point") else ""
            read_method_html = f"<p><strong>读图方法：</strong>{_escape(card['read_method'])}</p>" if card.get("read_method") else ""
            reviewed_cards.append(
                f"""
                <article class="chart-card">
                  <h3>{idx}. {_escape(card['title'])}</h3>
                  <p class="hint"><strong>正文状态：</strong>已选入正式报告正文；角色={_escape(card.get('section_role') or '未标注')}；已完成 final 读图回填。</p>
                  {image_html}
                  <p><strong>图表解读：</strong>{_escape(card['interpretation'])}</p>
                  {evidence_html}
                  {read_method_html}
                  <p><strong>业务含义：</strong>{_escape(card['implication'])}</p>
                  {caption}
                </article>
                """
            )
            continue

        governance_flag = "诊断/附录倾向" if card.get("diagnostic_only") else "未入正文"
        diagnostic_cards.append(
            f"""
            <article class="chart-card diagnostic-card">
              <h3>{idx}. {_escape(card['title'])}</h3>
              <p class="hint"><strong>过程角色：</strong>{_escape(governance_flag)}；角色={_escape(card.get('section_role') or '未标注')}；当前未做 agent 正式读图回填。</p>
              {image_html}
              <p><strong>保留原因：</strong>{_escape(card.get('process_note') or '该图仅保留用于过程审阅。')}</p>
              <p class="hint">说明：这里不再生成“图表解读 / 证据点 / 读图方法 / 业务含义”式模板内容，避免把诊断图误写成正式结论。</p>
              {caption}
            </article>
            """
        )

    return f"""
    <section class="panel">
      <h2>图表深度解读（基于图像复核）</h2>
      <p class="hint">本节保留过程审阅视角，但明确区分“已进入正式报告正文并完成 final 解读的图”和“仅供过程复核的诊断图”；正式报告正文图的最终去留仍以 `report_chart_decision.json` 为准。</p>
      <h3>已完成正式读图回填的正文图</h3>
      <div class="chart-grid">{''.join(reviewed_cards) or '<p>当前没有已完成 final 回填的正文图。</p>'}</div>
      <h3>仅供过程审阅的诊断图</h3>
      <div class="chart-grid">{''.join(diagnostic_cards) or '<p>当前没有额外的诊断图需要展示。</p>'}</div>
      <h3>正文图总体解读</h3>
      <p>{_escape(brain['overall_chart_summary'])}</p>
    </section>
    """


def _section_risks(brain: dict[str, Any]) -> str:
    items = "".join(f"<li>{_escape(item)}</li>" for item in brain["derived_risks"])
    return f"""
    <section class="panel">
      <h2>风险、假设与备选方案</h2>
      <ul class="bullet-list">{items}</ul>
      <p><strong>备选方案：</strong>若高缺失字段短期无法补齐，先采用高覆盖指标子集重做分层，再验证策略稳健性。</p>
    </section>
    """


def _build_meta_payload(context: dict[str, Any], brain: dict[str, Any]) -> dict[str, Any]:
    governance = brain.get("chart_governance") or {}
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run_dir": context.get("run_dir"),
        "artifact_status": context.get("artifact_status", {}),
        "chart_governance": {
            "status": governance.get("status"),
            "report_audience": governance.get("report_audience"),
            "candidate_count": governance.get("candidate_count"),
            "eligible_count": governance.get("eligible_count"),
            "diagnostic_count": governance.get("diagnostic_count"),
            "selected_count": governance.get("selected_count"),
            "selected_files": governance.get("selected_files", []),
        },
        "quality_checks": [
            {"name": name, "passed": bool(passed)} for name, passed in brain.get("quality_checks", [])
        ],
        "evidence_map": brain.get("evidence_map", []),
        "file_index": {
            "json_files": context.get("json_files", []),
            "markdown_files": context.get("markdown_files", []),
            "csv_files": context.get("csv_files", []),
            "png_files": context.get("png_files", []),
        },
    }


def _build_html(context: dict[str, Any], title: str | None = None) -> tuple[str, dict[str, Any]]:
    brain = _derive_report_brain(context)
    heading = title or f"{brain['task_label']} 全流程报告"
    checked_at = ((context.get("environment") or {}).get("checked_at")) or "N/A"
    run_dir = context.get("run_dir", "")

    sections = [
        _section_executive_summary(brain),
        _section_problem_scope(context, brain),
        _section_key_findings(brain),
        _section_suggestion_directions(brain),
        _section_data_quality(context, brain),
        _section_method_evidence(context, brain),
        _section_chart_governance(brain),
        _section_charts(brain, context.get("png_files", [])),
        _section_risks(brain),
    ]

    html_text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_escape(heading)}</title>
  <style>
    :root {{
      --bg: #f6f4ea;
      --panel: #fffdf6;
      --ink: #1b2430;
      --muted: #5f6b76;
      --line: #e8dfcf;
      --accent: #0b5d4f;
      --accent2: #8a3d14;
      --shadow: 0 10px 28px rgba(27, 36, 48, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at 100% 0, rgba(11,93,79,0.12), transparent 28%),
        radial-gradient(circle at 0 30%, rgba(138,61,20,0.08), transparent 24%),
        var(--bg);
      color: var(--ink);
    }}
    .wrap {{ max-width: 1180px; margin: 0 auto; padding: 28px 18px 56px; }}
    .hero, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: var(--shadow);
    }}
    .hero {{ padding: 26px 28px; margin-bottom: 18px; }}
    .panel {{ padding: 20px 22px; margin-top: 16px; }}
    .eyebrow {{
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 8px;
    }}
    h1, h2, h3 {{ margin: 0 0 10px; }}
    h1 {{ font-size: 33px; line-height: 1.15; }}
    h2 {{ font-size: 23px; }}
    h3 {{ font-size: 16px; color: var(--accent2); margin-top: 14px; }}
    p {{ margin: 0 0 10px; line-height: 1.65; }}
    .hint {{ color: var(--muted); font-size: 14px; }}
    .decision {{ font-size: 17px; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 14px; color: var(--muted); font-size: 14px; }}
    .meta-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      margin: 12px 0;
    }}
    .meta-grid > div {{ border: 1px solid var(--line); border-radius: 12px; padding: 10px 12px; background: #fffdf9; }}
    .meta-label {{ display: block; color: var(--muted); font-size: 12px; }}
    .meta-value {{ display: block; font-weight: 700; margin-top: 4px; }}
    ol, ul {{ margin: 0; padding-left: 20px; line-height: 1.75; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 14px; }}
    .kv-table th, .kv-table td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }}
    .kv-table th {{ width: 34%; color: var(--muted); font-weight: 600; }}
    .chart-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-top: 8px; }}
    .chart-card {{ border: 1px solid var(--line); border-radius: 14px; padding: 12px; background: #fffefb; }}
    .chart-card img {{ width: 100%; height: auto; display: block; border-radius: 10px; margin: 8px 0; }}
    .highlight {{ background: linear-gradient(180deg, #fffdf6 0%, #fff9ec 100%); }}
    @media (max-width: 760px) {{
      .wrap {{ padding: 18px 12px 34px; }}
      .hero, .panel {{ padding: 16px; border-radius: 14px; }}
      h1 {{ font-size: 27px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="eyebrow">全流程决策报告</div>
      <h1>{_escape(heading)}</h1>
      <p>这版报告聚焦“可读性与重点判断”：先结论、再证据，避免正文堆砌原始产物。</p>
      <div class="meta">
        <span>Task: {_escape(brain['task'])}</span>
        <span>Checked at: {_escape(checked_at)}</span>
        <span>Run dir: {_escape(run_dir)}</span>
      </div>
    </section>
    {''.join(sections)}
  </div>
</body>
</html>
"""

    return html_text, _build_meta_payload(context, brain)


def export_process_report(run_dir: Path, output_path: Path | None = None, title: str | None = None) -> Path:
    context = _collect_run_context(run_dir)
    path = output_path or (run_dir / "report_process.html")
    html_text, meta_payload = _build_html(context, title=title)
    path.write_text(html_text)

    meta_path = run_dir / "report_process_meta.json"
    meta_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a readable full process report from a data-analysis run directory.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output-path")
    parser.add_argument("--title")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    output_path = Path(args.output_path) if args.output_path else None
    path = export_process_report(run_dir, output_path=output_path, title=args.title)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
