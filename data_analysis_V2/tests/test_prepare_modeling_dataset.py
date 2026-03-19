from __future__ import annotations

import pandas as pd

from data_analysis_V2.scripts.column_profile import build_column_profile
from data_analysis_V2.scripts.prepare_modeling_dataset import apply_data_processing


def test_apply_data_processing_can_deduplicate_and_drop_flags() -> None:
    df = pd.DataFrame(
        {
            "id_col": [1, 1, 2, 3],
            "constant_col": ["x", "x", "x", "x"],
            "dominant_col": ["a", "a", "a", "b"],
            "useful_col": ["u1", "u1", "u2", "u3"],
            "target": [0, 0, 1, 0],
        }
    )
    profile = build_column_profile(df, target="target")
    cleaned, summary = apply_data_processing(
        df,
        target="target",
        deduplicate=True,
        profile=profile,
        drop_profile_flags=["constant"],
        drop_features=["id_col"],
    )
    assert len(cleaned) == 3
    assert "constant_col" not in cleaned.columns
    assert "id_col" not in cleaned.columns
    assert "useful_col" in cleaned.columns
    assert summary["steps"][0]["action"] == "deduplicate_rows"


def test_apply_data_processing_can_drop_risk_labels_and_keep_features() -> None:
    df = pd.DataFrame(
        {
            "safe_feature": ["a", "b", "c"],
            "soft_proxy_feature": ["x", "y", "z"],
            "target": [0, 1, 0],
        }
    )
    feature_risk_report = {
        "features": [
            {"feature": "safe_feature", "label": "safe", "reason": "safe"},
            {"feature": "soft_proxy_feature", "label": "soft_proxy", "reason": "proxy"},
        ],
        "summary": {"label_counts": {"safe": 1, "soft_proxy": 1}, "hard_block": False},
    }
    cleaned, _ = apply_data_processing(
        df,
        target="target",
        keep_features=["safe_feature", "soft_proxy_feature"],
        feature_risk_report=feature_risk_report,
        drop_risk_labels=["soft_proxy"],
    )
    assert list(cleaned.columns) == ["safe_feature", "target"]


def test_apply_data_processing_can_deduplicate_again_after_feature_drops() -> None:
    df = pd.DataFrame(
        {
            "safe_feature": ["a", "a", "b"],
            "soft_proxy_feature": ["x1", "x2", "x3"],
            "target": [0, 0, 1],
        }
    )
    feature_risk_report = {
        "features": [
            {"feature": "safe_feature", "label": "safe", "reason": "safe"},
            {"feature": "soft_proxy_feature", "label": "soft_proxy", "reason": "proxy"},
        ],
        "summary": {"label_counts": {"safe": 1, "soft_proxy": 1}, "hard_block": False},
    }
    cleaned, summary = apply_data_processing(
        df,
        target="target",
        deduplicate=True,
        feature_risk_report=feature_risk_report,
        drop_risk_labels=["soft_proxy"],
    )
    assert len(cleaned) == 2
    assert list(cleaned.columns) == ["safe_feature", "target"]
    assert summary["steps"][-1]["action"] == "deduplicate_rows_after_feature_processing"
    assert summary["steps"][-1]["rows_removed"] == 1
