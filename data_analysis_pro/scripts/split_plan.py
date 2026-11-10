#!/usr/bin/env python3
"""split_plan.py: create and validate leakage-safe CV folds."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402
import io_router  # noqa: E402
from workflow import file_sha256, load_json, write_json  # noqa: E402


def _temporal_folds(times: pd.Series, n_splits: int, test_size: float, gap: int) -> list[dict[str, Any]]:
    parsed = pd.to_datetime(times, errors="coerce")
    valid = parsed.notna().to_numpy()
    positions = np.where(valid)[0]
    if len(positions) < 20:
        raise ValueError("need at least 20 rows with a valid time value for temporal folds")
    raw = parsed.astype("int64").to_numpy()
    order = positions[np.argsort(raw[positions], kind="stable")]
    n = len(order)
    initial = max(10, int(round(n * (1.0 - test_size))))
    if initial >= n:
        raise ValueError("test_size leaves no test rows")
    block = max(1, (n - initial) // n_splits)
    folds: list[dict[str, Any]] = []
    for i in range(n_splits):
        start = initial + i * block
        end = n if i == n_splits - 1 else min(n, start + block)
        if start >= n or end <= start:
            break
        train_end = max(0, start - max(0, gap))
        train_idx = order[:train_end]
        test_idx = order[start:end]
        if len(train_idx) < 10 or len(test_idx) < 1:
            continue
        folds.append({
            "fold": len(folds),
            "train_indices": train_idx.tolist(),
            "test_indices": test_idx.tolist(),
            "train_start": str(pd.to_datetime(times.iloc[train_idx[0]])),
            "train_end": str(pd.to_datetime(times.iloc[train_idx[-1]])),
            "test_start": str(pd.to_datetime(times.iloc[test_idx[0]])),
            "test_end": str(pd.to_datetime(times.iloc[test_idx[-1]])),
        })
    if not folds:
        raise ValueError("no valid temporal folds produced")
    return folds


def create_plan(
    df: pd.DataFrame,
    target: str | None,
    time_col: str | None,
    strategy: str,
    n_splits: int,
    test_size: float,
    group_col: str | None,
    gap: int,
    seed: int = 42,
) -> dict[str, Any]:
    n = len(df)
    if strategy in {"temporal", "expanding", "rolling"}:
        if not time_col or time_col not in df.columns:
            raise ValueError("temporal strategy requires an existing time_col")
        folds = _temporal_folds(df[time_col], n_splits, test_size, gap)
    elif strategy == "group":
        if not group_col or group_col not in df.columns:
            raise ValueError("group strategy requires an existing group_col")
        from sklearn.model_selection import GroupKFold

        groups = df[group_col].astype(str).to_numpy()
        folds = []
        for i, (train_idx, test_idx) in enumerate(GroupKFold(n_splits=n_splits).split(df, groups=groups)):
            folds.append({"fold": i, "train_indices": train_idx.tolist(), "test_indices": test_idx.tolist()})
    else:
        from sklearn.model_selection import KFold

        folds = []
        for i, (train_idx, test_idx) in enumerate(KFold(n_splits=n_splits, shuffle=True, random_state=seed).split(df)):
            folds.append({"fold": i, "train_indices": train_idx.tolist(), "test_indices": test_idx.tolist()})

    return {
        "stage": "split_plan",
        "strategy": strategy,
        "target": target,
        "time_col": time_col,
        "group_col": group_col,
        "n_rows": int(n),
        "n_splits": len(folds),
        "test_size": test_size,
        "gap_rows": gap,
        "seed": seed,
        "data_hash": None,
        "folds": folds,
        "created_at": common.now_utc_iso(),
    }


def validate_plan(plan: dict[str, Any], df: pd.DataFrame | None = None) -> list[str]:
    errors: list[str] = []
    folds = plan.get("folds")
    if not isinstance(folds, list) or not folds:
        return ["folds must be a non-empty list"]
    n = plan.get("n_rows")
    if df is not None:
        n = len(df)
    seen_test: set[int] = set()
    for i, fold in enumerate(folds):
        train = fold.get("train_indices") or []
        test = fold.get("test_indices") or []
        if not train or not test:
            errors.append(f"fold {i}: empty train/test")
            continue
        if set(train) & set(test):
            errors.append(f"fold {i}: train/test overlap")
        if n and (max(train + test) >= n or min(train + test) < 0):
            errors.append(f"fold {i}: index out of range")
        if set(test) & seen_test:
            errors.append(f"fold {i}: test indices overlap another fold")
        seen_test |= set(test)
        if plan.get("strategy") in {"temporal", "expanding", "rolling"} and df is not None:
            time_col = plan.get("time_col")
            if time_col and time_col in df.columns:
                train_time = pd.to_datetime(df.iloc[train][time_col], errors="coerce").max()
                test_time = pd.to_datetime(df.iloc[test][time_col], errors="coerce").min()
                if pd.notna(train_time) and pd.notna(test_time) and not train_time < test_time:
                    errors.append(f"fold {i}: train time {train_time} is not before test time {test_time}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/validate CV folds.")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--input-path", required=True)
    create.add_argument("--output-path", required=True)
    create.add_argument("--target", default=None)
    create.add_argument("--time-col", default=None)
    create.add_argument("--group-col", default=None)
    create.add_argument("--strategy", default="temporal", choices=["temporal", "expanding", "rolling", "kfold", "group"])
    create.add_argument("--n-splits", type=int, default=5)
    create.add_argument("--test-size", type=float, default=0.3)
    create.add_argument("--gap", type=int, default=0)
    create.add_argument("--seed", type=int, default=42)
    create.add_argument("--sheet", default=None)
    create.add_argument("--comment", default=None)

    validate = sub.add_parser("validate")
    validate.add_argument("--plan", required=True)
    validate.add_argument("--input-path", default=None)
    validate.add_argument("--output-path", default=None)

    args = parser.parse_args()
    if args.command == "create":
        df = io_router.load_dataframe(args.input_path, auto_sample=False, sheet=args.sheet, comment=args.comment)
        plan = create_plan(df, args.target, args.time_col, args.strategy, args.n_splits, args.test_size,
                           args.group_col, args.gap, args.seed)
        plan["data_hash"] = file_sha256(args.input_path)
        errors = validate_plan(plan, df)
        plan["valid"] = not errors
        plan["errors"] = errors
        plan["source"] = str(Path(args.input_path).resolve())
        write_json(args.output_path, plan)
        print(f"wrote {args.output_path}: {len(plan['folds'])} folds, valid={plan['valid']}")
        return 0 if not errors else 2

    plan = load_json(args.plan, required=True)
    df = io_router.load_dataframe(args.input_path, auto_sample=False) if args.input_path else None
    errors = validate_plan(plan, df)
    result = {"valid": not errors, "errors": errors, "plan": str(Path(args.plan).resolve())}
    if args.output_path:
        write_json(args.output_path, result)
    print(result)
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
