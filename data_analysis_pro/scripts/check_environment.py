#!/usr/bin/env python3
"""check_environment.py: dependency/tool readiness without side effects."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))
import common  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Data Analysis Pro dependencies.")
    parser.add_argument("--output-path", default=None, help="optional env_snapshot.json path")
    args = parser.parse_args()

    print("--- Data Analysis Pro: Environment Check ---")
    report = common.get_availability_report()
    print(f"Python Version: {report['python_version']}")
    print(f"Timestamp: {report['timestamp']}")
    print(f"MPL Config Dir: {report['mpl_config_dir']}")

    print("\nDependency Groups:")
    for group, modules in common.DEPENDENCY_GROUPS.items():
        available = [m for m in modules if report["modules"].get(m)]
        missing = [m for m in modules if not report["modules"].get(m)]
        status = "✅" if not missing else "⚠️" if available else "❌"
        print(f"  {status} {group.capitalize()}: {', '.join(available) or '-'}")
        if missing:
            print(f"    Missing: {', '.join(missing)}")

    print("\nExternal Tools:")
    for tool, info in common.EXTERNAL_TOOLS.items():
        status = "✅" if report["tools"].get(tool) else "❌"
        print(f"  {status} {tool}: {info}")

    try:
        font = common.configure_matplotlib_fonts()
    except Exception as exc:  # noqa: BLE001 - readiness check must not crash
        font = None
        print(f"\n⚠️ Matplotlib font check failed: {exc}")
    if font:
        print(f"\n✅ Matplotlib CJK Font: {font}")
    else:
        print("\n⚠️ Matplotlib CJK Font: Not found (Chinese charts may have boxes)")

    core_ready = all(report["modules"].get(m) for m in common.DEPENDENCY_GROUPS["core"])
    print("\n--- Readiness Summary ---")
    if core_ready:
        print("✅ Core analysis dependencies are ready.")
    else:
        missing = [m for m in common.DEPENDENCY_GROUPS["core"] if not report["modules"].get(m)]
        print("❌ Core dependencies missing. Run: " + common.install_hint(missing))

    if args.output_path:
        out = Path(args.output_path)
        common.write_json(out, report)
        print(f"\nEnvironment snapshot saved to: {out}")
    return 0 if core_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
