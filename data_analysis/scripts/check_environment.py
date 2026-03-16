#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from common import availability_report, install_hint


def render_text(report: dict) -> str:
    lines = ["Environment report:"]
    for group_name, group_report in report["groups"].items():
        available = ", ".join(group_report["available_modules"]) or "-"
        missing = ", ".join(group_report["missing_modules"]) or "-"
        lines.append(f"- {group_name}:")
        lines.append(f"  available: {available}")
        lines.append(f"  missing: {missing}")
        if group_report["missing_modules"]:
            lines.append(f"  install: {install_hint(group_report['missing_modules'])}")
    runtime = report.get("runtime", {})
    lines.append("- runtime:")
    lines.append(f"  python: {report.get('python_version', 'unknown')}")
    lines.append(f"  mpl_backend: {runtime.get('mpl_backend') or '-'}")
    lines.append(f"  mpl_config_dir: {runtime.get('mpl_config_dir') or '-'}")
    lines.append(f"  mpl_config_dir_writable: {runtime.get('mpl_config_dir_writable')}")
    lines.append(f"  cjk_font: {runtime.get('detected_cjk_font') or '-'}")
    lines.append(f"  pdf_validation_level: {runtime.get('pdf_validation_level') or '-'}")
    readiness = runtime.get("readiness", {})
    for name, value in readiness.items():
        lines.append(f"  readiness:{name}: {value}")
    external_tools = runtime.get("external_tools", {})
    for tool_name, tool_report in external_tools.items():
        lines.append(f"  tool:{tool_name}: {'yes' if tool_report.get('available') else 'no'}")
    warnings = runtime.get("warnings", [])
    if warnings:
        lines.append("  warnings:")
        for warning in warnings:
            lines.append(f"    - {warning}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check dependency availability for the data-analysis skill.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    report = availability_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
