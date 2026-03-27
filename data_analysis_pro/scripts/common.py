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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# --- Constants & Configuration ---

DEPENDENCY_GROUPS = {
    "core": ["numpy", "pandas", "scipy", "sklearn"],
    "viz": ["matplotlib", "seaborn"],
    "database": ["sqlalchemy", "openpyxl"],
    "large_data": ["polars", "duckdb", "pyarrow"],
    "advanced": ["statsmodels", "xgboost", "lightgbm", "prophet", "plotly", "streamlit", "shap", "torch"],
}

EXTERNAL_TOOLS = {
    "pdftotext": "PDF text extraction",
    "qpdf": "PDF structure check",
    "pandoc": "Document conversion (DOCX/PDF)",
    "soffice": "LibreOffice (DOCX to PDF)",
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

DEFAULT_CHINESE_FIELD_LABELS = {
    "age_group": "年龄分组",
    "general_health": "总体健康状况",
    "diabetes_status": "糖尿病状态",
    "asthma_status": "哮喘状态",
    "income_bracket": "收入档位",
    "education_level": "教育水平",
    "exercise_past_30d": "过去30天运动情况",
    "leisure_time_activity": "休闲活动情况",
    "personal_doctor": "是否有固定医生",
    "ever_smoked_100": "是否曾累计吸烟100支",
    "heart_disease": "心脏病情况",
    "sex": "性别",
    "obese": "是否肥胖",
    "target": "目标",
}

COMMON_TOKEN_TRANSLATIONS = {
    "age": "年龄", "group": "分组", "general": "总体", "health": "健康",
    "diabetes": "糖尿病", "status": "状态", "asthma": "哮喘", "income": "收入",
    "bracket": "档位", "education": "教育", "level": "水平", "exercise": "运动",
    "past": "过去", "30d": "30天", "leisure": "休闲", "time": "时间",
    "activity": "活动", "personal": "个人", "doctor": "医生", "medical": "医疗",
    "cost": "费用", "ever": "曾经", "smoked": "吸烟", "heart": "心脏",
    "disease": "疾病", "sex": "性别", "obese": "肥胖", "target": "目标",
    "physical": "身体", "mental": "心理", "unhealthy": "不健康", "days": "天数",
}

DEFAULT_CHINESE_VALUE_LABELS = {
    "yes": "是", "no": "否", "male": "男性", "female": "女性", "unknown": "未知",
    "excellent": "极好", "very_good": "很好", "good": "好", "fair": "一般", "poor": "差",
}

# --- Runtime Setup ---

def _configure_runtime_environment() -> None:
    mpl_config_dir = Path(tempfile.gettempdir()) / "data-analysis-pro-mpl"
    mpl_config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_config_dir))
    os.environ.setdefault("MPLBACKEND", "Agg")
    cpu_count = os.cpu_count()
    if cpu_count:
        os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(cpu_count))
    warnings.filterwarnings("ignore", category=UserWarning)

_configure_runtime_environment()

# --- Utility Functions ---

def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None

def command_available(name: str) -> bool:
    return shutil.which(name) is not None

def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")

def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return normalized.strip("-") or "run"

def ensure_run_dir(output_dir: str | Path | None = None, prefix: str = "analysis") -> Path:
    root = Path(output_dir) if output_dir else Path.cwd() / "outputs"
    root.mkdir(parents=True, exist_ok=True)
    # If output_dir already looks like a run dir, reuse it.
    if output_dir and re.match(rf"^{re.escape(prefix)}-\d{{8}}-\d{{6}}$", Path(output_dir).name):
        return Path(output_dir)
    run_dir = root / f"{prefix}-{timestamp_slug()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir

def write_json(path: Path | str, payload: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(to_serializable(payload), ensure_ascii=False, indent=2, default=str) + "\n")
    return p

def write_artifact(run_dir: str | Path, artifact_name: str, payload: Any) -> Path:
    return write_json(Path(run_dir) / f"{artifact_name}.json", payload)

def write_markdown(path: str | Path, text: str) -> Path:
    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(text.rstrip() + "\n")
    return resolved

def write_status(run_dir: Path | str, stage: str, status: str, extra: dict | None = None) -> Path:
    payload = {"stage": stage, "status": status, "updated_at": now_utc_iso()}
    if extra: payload.update(extra)
    status_path = write_json(Path(run_dir) / "run_status.json", payload)
    # Also append to events log
    events_path = Path(run_dir) / "run_events.jsonl"
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(to_serializable(payload), ensure_ascii=False) + "\n")
    return status_path

def to_serializable(value: Any) -> Any:
    if isinstance(value, Path): return str(value)
    if hasattr(value, "tolist"): return value.tolist()
    if hasattr(value, "item"): 
        try: return value.item()
        except: return str(value)
    if isinstance(value, (datetime, timezone)): return value.isoformat()
    return value

# --- Localization & Labels ---

def friendly_label(name: str, locale: str = "zh") -> str:
    if locale != "zh": return name
    if name in DEFAULT_CHINESE_FIELD_LABELS: return DEFAULT_CHINESE_FIELD_LABELS[name]
    parts = re.split(r"[_\-\s]+", str(name).strip())
    translated = [COMMON_TOKEN_TRANSLATIONS.get(p.lower(), p) for p in parts if p]
    return "".join(translated) or name

def friendly_chart_feature_label(name: str, locale: str = "zh") -> str:
    return friendly_label(name, locale)

def friendly_value(value: Any, locale: str = "zh") -> str:
    text = str(value).lower()
    if locale != "zh": return text
    return DEFAULT_CHINESE_VALUE_LABELS.get(text, text)

# --- Environment Readiness ---

def get_availability_report() -> dict[str, Any]:
    modules = {name: module_available(name) for group in DEPENDENCY_GROUPS.values() for name in group}
    return {
        "python_version": sys.version.split()[0],
        "modules": modules,
        "tools": {name: command_available(name) for name in EXTERNAL_TOOLS},
        "mpl_config_dir": os.environ.get("MPLCONFIGDIR"),
        "fonts": configure_matplotlib_fonts(),
        "timestamp": now_utc_iso(),
    }

def parse_json_arg(raw: str | None) -> dict[str, Any]:
    if not raw: return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}

def ensure_output_dir(base_dir: str | None = None, prefix: str = "analysis") -> Path:
    return ensure_run_dir(base_dir, prefix)

def configure_matplotlib_defaults(preferred_fonts: list[str] | None = None):
    return configure_matplotlib_fonts()

def configure_matplotlib_fonts():
    if not module_available("matplotlib"): return None
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    available = {f.name for f in font_manager.fontManager.ttflist}
    for f in CJK_FONT_CANDIDATES:
        if f in available:
            plt.rcParams["font.sans-serif"] = [f] + plt.rcParams["font.sans-serif"]
            plt.rcParams["axes.unicode_minus"] = False
            return f
    return None
