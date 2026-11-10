#!/usr/bin/env python3
"""route.py: record the Agent's route decision as a checked artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402
from schemas import ALLOWED_ROUTES, validate_route_decision  # noqa: E402
from workflow import load_json, write_json  # noqa: E402


def _list(value: str | None) -> list[str]:
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/validate route_decision.json")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--route", required=True, choices=sorted(ALLOWED_ROUTES))
    init.add_argument("--reasons", required=True)
    init.add_argument("--blockers", default="")
    init.add_argument("--next-actions", default="")
    init.add_argument("--output-path", required=True)
    check = sub.add_parser("validate")
    check.add_argument("--path", required=True)
    args = parser.parse_args()

    if args.command == "validate":
        try:
            payload = validate_route_decision(load_json(args.path, required=True))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps({"valid": True, "route": payload["route"]}, ensure_ascii=False))
        return 0

    payload = {
        "version": 1,
        "route": args.route,
        "reasons": _list(args.reasons),
        "blockers": _list(args.blockers),
        "next_actions": _list(args.next_actions),
        "created_at": common.now_utc_iso(),
    }
    try:
        validate_route_decision(payload)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    write_json(args.output_path, payload)
    print(json.dumps({"valid": True, "path": str(Path(args.output_path).resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
