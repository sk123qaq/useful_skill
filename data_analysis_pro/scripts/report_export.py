#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
from common import write_markdown, ensure_output_dir
from causal_narrative import render_causal_narrative_markdown_fragment
from metadata_manager import MetadataManager

metadata_mgr = MetadataManager()

def load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def format_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "暂无数据。"
    
    cols = df.columns.tolist()
    # Translate column names using metadata manager
    translated_cols = [metadata_mgr.translate(c) for c in cols]
    
    header = "| " + " | ".join(map(str, translated_cols)) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    
    body = []
    for _, row in df.iterrows():
        row_str = "| " + " | ".join(map(lambda x: str(x).replace("\n", " "), row.values)) + " |"
        body.append(row_str)
        
    return "\n".join([header, sep] + body)


def generate_report(output_dir: Path) -> str:
    # 1. Scanning for artifacts
    env_path = next(output_dir.glob("**/env_snapshot.json"), None)
    profile_path = next(output_dir.glob("**/column_profile.json"), None)
    preprocess_path = next(output_dir.glob("**/preprocessing_report.json"), None)
    relationship_path = next(output_dir.glob("**/relationship_screening.json"), None)
    causal_path = next(output_dir.glob("**/causal_narrative_report.json"), None)
    explain_path = next(output_dir.glob("**/explainability_report.json"), None)
    gate_path = next(output_dir.glob("**/gate_review.json"), None)
    
    env_data = load_json(env_path)
    profile_data = load_json(profile_path)
    preprocess_data = load_json(preprocess_path)
    relationship_data = load_json(relationship_path)
    causal_data = load_json(causal_path)
    explain_data = load_json(explain_path)
    gate_data = load_json(gate_path)

    lines = ["# 数据分析专业报告 (Professional Data Analysis Report)", ""]

    # Phase 1: Problem Framing & Environment (问题定义与环境)
    lines.append("## Phase 1: Problem Framing & Environment (问题定义与环境)")
    if env_data:
        lines.append(f"- **Python 版本:** `{env_data.get('python_version', '未知')}`")
        lines.append(f"- **运行时间:** `{env_data.get('timestamp', '未知')}`")
        modules = env_data.get('modules', {})
        core_modules = ["pandas", "numpy", "scipy", "sklearn"]
        available_core = [m for m in core_modules if modules.get(m)]
        ready_status = "✅ 就绪" if len(available_core) == len(core_modules) else "⚠️ 部分缺失"
        lines.append(f"- **环境状态:** {ready_status} ({', '.join(available_core)})")
    else:
        lines.append("该阶段分析未执行或环境快照缺失。")
    lines.append("")

    # Phase 2: Data Profiling & Quality Control (数据画像与质量控制)
    lines.append("## Phase 2: Data Profiling & Quality Control (数据画像与质量控制)")
    if profile_data or preprocess_data:
        if profile_data:
            lines.append(f"### 数据概览")
            lines.append(f"- **原始数据量:** `{profile_data.get('row_count', '未知')}` 行")
            summary = profile_data.get("summary", {})
            if summary:
                lines.append(f"- **高缺失列:** {', '.join(summary.get('high_missingness', [])) or '无'}")
                lines.append(f"- **常量列:** {', '.join(summary.get('constant_features', [])) or '无'}")
        
        if preprocess_data:
            lines.append(f"### 数据清洗与预处理")
            # Cleaning details
            cleaning = preprocess_data.get("cleaning", {})
            if cleaning:
                actions = cleaning.get("actions", [])
                if actions:
                    lines.append("- **清洗操作:**")
                    for action in actions:
                        lines.append(f"  - {action}")
            
            # Identify processed columns
            initial_stats = preprocess_data.get("initial_stats", {})
            schema = initial_stats.get("schema", {})
            fields = schema.get("fields", [])
            if fields:
                processed_cols = [metadata_mgr.translate(f["name"]) for f in fields]
                lines.append(f"- **已处理字段 ({len(fields)}个):** {', '.join(processed_cols)}")
            
            # Cleaned data volume (if available in report)
            if "output_path" in preprocess_data:
                # We assume if cleaning happened, we might have new row count info
                # But if not explicit, we skip
                pass
    else:
        lines.append("该阶段分析未执行。")
    lines.append("")

    # Phase 3: Relationship Screening (特征探索与关系筛查)
    lines.append("## Phase 3: Relationship Screening (特征探索与关系筛查)")
    if relationship_data:
        lines.append("### 关键关系筛查结果")
        if isinstance(relationship_data, list) and len(relationship_data) > 0:
            df_rel = pd.DataFrame(relationship_data)
            # Rename columns for readability
            col_map = {
                "x": "特征 (x)",
                "y": "目标 (y)",
                "x_kind": "x 类型",
                "y_kind": "y 类型",
                "effect_size": "相关强度 (Effect)",
                "metric": "度量指标",
                "visualization_hint": "推荐图表"
            }
            df_rel = df_rel.rename(columns=col_map)
            lines.append(format_table(df_rel))
        else:
            lines.append("未发现显著的统计关系。")
    else:
        lines.append("该阶段分析未执行。")
    lines.append("")

    # Phase 4: Deep Dive Analysis (深度专项分析)
    lines.append("## Phase 4: Deep Dive Analysis (深度专项分析)")
    if causal_data:
        key_est = causal_data.get("key_estimate", {})
        lines.append(f"### 因果效应分析: {causal_data.get('method_label', 'Causal Analysis')}")
        
        # Explicitly distinguish ATE and Significance
        ate_val = key_est.get("value", "N/A")
        if isinstance(ate_val, float):
            ate_str = f"{ate_val:.4f}"
        else:
            ate_str = str(ate_val)
            
        lines.append(f"- **因果效应量 (ATE/Estimate):** `{ate_str}`")
        
        sig = key_est.get("significant")
        p_val = key_est.get("p_value")
        p_str = f"{p_val:.4f}" if isinstance(p_val, float) else str(p_val)
        sig_label = "✅ 统计显著" if sig is True else "❌ 统计不显著" if sig is False else "未知"
        lines.append(f"- **统计显著性 (p-value={p_str}):** {sig_label}")
        
        lines.append("")
        lines.append("#### 详细分析叙述")
        causal_fragment = render_causal_narrative_markdown_fragment(causal_data, heading_level_offset=2)
        lines.append(causal_fragment)
        
        # Check for plots
        causal_plots = list(output_dir.glob("**/dml_*.png")) + list(output_dir.glob("**/did_*.png")) + list(output_dir.glob("**/rd_*.png"))
        if causal_plots:
            lines.append("\n#### 分析图表")
            for plot in causal_plots:
                rel_path = plot.relative_to(output_dir)
                lines.append(f"![{plot.stem}]({rel_path})")
    else:
        lines.append("该阶段分析未执行。")
    lines.append("")

    # Phase 5: Explainability & Gatekeeping (可解释性与准入复核)
    lines.append("## Phase 5: Explainability & Gatekeeping (可解释性与准入复核)")
    
    # Admission Status (Gate Review)
    lines.append("### 准入复核状态 (Admission Status)")
    if gate_data:
        lines.append(f"- **最终证据等级:** `{gate_data.get('max_evidence_grade', '未知')}`")
        lines.append("- **复核明细表:**")
        
        passed = gate_data.get("passed_gates", [])
        blockers = gate_data.get("blockers", [])
        
        if not passed and not blockers:
            lines.append("  - (暂无复核记录)")
        else:
            for p in passed:
                lines.append(f"  - [通过] {p}")
            for b in blockers:
                lines.append(f"  - [未通过] {b}")
    else:
        lines.append("跳过准入复核或数据缺失。")
    
    lines.append("")
    lines.append("### 模型可解释性分析")
    if explain_data:
        lines.append("#### 特征重要性排序 (SHAP/Correlation)")
        top_features = explain_data.get("top_features", [])
        if top_features:
            if isinstance(top_features, list):
                df_feat = pd.DataFrame(top_features)
            else: # dict format
                df_feat = pd.DataFrame([{"feature": k, "importance": v} for k, v in top_features.items()])
            lines.append(format_table(df_feat))
        
        shap_img = next(output_dir.glob("**/shap_bar.png"), None)
        if shap_img:
            rel_path = shap_img.relative_to(output_dir)
            lines.append(f"![SHAP Global Importance]({rel_path})")
    else:
        lines.append("该阶段分析未执行或解释数据缺失。")
    lines.append("")

    # Phase 6: Actionable Insights & Artifacts (行动建议与工件索引)
    lines.append("## Phase 6: Actionable Insights & Artifacts (行动建议与工件索引)")
    
    lines.append("### 核心行动建议")
    if causal_data:
        recommendation = causal_data.get("recommendation")
        if recommendation:
            lines.append(f"1. **结论建议:** {recommendation}")
        
        interpretations = causal_data.get("business_interpretation", [])
        if interpretations:
            lines.append("2. **业务解读:**")
            for item in interpretations:
                lines.append(f"   - {item}")
    else:
        lines.append("- 暂无基于分析的自动化建议。")
        
    lines.append("")
    lines.append("### 分析工件索引 (Artifact Index)")
    artifacts = sorted(list(output_dir.glob("**/*")))
    found_artifact = False
    for art in artifacts:
        if art.is_file():
            if art.name.startswith(".") or art.suffix == ".py": continue
            rel_path = art.relative_to(output_dir)
            lines.append(f"- [{rel_path}]({rel_path})")
            found_artifact = True
    
    if not found_artifact:
        lines.append("未生成任何工件。")
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Professional Report Exporter")
    parser.add_argument("--output-dir", required=True, help="Directory containing analysis artifacts")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    report_md = generate_report(output_dir)
    
    report_path = output_dir / "analysis_report.md"
    write_markdown(report_path, report_md)
    print(f"Report generated at: {report_path}")


if __name__ == "__main__":
    main()
