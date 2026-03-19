from __future__ import annotations

from pathlib import Path
from typing import Any

from data_analysis_V2.scripts.common import read_json, write_artifact
from data_analysis_V2.scripts.evidence_grader import validate_claim_grade_transitions
from data_analysis_V2.scripts.schemas import validate_claim_registry, validate_judgment_bundle


def _load_required(run_dir: Path, artifact_name: str) -> dict[str, Any]:
    path = run_dir / f"{artifact_name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing required artifact: {path}")
    return read_json(path)


def build_report_bundle(
    run_dir: str | Path,
    judgment_bundle: dict[str, Any] | None = None,
    claim_registry: dict[str, Any] | None = None,
    route_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_path = Path(run_dir)
    judgment = validate_judgment_bundle(judgment_bundle or _load_required(run_path, "judgment_bundle"))
    claims = validate_claim_registry(claim_registry or _load_required(run_path, "claim_registry"))
    validate_claim_grade_transitions(claims, judgment)
    route = route_decision or ((run_path / "route_decision.json").exists() and _load_required(run_path, "route_decision")) or {}
    bundle = {
        "report_mode": judgment["allowed_report_mode"],
        "summary": judgment["safe_summary"],
        "claims": claims["claims"],
        "guardrails": judgment["narrative_guardrails"],
        "route": route.get("route"),
    }
    write_artifact(run_path, "report_bundle", bundle)
    return bundle
