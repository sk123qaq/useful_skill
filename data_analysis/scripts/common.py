#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

DEPENDENCY_GROUPS = {
    "core": ["numpy", "pandas", "scipy", "sklearn"],
    "viz": ["matplotlib", "seaborn"],
    "database": ["sqlalchemy", "openpyxl"],
    "large_data": ["polars", "duckdb", "pyarrow"],
    "advanced": ["statsmodels", "xgboost", "lightgbm", "prophet", "plotly", "streamlit", "shap", "torch"],
}

EXTERNAL_TOOLS = {
    "pdftotext": "PDF 文本抽取与质检",
    "qpdf": "PDF 结构检查与拆分",
    "pandoc": "DOCX/PDF 内容转换与复核",
    "soffice": "LibreOffice 文档转换",
    "file": "基础文件类型与页数探测",
}

CJK_FONT_CANDIDATES = [
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "PingFang SC",
    "Hiragino Sans GB",
    "Songti SC",
    "Microsoft YaHei",
    "SimHei",
    "Arial Unicode MS",
]

CJK_FONT_FILE_CANDIDATES = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
]


def _configure_runtime_environment() -> None:
    mpl_config_dir = Path(tempfile.gettempdir()) / "codex-mplconfig"
    mpl_config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_config_dir))
    os.environ.setdefault("MPLBACKEND", "Agg")
    cpu_count = os.cpu_count()
    if cpu_count:
        os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(cpu_count))
    warnings.filterwarnings(
        "ignore",
        message="Could not find the number of physical cores for the following reason:",
        category=UserWarning,
    )


_configure_runtime_environment()


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def command_available(name: str) -> bool:
    return shutil.which(name) is not None


def detect_cjk_font(candidates: Iterable[str] | None = None) -> str | None:
    if not module_available("matplotlib"):
        return None
    from matplotlib import font_manager  # type: ignore

    available_fonts = {font.name for font in font_manager.fontManager.ttflist}
    for font_name in candidates or CJK_FONT_CANDIDATES:
        if font_name in available_fonts:
            return font_name
    return None


def detect_cjk_font_path(candidates: Iterable[str] | None = None) -> str | None:
    for raw_path in candidates or CJK_FONT_FILE_CANDIDATES:
        path = Path(raw_path).expanduser()
        if path.exists():
            return str(path)
    return None


def configure_matplotlib_defaults(candidates: Iterable[str] | None = None) -> str | None:
    if not module_available("matplotlib"):
        return None
    import matplotlib as mpl  # type: ignore

    font_name = detect_cjk_font(candidates)
    if font_name:
        mpl.rcParams["font.family"] = [font_name]
        mpl.rcParams["font.sans-serif"] = [font_name]
    mpl.rcParams["axes.unicode_minus"] = False
    return font_name


def runtime_readiness_report(modules: dict[str, bool] | None = None) -> dict[str, Any]:
    module_map = modules or {name: module_available(name) for group in DEPENDENCY_GROUPS.values() for name in group}
    mpl_config_dir = Path(os.environ.get("MPLCONFIGDIR", tempfile.gettempdir())).expanduser()
    tool_status = {name: {"available": command_available(name), "purpose": purpose} for name, purpose in EXTERNAL_TOOLS.items()}
    cjk_font = detect_cjk_font() if module_map.get("matplotlib") else None
    writable = False
    try:
        mpl_config_dir.mkdir(parents=True, exist_ok=True)
        probe = mpl_config_dir / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        writable = True
    except OSError:
        writable = False

    warnings_list: list[str] = []
    if module_map.get("matplotlib") and not cjk_font:
        warnings_list.append("matplotlib 可用，但未检测到常见中文字体；中文图表可能回退为缺字字体。")
    if module_map.get("reportlab") is False:
        warnings_list.append("缺少 reportlab，无法导出正式 PDF 报告。")
    if module_map.get("docx") is False:
        warnings_list.append("缺少 python-docx，无法导出正式 DOCX 报告。")
    if not writable:
        warnings_list.append(f"MPLCONFIGDIR 不可写：{mpl_config_dir}")
    if not tool_status["pdftotext"]["available"] and not module_map.get("pypdf", False):
        warnings_list.append("未检测到 pdftotext 或 pypdf，PDF 文本级质检能力有限。")

    pdf_validation_level = "text" if (module_map.get("pypdf") or tool_status["pdftotext"]["available"]) else "file" if tool_status["file"]["available"] else "none"
    readiness = {
        "chinese_chart_ready": bool(module_map.get("matplotlib") and cjk_font and writable),
        "formal_docx_ready": bool(module_map.get("docx")),
        "formal_pdf_ready": bool(module_map.get("reportlab")),
        "formal_report_ready": bool(module_map.get("docx") and module_map.get("reportlab")),
        "pdf_text_validation_ready": pdf_validation_level == "text",
    }

    return {
        "python_version": sys.version.split()[0],
        "mpl_backend": os.environ.get("MPLBACKEND"),
        "mpl_config_dir": str(mpl_config_dir),
        "mpl_config_dir_writable": writable,
        "detected_cjk_font": cjk_font,
        "external_tools": tool_status,
        "pdf_validation_level": pdf_validation_level,
        "readiness": readiness,
        "warnings": warnings_list,
    }


def availability_report() -> dict[str, Any]:
    modules = {name: module_available(name) for group in DEPENDENCY_GROUPS.values() for name in group}
    modules.update(
        {
            "docx": module_available("docx"),
            "reportlab": module_available("reportlab"),
            "pypdf": module_available("pypdf"),
        }
    )
    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "python_version": sys.version.split()[0],
        "modules": modules,
        "groups": {
            group: {
                "required_modules": names,
                "available_modules": [name for name in names if modules[name]],
                "missing_modules": [name for name in names if not modules[name]],
            }
            for group, names in DEPENDENCY_GROUPS.items()
        },
        "runtime": runtime_readiness_report(modules),
    }


def missing_modules(modules: Iterable[str]) -> list[str]:
    return [name for name in modules if not module_available(name)]


def install_hint(modules: Iterable[str]) -> str:
    deduped = sorted(set(modules))
    return f"python3 -m pip install {' '.join(deduped)}"


def ensure_modules(modules: Iterable[str], context: str) -> None:
    missing = missing_modules(modules)
    if missing:
        raise RuntimeError(
            f"Missing required modules for {context}: {', '.join(missing)}. "
            f"Install with: {install_hint(missing)}"
        )


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    normalized = normalized.strip("-")
    return normalized or "run"


def ensure_output_dir(base_dir: str | None = None, prefix: str = "analysis") -> Path:
    root = Path(base_dir) if base_dir else Path.cwd() / "outputs"
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")


def write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n")


def parse_json_arg(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    return json.loads(raw)


def to_serializable(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    return value
