from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))

from data_analysis_V2.scripts.common import write_json


def load_table(input_path: str | Path) -> pd.DataFrame:
    path = Path(input_path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix in {".json", ".jsonl"}:
        return pd.read_json(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"Unsupported input file: {path}")


def _top_values(series: pd.Series, top_n: int) -> list[dict[str, Any]]:
    counts = series.astype(str).value_counts(dropna=False).head(top_n)
    total = len(series) or 1
    return [
        {
            "value": str(value),
            "count": int(count),
            "share": float(count / total),
        }
        for value, count in counts.items()
    ]


def build_column_profile(df: pd.DataFrame, target: str | None = None, top_n: int = 5) -> dict[str, Any]:
    profiles: list[dict[str, Any]] = []
    flag_counter: Counter[str] = Counter()
    row_count = len(df)
    for column in df.columns:
        series = df[column]
        missing_rate = float(series.isna().mean())
        unique_count = int(series.nunique(dropna=True))
        non_null = series.dropna()
        dominant_share = float(non_null.astype(str).value_counts(normalize=True).iloc[0]) if not non_null.empty else 0.0
        flags: list[str] = []
        if unique_count <= 1:
            flags.append("constant")
        if missing_rate >= 0.2:
            flags.append("high_missingness")
        if row_count > 0 and unique_count > max(50, int(row_count * 0.8)):
            flags.append("high_cardinality")
        if unique_count > 1 and dominant_share >= 0.95:
            flags.append("dominant_category")
        if column == target:
            flags.append("target")
        for flag in flags:
            flag_counter[flag] += 1
        profiles.append(
            {
                "column": column,
                "dtype": str(series.dtype),
                "missing_rate": missing_rate,
                "unique_count": unique_count,
                "dominant_share": dominant_share,
                "top_values": _top_values(series, top_n=top_n),
                "flags": flags,
            }
        )
    summary = {
        "flag_counts": dict(sorted(flag_counter.items())),
        "constant_features": [p["column"] for p in profiles if "constant" in p["flags"]],
        "high_missingness_features": [p["column"] for p in profiles if "high_missingness" in p["flags"]],
        "high_cardinality_features": [p["column"] for p in profiles if "high_cardinality" in p["flags"]],
        "dominant_category_features": [p["column"] for p in profiles if "dominant_category" in p["flags"]],
    }
    return {"row_count": row_count, "profiles": profiles, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile columns for agent review.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--target")
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args()

    df = load_table(args.input_path)
    profile = build_column_profile(df, target=args.target, top_n=args.top_n)
    write_json(args.output_path, profile)
    print(json.dumps(profile["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
