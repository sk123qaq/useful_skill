from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from data_analysis_V2.scripts.baseline_runner import run_baseline_ladder
from data_analysis_V2.scripts.common import (
    configure_matplotlib_defaults,
    ensure_run_dir,
    read_json,
    write_artifact,
    write_status,
)
from data_analysis_V2.scripts.column_profile import build_column_profile
from data_analysis_V2.scripts.decision_context_builder import (
    build_baseline_judgment_context,
    build_scout_judgment_context,
    write_judgment_context,
)
from data_analysis_V2.scripts.evidence_grader import build_claim_registry, build_judgment_bundle
from data_analysis_V2.scripts.explainability_guarded import build_guarded_explainability
from data_analysis_V2.scripts.feature_risk_audit import audit_feature_risk
from data_analysis_V2.scripts.formal_report_export_v2 import export_formal_report_v2
from data_analysis_V2.scripts.gate_evaluator import evaluate_gates
from data_analysis_V2.scripts.report_bundle_builder import build_report_bundle
from data_analysis_V2.scripts.route_problem import build_analysis_contract, route_problem
from data_analysis_V2.scripts.schemas import validate_agent_decision
from data_analysis_V2.scripts.scout_audit import run_scout_audit


def _load_dataset(
    input_path: str | None,
    db_url: str | None,
    query: str | None,
    data_scope: str,
    sample_rows: int | None,
) -> pd.DataFrame:
    if input_path:
        path = Path(input_path)
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path)
        elif path.suffix.lower() in {".parquet", ".pq"}:
            df = pd.read_parquet(path)
        elif path.suffix.lower() in {".json", ".jsonl"}:
            df = pd.read_json(path)
        elif path.suffix.lower() in {".xlsx", ".xls"}:
            df = pd.read_excel(path)
        else:
            raise ValueError(f"Unsupported input file: {path}")
    elif db_url and query:
        if db_url.startswith("sqlite:///"):
            connection = sqlite3.connect(db_url.replace("sqlite:///", "", 1))
            try:
                df = pd.read_sql_query(query, connection)
            finally:
                connection.close()
        elif db_url.startswith("duckdb:///"):
            connection = duckdb.connect(db_url.replace("duckdb:///", "", 1))
            try:
                df = connection.execute(query).df()
            finally:
                connection.close()
        else:
            raise ValueError("Unsupported db_url. Use sqlite:/// or duckdb:///")
    else:
        raise ValueError("Either input_path or (db_url + query) is required.")

    if data_scope == "sample" and sample_rows and len(df) > sample_rows:
        return df.sample(sample_rows, random_state=42).reset_index(drop=True)
    return df.reset_index(drop=True)


def _artifact_or_build(run_dir: Path, name: str, builder):
    path = run_dir / f"{name}.json"
    if path.exists():
        return read_json(path)
    payload = builder()
    write_artifact(run_dir, name, payload)
    return payload


def _load_agent_decision(run_dir: Path, filename: str, expected_stage: str) -> dict[str, Any] | None:
    path = run_dir / filename
    if not path.exists():
        return None
    decision = validate_agent_decision(read_json(path))
    if decision["stage"] != expected_stage:
        raise ValueError(f"{filename} has stage={decision['stage']}, expected {expected_stage}")
    return decision


