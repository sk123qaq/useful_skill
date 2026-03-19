from __future__ import annotations

import pandas as pd

from data_analysis_V2.scripts.column_profile import build_column_profile


def test_column_profile_flags_constant_and_dominant_and_missing() -> None:
    df = pd.DataFrame(
        {
            "constant_col": ["x", "x", "x", "x", "x"],
            "dominant_col": ["a", "a", "a", "a", "b"],
            "missing_col": [1, None, None, None, None],
            "target": [0, 1, 0, 1, 0],
        }
    )
    profile = build_column_profile(df, target="target")
    by_column = {entry["column"]: entry for entry in profile["profiles"]}
    assert "constant" in by_column["constant_col"]["flags"]
    assert "dominant_category" not in by_column["dominant_col"]["flags"]
    assert "high_missingness" in by_column["missing_col"]["flags"]
    assert "target" in by_column["target"]["flags"]


def test_column_profile_summary_tracks_flag_counts() -> None:
    df = pd.DataFrame(
        {
            "constant_col": ["x", "x", "x"],
            "regular_col": ["a", "b", "c"],
            "target": [0, 1, 0],
        }
    )
    profile = build_column_profile(df, target="target")
    assert profile["summary"]["flag_counts"]["constant"] == 1
    assert "constant_col" in profile["summary"]["constant_features"]
