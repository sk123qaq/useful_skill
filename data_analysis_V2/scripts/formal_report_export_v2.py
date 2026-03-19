from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from data_analysis_V2.scripts.common import read_json, write_markdown
from data_analysis_V2.scripts.report_bundle_builder import build_report_bundle


def export_formal_report_v2(run_dir: str | Path, title: str | None = None) -> dict[str, Any]:
    run_path = Path(run_dir)
    judgment_path = run_path / "judgment_bundle.json"
    if not judgment_path.exists():
        raise FileNotFoundError("judgment_bundle.json is required for formal report export.")
    claim_path = run_path / "claim_registry.json"
    if not claim_path.exists():
        raise FileNotFoundError("claim_registry.json is required for formal report export.")
    bundle = build_report_bundle(run_path)
    judgment = read_json(judgment_path)
    lines = [
        f"# {title or 'Data Analysis V2 Report'}",
        "",
        "## Evidence Grade",
        "",
        judgment["evidence_grade"],
        "",
        "## Safe Summary",
        "",
        bundle["summary"],
        "",
        "## Claims",
        "",
    ]
    for claim in bundle["claims"]:
        lines.append(f"- [{claim['evidence_grade']}] {claim['text']}")
    lines.extend(["", "## Guardrails", ""])
    for rule in bundle["guardrails"]:
        lines.append(f"- {rule}")
    report_path = write_markdown(run_path / "formal_report_v2.md", "\n".join(lines))
    return {"report_path": str(report_path), "report_mode": bundle["report_mode"]}
