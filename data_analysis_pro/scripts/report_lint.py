#!/usr/bin/env python3
"""report_lint.py: enforce claim/evidence consistency before delivery."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402
from workflow import EVIDENCE_GRADES, load_json, write_json  # noqa: E402

GRADE_ORDER = {"not_usable": 0, "exploratory": 1, "report-ready": 2}
REQUIRED_SECTIONS = ["决策问题", "数据与口径", "方法", "结果", "结论", "局限", "工件索引"]


def lint(report_path: Path, claims_path: Path, gate_path: Path, run_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not report_path.exists():
        errors.append(f"report not found: {report_path}")
        report = ""
    else:
        report = report_path.read_text(encoding="utf-8")
    if not claims_path.exists():
        errors.append(f"claim_registry not found: {claims_path}")
        claims: list[dict[str, Any]] = []
    else:
        claims = load_json(claims_path).get("claims", [])
    gate = load_json(gate_path) if gate_path.exists() else {}
    gate_grade = gate.get("max_evidence_grade")
    if not gate:
        errors.append("gate_review.json missing; cannot certify evidence grade")
    elif gate_grade not in GRADE_ORDER:
        errors.append(f"invalid gate grade: {gate_grade}")

    for section in REQUIRED_SECTIONS:
        if section not in report:
            errors.append(f"missing section: {section}")

    if not claims:
        errors.append("claim_registry has no claims")
    claim_ids = set()
    for claim in claims:
        cid = claim.get("claim_id")
        if not cid:
            errors.append("claim without claim_id")
            continue
        if cid in claim_ids:
            errors.append(f"duplicate claim_id: {cid}")
        claim_ids.add(cid)
        if f"[{cid}]" not in report:
            errors.append(f"claim {cid} not referenced in report")
        if not claim.get("text"):
            errors.append(f"claim {cid} has no text")
        grade = claim.get("evidence_grade")
        if grade not in EVIDENCE_GRADES:
            errors.append(f"claim {cid} invalid evidence_grade: {grade}")
        elif gate_grade in GRADE_ORDER and GRADE_ORDER[grade] > GRADE_ORDER[gate_grade]:
            errors.append(f"claim {cid} grade {grade} exceeds gate {gate_grade}")
        support = claim.get("supported_by")
        paths = support if isinstance(support, list) else [support]
        if not paths or any(not p for p in paths):
            errors.append(f"claim {cid} has empty supported_by")
        for rel in paths:
            if not rel:
                continue
            candidate = Path(rel) if Path(rel).is_absolute() else run_dir / rel
            if not candidate.exists():
                errors.append(f"claim {cid} evidence missing: {rel}")

    if gate_grade and gate_grade != "report-ready" and "report-ready" in report:
        errors.append("report claims report-ready but gate does not")
    if "TODO" in report or "TBD" in report:
        warnings.append("report contains TODO/TBD")
    # Artifact paths in backticks should resolve if they look like files.
    for token in re.findall(r"`([^`]+)`", report):
        if "/" in token and not token.startswith(("http", "target=", "time=")):
            candidate = Path(token) if Path(token).is_absolute() else run_dir / token
            if not candidate.exists() and token not in {"analysis_contract.json"}:
                warnings.append(f"referenced path not found: {token}")

    result = {
        "stage": "report_lint",
        "passed": not errors,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "n_claims": len(claims),
        "gate_grade": gate_grade,
        "created_at": common.now_utc_iso(),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint report against claims and gate.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--report-path", default=None)
    parser.add_argument("--claims-path", default=None)
    parser.add_argument("--gate-path", default=None)
    parser.add_argument("--output-path", default=None)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    report_path = Path(args.report_path) if args.report_path else run_dir / "report.md"
    claims_path = Path(args.claims_path) if args.claims_path else run_dir / "claim_registry.json"
    gate_path = Path(args.gate_path) if args.gate_path else run_dir / "gate_review.json"
    result = lint(report_path, claims_path, gate_path, run_dir)
    out = Path(args.output_path) if args.output_path else run_dir / "report_lint.json"
    write_json(out, result)
    print(json.dumps({"output_path": str(out), "passed": result["passed"],
                      "errors": result["errors"]}, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
