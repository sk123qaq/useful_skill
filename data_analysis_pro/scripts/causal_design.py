#!/usr/bin/env python3
"""causal_design.py: force identification assumptions to be stated first."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402
import io_router  # noqa: E402
from workflow import load_json, write_json  # noqa: E402


def _split(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def validate(payload: dict, columns: list[str] | None = None) -> list[str]:
    errors = []
    for key in ("estimand", "treatment", "outcome", "design", "identification_assumptions"):
        if not payload.get(key):
            errors.append(f"missing/empty: {key}")
    if payload.get("estimand") not in {"ATE", "ATT", "ATU", "LATE", "CATE", None}:
        errors.append("estimand must be ATE/ATT/ATU/LATE/CATE")
    if columns:
        for key in ("treatment", "outcome"):
            if payload.get(key) and payload[key] not in columns:
                errors.append(f"{key} not found in data: {payload[key]}")
    if not isinstance(payload.get("identification_assumptions"), list) or not payload["identification_assumptions"]:
        errors.append("identification_assumptions must be a non-empty list")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/validate causal_design.json")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--estimand", default="ATE", choices=["ATE", "ATT", "ATU", "LATE", "CATE"])
    init.add_argument("--treatment", required=True)
    init.add_argument("--outcome", required=True)
    init.add_argument("--design", default="observational", choices=["observational", "did", "rd", "iv", "psm", "dml"])
    init.add_argument("--assumptions", required=True, help="comma-separated identification assumptions")
    init.add_argument("--adjustment", default="")
    init.add_argument("--instrument", default=None)
    init.add_argument("--sensitivity", default="")
    init.add_argument("--output-path", required=True)
    init.add_argument("--data-path", default=None)
    init.add_argument("--sheet", default=None)

    validate_p = sub.add_parser("validate")
    validate_p.add_argument("--design", required=True)
    validate_p.add_argument("--data-path", default=None)
    validate_p.add_argument("--sheet", default=None)

    args = parser.parse_args()
    if args.command == "validate":
        payload = load_json(args.design, required=True)
        columns = None
        if args.data_path:
            columns = [str(c) for c in io_router.load_dataframe(args.data_path, sample_rows=5, auto_sample=False,
                                                                 sheet=args.sheet).columns]
        errors = validate(payload, columns)
        print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if not errors else 2

    payload = {
        "version": 1,
        "estimand": args.estimand,
        "treatment": args.treatment,
        "outcome": args.outcome,
        "design": args.design,
        "identification_assumptions": _split(args.assumptions),
        "adjustment_set": _split(args.adjustment),
        "instrument": args.instrument,
        "sensitivity_checks": _split(args.sensitivity),
        "created_at": common.now_utc_iso(),
    }
    columns = None
    if args.data_path:
        columns = [str(c) for c in io_router.load_dataframe(args.data_path, sample_rows=5, auto_sample=False,
                                                             sheet=args.sheet).columns]
    errors = validate(payload, columns)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 2
    write_json(args.output_path, payload)
    print(json.dumps({"valid": True, "path": str(Path(args.output_path).resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
