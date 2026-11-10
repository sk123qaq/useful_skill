#!/usr/bin/env python3
"""feature_risk.py: deterministic leakage / artifact scan before modelling.

The scan is deliberately conservative. It labels obvious mechanical risks and
leaves the rest as `unreviewed`; a human/Agent must run `confirm` with reasons
before the gate will accept a predictive or causal route.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402
import io_router  # noqa: E402
from workflow import RISK_LABELS, load_json, read_contract, write_json  # noqa: E402

FUTURE_TOKENS = (
    "next", "future", "forward", "lead", "tomorrow", "ahead", "fwd",
    "次日", "未来", "随后", "下一个", "下期", "后期",
)
POST_OUTCOME_TOKENS = (
    "outcome", "result", "realized", "actual", "post_", "after_",
    "pnl", "profit", "label", "target", "y_",
)
ID_TOKENS = ("id", "uuid", "key", "code", "编号", "代码")


def _is_future(name: str) -> bool:
    low = name.lower()
    return any(token in low for token in FUTURE_TOKENS) or bool(re.search(r"(^|_)t\+?\d+($|_)", low))


def _is_post_outcome(name: str) -> bool:
    low = name.lower()
    return any(token in low for token in POST_OUTCOME_TOKENS)


def _is_id_like(name: str, series: pd.Series, n: int) -> bool:
    low = name.lower()
    unique = series.nunique(dropna=True)
    if n and unique / n >= 0.95 and (pd.api.types.is_integer_dtype(series) or pd.api.types.is_string_dtype(series)):
        return True
    return any(token in low for token in ID_TOKENS) and n and unique / n >= 0.9


def _target_match(series: pd.Series, target: pd.Series) -> bool:
    if len(series) != len(target):
        return False
    if pd.api.types.is_numeric_dtype(series) and pd.api.types.is_numeric_dtype(target):
        a = pd.to_numeric(series, errors="coerce")
        b = pd.to_numeric(target, errors="coerce")
        mask = a.notna() & b.notna()
        return bool(mask.sum() >= 10 and np.allclose(a[mask], b[mask], rtol=1e-9, atol=1e-9))
    return bool((series.astype(str) == target.astype(str)).mean() >= 0.999)


def _corr(series: pd.Series, target: pd.Series) -> float | None:
    if not (pd.api.types.is_numeric_dtype(series) and pd.api.types.is_numeric_dtype(target)):
        return None
    pair = pd.concat([pd.to_numeric(series, errors="coerce"), pd.to_numeric(target, errors="coerce")], axis=1).dropna()
    if len(pair) < 10 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
        return None
    value = pair.iloc[:, 0].corr(pair.iloc[:, 1])
    return None if pd.isna(value) else float(value)


def scan(df: pd.DataFrame, target_col: str | None, features: list[str] | None = None,
         time_col: str | None = None) -> dict[str, Any]:
    target = df[target_col] if target_col and target_col in df.columns else None
    if features is None or not features:
        features = [str(c) for c in df.columns if c != target_col]
    rows: list[dict[str, Any]] = []
    for name in features:
        if name not in df.columns:
            rows.append({"feature": name, "label": "unreviewed", "reason": "column not found", "confirmed": False})
            continue
        series = df[name]
        label = "unreviewed"
        reasons: list[str] = []
        evidence: dict[str, Any] = {}

        if pd.api.types.is_datetime64_any_dtype(series):
            label = "collection_artifact"
            reasons.append("datetime column; not a model feature")
        elif series.nunique(dropna=True) <= 1:
            label = "collection_artifact"
            reasons.append("constant column")
        elif _is_id_like(name, series, len(df)):
            label = "collection_artifact"
            reasons.append("ID/high-cardinality column")
        elif target is not None and _target_match(series, target):
            label = "hard_leakage"
            reasons.append("exact duplicate of target")
        elif _is_future(name):
            label = "hard_leakage"
            reasons.append("name indicates a future/next-period value")
        elif target is not None and (_corr(series, target) is not None and abs(_corr(series, target)) >= 0.999):
            label = "hard_leakage"
            reasons.append(f"near-perfect correlation with target ({_corr(series, target):.4f})")
        elif _is_post_outcome(name):
            label = "post_outcome"
            reasons.append("name indicates a post-outcome/result field")
        elif target is not None and _corr(series, target) is not None and abs(_corr(series, target)) >= 0.95:
            label = "soft_proxy"
            reasons.append(f"very high correlation with target ({_corr(series, target):.4f})")
        else:
            reasons.append("no mechanical risk detected; Agent confirmation required")

        if target is not None and _corr(series, target) is not None:
            evidence["corr_with_target"] = round(float(_corr(series, target)), 6)
        evidence["dtype"] = str(series.dtype)
        evidence["unique"] = int(series.nunique(dropna=True))
        rows.append({
            "feature": name,
            "label": label,
            "reason": "; ".join(reasons),
            "evidence": evidence,
            "confirmed": False,
            "used": name != time_col and label != "collection_artifact",
        })

    summary = {label: 0 for label in RISK_LABELS}
    for row in rows:
        summary[row["label"]] = summary.get(row["label"], 0) + 1
    return {
        "stage": "feature_risk",
        "target": target_col,
        "features": rows,
        "summary": summary,
        "created_at": common.now_utc_iso(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan / confirm feature leakage risk.")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan")
    scan_p.add_argument("--input-path", required=True)
    scan_p.add_argument("--contract", default="analysis_contract.json")
    scan_p.add_argument("--output-path", required=True)
    scan_p.add_argument("--focus-columns", default=None, help="comma-separated override")
    scan_p.add_argument("--sheet", default=None)
    scan_p.add_argument("--comment", default=None)

    confirm = sub.add_parser("confirm")
    confirm.add_argument("--report", required=True)
    confirm.add_argument("--labels", required=True, help="JSON object: feature -> label or {label, reason}")
    confirm.add_argument("--output-path", required=True)

    args = parser.parse_args()
    if args.command == "scan":
        contract = load_json(args.contract)
        df = io_router.load_dataframe(args.input_path, auto_sample=False, sheet=args.sheet, comment=args.comment)
        target = contract.get("target")
        if target and target not in df.columns:
            raise SystemExit(f"target not found in data: {target}")
        focus = [c.strip() for c in args.focus_columns.split(",") if c.strip()] if args.focus_columns else contract.get("focus_columns")
        report = scan(df, target, focus or None, time_col=contract.get("time_col"))
        report["source"] = str(Path(args.input_path).resolve())
        report["contract"] = str(Path(args.contract).resolve())
        write_json(args.output_path, report)
        print(json.dumps({"output_path": str(Path(args.output_path).resolve()), "summary": report["summary"]},
                         ensure_ascii=False, indent=2))
        return 0

    report = load_json(args.report, required=True)
    raw = Path(args.labels)
    labels = json.loads(raw.read_text(encoding="utf-8") if raw.exists() else args.labels)
    if not isinstance(labels, dict):
        raise SystemExit("--labels must be a JSON object")
    known = {row["feature"] for row in report.get("features", [])}
    missing = sorted(known - set(labels))
    if missing:
        raise SystemExit(f"labels missing for: {', '.join(missing)}")
    for row in report.get("features", []):
        value = labels[row["feature"]]
        if isinstance(value, str):
            value = {"label": value, "reason": row.get("reason", "")}
        label = value.get("label", row["label"])
        if label not in RISK_LABELS:
            raise SystemExit(f"invalid label for {row['feature']}: {label}")
        row["label"] = label
        row["reason"] = value.get("reason", row.get("reason", ""))
        row["used"] = bool(value.get("used", row.get("used", True)))
        row["confirmed"] = True
    report["summary"] = {label: 0 for label in RISK_LABELS}
    for row in report["features"]:
        report["summary"][row["label"]] += 1
    report["confirmed_at"] = common.now_utc_iso()
    write_json(args.output_path, report)
    print(json.dumps({"output_path": str(Path(args.output_path).resolve()), "summary": report["summary"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
