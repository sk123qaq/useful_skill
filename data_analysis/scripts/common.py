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

CHART_TARGET_LABELS = {
    "obese": "是否肥胖",
}

CHART_FEATURE_LABELS = {
    "diabetes_status_no": "无糖尿病",
    "diabetes_status_yes": "已确诊糖尿病",
    "diabetes_status_prediabetes": "前驱糖尿病",
    "general_health_excellent": "自评健康优秀",
    "general_health_very_good": "自评健康很好",
    "general_health_good": "自评健康良好",
    "general_health_fair": "自评健康一般偏差",
    "general_health_poor": "自评健康较差",
    "age_group_80": "80岁及以上组",
    "age_group_18_24": "18-24岁组",
    "exercise_past_30d_no": "过去30天未运动",
    "exercise_past_30d_yes": "过去30天有运动",
    "leisure_time_activity_no": "无休闲活动",
    "leisure_time_activity_yes": "有休闲活动",
    "asthma_status_yes": "有哮喘史",
    "asthma_status_no": "无哮喘史",
    "education_level_college_grad": "大学毕业",
    "education_level_some_college": "部分大学教育",
    "personal_doctor_one_doctor": "有1位固定医生",
    "personal_doctor_multiple_doctors": "有多位固定医生",
    "ever_smoked_100_no": "无明显吸烟史",
    "ever_smoked_100_yes": "有明显吸烟史",
    "sex_female": "女性",
    "sex_male": "男性",
    "income_bracket_unknown": "收入分组未知",
}

CHART_PREFIX_LABELS = {
    "age_group": "年龄组",
    "general_health": "自评健康",
    "exercise_past_30d": "过去30天运动情况",
    "leisure_time_activity": "休闲活动",
    "diabetes_status": "糖尿病状态",
    "education_level": "教育程度",
    "personal_doctor": "固定医生情况",
    "ever_smoked_100": "吸烟史",
    "income_bracket": "收入分组",
    "heart_disease": "心脏病情况",
    "asthma_status": "哮喘情况",
    "sex": "性别",
}

CHART_VALUE_LABELS = {
    "yes": "有",
    "no": "无",
    "unknown": "未知",
    "excellent": "优秀",
    "very_good": "很好",
    "good": "良好",
    "fair": "一般偏差",
    "poor": "较差",
    "female": "女性",
    "male": "男性",
    "one_doctor": "有1位固定医生",
    "multiple_doctors": "有多位固定医生",
    "18_24": "18-24岁组",
    "25_29": "25-29岁组",
    "30_34": "30-34岁组",
    "35_39": "35-39岁组",
    "40_44": "40-44岁组",
    "45_49": "45-49岁组",
    "50_54": "50-54岁组",
    "55_59": "55-59岁组",
    "60_64": "60-64岁组",
    "65_69": "65-69岁组",
    "70_74": "70-74岁组",
    "75_79": "75-79岁组",
    "80": "80岁及以上组",
    "college_grad": "大学毕业",
    "some_college": "部分大学教育",
    "prediabetes": "前驱糖尿病",
}

CHART_TOKEN_LABELS = {
    "age": "年龄",
    "group": "组",
    "general": "总体",
    "health": "健康",
    "exercise": "运动",
    "past": "过去",
    "status": "状态",
    "diabetes": "糖尿病",
    "education": "教育",
    "level": "程度",
    "personal": "个人",
    "doctor": "医生",
    "income": "收入",
    "bracket": "分组",
    "heart": "心脏",
    "disease": "疾病",
    "asthma": "哮喘",
    "sex": "性别",
    "smoked": "吸烟",
    "smoke": "吸烟",
    "unknown": "未知",
    "yes": "有",
    "no": "无",
}


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


def friendly_chart_target_label(name: str | None) -> str:
    if not name:
        return "目标变量"
    return CHART_TARGET_LABELS.get(name, name)


def friendly_chart_feature_label(name: str | None) -> str:
    if not name:
        return "变量"
    if name in CHART_FEATURE_LABELS:
        return CHART_FEATURE_LABELS[name]

    for prefix in sorted(CHART_PREFIX_LABELS, key=len, reverse=True):
        needle = f"{prefix}_"
        if name.startswith(needle):
            value = name[len(needle) :]
            friendly_prefix = CHART_PREFIX_LABELS[prefix]
            friendly_value = CHART_VALUE_LABELS.get(value)
            if friendly_value:
                if prefix == "age_group":
                    return friendly_value
                return f"{friendly_prefix}={friendly_value}"
            if re.fullmatch(r"\d+_\d+", value):
                if prefix == "age_group":
                    return f"{value.replace('_', '-')}岁组"
                return f"{friendly_prefix}={value.replace('_', '-')}"
            if re.fullmatch(r"\d+", value):
                if prefix == "age_group":
                    return f"{value}岁及以上组"
                return f"{friendly_prefix}={value}"
            return f"{friendly_prefix}={value.replace('_', ' ')}"

    tokens = [CHART_TOKEN_LABELS.get(token, token) for token in str(name).split("_")]
    return " ".join(tokens)
