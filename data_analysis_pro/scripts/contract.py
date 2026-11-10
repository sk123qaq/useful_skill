#!/usr/bin/env python3
"""contract.py: lock the decision question before any analysis runs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import io_router  # noqa: E402
from workflow import TASKS, load_json, validate_contract_payload, write_json  # noqa: E402


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _columns(path: str, sheet: str | None = None, comment: str | None = None) -> list[str]:
    frame = io_router.load_dataframe(path, sample_rows=20, auto_sample=False, sheet=sheet, comment=comment)
    return [str(c) for c in frame.columns]


def _check_time(path: str, time_col: str, sheet: str | None = None, comment: str | None = None) -> str | None:
    import pandas as pd

    frame = io_router.load_dataframe(path, sample_rows=200, auto_sample=False, sheet=sheet, comment=comment)
    parsed = pd.to_datetime(frame[time_col], errors="coerce")
    if parsed.notna().mean() < 0.8:
        return f"time_col {time_col!r} is not parseable as datetime (>=80% required)"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Create / validate analysis_contract.json")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--question", required=True)
    init.add_argument("--task", default="descriptive", choices=sorted(TASKS))
    init.add_argument("--target", default=None)
    init.add_argument("--time-col", default=None)
    init.add_argument("--unit-of-analysis", default="one row per record")
    init.add_argument("--data-source", required=True)
    init.add_argument("--data-scope", default="full", choices=["full", "sample"])
    init.add_argument("--sample-rows", type=int, default=None)
    init.add_argument("--success-criteria", default="")
    init.add_argument("--stop-conditions", default="")
    init.add_argument("--constraints", default="")
    init.add_argument("--focus-columns", default="")
    init.add_argument("--group-col", default=None)
    init.add_argument("--treatment", default=None)
    init.add_argument("--dataset-kind", default="single_table",
                      choices=["single_table", "dataset_package", "sql_query"])
    init.add_argument("--report-locale", default="zh", choices=["zh", "en"])
    init.add_argument("--config-json", default=None, help="inline JSON or path; overrides flags")
    init.add_argument("--output-path", default="analysis_contract.json")

    show = sub.add_parser("show")
    show.add_argument("--contract", default="analysis_contract.json")

    validate = sub.add_parser("validate")
    validate.add_argument("--contract", default="analysis_contract.json")
    validate.add_argument("--data-path", default=None)
    validate.add_argument("--sheet", default=None)
    validate.add_argument("--comment", default=None)

    args = parser.parse_args()
    if args.command == "show":
        print(json.dumps(load_json(args.contract, required=True), ensure_ascii=False, indent=2))
        return 0

    if args.command == "validate":
        payload = load_json(args.contract, required=True)
        cols = _columns(args.data_path, args.sheet, args.comment) if args.data_path else None
        errors = validate_contract_payload(payload, data_columns=cols)
        if not errors and args.data_path and payload.get("time_col"):
            time_error = _check_time(args.data_path, payload["time_col"], args.sheet, args.comment)
            if time_error:
                errors.append(time_error)
        result = {"valid": not errors, "errors": errors, "path": str(Path(args.contract).resolve())}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not errors else 2

    overrides = {}
    if args.config_json:
        raw_text = args.config_json.strip()
        if raw_text.startswith("{"):
            overrides = json.loads(raw_text)
        else:
            raw = Path(args.config_json)
            if not raw.exists():
                raise SystemExit(f"config JSON not found: {raw}")
            overrides = json.loads(raw.read_text(encoding="utf-8"))
    payload = {
        "version": 1,
        "decision_question": args.question,
        "question": args.question,
        "task": args.task,
        "target": args.target,
        "time_col": args.time_col,
        "unit_of_analysis": args.unit_of_analysis,
        "data_source": str(Path(args.data_source).expanduser().resolve()) if Path(args.data_source).expanduser().exists() else args.data_source,
        "data_scope": args.data_scope,
        "sample_rows": args.sample_rows,
        "success_criteria": _split(args.success_criteria),
        "stop_conditions": _split(args.stop_conditions),
        "constraints": _split(args.constraints),
        "focus_columns": _split(args.focus_columns),
        "group_col": args.group_col,
        "treatment": args.treatment,
        "dataset_kind": args.dataset_kind,
        "report_locale": args.report_locale,
        "continue_after_scout": True,
        "continue_after_baseline": True,
    }
    payload.update(overrides)
    errors = validate_contract_payload(payload)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 2
    write_json(args.output_path, payload)
    print(json.dumps({"valid": True, "path": str(Path(args.output_path).resolve()), "contract": payload},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
