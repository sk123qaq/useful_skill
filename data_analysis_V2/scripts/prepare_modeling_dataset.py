from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))

from data_analysis_V2.scripts.column_profile import build_column_profile, load_table
from data_analysis_V2.scripts.common import write_json


def _parse_csv_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _load_json_if_present(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    return json.loads(Path(path).read_text())


def _write_table(df: pd.DataFrame, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df.to_csv(path, index=False)
    elif suffix in {".parquet", ".pq"}:
        df.to_parquet(path, index=False)
    elif suffix in {".json", ".jsonl"}:
        df.to_json(path, orient="records")
    elif suffix in {".xlsx", ".xls"}:
        df.to_excel(path, index=False)
    else:
        raise ValueError(f"Unsupported output file: {path}")
    return path


def apply_data_processing(
    df: pd.DataFrame,
    target: str | None = None,
    deduplicate: bool = False,
    keep_features: list[str] | None = None,
    drop_features: list[str] | None = None,
    profile: dict[str, Any] | None = None,
    drop_profile_flags: list[str] | None = None,
    feature_risk_report: dict[str, Any] | None = None,
    drop_risk_labels: list[str] | None = None,
    drop_constant_features: bool = False,
    drop_missing_above: float | None = None,
    drop_high_cardinality_ratio: float | None = None,
    drop_dominant_category_above: float | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    working = df.copy()
    target_set = {target} if target else set()
    summary: dict[str, Any] = {
        "rows_before": int(len(working)),
        "columns_before": list(working.columns),
        "steps": [],
        "dropped_features_by_reason": {},
    }

    if deduplicate:
        before = len(working)
        working = working.drop_duplicates().reset_index(drop=True)
        summary["steps"].append({"action": "deduplicate_rows", "rows_removed": int(before - len(working))})

    if keep_features:
        keep_set = set(keep_features) | target_set
        missing_keep = sorted(keep_set - set(working.columns))
        if missing_keep:
            raise ValueError(f"Requested keep_features not found: {', '.join(missing_keep)}")
        to_drop = sorted(set(working.columns) - keep_set)
        if to_drop:
            working = working.drop(columns=to_drop)
            summary["dropped_features_by_reason"]["not_in_keep_features"] = to_drop

    explicit_drop = sorted((set(drop_features or []) & set(working.columns)) - target_set)
    if explicit_drop:
        working = working.drop(columns=explicit_drop)
        summary["dropped_features_by_reason"]["explicit_drop_features"] = explicit_drop

    if profile and drop_profile_flags:
        profiled_drop = sorted(
            {
                entry["column"]
                for entry in profile["profiles"]
                if entry["column"] in working.columns
                and entry["column"] not in target_set
                and any(flag in set(entry["flags"]) for flag in drop_profile_flags)
            }
        )
        if profiled_drop:
            working = working.drop(columns=profiled_drop)
            summary["dropped_features_by_reason"]["profile_flags"] = profiled_drop

    if feature_risk_report and drop_risk_labels:
        risky_drop = sorted(
            {
                entry["feature"]
                for entry in feature_risk_report["features"]
                if entry["feature"] in working.columns
                and entry["feature"] not in target_set
                and entry["label"] in set(drop_risk_labels)
            }
        )
        if risky_drop:
            working = working.drop(columns=risky_drop)
            summary["dropped_features_by_reason"]["risk_labels"] = risky_drop

    if drop_constant_features:
        constant_drop = sorted(
            column
            for column in working.columns
            if column not in target_set and working[column].nunique(dropna=False) <= 1
        )
        if constant_drop:
            working = working.drop(columns=constant_drop)
            summary["dropped_features_by_reason"]["constant_features"] = constant_drop

    if drop_missing_above is not None:
        high_missing_drop = sorted(
            column
            for column in working.columns
            if column not in target_set and float(working[column].isna().mean()) > drop_missing_above
        )
        if high_missing_drop:
            working = working.drop(columns=high_missing_drop)
            summary["dropped_features_by_reason"]["high_missingness"] = high_missing_drop

    if drop_high_cardinality_ratio is not None:
        high_card_drop = sorted(
            column
            for column in working.columns
            if column not in target_set and len(working) > 0 and working[column].nunique(dropna=False) / len(working) > drop_high_cardinality_ratio
        )
        if high_card_drop:
            working = working.drop(columns=high_card_drop)
            summary["dropped_features_by_reason"]["high_cardinality"] = high_card_drop

    if drop_dominant_category_above is not None:
        dominant_drop: list[str] = []
        for column in working.columns:
            if column in target_set:
                continue
            non_null = working[column].dropna()
            dominant_share = float(non_null.astype(str).value_counts(normalize=True).iloc[0]) if not non_null.empty else 0.0
            if dominant_share > drop_dominant_category_above:
                dominant_drop.append(column)
        dominant_drop = sorted(dominant_drop)
        if dominant_drop:
            working = working.drop(columns=dominant_drop)
            summary["dropped_features_by_reason"]["dominant_category"] = dominant_drop

    if deduplicate:
        before = len(working)
        working = working.drop_duplicates().reset_index(drop=True)
        rows_removed = int(before - len(working))
        if rows_removed:
            summary["steps"].append(
                {
                    "action": "deduplicate_rows_after_feature_processing",
                    "rows_removed": rows_removed,
                }
            )

    summary["rows_after"] = int(len(working))
    summary["columns_after"] = list(working.columns)
    summary["target"] = target
    summary["kept_feature_count"] = len([column for column in working.columns if column != target])
    return working, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply agent-chosen data processing actions to build a modeling dataset.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--summary-path", required=True)
    parser.add_argument("--target")
    parser.add_argument("--deduplicate", action="store_true")
    parser.add_argument("--keep-features")
    parser.add_argument("--drop-features")
    parser.add_argument("--profile-path")
    parser.add_argument("--drop-profile-flags")
    parser.add_argument("--feature-risk-report-path")
    parser.add_argument("--drop-risk-labels")
    parser.add_argument("--drop-constant-features", action="store_true")
    parser.add_argument("--drop-missing-above", type=float)
    parser.add_argument("--drop-high-cardinality-ratio", type=float)
    parser.add_argument("--drop-dominant-category-above", type=float)
    args = parser.parse_args()

    df = load_table(args.input_path)
    profile = _load_json_if_present(args.profile_path) or build_column_profile(df, target=args.target)
    feature_risk_report = _load_json_if_present(args.feature_risk_report_path)
    cleaned_df, summary = apply_data_processing(
        df,
        target=args.target,
        deduplicate=args.deduplicate,
        keep_features=_parse_csv_list(args.keep_features),
        drop_features=_parse_csv_list(args.drop_features),
        profile=profile,
        drop_profile_flags=_parse_csv_list(args.drop_profile_flags),
        feature_risk_report=feature_risk_report,
        drop_risk_labels=_parse_csv_list(args.drop_risk_labels),
        drop_constant_features=args.drop_constant_features,
        drop_missing_above=args.drop_missing_above,
        drop_high_cardinality_ratio=args.drop_high_cardinality_ratio,
        drop_dominant_category_above=args.drop_dominant_category_above,
    )
    output_path = _write_table(cleaned_df, args.output_path)
    summary["output_path"] = str(output_path)
    write_json(args.summary_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
