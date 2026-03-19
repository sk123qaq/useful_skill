from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    import sys

    sys.path.append(str(Path(__file__).resolve().parents[2]))

from data_analysis_V2.scripts.baseline_runner import run_model_ladder
from data_analysis_V2.scripts.column_profile import load_table
from data_analysis_V2.scripts.model_catalog import get_model_catalog, get_tuning_catalog
from data_analysis_V2.scripts.monitored_job import run_monitored_job


def _default_selection_metric(df: pd.DataFrame, target: str, task: str) -> str:
    if task == "classification":
        return "average_precision" if df[target].nunique(dropna=True) == 2 else "f1_macro"
    return "rmse"


def run_optimized_candidates(
    df: pd.DataFrame,
    target: str,
    task: str,
    output_dir: str,
    n_splits: int = 5,
    selection_metric: str | None = None,
) -> dict[str, Any]:
    task_type = task
    specs = get_model_catalog(task_type) + get_tuning_catalog(task_type)
    metric_name = selection_metric or _default_selection_metric(df, target=target, task=task_type)

    def job(heartbeat):
        heartbeat("starting optimized candidate run")
        results = run_model_ladder(
            df,
            target=target,
            task=task_type,
            model_specs=specs,
            output_dir=output_dir,
            n_splits=n_splits,
            primary_metric=metric_name,
            artifact_name="optimized_results",
            heartbeat=heartbeat,
        )
        heartbeat("completed optimized candidate run")
        return results

    return run_monitored_job(
        "optimize_runner",
        output_dir,
        job,
        heartbeat_interval=1.0,
        stall_after=300.0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a deterministic optimized model candidate ladder for agent review.")
    parser.add_argument("--input-path", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--task", choices=["classification", "regression"], required=True)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--selection-metric")
    args = parser.parse_args()

    df = load_table(args.input_path)
    results = run_optimized_candidates(
        df,
        target=args.target,
        task=args.task,
        output_dir=args.output_dir,
        n_splits=args.n_splits,
        selection_metric=args.selection_metric,
    )
    print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