def run_pipeline(
    question: str = "",
    input_path: str | None = None,
    db_url: str | None = None,
    query: str | None = None,
    task: str | None = None,
    target: str | None = None,
    time_col: str | None = None,
    data_scope: str = "sample",
    sample_rows: int | None = 5000,
    continue_after_scout: bool = False,
    continue_after_baseline: bool = False,
    formal_report: bool = False,
    output_dir: str | None = None,
    report_title: str | None = None,
) -> dict[str, Any]:
    run_dir = ensure_run_dir(output_dir)
    configure_matplotlib_defaults(run_dir / ".mplconfig")
    write_status(run_dir, "initialized", "running")

    contract = _artifact_or_build(
        run_dir,
        "analysis_contract",
        lambda: build_analysis_contract(
            question=question,
            task=task,
            target=target,
            time_col=time_col,
            data_scope=data_scope,
            sample_rows=sample_rows,
            continue_after_scout=continue_after_scout,
            continue_after_baseline=continue_after_baseline,
        ),
    )
    df = _load_dataset(input_path, db_url, query, data_scope, sample_rows)
    write_status(run_dir, "scouting", "running", {"row_count": len(df)})
    scout_report = _artifact_or_build(run_dir, "scout_report", lambda: run_scout_audit(df, target=target, time_col=time_col))
    column_profile = _artifact_or_build(run_dir, "column_profile", lambda: build_column_profile(df, target=target))
    feature_risk_report = _artifact_or_build(run_dir, "feature_risk_report", lambda: audit_feature_risk(df, target=target))
    route_decision = _artifact_or_build(
        run_dir,
        "route_decision",
        lambda: route_problem(contract, scout_report, feature_risk_report),
    )
    scout_context = _artifact_or_build(
        run_dir,
        "judgment_context_after_scout",
        lambda: build_scout_judgment_context(contract, scout_report, feature_risk_report, route_decision, column_profile),
    )
    write_judgment_context(run_dir, "judgment_context_after_scout", scout_context)

    if route_decision["route"] == "stop_and_report":
        gate_review = _artifact_or_build(
            run_dir,
            "gate_review",
            lambda: evaluate_gates(route_decision, feature_risk_report),
        )
        judgment_bundle = _artifact_or_build(
            run_dir,
            "judgment_bundle",
            lambda: build_judgment_bundle(gate_review),
        )
        claim_registry = _artifact_or_build(
            run_dir,
            "claim_registry",
            lambda: build_claim_registry(judgment_bundle, scout_report=scout_report, route_decision=route_decision),
        )
        build_report_bundle(run_dir, judgment_bundle=judgment_bundle, claim_registry=claim_registry, route_decision=route_decision)
        write_status(run_dir, "stop_and_report", "completed", {"route": route_decision["route"]})
        return {"run_dir": str(run_dir), "state": "stop_and_report", "route": route_decision["route"]}

    if route_decision["route"] == "predictive":
        scout_decision = _load_agent_decision(run_dir, "data_processing_decision.json", "after_scout")
        if not continue_after_scout or scout_decision is None:
            write_status(
                run_dir,
                "awaiting_agent_review_after_scout",
                "completed",
                {"route": route_decision["route"], "required_decision_file": "data_processing_decision.json"},
            )
            return {"run_dir": str(run_dir), "state": "awaiting_agent_review_after_scout", "route": route_decision["route"]}
        if scout_decision["decision"] != "continue_to_baseline":
            write_status(
                run_dir,
                "agent_halt_after_scout",
                "completed",
                {"route": route_decision["route"], "agent_decision": scout_decision["decision"]},
            )
            return {"run_dir": str(run_dir), "state": "agent_halt_after_scout", "agent_decision": scout_decision["decision"]}
        write_status(run_dir, "baselining", "running")
        baseline_results = _artifact_or_build(
            run_dir,
            "baseline_results",
            lambda: run_baseline_ladder(
                df,
                target=target or route_decision["suggested_task_type"],
                task=route_decision["suggested_task_type"],
                output_dir=str(run_dir),
                time_col=time_col,
            ),
        )
        baseline_context = _artifact_or_build(
            run_dir,
            "judgment_context_after_baseline",
            lambda: build_baseline_judgment_context(
                contract,
                scout_report,
                feature_risk_report,
                route_decision,
                baseline_results,
            ),
        )
        write_judgment_context(run_dir, "judgment_context_after_baseline", baseline_context)
        baseline_decision = _load_agent_decision(run_dir, "modeling_decision.json", "after_baseline")
        if not continue_after_baseline or baseline_decision is None:
            write_status(
                run_dir,
                "awaiting_agent_review_after_baseline",
                "completed",
                {"route": route_decision["route"], "required_decision_file": "modeling_decision.json"},
            )
            return {"run_dir": str(run_dir), "state": "awaiting_agent_review_after_baseline", "route": route_decision["route"]}
        if baseline_decision["decision"] != "continue_to_report":
            write_status(
                run_dir,
                "agent_halt_after_baseline",
                "completed",
                {"route": route_decision["route"], "agent_decision": baseline_decision["decision"]},
            )
            return {"run_dir": str(run_dir), "state": "agent_halt_after_baseline", "agent_decision": baseline_decision["decision"]}
        explainability = _artifact_or_build(
            run_dir,
            "explainability_guarded",
            lambda: build_guarded_explainability(df, target=target or "", feature_risk_report=feature_risk_report),
        )
        gate_review = _artifact_or_build(
            run_dir,
            "gate_review",
            lambda: evaluate_gates(route_decision, feature_risk_report, baseline_results, explainability),
        )
        judgment_bundle = _artifact_or_build(
            run_dir,
            "judgment_bundle",
            lambda: build_judgment_bundle(gate_review, baseline_results, explainability),
        )
        claim_registry = _artifact_or_build(
            run_dir,
            "claim_registry",
            lambda: build_claim_registry(
                judgment_bundle,
                scout_report=scout_report,
                baseline_results=baseline_results,
                explainability=explainability,
                route_decision=route_decision,
            ),
        )
        bundle = build_report_bundle(run_dir, judgment_bundle=judgment_bundle, claim_registry=claim_registry, route_decision=route_decision)
        if formal_report:
            export_formal_report_v2(run_dir, title=report_title)
        write_status(run_dir, "completed", "completed", {"report_mode": bundle["report_mode"]})
        return {"run_dir": str(run_dir), "state": "completed", "report_mode": bundle["report_mode"]}

    judgment_bundle = _artifact_or_build(
        run_dir,
        "judgment_bundle",
        lambda: build_judgment_bundle(
            {
                "gate_results": {
                    "baseline": {"passed": False, "reason": "Not applicable."},
                    "stability": {"passed": False, "reason": "Not applicable."},
                    "feature_risk": {"passed": True, "reason": "No supervised feature gate needed."},
                    "report": {"passed": True, "reason": "Descriptive route."},
                },
                "max_evidence_grade": "exploratory",
                "blockers": [],
                "warnings": [],
            }
        ),
    )
    claim_registry = _artifact_or_build(
        run_dir,
        "claim_registry",
        lambda: build_claim_registry(judgment_bundle, scout_report=scout_report, route_decision=route_decision),
    )
    bundle = build_report_bundle(run_dir, judgment_bundle=judgment_bundle, claim_registry=claim_registry, route_decision=route_decision)
    if formal_report:
        export_formal_report_v2(run_dir, title=report_title)
    write_status(run_dir, "completed", "completed", {"report_mode": bundle["report_mode"]})
    return {"run_dir": str(run_dir), "state": "completed", "report_mode": bundle["report_mode"]}
