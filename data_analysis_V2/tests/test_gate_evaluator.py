from __future__ import annotations

from copy import deepcopy

from data_analysis_V2.scripts.gate_evaluator import evaluate_gates


def _baseline_results() -> dict:
    return {
        "task_type": "classification",
        "primary_metric": "accuracy",
        "primary_metric_direction": "max",
        "best_model_name": "logistic_regression",
        "best_dummy_name": "dummy_most_frequent",
        "models": [
            {
                "model_name": "dummy_most_frequent",
                "family": "dummy",
                "mean_metrics": {"accuracy": 0.60, "f1_macro": 0.55},
                "std_metrics": {"accuracy": 0.01, "f1_macro": 0.01},
            },
            {
                "model_name": "logistic_regression",
                "family": "linear",
                "mean_metrics": {"accuracy": 0.78, "f1_macro": 0.77},
                "std_metrics": {"accuracy": 0.03, "f1_macro": 0.03},
            },
        ],
    }


def _feature_risk_report() -> dict:
    return {
        "features": [
            {"feature": "feature_num_1", "label": "safe", "reason": "safe"},
            {"feature": "entity_id", "label": "collection_artifact", "reason": "id-like"},
        ],
        "summary": {"label_counts": {"safe": 1, "collection_artifact": 1}, "hard_block": False},
    }


def test_model_weaker_than_dummy_fails_baseline_gate() -> None:
    baseline_results = _baseline_results()
    baseline_results["models"][1]["mean_metrics"]["accuracy"] = 0.58
    review = evaluate_gates({"route": "predictive", "blockers": []}, _feature_risk_report(), baseline_results, {"top_features": []})
    assert not review["gate_results"]["baseline"]["passed"]
    assert review["max_evidence_grade"] == "exploratory"


def test_high_variance_fails_stability_gate() -> None:
    baseline_results = _baseline_results()
    baseline_results["models"][1]["std_metrics"]["accuracy"] = 0.20
    review = evaluate_gates({"route": "predictive", "blockers": []}, _feature_risk_report(), baseline_results, {"top_features": []})
    assert not review["gate_results"]["stability"]["passed"]
    assert review["max_evidence_grade"] == "exploratory"


def test_risky_top_features_fail_feature_risk_gate() -> None:
    explainability = {
        "top_features": [
            {"feature": "target_proxy_after_event", "risk_label": "post_outcome"},
        ]
    }
    review = evaluate_gates({"route": "predictive", "blockers": []}, _feature_risk_report(), _baseline_results(), explainability)
    assert not review["gate_results"]["feature_risk"]["passed"]
    assert review["max_evidence_grade"] == "exploratory"


def test_stop_route_is_not_usable() -> None:
    review = evaluate_gates({"route": "stop_and_report", "blockers": ["hard leakage"]}, _feature_risk_report(), None, None)
    assert review["max_evidence_grade"] == "not_usable"
    assert not review["gate_results"]["report"]["passed"]
