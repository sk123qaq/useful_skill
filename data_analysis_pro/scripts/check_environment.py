#!/usr/bin/env python3
import sys
from pathlib import Path

# Add the scripts directory to sys.path so we can import common
sys.path.append(str(Path(__file__).parent))
import common

def main():
    print("--- Data Analysis Pro: Environment Check ---")
    report = common.get_availability_report()
    
    print(f"Python Version: {report['python_version']}")
    print(f"Timestamp: {report['timestamp']}")
    print(f"MPL Config Dir: {report['mpl_config_dir']}")
    
    print("\nDependency Groups:")
    for group, modules in common.DEPENDENCY_GROUPS.items():
        available = [m for m in modules if report['modules'].get(m)]
        missing = [m for m in modules if not report['modules'].get(m)]
        status = "✅" if not missing else "⚠️" if available else "❌"
        print(f"  {status} {group.capitalize()}: {', '.join(available)}")
        if missing:
            print(f"    Missing: {', '.join(missing)}")

    print("\nExternal Tools:")
    for tool, info in common.EXTERNAL_TOOLS.items():
        status = "✅" if report['tools'].get(tool) else "❌"
        print(f"  {status} {tool}: {info}")

    font = common.configure_matplotlib_fonts()
    if font:
        print(f"\n✅ Matplotlib CJK Font: {font}")
    else:
        print("\n⚠️ Matplotlib CJK Font: Not found (Chinese charts may have boxes)")

    print("\n--- Readiness Summary ---")
    core_ready = all(report['modules'].get(m) for m in common.DEPENDENCY_GROUPS['core'])
    if core_ready:
        print("✅ Core analysis dependencies are ready.")
    else:
        print("❌ Core dependencies missing. Run: " + common.install_hint(common.DEPENDENCY_GROUPS['core']))

if __name__ == "__main__":
    main()
