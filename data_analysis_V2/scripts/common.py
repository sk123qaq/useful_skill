from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_RUN_PREFIX = "data-analysis-v2"


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return re.sub(r"-{2,}", "-", cleaned).strip("-")


def ensure_dir(path: str | Path) -> Path:
    resolved = Path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def ensure_run_dir(output_dir: str | Path | None, prefix: str = DEFAULT_RUN_PREFIX) -> Path:
    base_dir = Path(output_dir) if output_dir else Path(__file__).resolve().parents[1] / "outputs"
    ensure_dir(base_dir)
    if base_dir.name.startswith(prefix):
        return ensure_dir(base_dir)
    run_dir = base_dir / f"{prefix}-{timestamp_slug()}"
    return ensure_dir(run_dir)


def to_serializable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_serializable(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_serializable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def write_json(path: str | Path, payload: Any) -> Path:
    resolved = Path(path)
    ensure_dir(resolved.parent)
    resolved.write_text(
        json.dumps(to_serializable(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return resolved


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text())


def append_jsonl(path: str | Path, payload: dict[str, Any]) -> Path:
    resolved = Path(path)
    ensure_dir(resolved.parent)
    with resolved.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(to_serializable(payload), ensure_ascii=False, sort_keys=True) + "\n")
    return resolved


def write_markdown(path: str | Path, text: str) -> Path:
    resolved = Path(path)
    ensure_dir(resolved.parent)
    resolved.write_text(text.rstrip() + "\n")
    return resolved


def write_artifact(run_dir: str | Path, artifact_name: str, payload: Any) -> Path:
    return write_json(Path(run_dir) / f"{artifact_name}.json", payload)


def write_status(
    run_dir: str | Path,
    stage: str,
    status: str,
    extra: dict[str, Any] | None = None,
) -> Path:
    payload = {
        "stage": stage,
        "status": status,
        "updated_at": now_utc_iso(),
    }
    if extra:
        payload.update(to_serializable(extra))
    status_path = write_json(Path(run_dir) / "run_status.json", payload)
    append_jsonl(Path(run_dir) / "run_events.jsonl", payload)
    return status_path


def module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def command_available(command_name: str) -> bool:
    return shutil.which(command_name) is not None


def ensure_mplconfigdir(base_dir: str | Path | None = None) -> Path:
    target = Path(base_dir) if base_dir else Path(tempfile.gettempdir()) / "matplotlib-data-analysis-v2"
    ensure_dir(target)
    os.environ["MPLCONFIGDIR"] = str(target)
    return target


def configure_matplotlib_defaults(base_dir: str | Path | None = None) -> dict[str, Any]:
    mpl_dir = ensure_mplconfigdir(base_dir)
    configured = {
        "mplconfigdir": str(mpl_dir),
        "matplotlib": module_available("matplotlib"),
        "configured": False,
    }
    if configured["matplotlib"]:
        import matplotlib

        matplotlib.use("Agg")
        matplotlib.rcParams["figure.max_open_warning"] = 0
        configured["configured"] = True
    return configured


def availability_report() -> dict[str, Any]:
    python_modules = ["pandas", "numpy", "sklearn", "scipy", "duckdb", "matplotlib", "seaborn"]
    commands = ["python3.13", "pytest"]
    return {
        "generated_at": now_utc_iso(),
        "python_version": shutil.which("python3.13") is not None,
        "modules": {module: module_available(module) for module in python_modules},
        "commands": {command: command_available(command) for command in commands},
        "mplconfigdir": str(ensure_mplconfigdir()),
    }
