#!/usr/bin/env python3
"""features.py: deterministic feature transforms with an explicit output."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402
import io_router  # noqa: E402
from preprocessing import add_calendar_features, encode_categoricals  # noqa: E402
from workflow import write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Add calendar/one-hot features; write a new dataset.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--report-path", required=True)
    parser.add_argument("--time-col")
    parser.add_argument("--calendar", action="store_true")
    parser.add_argument("--one-hot", action="store_true")
    parser.add_argument("--drop-columns", default="")
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--comment", default=None)
    args = parser.parse_args()

    df = io_router.load_dataframe(args.input_path, auto_sample=False, sheet=args.sheet, comment=args.comment)
    actions: list[str] = []
    drop = [c.strip() for c in args.drop_columns.split(",") if c.strip()]
    if drop:
        df = df.drop(columns=[c for c in drop if c in df.columns])
        actions.append(f"dropped columns: {drop}")
    if args.calendar:
        if not args.time_col:
            raise SystemExit("--calendar requires --time-col")
        df = add_calendar_features(df, args.time_col)
        actions.append(f"calendar features from {args.time_col}")
    if args.one_hot:
        df = encode_categoricals(df)
        actions.append("one-hot encoded categorical columns")

    out = Path(args.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".csv":
        df.to_csv(out, index=False)
    else:
        df.to_parquet(out, index=False)
    report = {
        "stage": "features",
        "source": str(Path(args.input_path).resolve()),
        "output_path": str(out.resolve()),
        "actions": actions,
        "shape": [int(df.shape[0]), int(df.shape[1])],
        "columns": [str(c) for c in df.columns],
        "created_at": common.now_utc_iso(),
    }
    write_json(args.report_path, report)
    print(json.dumps({"output_path": str(out.resolve()), "rows": len(df), "columns": len(df.columns)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
