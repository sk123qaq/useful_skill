from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from data_analysis_V2.scripts.common import availability_report, configure_matplotlib_defaults


def main() -> int:
    parser = argparse.ArgumentParser(description="Check data_analysis_V2 runtime availability.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    args = parser.parse_args()

    matplotlib_config = configure_matplotlib_defaults()
    report = availability_report()
    report["matplotlib_config"] = matplotlib_config

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("data_analysis_V2 environment report")
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
