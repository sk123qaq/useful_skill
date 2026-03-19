from __future__ import annotations

import pandas as pd

from data_analysis_V2.scripts.feature_risk_audit import audit_feature_risk
from data_analysis_V2.scripts.route_problem import build_analysis_contract, route_problem
from data_analysis_V2.scripts.scout_audit import run_scout_audit


def _predictive_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "feature_num_1": [0.9, 0.8, 0.2, 0.1],
            "feature_cat_1": ["A", "A", "B", "B"],
            "target": [1, 1, 0, 0],
        }
    )


def test_missing_target_for_predictive_question_routes_to_stop() -> None:
    df = _predictive_df()
    contract = build_analysis_contract(question="predict churn", task="predictive", target=None)
    scout = run_scout_audit(df, target=None)
    feature_risk = audit_feature_risk(df, target=None)
    decision = route_problem(contract, scout, feature_risk)
    assert decision["route"] == "stop_and_report"
    assert any("target" in blocker.lower() for blocker in decision["blockers"])


def test_descriptive_question_routes_to_descriptive() -> None:
    df = _predictive_df().drop(columns=["target"])
    contract = build_analysis_contract(question="describe customer distribution", task="descriptive", target=None)
    scout = run_scout_audit(df)
    feature_risk = audit_feature_risk(df)
    decision = route_problem(contract, scout, feature_risk)
    assert decision["route"] == "descriptive"


def test_predictive_question_with_target_routes_to_predictive() -> None:
    df = _predictive_df()
    contract = build_analysis_contract(question="predict churn", task="classification", target="target")
    scout = run_scout_audit(df, target="target")
    feature_risk = audit_feature_risk(df, target="target")
    decision = route_problem(contract, scout, feature_risk)
    assert decision["route"] == "predictive"
    assert decision["suggested_task_type"] == "classification"


def test_causal_question_routes_to_causal() -> None:
    df = pd.DataFrame(
        {
            "treated": [0, 0, 1, 1],
            "post_period": [0, 1, 0, 1],
            "outcome": [10, 11, 13, 16],
        }
    )
    contract = build_analysis_contract(question="what was the treatment effect?", task="causal", target="outcome")
    scout = run_scout_audit(df, target="outcome")
    feature_risk = audit_feature_risk(df, target="outcome")
    decision = route_problem(contract, scout, feature_risk)
    assert decision["route"] == "causal"


def test_hard_leakage_forces_stop_and_report() -> None:
    df = pd.DataFrame(
        {
            "feature_num_1": [0.9, 0.8, 0.2, 0.1],
            "leakage_target_copy": [1, 1, 0, 0],
            "target": [1, 1, 0, 0],
        }
    )
    contract = build_analysis_contract(question="predict churn", task="classification", target="target")
    scout = run_scout_audit(df, target="target")
    feature_risk = audit_feature_risk(df, target="target")
    decision = route_problem(contract, scout, feature_risk)
    assert decision["route"] == "stop_and_report"
    assert "hard leakage" in decision["reasons"][0].lower() or "hard leakage" in decision["blockers"][0].lower()


def test_scout_and_feature_risk_include_required_fields() -> None:
    df = _predictive_df()
    scout = run_scout_audit(df, target="target")
    feature_risk = audit_feature_risk(df, target="target")
    assert {"row_count", "missingness", "duplicate_rate", "target_distribution", "suspicious_fields"} <= set(scout)
    labels = {entry["label"] for entry in feature_risk["features"]}
    assert labels <= {"safe", "soft_proxy", "post_outcome", "hard_leakage", "collection_artifact"}
