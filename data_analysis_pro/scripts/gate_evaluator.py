#!/usr/bin/env python3
"""gate_evaluator.py: hard evidence gate.

An empty run directory is not "report-ready". A missing baseline is not
"passed". A hard-leakage feature is a blocker. This script is intentionally
unforgiving: the Agent can downgrade to exploratory, but cannot fake a pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402
from split_plan import validate_plan  # noqa: E402
from workflow import EVIDENCE_GRADES, load_json, write_json  # noqa: E402

GRADE_ORDER = {"not_usable": 0, "exploratory": 1, "report-ready": 2}


def _result(status: str, reasons: list[str] | None = None, details: Any = None) -> dict[str, Any]:
    return {"status": status, "reasons": reasons or [], "details": details}


def _exists(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _load_optional(path: Path) -> dict[str, Any]:
    return load_json(path) if _exists(path) else {}


def stability_check(train_metrics: dict[str, Any], test_metrics: dict[str, Any], threshold: float = 0.2) -> dict[str, Any]:
    """Backward-compatible helper; not a substitute for CV spread."""
    keys = set(train_metrics) & set(test_metrics)
    diffs = {}
    for key in keys:
        a, b = train_metrics.get(key), test_metrics.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a not in (0, None):
            diffs[key] = abs((b - a) / a)
    worst = max(diffs.values()) if diffs else None
    return {"passed": bool(worst is not None and worst <= threshold), "worst_relative_change": worst, "diffs": diffs}


def intuition_check(explainability_report: dict[str, Any], expected_signs: dict[str, int]) -> dict[str, Any]:
    checks = []
    for feature, expected in expected_signs.items():
        item = next((x for x in explainability_report.get("features", []) if x.get("feature") == feature), None)
        if item is None:
            checks.append({"feature": feature, "passed": False, "reason": "feature not found"})
            continue
        actual = item.get("sign") or item.get("direction")
        checks.append({"feature": feature, "passed": actual == expected, "expected": expected, "actual": actual})
    return {"passed": all(c["passed"] for c in checks), "checks": checks}


def evaluate(run_dir: Path) -> dict[str, Any]:
    contract = _load_optional(run_dir / "analysis_contract.json")
    profile = _load_optional(run_dir / "profile.json")
    cleaning = _load_optional(run_dir / "cleaning_report.json")
    risk = _load_optional(run_dir / "feature_risk_report.json")
    plan = _load_optional(run_dir / "split_plan.json")
    baseline = _load_optional(run_dir / "baseline_results.json")
    causal_design = _load_optional(run_dir / "causal_design.json")
    causal_report = _load_optional(run_dir / "causal_report.json")
    experiment = _load_optional(run_dir / "experiment_report.json")
    claims = _load_optional(run_dir / "claim_registry.json")
    report_lint = _load_optional(run_dir / "report_lint.json")

    route = contract.get("task", "unknown")
    time_col = contract.get("time_col")
    gates: dict[str, dict[str, Any]] = {}
    blockers: list[str] = []
    warnings: list[str] = []

    # 1. contract
    if not contract:
        gates["contract"] = _result("fail", ["analysis_contract.json is missing"])
        blockers.append("contract missing")
    else:
        missing = [k for k in ("decision_question", "task", "unit_of_analysis", "success_criteria", "stop_conditions")
                   if not contract.get(k)]
        gates["contract"] = _result("pass" if not missing else "fail", [f"missing/empty: {k}" for k in missing])
        if missing:
            blockers.append("contract incomplete")

    # 2. data quality
    if not profile:
        gates["data_quality"] = _result("fail", ["profile.json is missing"])
        blockers.append("profile missing")
    else:
        rows = int(profile.get("row_count") or 0)
        reasons = []
        if rows < 30:
            reasons.append(f"row_count={rows} < 30")
        target = contract.get("target")
        if target:
            target_profile = next((p for p in profile.get("profiles", []) if p.get("column") == target), None)
            if not target_profile:
                reasons.append(f"target {target!r} not in profile")
            elif target_profile.get("missing_rate", 0) > 0.5:
                reasons.append(f"target missing_rate={target_profile['missing_rate']:.2f} > 0.50")
        if cleaning and cleaning.get("after", {}).get("rows") == 0:
            reasons.append("cleaning removed every row")
        gates["data_quality"] = _result("pass" if not reasons else "fail", reasons,
                                         {"rows": rows, "source": profile.get("source")})
        if reasons:
            blockers.append("data quality")

    # 3. feature risk
    needs_risk = route in {"predictive", "causal", "experiment"}
    if not needs_risk:
        gates["feature_risk"] = _result("not_applicable", ["only required for predictive/causal/experiment"])
    elif not risk:
        gates["feature_risk"] = _result("fail", ["feature_risk_report.json is missing"])
        blockers.append("feature risk missing")
    else:
        features = risk.get("features", [])
        unconfirmed = [f["feature"] for f in features if not f.get("confirmed")]
        hard = [f["feature"] for f in features if f.get("used", True) and f.get("label") == "hard_leakage"]
        post = [f["feature"] for f in features if f.get("used", True) and f.get("label") == "post_outcome"]
        artifacts = [f["feature"] for f in features if f.get("used", True) and f.get("label") == "collection_artifact"]
        reasons = []
        if unconfirmed:
            reasons.append(f"unconfirmed: {', '.join(unconfirmed[:8])}")
        if hard:
            reasons.append(f"hard_leakage: {', '.join(hard)}")
        if post:
            reasons.append(f"post_outcome: {', '.join(post)}")
        if artifacts:
            reasons.append(f"used collection artifacts: {', '.join(artifacts)}")
        gates["feature_risk"] = _result("pass" if not reasons else "fail", reasons,
                                         {"summary": risk.get("summary", {})})
        if hard or post:
            blockers.append("feature leakage")
        elif unconfirmed or artifacts:
            warnings.append("feature risk requires confirmation/cleanup")

    # 4. split
    needs_split = route == "predictive" or (route == "causal" and bool(time_col))
    if not needs_split:
        gates["split"] = _result("not_applicable")
    elif not plan:
        gates["split"] = _result("fail", ["split_plan.json is missing"])
        blockers.append("split plan missing")
    else:
        errors = validate_plan(plan)
        if time_col and plan.get("strategy") == "kfold":
            errors.append("time series must not use random kfold")
        gates["split"] = _result("pass" if not errors else "fail", errors,
                                  {"strategy": plan.get("strategy"), "folds": plan.get("n_splits")})
        if errors:
            blockers.append("invalid split")

    # 5. baseline
    if route != "predictive":
        gates["baseline"] = _result("not_applicable")
    elif not baseline:
        gates["baseline"] = _result("fail", ["baseline_results.json is missing"])
        blockers.append("baseline missing")
    else:
        comparison = baseline.get("dummy_comparison", {})
        stability = baseline.get("stability", {})
        reasons = []
        if not baseline.get("best_non_dummy_name") and not comparison.get("best_non_dummy"):
            # Old reports may not carry this key; infer from models.
            non_dummy = [m for m in baseline.get("models", []) if m.get("family") != "dummy"]
            if not non_dummy:
                reasons.append("no non-dummy model")
        if comparison.get("beats_dummy") is False:
            reasons.append("best non-dummy does not beat dummy by the required margin")
        if stability.get("stable") is False:
            reasons.append("CV std/mean > 0.2")
        status = "pass" if not reasons else "exploratory"
        gates["baseline"] = _result(status, reasons,
                                     {"best_model": baseline.get("best_model_name"),
                                      "metric": baseline.get("primary_metric"),
                                      "comparison": comparison, "stability": stability})
        if status == "exploratory":
            warnings.append("baseline is exploratory")
        if "no non-dummy model" in reasons:
            blockers.append("no predictive model")

    # 6. causal
    if route != "causal":
        gates["causal"] = _result("not_applicable")
    else:
        reasons = []
        if not causal_design:
            reasons.append("causal_design.json is missing")
        else:
            for key in ("estimand", "treatment", "outcome", "identification_assumptions"):
                if not causal_design.get(key):
                    reasons.append(f"causal_design missing/empty: {key}")
        if not causal_report:
            reasons.append("causal_report.json is missing")
        gates["causal"] = _result("pass" if not reasons else "exploratory", reasons)
        if reasons:
            warnings.append("causal evidence incomplete")

    # 7. experiment
    if route != "experiment":
        gates["experiment"] = _result("not_applicable")
    else:
        reasons = []
        if not experiment:
            reasons.append("experiment_report.json is missing")
        else:
            srm = experiment.get("srm_p_value")
            if srm is not None and float(srm) <= 0.001:
                reasons.append(f"SRM p={srm} <= 0.001")
            if experiment.get("balance_passed") is False:
                reasons.append("covariate balance failed")
        gates["experiment"] = _result("pass" if not reasons else "fail", reasons)
        if reasons:
            blockers.append("experiment invalid")

    # 8. claims (optional at gate time; report_lint is the final check)
    claim_errors = []
    if claims:
        for claim in claims.get("claims", []):
            support = claim.get("supported_by")
            paths = support if isinstance(support, list) else [support]
            for rel in paths:
                if not rel:
                    claim_errors.append(f"{claim.get('claim_id', '?')}: empty supported_by")
                elif not (Path(rel).exists() if Path(rel).is_absolute() else (run_dir / rel).exists()):
                    claim_errors.append(f"{claim.get('claim_id', '?')}: evidence not found: {rel}")
            if claim.get("evidence_grade") not in EVIDENCE_GRADES:
                claim_errors.append(f"{claim.get('claim_id', '?')}: invalid evidence grade")
    gates["claims"] = _result("pass" if claims and not claim_errors else "not_applicable",
                              claim_errors, {"n_claims": len(claims.get("claims", [])) if claims else 0})
    if claim_errors:
        warnings.append("claim registry has broken evidence links")

    # 9. report lint
    if report_lint:
        gates["report"] = _result("pass" if report_lint.get("passed") else "fail",
                                  report_lint.get("errors", []))
        if not report_lint.get("passed"):
            warnings.append("report lint failed")
    else:
        gates["report"] = _result("not_applicable", ["report_lint.json not yet generated"])

    hard_blockers = {"contract missing", "contract incomplete", "profile missing", "data quality",
                     "feature risk missing", "feature leakage", "split plan missing", "invalid split",
                     "baseline missing", "no predictive model", "experiment invalid"}
    if any(b in hard_blockers for b in blockers):
        grade = "not_usable"
    elif any(g["status"] == "fail" for g in gates.values()):
        grade = "exploratory"
    elif any(g["status"] == "exploratory" for g in gates.values()):
        grade = "exploratory"
    else:
        grade = "report-ready"

    return {
        "stage": "gate",
        "route": route,
        "status": "blocked" if grade == "not_usable" else ("exploratory" if grade == "exploratory" else "report_ready"),
        "max_evidence_grade": grade,
        "gate_results": gates,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "created_at": common.now_utc_iso(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate analysis gates.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output-path", default=None)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.exists():
        raise SystemExit(f"run dir not found: {run_dir}")
    review = evaluate(run_dir)
    out = Path(args.output_path) if args.output_path else run_dir / "gate_review.json"
    write_json(out, review)
    print(json.dumps({"output_path": str(out), "status": review["status"],
                      "max_evidence_grade": review["max_evidence_grade"],
                      "blockers": review["blockers"]}, ensure_ascii=False, indent=2))
    return 0 if review["max_evidence_grade"] != "not_usable" else 2


if __name__ == "__main__":
    raise SystemExit(main())
