from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from data_analysis_V2.scripts.orchestrator import run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the data_analysis_V2 orchestrator.")
    parser.add_argument("--question", default="", help="Business question or analysis intent.")
    parser.add_argument("--input-path", help="Path to a CSV/Parquet/JSON/Excel input file.")
    parser.add_argument("--db-url", help="Optional sqlite:/// or duckdb:/// database URL.")
    parser.add_argument("--query", help="SQL query when using --db-url.")
    parser.add_argument("--task", help="Task type: descriptive, predictive, classification, regression, causal.")
    parser.add_argument("--target", help="Target column for predictive tasks.")
    parser.add_argument("--time-col", help="Time column when temporal ordering matters.")
    parser.add_argument("--data-scope", choices=["sample", "full"], default="sample")
    parser.add_argument("--sample-rows", type=int, default=5000)
    parser.add_argument("--continue-after-scout", action="store_true")
    parser.add_argument("--continue-after-baseline", action="store_true")
    parser.add_argument("--formal-report", action="store_true")
    parser.add_argument("--output-dir", help="Optional output root or run directory.")
    parser.add_argument("--report-title", help="Optional report title.")
    args = parser.parse_args()

    result = run_pipeline(
        question=args.question,
        input_path=args.input_path,
        db_url=args.db_url,
        query=args.query,
        task=args.task,
        target=args.target,
        time_col=args.time_col,
        data_scope=args.data_scope,
        sample_rows=args.sample_rows,
        continue_after_scout=args.continue_after_scout,
        continue_after_baseline=args.continue_after_baseline,
        formal_report=args.formal_report,
        output_dir=args.output_dir,
        report_title=args.report_title,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
