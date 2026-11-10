#!/usr/bin/env python3
"""report_bundle.py: assemble a report from claims + artifacts.

The bundle does not invent findings. If claim_registry.json is missing it
writes a template and refuses to produce a report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402
from workflow import EVIDENCE_GRADES, load_json, write_json, write_text  # noqa: E402


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if value != value:
            return "NaN"
        return f"{value:.{digits}g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "_无_\n"
    out = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(_fmt(row.get(c)) for c in columns) + " |")
    return "\n".join(out) + "\n"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _artifact_index(run_dir: Path, report_path: Path) -> list[dict[str, str]]:
    rows = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path == report_path:
            continue
        if path.name.endswith(".pyc") or "__pycache__" in path.parts:
            continue
        rows.append({"path": str(path.relative_to(run_dir)), "bytes": str(path.stat().st_size),
                     "sha256": _sha(path)})
    return rows


def _template() -> dict[str, Any]:
    return {
        "version": 1,
        "instructions": "Agent: write one claim per conclusion. supported_by must list real artifact paths relative to run_dir.",
        "claims": [],
    }


def build(run_dir: Path, claims_path: Path, output_path: Path) -> str:
    contract = load_json(run_dir / "analysis_contract.json", required=True)
    gate = load_json(run_dir / "gate_review.json") if (run_dir / "gate_review.json").exists() else {}
    claims_payload = load_json(claims_path, required=True)
    claims = claims_payload.get("claims", [])
    if not claims:
        raise SystemExit("claim_registry has no claims; add at least one supported claim")

    errors = []
    for claim in claims:
        support = claim.get("supported_by")
        paths = support if isinstance(support, list) else [support]
        for rel in paths:
            if not rel:
                errors.append(f"{claim.get('claim_id', '?')}: empty supported_by")
                continue
            candidate = Path(rel) if Path(rel).is_absolute() else run_dir / rel
            if not candidate.exists():
                errors.append(f"{claim.get('claim_id', '?')}: evidence missing: {rel}")
        if claim.get("evidence_grade") not in EVIDENCE_GRADES:
            errors.append(f"{claim.get('claim_id', '?')}: invalid evidence_grade")
    if errors:
        raise SystemExit("claim registry invalid:\n- " + "\n- ".join(errors))

    describe = load_json(run_dir / "describe.json") if (run_dir / "describe.json").exists() else {}
    baseline = load_json(run_dir / "baseline_results.json") if (run_dir / "baseline_results.json").exists() else {}
    cleaning = load_json(run_dir / "cleaning_report.json") if (run_dir / "cleaning_report.json").exists() else {}
    profile = load_json(run_dir / "profile.json") if (run_dir / "profile.json").exists() else {}
    causal = load_json(run_dir / "causal_report.json") if (run_dir / "causal_report.json").exists() else {}
    causal_design = load_json(run_dir / "causal_design.json") if (run_dir / "causal_design.json").exists() else {}
    experiment = load_json(run_dir / "experiment_report.json") if (run_dir / "experiment_report.json").exists() else {}

    lines: list[str] = []
    title = contract.get("decision_question") or "分析报告"
    lines.append(f"# {title}\n")
    lines.append(f"- **任务类型**: `{contract.get('task')}`")
    lines.append(f"- **分析单元**: {contract.get('unit_of_analysis')}")
    lines.append(f"- **数据来源**: {contract.get('data_source')}")
    lines.append(f"- **数据范围**: {contract.get('data_scope')}")
    lines.append(f"- **目标/时间**: target=`{contract.get('target')}`, time=`{contract.get('time_col')}`")
    lines.append(f"- **证据等级（gate）**: `{gate.get('max_evidence_grade', 'missing')}`\n")

    lines.append("## 决策问题\n")
    lines.append(str(contract.get("decision_question", "")) + "\n")
    lines.append("## 数据与口径\n")
    if profile:
        lines.append(f"- 行数: {profile.get('row_count')}; 列数: {profile.get('column_count')}; 来源: `{profile.get('source')}`")
    if cleaning:
        before = cleaning.get("before", {}).get("rows")
        after = cleaning.get("after", {}).get("rows")
        lines.append(f"- 清洗: {before} → {after} 行; 重复删除 {cleaning.get('duplicates_removed', 0)}")
    lines.append("")

    lines.append("## 方法\n")
    lines.append(f"路线由 `analysis_contract.json` 固定为 `{contract.get('task')}`；特征风险、切分、基线等前置工件见工件索引。\n")

    lines.append("## 结果\n")
    if describe:
        numeric = describe.get("numeric", {})
        lines.append("### 描述性统计\n")
        lines.append(f"- 数值列: {len(numeric)}; 分类列: {len(describe.get('categorical', {}))}")
        if describe.get("time_series"):
            lines.append(f"- 时间序列: {len(describe['time_series'])} 列（首末值、ACF、异常点见 describe.json）")
        lines.append("")
    if baseline:
        lines.append("### 预测基线\n")
        models = baseline.get("models", [])
        metric = baseline.get("primary_metric")
        rows = []
        for m in models:
            rows.append({
                "model": m.get("model_name") or m.get("name"),
                "family": m.get("family"),
                "metric": metric,
                "value": (m.get("mean_metrics") or {}).get(metric),
                "fold_std": (m.get("std_metrics") or {}).get(metric),
            })
        lines.append(_table(rows, ["model", "family", "metric", "value", "fold_std"]))
        comp = baseline.get("dummy_comparison", {})
        lines.append(
            f"- 最佳非 dummy: `{baseline.get('best_model_name')}`; "
            f"beats_dummy={comp.get('beats_dummy')}, delta={comp.get('delta')}, "
            f"relative={comp.get('relative')}, threshold={comp.get('threshold')}"
        )
        lines.append("")
    if causal:
        lines.append("### 因果\n")
        effect = next((causal.get(k) for k in (
            "average_treatment_effect_on_treated", "average_treatment_effect", "did_estimate", "ate", "estimate", "att", "effect", "coefficient"
        ) if causal.get(k) is not None), None)
        ci = causal.get("confidence_interval") or causal.get("ci") or (causal.get("regression") or {}).get("confidence_interval")
        p_value = causal.get("p_value") or (causal.get("regression") or {}).get("p_value")
        lines.append(f"- 设计: `{causal_design.get('design', causal.get('task', '—'))}`; 估计量: `{causal_design.get('estimand', '—')}`")
        lines.append(f"- 点估计: {_fmt(effect)}; 95% CI: {_fmt(ci)}; p={_fmt(p_value)}")
        lines.append(f"- 方法/任务: `{causal.get('task', '—')}`; 假设与局限见 `causal_design.json` / `causal_report.json`")
        lines.append("")
    if experiment:
        lines.append("### 实验\n")
        lines.append(f"- 主指标: `{experiment.get('primary_metric', '—')}`; 效应: {_fmt(experiment.get('effect'))}; p={_fmt(experiment.get('p_value'))}")
        lines.append(f"- SRM p={_fmt(experiment.get('srm_p_value'))}; 平衡性通过: `{experiment.get('balance_passed')}`")
        lines.append(f"- 决策: `{(experiment.get('decision') or {}).get('status', '—')}` — {(experiment.get('decision') or {}).get('summary', '')}")
        lines.append("")

    lines.append("## 结论（仅 claim_registry）\n")
    for claim in claims:
        cid = claim.get("claim_id", "?")
        grade = claim.get("evidence_grade", "?")
        support = claim.get("supported_by")
        support_txt = ", ".join(f"`{x}`" for x in (support if isinstance(support, list) else [support]))
        lines.append(f"- **[{cid}]** {claim.get('text')} — 证据: {support_txt}; 等级: `{grade}`")
    lines.append("")

    lines.append("## 局限\n")
    lines.append(str(contract.get("limitations") or "见各工件 limitations 字段；未列出的口径风险不应假定不存在。") + "\n")

    lines.append("## 工件索引\n")
    index = _artifact_index(run_dir, output_path)
    lines.append(_table(index, ["path", "bytes", "sha256"]))

    report = "\n".join(lines).rstrip() + "\n"
    write_text(output_path, report)
    write_json(run_dir / "report_bundle.json", {
        "version": 1, "report_path": str(output_path), "n_claims": len(claims),
        "gate_grade": gate.get("max_evidence_grade"), "artifacts": index,
        "created_at": common.now_utc_iso(),
    })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble report from claims and artifacts.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--claims-path", default=None)
    parser.add_argument("--output-path", default=None)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    claims_path = Path(args.claims_path) if args.claims_path else run_dir / "claim_registry.json"
    output_path = Path(args.output_path) if args.output_path else run_dir / "report.md"
    if not claims_path.exists():
        template = run_dir / "claim_registry.template.json"
        write_json(template, _template())
        print(f"claim_registry missing; wrote template: {template}")
        return 2
    stale_lint = run_dir / "report_lint.json"
    if stale_lint.exists():
        stale_lint.unlink()
    try:
        build(run_dir, claims_path, output_path)
    except SystemExit as exc:
        print(str(exc))
        return 2
    print(json.dumps({"report": str(output_path), "bytes": output_path.stat().st_size}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
