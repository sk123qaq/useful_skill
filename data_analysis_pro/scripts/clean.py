#!/usr/bin/env python3
"""clean.py: apply explicit cleaning config, write data + a cleaning report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402
import io_router  # noqa: E402
from preprocessing import apply_cleaning, build_schema, duplicate_summary, missing_summary  # noqa: E402
from workflow import file_sha256, write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean a tabular dataset with an explicit config.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--report-path", required=True)
    parser.add_argument("--target")
    parser.add_argument("--time-col")
    parser.add_argument("--config-json", default="{}", help="inline JSON or a path to a JSON file")
    parser.add_argument("--sheet", default=None)
    parser.add_argument("--comment", default=None)
    parser.add_argument("--skiprows", type=int, default=None)
    parser.add_argument("--drop-duplicates", action="store_true")
    args = parser.parse_args()

    raw_config = args.config_json
    if raw_config and Path(raw_config).exists():
        config = json.loads(Path(raw_config).read_text(encoding="utf-8"))
    else:
        config = json.loads(raw_config or "{}")
    if args.drop_duplicates:
        config["drop_duplicates"] = True

    df = io_router.load_dataframe(
        args.input_path, auto_sample=False, sheet=args.sheet, comment=args.comment, skiprows=args.skiprows
    )
    before = {
        "rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "missing": missing_summary(df),
        "duplicates": duplicate_summary(df),
        "schema": build_schema(df, target=args.target, time_col=args.time_col),
        "source_sha256": file_sha256(args.input_path),
    }
    cleaned, cleaning = apply_cleaning(df, config)
    after = {
        "rows": int(len(cleaned)),
        "columns": [str(c) for c in cleaned.columns],
        "missing": missing_summary(cleaned),
        "duplicates": duplicate_summary(cleaned),
    }

    out = Path(args.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".csv":
        cleaned.to_csv(out, index=False)
    elif out.suffix.lower() in {".parquet", ".pq"}:
        cleaned.to_parquet(out, index=False)
    else:
        raise SystemExit(f"unsupported output format: {out.suffix}")

    report = {
        "stage": "clean",
        "source": str(Path(args.input_path).resolve()),
        "output_path": str(out.resolve()),
        "target": args.target,
        "time_col": args.time_col,
        "before": before,
        "after": after,
        "cleaning": cleaning,
        "config": config,
        "created_at": common.now_utc_iso(),
    }
    write_json(args.report_path, report)
    print(json.dumps({"output_path": str(out.resolve()), "report_path": str(Path(args.report_path).resolve()),
                      "rows_before": before["rows"], "rows_after": after["rows"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
