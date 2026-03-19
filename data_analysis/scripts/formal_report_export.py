#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from common import command_available, detect_cjk_font, detect_cjk_font_path, friendly_chart_feature_label, module_available, write_json, write_markdown


KNOWN_JSON = [
    "environment.json",
    "read_plan.json",
    "semantic_schema.json",
    "feature_lineage.json",
    "chart_plan.json",
    "chart_candidates.json",
    "chart_review.json",
    "report_chart_decision.json",
    "cleaning_report.json",
    "stats_report.json",
    "feature_plan.json",
    "model_report.json",
    "explainability_report.json",
    "business_report.json",
    "experiment_report.json",
    "analysis_report.json",
    "causal_report.json",
    "causal_narrative_report.json",
    "research_report.json",
]

TASK_LABELS = {
    "descriptive": "描述性分析",
    "classification": "分类建模分析",
    "regression": "回归建模分析",
    "time-series": "时间序列分析",
    "cluster": "聚类分析",
    "clustering": "聚类分析",
    "apriori": "关联规则分析",
    "anova": "方差分析",
    "root-cause": "根因分析",
    "experiment": "实验分析",
    "ab-test": "A/B 测试分析",
    "did": "双重差分分析",
    "rd": "断点回归分析",
    "synthetic-control": "合成控制分析",
    "iv": "工具变量分析",
    "dml": "双重机器学习分析",
    "dr": "双重稳健分析",
    "psm": "倾向得分匹配分析",
    "orthogonal": "正交学习器分析",
    "uplift": "增益建模分析",
    "cate": "异质处理效应分析",
    "causal": "综合因果分析",
}

SECTION_ALIASES = {
    "关键发现": ["关键发现", "Insight"],
    "业务/公共卫生解释": ["业务/公共卫生解释", "Recommendation"],
    "风险与限制": ["风险与限制", "Risk"],
    "分析范围": ["分析范围", "Context"],
    "数据来源": ["数据来源", "Read Plan"],
    "模型结果": ["模型结果", "Insight"],
    "可解释性结论": ["可解释性结论", "Insight"],
}

EXPERIMENT_STATUS_LABELS = {
    "treatment_looks_promising": "实验组表现较好",
    "guardrail_regression_detected": "存在护栏指标回退",
    "no_clear_winner": "暂无明确优胜方案",
    "inconclusive": "结论暂不充分",
}

CAUSAL_ESTIMATE_LABELS = {
    "did_estimate": "DID 估计值",
    "local_effect": "局部处理效应",
    "iv_estimate": "IV 估计值",
    "average_treatment_effect": "ATE",
    "average_treatment_effect_on_treated": "ATT",
    "post_average_gap": "处理后平均差距",
}

DOCX_FONT_NAME = detect_cjk_font(
    ["Songti SC", "STSong", "Songti TC", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "SimHei", "Arial Unicode MS"]
) or "Arial Unicode MS"
DOCX_HEADING_FONT_NAME = detect_cjk_font(
    ["PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "SimHei", "Songti SC", "Arial Unicode MS"]
) or DOCX_FONT_NAME
PDF_FONT_NAME = "DataAnalysisCJK"
PDF_FONT_FALLBACK = "STSong-Light"

MODEL_LABELS = {
    "hist_gradient_boosting_classifier": "直方梯度提升分类模型",
    "random_forest_classifier": "随机森林分类模型",
    "xgboost_classifier": "XGBoost 分类模型",
    "lightgbm_classifier": "LightGBM 分类模型",
    "hist_gradient_boosting_regressor": "直方梯度提升回归模型",
    "random_forest_regressor": "随机森林回归模型",
    "xgboost_regressor": "XGBoost 回归模型",
    "lightgbm_regressor": "LightGBM 回归模型",
}

TARGET_LABELS = {
    "obese": "肥胖风险",
}

WDI_INDICATOR_LABELS = {
    "NY.GDP.PCAP.CD": "人均GDP",
    "SP.DYN.LE00.IN": "预期寿命",
    "IT.NET.USER.ZS": "互联网使用率",
    "EG.ELC.ACCS.ZS": "电力可及率",
    "SP.POP.TOTL": "总人口",
    "SP.DYN.IMRT.IN": "婴儿死亡率",
    "NE.TRD.GNFS.ZS": "贸易开放度",
    "SL.UEM.TOTL.ZS": "失业率",
}

FEATURE_LABELS = {
    "diabetes_status_no": "无糖尿病",
    "diabetes_status_yes": "已确诊糖尿病",
    "diabetes_status_prediabetes": "前驱糖尿病",
    "general_health_excellent": "自评健康优秀",
    "general_health_very_good": "自评健康很好",
    "general_health_good": "自评健康良好",
    "general_health_fair": "自评健康一般偏差",
    "general_health_poor": "自评健康较差",
    "age_group_80": "年龄组 80 岁及以上",
    "age_group_18_24": "年龄组 18-24 岁",
    "exercise_past_30d_no": "过去 30 天未运动",
    "exercise_past_30d_yes": "过去 30 天有运动",
    "asthma_status_yes": "有哮喘史",
    "education_level_college_grad": "大学毕业",
    "education_level_some_college": "部分大学教育",
    "personal_doctor_one_doctor": "有 1 位固定医生",
    "ever_smoked_100_no": "无明显吸烟史",
    "ever_smoked_100_yes": "有明显吸烟史",
    "sex_female": "女性",
    "sex_male": "男性",
    "income_bracket_unknown": "收入分组未知",
}

PREFIX_LABELS = {
    "age_group": "年龄组",
    "general_health": "自评健康",
    "exercise_past_30d": "过去 30 天运动情况",
    "leisure_time_activity": "休闲活动",
    "mental_unhealthy_days_bucket": "近 30 天心理不健康天数分组",
    "physical_unhealthy_days_bucket": "近 30 天身体不健康天数分组",
    "diabetes_status": "糖尿病状态",
    "education_level": "教育程度",
    "personal_doctor": "固定医生情况",
    "ever_smoked_100": "吸烟史",
    "income_bracket": "收入分组",
    "heart_disease": "心脏病情况",
    "asthma_status": "哮喘情况",
    "sex": "性别",
}

VALUE_LABELS = {
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
    "one_doctor": "有 1 位固定医生",
    "multiple_doctors": "有多位固定医生",
    "18_24": "18-24 岁",
    "25_29": "25-29 岁",
    "30_34": "30-34 岁",
    "35_39": "35-39 岁",
    "40_44": "40-44 岁",
    "45_49": "45-49 岁",
    "50_54": "50-54 岁",
    "55_59": "55-59 岁",
    "60_64": "60-64 岁",
    "65_69": "65-69 岁",
    "70_74": "70-74 岁",
    "75_79": "75-79 岁",
    "80": "80 岁及以上",
    "college_grad": "大学毕业",
    "some_college": "部分大学教育",
    "prediabetes": "前驱糖尿病",
}

TOKEN_LABELS = {
    "age": "年龄",
    "group": "组",
    "general": "总体",
    "health": "健康",
    "exercise": "运动",
    "past": "过去",
    "mental": "心理",
    "physical": "身体",
    "unhealthy": "不健康",
    "days": "天数",
    "day": "天数",
    "bucket": "分组",
    "status": "状态",
    "diabetes": "糖尿病",
    "education": "教育",
    "level": "水平",
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

TEXT_REPLACEMENTS = {
    "classification": "分类建模分析",
    "regression": "回归建模分析",
    "clustering": "聚类分析",
    "cluster": "聚类分析",
    "xgboost_classifier": "XGBoost 分类模型",
    "lightgbm_classifier": "LightGBM 分类模型",
    "random_forest_classifier": "随机森林分类模型",
    "hist_gradient_boosting_classifier": "直方梯度提升分类模型",
    "xgboost_regressor": "XGBoost 回归模型",
    "lightgbm_regressor": "LightGBM 回归模型",
    "random_forest_regressor": "随机森林回归模型",
    "hist_gradient_boosting_regressor": "直方梯度提升回归模型",
    "one-hot": "独热编码",
    "permutation importance": "置换重要性",
    "accuracy = ": "Accuracy 约为 ",
    "加权 F1 = ": "加权 F1 约为 ",
    "excellent": "优秀",
    "very_good": "很好",
    "good": "良好",
    "fair": "一般偏差",
    "poor": "较差",
    "_BMI5 >= 3000": "BMI 编码阈值达到肥胖判定标准",
    "obese": "肥胖风险",
}

METRIC_META = {
    "accuracy": {
        "label": "Accuracy",
        "meaning": "预测正确的比例。",
        "reading": "越高越好，但必须结合类别分布和基线一起看。",
    },
    "precision_weighted": {
        "label": "Precision",
        "meaning": "预测为目标类别时真正命中的比例。",
        "reading": "越高越好，误报成本高时更重要。",
    },
    "recall_weighted": {
        "label": "Recall",
        "meaning": "真实目标样本里被模型找回来的比例。",
        "reading": "越高越好，漏报成本高时更重要。",
    },
    "f1_weighted": {
        "label": "F1",
        "meaning": "Precision 和 Recall 的折中指标。",
        "reading": "越高越好，比只看 Accuracy 更稳。",
    },
    "neg_root_mean_squared_error": {
        "label": "RMSE",
        "meaning": "均方根误差，反映预测值与真实值的偏差。",
        "reading": "绝对值越小越好，但必须结合目标量纲。",
    },
    "neg_mean_absolute_error": {
        "label": "MAE",
        "meaning": "平均绝对误差，反映平均偏差大小。",
        "reading": "绝对值越小越好，更容易直观理解。",
    },
    "r2": {
        "label": "R2",
        "meaning": "模型解释结果波动的能力。",
        "reading": "越高越好；接近 0 表示接近均值基线，负数通常较差。",
    },
    "p_value": {
        "label": "p_value",
        "meaning": "在零假设成立时观察到当前或更极端结果的概率。",
        "reading": "越小越支持存在差异，但不代表业务价值一定高。",
    },
    "silhouette_score": {
        "label": "Silhouette",
        "meaning": "衡量聚类内紧密度和群间分离度。",
        "reading": "越高越好；大于 0.5 通常表示群组分离较清晰。",
    },
    "lift": {
        "label": "Lift",
        "meaning": "关联规则中相对独立情形的提升倍数。",
        "reading": "大于 1 才表示正向关联；越大通常越强。",
    },
}

IMAGE_EXPLANATIONS = {
    "target_distribution.png": {
        "title": "目标分布图",
        "how_to_read": "先看正负样本是否明显不平衡，再看分布是否偏斜。",
        "meaning": "帮助判断当前建模任务的难度，以及 Accuracy 是否可能被类别分布误导。",
    },
    "shap_bar.png": {
        "title": "SHAP 重要性图",
        "how_to_read": "横向条越长，表示该变量对模型预测的平均影响越强。",
        "meaning": "说明模型最依赖哪些变量，但不代表这些变量一定具有因果作用。",
    },
    "pdp_diabetes_status_no.png": {
        "title": "糖尿病状态 PDP 图",
        "how_to_read": "观察变量变化时模型预测均值的变化方向和幅度。",
        "meaning": "帮助判断模型如何利用糖尿病状态区分肥胖风险。",
    },
    "pdp_age_group_80.png": {
        "title": "年龄组 PDP 图",
        "how_to_read": "观察高龄组变量出现时预测结果如何变化。",
        "meaning": "帮助理解年龄变量在模型中的边际影响。",
    },
    "pdp_general_health_excellent.png": {
        "title": "健康自评 PDP 图",
        "how_to_read": "看健康自评优秀这一特征出现时预测值的变化方向。",
        "meaning": "帮助理解自评健康与肥胖风险预测之间的关系。",
    },
}

IMAGE_ORDER = [
    "target_distribution.png",
    "shap_bar.png",
    "pdp_diabetes_status_no.png",
    "pdp_general_health_excellent.png",
    "pdp_age_group_80.png",
]

MAX_FORMAL_REPORT_CHARTS = 4
CHART_KIND_LABELS = {
    "line": "趋势图",
    "scatter": "散点图",
    "bar": "柱状对比图",
    "heatmap": "热力图",
    "histogram": "分布图",
    "box": "箱线图",
}
TECHNICAL_TERM_LABELS = {
    "accuracy": "Accuracy（准确率）",
    "precision": "Precision（查准率）",
    "recall": "Recall（召回率）",
    "f1": "F1（综合平衡查准率与召回率的指标）",
    "rmse": "RMSE（均方根误差）",
    "mae": "MAE（平均绝对误差）",
    "r2": "R2（拟合优度）",
    "shap": "SHAP（模型解释中衡量变量影响强弱的方法）",
    "pdp": "PDP（部分依赖图，用来观察变量变化和预测结果的关系）",
    "incomegroup": "Income Group（收入分组）",
    "gdp": "GDP（国内生产总值）",
    "life expectancy": "Life expectancy（预期寿命）",
    "internet": "Internet（互联网）",
    "electricity": "Electricity access（电力可及率）",
    "轮廓系数": "轮廓系数（衡量聚类结果是否分得清楚、组内是否紧密的指标）",
    "双重差分": "双重差分（比较处理组和对照组在干预前后变化差异的方法）",
    "断点回归": "断点回归（利用阈值附近样本识别局部处理效应的方法）",
    "工具变量": "工具变量（用外生变量帮助识别因果效应的方法）",
    "倾向得分匹配": "倾向得分匹配（先匹配相似样本，再比较处理效应的方法）",
    "置信区间": "置信区间（反映估计结果可能落入范围的区间）",
    "相关系数": "相关系数（衡量两个变量同向或反向变化强弱的指标）",
    "部分依赖图": "部分依赖图（观察某个变量变化时模型预测如何变化的图）",
    "特征重要性": "特征重要性（表示模型在判断时更依赖哪些变量的结果）",
    "显著性": "显著性（说明结果不太像随机波动造成的统计证据强弱）",
}
CHART_REVIEW_META_PHRASES = [
    "这张图围绕",
    "帮助读者",
    "帮助基础读者",
    "用于说明",
    "用来补充说明",
    "当前分布、差异或关系",
    "不能只当成单一数字来理解",
]

FORMAL_REPORT_TEMPLATE_LEAK_PHRASES = [
    "explainability generated",
    "top permutation-importance",
    "top 3",
    "context",
    "insight",
    "recommendation",
    "risk",
    "loaded ",
    "detected ",
    "review ",
    "consider ",
    "generated for model",
    "no recommendation generated yet",
    "a planning-only run was requested",
]


def _report_stage_label(stage: str | None) -> str:
    if stage == "final":
        return "正式版（已完成图表复核）"
    return "草稿版（需二次图表复核）"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, str):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number):
        return "N/A"
    if abs(number) >= 1000:
        return f"{number:,.{digits}f}"
    return f"{number:.{digits}f}"


def _pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return str(value)


def _strip_markdown(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("`", "")
    return text.strip()


def _normalize_report_text(text: str | None) -> str:
    if not text:
        return ""
    normalized = _strip_markdown(text)
    for source, target in sorted(FEATURE_LABELS.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = normalized.replace(source, target)
    for source, target in sorted(TEXT_REPLACEMENTS.items(), key=lambda item: len(item[0]), reverse=True):
        normalized = normalized.replace(source, target)
    normalized = re.sub(
        r"\bmental[_ ]unhealthy[_ ]days[_ ]bucket[_ ](\d+)[_ ](\d+)\b",
        lambda match: f"近30天心理不健康天数分组={match.group(1)}-{match.group(2)}天",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\bphysical[_ ]unhealthy[_ ]days[_ ]bucket[_ ](\d+)[_ ](\d+)\b",
        lambda match: f"近30天身体不健康天数分组={match.group(1)}-{match.group(2)}天",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\bmental[_ ]unhealthy[_ ]days[_ ]bucket\b",
        "近30天心理不健康天数分组",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\bphysical[_ ]unhealthy[_ ]days[_ ]bucket\b",
        "近30天身体不健康天数分组",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = normalized.replace("PDP", "PDP")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z0-9])", "", normalized)
    normalized = re.sub(r"(?<=[A-Za-z0-9])\s+(?=[\u4e00-\u9fff])", "", normalized)
    return normalized.strip()


def _plain_file_name(path_text: str | None) -> str:
    if not path_text:
        return "N/A"
    return Path(str(path_text)).name


def _friendly_task_label(task: str | None) -> str:
    if not task:
        return "未知任务"
    return TASK_LABELS.get(task, task)


def _friendly_model_name(name: str | None) -> str:
    if not name:
        return "N/A"
    return MODEL_LABELS.get(name, name.replace("_", " "))


def _friendly_target_label(target: str | None) -> str:
    if not target:
        return "目标指标"
    return TARGET_LABELS.get(target, _friendly_feature_name(target))


def _friendly_feature_name(name: str | None) -> str:
    if not name:
        return "N/A"
    if name in WDI_INDICATOR_LABELS:
        return WDI_INDICATOR_LABELS[name]
    if name in FEATURE_LABELS:
        return FEATURE_LABELS[name]

    for prefix in sorted(PREFIX_LABELS, key=len, reverse=True):
        needle = f"{prefix}_"
        if name.startswith(needle):
            value = name[len(needle) :]
            friendly_prefix = PREFIX_LABELS[prefix]
            friendly_value = VALUE_LABELS.get(value)
            if friendly_value:
                return f"{friendly_prefix}={friendly_value}"
            if prefix in {"mental_unhealthy_days_bucket", "physical_unhealthy_days_bucket"}:
                if re.fullmatch(r"\d+_\d+", value):
                    return f"{friendly_prefix}={value.replace('_', '-')}天"
                if re.fullmatch(r"\d+", value):
                    return f"{friendly_prefix}={value}天"
            if re.fullmatch(r"\d+_\d+", value):
                return f"{friendly_prefix}={value.replace('_', '-')}"
            if re.fullmatch(r"\d+", value):
                return f"{friendly_prefix}={value} 岁及以上"
            return f"{friendly_prefix}={value.replace('_', ' ')}"

    friendly = friendly_chart_feature_label(name)
    if friendly and friendly != "变量":
        return friendly
    tokens = [TOKEN_LABELS.get(token, token) for token in name.split("_")]
    return " ".join(tokens)


def _compact_feature_names(names: list[str] | tuple[str, ...], limit: int = 2) -> str:
    friendly = [_friendly_feature_name(name) for name in names if name]
    if not friendly:
        return "N/A"
    if len(friendly) <= limit:
        return "、".join(friendly)
    return "、".join(friendly[:limit]) + " 等"


def _summarize_source_name(text: str) -> str:
    lowered = text.lower()
    if "world development indicators" in lowered or "wdi" in lowered:
        return "世界银行 World Development Indicators 2026 版（WDI）"
    return text


def _metric_judgment(metric_key: str, value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "需结合上下文判断"
    if metric_key in {"accuracy", "precision_weighted", "recall_weighted", "f1_weighted"}:
        if number >= 0.8:
            return "表现较强"
        if number >= 0.65:
            return "具备可用价值"
        return "仍需提升"
    if metric_key == "r2":
        if number >= 0.7:
            return "表现较强"
        if number >= 0.4:
            return "具备可用价值"
        if number >= 0:
            return "解释力偏弱"
        return "明显偏弱"
    if metric_key == "p_value":
        if number < 0.01:
            return "强支持存在差异"
        if number < 0.05:
            return "支持存在差异"
        return "证据不足"
    if metric_key == "silhouette_score":
        if number >= 0.5:
            return "聚类结构清晰"
        if number >= 0.25:
            return "聚类结构一般"
        return "聚类结构偏弱"
    if metric_key == "lift":
        if number > 1.2:
            return "正向关联较明显"
        if number > 1.0:
            return "存在轻微正向关联"
        return "无明显正向关联"
    if metric_key in {"neg_root_mean_squared_error", "neg_mean_absolute_error"}:
        return "需结合目标量纲和基线判断"
    return "需结合上下文判断"


def _parse_markdown_sections(text: str | None) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "未命名部分"
    if not text:
        return sections
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            current = _normalize_report_text(stripped.lstrip("# ").strip())
            sections.setdefault(current, [])
            continue
        cleaned = _normalize_report_text(stripped)
        if cleaned.startswith("- "):
            cleaned = cleaned[2:].strip()
        sections.setdefault(current, []).append(cleaned)
    return sections


def _task_name(context: dict[str, Any]) -> str:
    chart_plan = context.get("chart_plan") or {}
    task = chart_plan.get("task")
    if task:
        return str(task)
    model_report = context.get("model_report") or {}
    if model_report.get("task"):
        return str(model_report["task"])
    analysis_report = context.get("analysis_report") or {}
    if analysis_report.get("task"):
        return str(analysis_report["task"])
    return "unknown"


def _load_context(run_dir: Path) -> dict[str, Any]:
    context = {path.stem: _load_json(run_dir / path) for path in map(Path, KNOWN_JSON)}
    context["run_summary"] = _load_text(run_dir / "run_summary.md")
    context["run_summary_sections"] = _parse_markdown_sections(context["run_summary"])
    context["report_brief"] = _load_text(run_dir / "report_brief.md")
    context["report_brief_sections"] = _parse_markdown_sections(context["report_brief"])
    context["png_files"] = sorted(run_dir.glob("*.png"))
    context["json_files"] = sorted(run_dir.glob("*.json"))
    context["markdown_files"] = sorted(run_dir.glob("*.md"))
    context["task"] = _task_name(context)
    return context


def _best_model_metrics(context: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    model_report = context.get("model_report") or {}
    task = model_report.get("task")
    models = model_report.get("models", {})
    if not task or not models:
        return None, {}
    ranking_metric = "test_f1_weighted" if task == "classification" else "test_r2" if task == "regression" else None
    if ranking_metric is None:
        return None, {}
    candidates: list[tuple[float, str]] = []
    for name, metrics in models.items():
        if "error" in metrics or ranking_metric not in metrics:
            continue
        candidates.append((float(metrics[ranking_metric]), name))
    if not candidates:
        return None, {}
    candidates.sort(reverse=True)
    best_name = candidates[0][1]
    return best_name, models[best_name]


def _top_explainability_features(context: dict[str, Any], limit: int = 5) -> list[str]:
    explainability = context.get("explainability_report") or {}
    shap = explainability.get("shap") or {}
    rows = shap.get("top_features") or explainability.get("permutation_importance") or []
    return [_friendly_feature_name(item.get("feature")) for item in rows[:limit] if item.get("feature")]


def _feature_dimension_name(name: str | None) -> str:
    if not name:
        return "N/A"
    for prefix in sorted(PREFIX_LABELS, key=len, reverse=True):
        if name == prefix or name.startswith(f"{prefix}_"):
            return PREFIX_LABELS[prefix]
    friendly = _friendly_feature_name(name)
    if "=" in friendly:
        return friendly.split("=", 1)[0]
    return friendly


def _top_explainability_dimensions(context: dict[str, Any], limit: int = 5) -> list[str]:
    explainability = context.get("explainability_report") or {}
    shap = explainability.get("shap") or {}
    rows = shap.get("top_features") or explainability.get("permutation_importance") or []
    dimensions: list[str] = []
    seen: set[str] = set()
    for item in rows:
        feature = item.get("feature")
        if not feature:
            continue
        dimension = _feature_dimension_name(str(feature))
        if dimension in seen:
            continue
        seen.add(dimension)
        dimensions.append(dimension)
        if len(dimensions) >= limit:
            break
    return dimensions


def _section_lines(context: dict[str, Any], section_name: str, limit: int | None = None) -> list[str]:
    aliases = SECTION_ALIASES.get(section_name, [section_name])
    collected: list[str] = []
    for source_name in aliases:
        collected.extend((context.get("report_brief_sections") or {}).get(source_name, []))
    if not collected:
        for source_name in aliases:
            collected.extend((context.get("run_summary_sections") or {}).get(source_name, []))
    normalized = _normalize_section_lines(collected)
    if section_name == "业务/公共卫生解释":
        normalized = [_polish_business_line(line) for line in normalized]
    normalized = list(dict.fromkeys(normalized))
    return normalized[:limit] if limit is not None else normalized


def _contains_template_leak(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in FORMAL_REPORT_TEMPLATE_LEAK_PHRASES)


def _line_is_formal_report_ready(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("Loaded ", "Detected ", "Review ", "Consider ", "Experiment decision status:", "DID estimate:", "did ", "Top permutation-importance")):
        return False
    if _contains_template_leak(stripped):
        return False
    chinese_chars = sum(1 for char in stripped if "\u4e00" <= char <= "\u9fff")
    ascii_letters = sum(1 for char in stripped if char.isascii() and char.isalpha())
    if chinese_chars == 0 and ascii_letters >= 6:
        return False
    if ascii_letters >= 18 and chinese_chars < 6:
        return False
    return True


def _chart_count(context: dict[str, Any]) -> int:
    return len(context.get("png_files", []))


def _cleaning_shape(context: dict[str, Any]) -> tuple[Any, Any]:
    cleaning = context.get("cleaning_report") or {}
    shape = cleaning.get("shape", {})
    return shape.get("rows", "N/A"), shape.get("columns", "N/A")


def _experiment_primary_metric(context: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    experiment = context.get("experiment_report") or {}
    metrics = experiment.get("metrics") or {}
    for name, details in metrics.items():
        if isinstance(details, dict) and details.get("role") == "primary":
            return str(name), details
    if metrics:
        name = next(iter(metrics))
        details = metrics[name]
        if isinstance(details, dict):
            return str(name), details
    return None, {}


def _causal_estimate_snapshot(context: dict[str, Any]) -> tuple[str | None, Any, Any]:
    report = context.get("causal_report") or {}
    for field, label in CAUSAL_ESTIMATE_LABELS.items():
        if report.get(field) is not None:
            p_value = None
            regression = report.get("regression") or {}
            if isinstance(regression, dict) and regression.get("available") and regression.get("p_value") is not None:
                p_value = regression.get("p_value")
            return label, report.get(field), p_value
    return None, None, None


def _normalize_section_lines(lines: list[str]) -> list[str]:
    normalized: list[str] = []
    pending_prefix: str | None = None
    for raw_line in lines:
        line = _normalize_report_text(raw_line)
        if not line:
            continue
        if line.endswith("："):
            pending_prefix = line
            continue
        if pending_prefix and len(line) <= 24 and not re.search(r"[。！？；]$", line):
            normalized.append(f"{pending_prefix}{line}")
            continue
        pending_prefix = None
        normalized.append(line)
    return normalized


def _polish_business_line(line: str) -> str:
    if "最值得优先分层的人群是：" in line:
        return re.sub(r"^.*最值得优先分层的人群是：", "优先分层对象：", line)
    if line.startswith("对业务侧来说，这意味着"):
        return line.replace("对业务侧来说，这意味着", "业务含义：")
    if "最清晰的信号不是" in line:
        return line.replace("这份样本里最清晰的信号不是", "优先关注的风险组合不是")
    return line


def _positive_rate(context: dict[str, Any]) -> float | None:
    stats_report = context.get("stats_report") or {}
    target_summary = (stats_report.get("summary_statistics") or {}).get("obese")
    if target_summary and "mean" in target_summary:
        return float(target_summary["mean"])
    return None


def _executive_conclusion(context: dict[str, Any]) -> str:
    task = context.get("task")
    best_model, metrics = _best_model_metrics(context)
    positive_rate = _positive_rate(context)
    top_dimensions = _top_explainability_dimensions(context, limit=3)
    target_label = _friendly_target_label("obese" if task == "classification" else None)
    if task == "classification" and best_model and metrics:
        f1_value = float(metrics.get("test_f1_weighted", 0.0))
        capability = "中等区分能力" if f1_value >= 0.65 else "初步区分能力"
        feature_text = "、".join(top_dimensions) if top_dimensions else "关键健康行为变量"
        rate_text = _pct(positive_rate) if positive_rate is not None else "N/A"
        return (
            f"本次基于调查样本对{target_label}进行了分类建模，样本中的目标发生率约为 {rate_text}。"
            f"模型已具备{capability}，更适合用于高风险人群分层和干预优先级排序，"
            f"不适合作单次个体级最终判断。当前最稳定的风险信号主要集中在 {feature_text}。"
        )
    if task in {"cluster", "clustering"}:
        analysis = context.get("analysis_report") or {}
        n_clusters = analysis.get("n_clusters", "N/A")
        score = None
        for item in analysis.get("candidate_scores", []):
            if int(item.get("n_clusters", -1)) == int(n_clusters):
                score = item.get("silhouette_score")
                break
        return (
            f"本次聚类分析将样本划分为 {n_clusters} 个主要群组，"
            f"轮廓系数约为 {_fmt(score)}。这说明数据中存在可解释的分层结构，"
            "适合用于对象画像和分群运营，但不应直接当作因果结论。"
        )
    if task == "regression" and best_model and metrics:
        r2_value = metrics.get("test_r2")
        rmse_value = metrics.get("test_neg_root_mean_squared_error")
        rmse_text = _fmt(abs(rmse_value)) if rmse_value is not None else "N/A"
        return (
            f"本次对连续型目标进行了回归建模，当前最佳模型为 {_friendly_model_name(best_model)}。"
            f"模型的 R2 约为 {_fmt(r2_value)}，说明已能解释部分波动；RMSE 约为 {rmse_text}，"
            "更适合作为趋势判断和排序工具，而不是完全替代业务口径。"
        )
    if task in {"experiment", "ab-test"}:
        experiment = context.get("experiment_report") or {}
        decision = experiment.get("decision") or {}
        metric_name, metric_details = _experiment_primary_metric(context)
        lift = metric_details.get("relative_lift")
        lift_text = _pct(lift) if lift is not None else "N/A"
        status = EXPERIMENT_STATUS_LABELS.get(decision.get("status"), decision.get("summary") or "实验结论待结合原始指标复核。")
        if metric_name:
            return (
                f"本次实验的总体判断为“{status}”。"
                f"主指标 {metric_name} 的相对提升约为 {lift_text}，"
                "但是否值得上线仍需结合统计显著性、护栏指标和样本分配是否稳定一起看。"
            )
        return f"本次实验的总体判断为“{status}”，建议结合主指标 lift、p_value 和护栏指标一起复核。"
    if task in {"did", "rd", "synthetic-control", "iv", "dml", "dr", "psm", "orthogonal", "uplift", "cate", "causal"}:
        causal_narrative = context.get("causal_narrative_report") or {}
        if causal_narrative.get("headline"):
            return _normalize_report_text(causal_narrative["headline"])
        estimate_label, estimate_value, p_value = _causal_estimate_snapshot(context)
        if estimate_label:
            p_text = f"，对应 p_value 约为 {_fmt(p_value)}" if p_value is not None else ""
            return (
                f"本次采用 {_friendly_task_label(task)} 来评估处理效应，"
                f"核心结果 {estimate_label} 约为 {_fmt(estimate_value)}{p_text}。"
                "该结果可作为决策参考，但前提仍是识别假设成立。"
            )
    rows, cols = _cleaning_shape(context)
    return (
        f"本次报告基于 {rows} 行、{cols} 列数据的标准化产物整理而成，"
        f"当前任务类型为 {_friendly_task_label(task)}，共纳入 {_chart_count(context)} 张图表用于辅助解读。"
    )


def _method_summary(context: dict[str, Any]) -> str:
    task = context.get("task")
    cleaning = context.get("cleaning_report") or {}
    model_report = context.get("model_report") or {}
    explainability = context.get("explainability_report") or {}
    analysis = context.get("analysis_report") or {}
    row_count = cleaning.get("shape", {}).get("rows", "N/A")

    if task == "classification":
        model_count = len(model_report.get("models", {}))
        if model_count == 0:
            return (
                f"本次采用 {_friendly_task_label(task)} 的预建模流程。"
                f"已完成 {row_count} 条样本的数据质量检查、统计分析、特征规划和基础图表产出，"
                "当前尚未进入模型训练。"
            )
        explain_model = _friendly_model_name(explainability.get("model_name"))
        return (
            f"本次采用 {_friendly_task_label(task)}。首先对 {row_count} 条样本做数据质量检查，"
            f"随后对 {model_count} 个基线分类模型进行 5 折交叉验证比较，"
            f"再使用 {explain_model} 生成特征重要性、PDP 和 SHAP 解释结果。"
        )
    if task in {"cluster", "clustering"}:
        return (
            f"本次采用 {_friendly_task_label(task)}，先对数值变量做标准化处理，再尝试多个聚类数，"
            f"最后用轮廓系数自动选择最优分群方案。当前选出的聚类数为 {analysis.get('n_clusters', 'N/A')}。"
        )
    if task == "regression":
        model_count = len(model_report.get("models", {}))
        if model_count == 0:
            return (
                f"本次采用 {_friendly_task_label(task)} 的预建模流程。"
                f"已完成 {row_count} 条样本的数据质量检查、统计分析、特征规划和基础图表产出，"
                "当前尚未进入模型训练。"
            )
        return (
            f"本次采用 {_friendly_task_label(task)}。首先对 {row_count} 条样本做数据质量检查和特征规划，"
            f"随后比较 {model_count} 个基线回归模型，并使用 R2、RMSE、MAE 等指标评估预测误差与解释力。"
        )
    if task in {"experiment", "ab-test"}:
        experiment = context.get("experiment_report") or {}
        metric_names = list((experiment.get("metrics") or {}).keys())[:3]
        return (
            f"本次采用 {_friendly_task_label(task)}，围绕分组字段 {experiment.get('group_col', 'N/A')} "
            f"比较实验组和对照组在 {', '.join(metric_names) if metric_names else '目标指标'} 上的差异，"
            f"并同时检查样本比例是否异常和护栏指标是否回退。"
        )
    if task in {"did", "rd", "synthetic-control", "iv", "dml", "dr", "psm", "orthogonal", "uplift", "cate", "causal"}:
        return (
            f"本次采用 {_friendly_task_label(task)}，先根据任务类型生成因果估计结果，"
            "再结合识别假设、稳健性诊断和叙事化说明整理成正式报告。"
        )
    if task == "descriptive":
        numeric_count = len(cleaning.get("roles", {}).get("numeric", []))
        return (
            f"本次采用 {_friendly_task_label(task)}，先对 {row_count} 条样本做缺失、重复和分布检查，"
            f"再对 {numeric_count} 个数值字段输出描述统计和相关关系，并生成基础图表用于管理层阅读。"
        )
    return f"本次采用 {_friendly_task_label(task)}，并基于 run 目录中的标准化产物进行结果整理。"


def _source_and_scope_rows(context: dict[str, Any]) -> list[list[str]]:
    read_plan = context.get("read_plan") or {}
    cleaning = context.get("cleaning_report") or {}
    source_lines = _section_lines(context, "数据来源", limit=2)
    source_name = _summarize_source_name(source_lines[0]) if source_lines else "本地 run 目录中的结构化数据"
    selected_member = read_plan.get("member_name")
    return [
        ["字段", "内容"],
        ["数据来源", source_name],
        ["输入文件", _plain_file_name(read_plan.get("path"))],
        ["容器内成员", selected_member or "N/A"],
        ["实际分析行数", str(cleaning.get("shape", {}).get("rows", "N/A"))],
        ["实际分析列数", str(cleaning.get("shape", {}).get("columns", "N/A"))],
        ["报告日期", str(date.today())],
    ]


def _data_quality_rows(context: dict[str, Any]) -> list[list[str]]:
    cleaning = context.get("cleaning_report") or {}
    return [
        ["指标", "当前值", "怎么理解"],
        ["缺失列数", str(cleaning.get("missing_values", {}).get("columns_with_missing_values", "N/A")), "越少越好，但也要确认是否上游已提前过滤。"],
        ["缺失单元格", str(cleaning.get("missing_values", {}).get("total_missing_cells", "N/A")), "用于判断数据完整性。"],
        ["重复率", _pct(cleaning.get("duplicates", {}).get("duplicate_ratio", 0.0)), "越低越好，但要结合业务是否允许重复记录。"],
        ["IQR 异常值提示", str(len(cleaning.get("outliers_iqr", {}))), "表示有多少数值列在统计意义上出现极端值提示。"],
        ["Isolation Forest", _pct((cleaning.get("outliers_isolation_forest", {}) or {}).get("outlier_ratio")), "反映多变量层面的异常样本占比。"],
    ]


def _metric_commentary(context: dict[str, Any]) -> list[list[str]]:
    rows = [["指标", "当前值", "含义", "本次判断", "为什么这样判断"]]
    best_model, metrics = _best_model_metrics(context)
    positive_rate = _positive_rate(context)
    task = context.get("task")
    analysis = context.get("analysis_report") or {}
    if task in {"classification", "regression"} and not best_model and not metrics:
        rows.append(
            [
                "当前阶段",
                "预建模检查",
                "表示本次运行停留在数据准备与图表复核阶段，尚未训练模型。",
                "需确认是否继续",
                "如果用户确认继续，再进入模型训练与评估；如果不继续，本报告可作为阶段性复核版本。",
            ]
        )
        return rows
    if best_model:
        rows.append(
            [
                "最佳模型",
                _friendly_model_name(best_model),
                "本次基线比较中相对表现最好的模型。",
                "用于当前正式报告",
                "当前任务用加权 F1 作为主要排序依据，更能反映类别不平衡下的实际识别质量。",
            ]
        )
    for key, value in metrics.items():
        metric_key = key.replace("test_", "")
        meta = METRIC_META.get(metric_key)
        if not meta:
            continue
        display_value = abs(value) if metric_key in {"neg_root_mean_squared_error", "neg_mean_absolute_error"} else value
        why = meta["reading"]
        if metric_key == "accuracy" and positive_rate is not None:
            majority_baseline = max(positive_rate, 1 - positive_rate)
            why = f"当前正类占比约 {_pct(positive_rate)}，多数类基线约 {_pct(majority_baseline)}，因此不能只看 Accuracy。"
        elif metric_key == "f1_weighted":
            why = "当前更看重 F1，是因为它能同时反映精确率和召回率，比单看 Accuracy 更适合本类风险分层任务。"
        elif metric_key == "precision_weighted":
            why = "这个值越高，代表误报相对更少；但仍要和召回率一起看，避免只会保守预测。"
        elif metric_key == "recall_weighted":
            why = "这个值越高，代表漏报相对更少；若业务更怕漏掉高风险人群，应优先关注它。"
        rows.append(
            [
                meta["label"],
                _fmt(display_value),
                meta["meaning"],
                _metric_judgment(metric_key, display_value),
                why,
            ]
        )
    if not best_model and task in {"cluster", "clustering"}:
        cluster_size_summary = _cluster_size_summary(context)
        n_clusters = analysis.get("n_clusters")
        if n_clusters is not None:
            rows.append(
                [
                    "分群数量",
                    str(n_clusters),
                    "聚类算法最终保留的群组数。",
                    "需结合样本异质性判断",
                    "群组数过少会丢失差异，过多会让每组样本过碎，通常要和轮廓系数一起看。",
                ]
            )
        silhouette = analysis.get("silhouette_score")
        if silhouette is not None:
            rows.append(
                [
                    "Silhouette",
                    _fmt(silhouette),
                    METRIC_META["silhouette_score"]["meaning"],
                    _metric_judgment("silhouette_score", silhouette),
                    "这是聚类任务里最直接的结构清晰度指标，越高代表组内更像、组间更分离。",
                ]
            )
        largest_share = cluster_size_summary.get("largest_share")
        if largest_share is not None:
            rows.append(
                [
                    "最大群占比",
                    _pct(largest_share),
                    "样本最多的群组占总样本的比例。",
                    "过高需谨慎",
                    "如果最大群过大，说明分群可能仍偏粗，很多国家被压进同一类。",
                ]
            )
        smallest_share = cluster_size_summary.get("smallest_share")
        if smallest_share is not None:
            rows.append(
                [
                    "最小群占比",
                    _pct(smallest_share),
                    "样本最少的群组占总样本的比例。",
                    "过小需谨慎" if float(smallest_share) < 0.03 else "可解释",
                    "极小群组往往更像特殊样本簇或离群组合，适合画像，不适合直接外推成普遍规律。",
                ]
            )
    if task in {"experiment", "ab-test"}:
        experiment = context.get("experiment_report") or {}
        decision = experiment.get("decision") or {}
        metric_name, metric_details = _experiment_primary_metric(context)
        rows.append(
            [
                "实验结论",
                EXPERIMENT_STATUS_LABELS.get(decision.get("status"), decision.get("status") or "N/A"),
                "对实验整体结果的摘要判断。",
                "需结合主指标与护栏指标",
                decision.get("summary") or "实验结论不应只看单一 lift，还要结合显著性与 SRM。",
            ]
        )
        srm = experiment.get("sample_ratio_mismatch") or {}
        if srm.get("p_value") is not None:
            rows.append(
                [
                    "SRM p_value",
                    _fmt(srm.get("p_value")),
                    "检验样本分流是否偏离预期分配。",
                    "越大越稳",
                    "如果该值很小，说明实验分流可能异常，后续 lift 结论需要谨慎。",
                ]
            )
        if metric_name:
            if metric_details.get("absolute_lift") is not None:
                rows.append(
                    [
                        f"{metric_name} 绝对提升",
                        _fmt(metric_details.get("absolute_lift")),
                        "实验组相对对照组的绝对差值。",
                        "方向需结合业务目标",
                        "若该指标期望上升，则正值更好；若期望下降，则需要反向理解。",
                    ]
                )
            if metric_details.get("relative_lift") is not None:
                rows.append(
                    [
                        f"{metric_name} 相对提升",
                        _pct(metric_details.get("relative_lift")),
                        "实验组相对对照组的比例变化。",
                        "绝对值越大越显著",
                        "应同时结合基线水平和统计显著性，避免只看百分比提升。",
                    ]
                )
            if metric_details.get("p_value") is not None:
                rows.append(
                    [
                        f"{metric_name} p_value",
                        _fmt(metric_details.get("p_value")),
                        METRIC_META["p_value"]["meaning"],
                        _metric_judgment("p_value", metric_details.get("p_value")),
                        "若同时满足 practical significance，结论会更稳。",
                    ]
                )
    if task in {"did", "rd", "synthetic-control", "iv", "dml", "dr", "psm", "orthogonal", "uplift", "cate", "causal"}:
        estimate_label, estimate_value, p_value = _causal_estimate_snapshot(context)
        if estimate_label:
            rows.append(
                [
                    estimate_label,
                    _fmt(estimate_value),
                    "当前因果方法给出的核心处理效应估计。",
                    "需结合假设判断",
                    "这个值本身不代表一定可执行，前提是识别假设和重叠/平行趋势等条件成立。",
                ]
            )
        if p_value is not None:
            rows.append(
                [
                    "p_value",
                    _fmt(p_value),
                    METRIC_META["p_value"]["meaning"],
                    _metric_judgment("p_value", p_value),
                    "显著并不等于可落地，仍需结合效应大小与识别质量。",
                ]
            )
    if task in {"descriptive", "time-series"} and not best_model:
        rows_count, cols_count = _cleaning_shape(context)
        rows.append(
            [
                "样本规模",
                f"{rows_count} x {cols_count}",
                "进入本次分析的行列规模。",
                "规模充足即可",
                "描述性分析更关注口径是否一致，而不只是样本是否足够大。",
            ]
        )
        rows.append(
            [
                "图表数量",
                str(_chart_count(context)),
                "本次报告纳入的可视化图表数量。",
                "与任务复杂度匹配即可",
                "图表过少可能不足以支撑沟通，过多则会分散读者注意力。",
            ]
        )
    return rows


def _model_result_section_title(context: dict[str, Any]) -> str:
    if context.get("task") in {"classification", "regression"}:
        return "五、模型设计与结果"
    return "五、关键指标与判断"


def _model_design_paragraph(context: dict[str, Any]) -> str:
    task = context.get("task")
    best_model, _ = _best_model_metrics(context)
    model_report = context.get("model_report") or {}
    model_count = len(model_report.get("models", {}))
    positive_rate = _positive_rate(context)
    if task == "classification":
        if not best_model:
            return (
                "本节原本用于说明分类模型如何设计与比较，但当前运行停留在预建模阶段，"
                "因此这里只保留后续计划与判断依据，尚未形成正式模型结果。"
            )
        rate_text = _pct(positive_rate) if positive_rate is not None else "N/A"
        return (
            f"为了回答“现有调查字段能否支持肥胖风险的初步分层识别”这一问题，"
            f"本次先在 5000 条样本上比较 {model_count} 个基线分类模型，"
            f"并把加权 F1 作为主要排序依据。这样做的目的是避免在目标发生率约为 {rate_text} "
            "的情况下被单一准确率误导，让模型设计更贴近真实筛查和分层场景。"
        )
    if task == "regression":
        if not best_model:
            return "当前运行停留在预建模阶段，因此这里只说明后续的回归评估思路，尚未形成正式模型结果。"
        return (
            "为了判断现有字段能否对连续目标形成稳定预测，本次先比较多个轻量基线回归模型，"
            "再结合 R2、RMSE 等指标判断解释力和误差水平，避免过早依赖复杂模型。"
        )
    return _method_summary(context)


def _model_result_readout_paragraph(context: dict[str, Any]) -> str:
    task = context.get("task")
    best_model, metrics = _best_model_metrics(context)
    positive_rate = _positive_rate(context)
    if task == "classification" and best_model and metrics:
        accuracy = metrics.get("test_accuracy")
        f1_value = metrics.get("test_f1_weighted")
        majority_baseline = max(positive_rate, 1 - positive_rate) if positive_rate is not None else None
        baseline_text = _pct(majority_baseline) if majority_baseline is not None else "N/A"
        return (
            f"从结果上看，当前最佳模型为 {_friendly_model_name(best_model)}。"
            f"表格中的 Accuracy 约为 {_fmt(accuracy)}，加权 F1 约为 {_fmt(f1_value)}，"
            f"同时多数类基线约为 {baseline_text}。这说明模型已经不只是机械地跟随多数类，"
            "而是在一定程度上学到了可用于区分风险高低的结构性信号。"
        )
    if task == "regression" and best_model and metrics:
        r2_value = metrics.get("test_r2")
        rmse_value = metrics.get("test_neg_root_mean_squared_error")
        rmse_text = _fmt(abs(rmse_value)) if rmse_value is not None else "N/A"
        return (
            f"从结果上看，当前最佳模型为 {_friendly_model_name(best_model)}。"
            f"表格中的 R2 约为 {_fmt(r2_value)}，RMSE 约为 {rmse_text}。"
            "这意味着模型已经具备一定解释力，但误差仍需放回业务量纲中理解。"
        )
    return "当前尚未形成可供正式引用的模型结果表，因此本节暂以说明性文字为主。"


def _model_usability_paragraph(context: dict[str, Any]) -> str:
    task = context.get("task")
    best_model, metrics = _best_model_metrics(context)
    if task == "classification" and best_model and metrics:
        f1_value = metrics.get("test_f1_weighted")
        recall_value = metrics.get("test_recall_weighted")
        judgment = _metric_judgment("f1_weighted", f1_value)
        recall_text = _fmt(recall_value)
        return (
            f"结合表格里的指标，这个模型目前更适合作为“可用但仍需继续打磨”的分层工具。"
            f"加权 F1 的判断为“{judgment}”，召回率约为 {recall_text}，"
            "说明它已经可以支持高风险人群排序和优先干预，但还不足以承担个体级最终判断或高代价决策。"
        )
    if task == "regression" and best_model and metrics:
        r2_value = metrics.get("test_r2")
        judgment = _metric_judgment("r2", r2_value)
        return (
            f"结合表格里的指标，这个模型当前属于“{judgment}”水平。"
            "它更适合做趋势判断、排序或资源分配参考，而不宜直接替代业务主口径。"
        )
    return "当前结果更适合作为阶段性复核依据，是否进入正式业务使用仍需结合后续验证结果决定。"


def _model_next_steps_paragraph(context: dict[str, Any]) -> str:
    recommendations = _recommendations(context)
    if context.get("task") in {"classification", "regression"} and recommendations:
        first = _normalize_report_text(recommendations[0]).rstrip("。")
        second = _normalize_report_text(recommendations[1]).rstrip("。") if len(recommendations) > 1 else ""
        if second:
            return f"下一步建议是：{first}；同时{second}。"
        return f"下一步建议是：{first}。"
    if recommendations:
        return "下一步建议是：" + "；".join(_normalize_report_text(item).rstrip("。") for item in recommendations[:2]) + "。"
    return "下一步应围绕模型可用性、稳定性和业务落地方式继续补充验证。"


def _key_findings(context: dict[str, Any]) -> list[str]:
    findings = [line for line in _section_lines(context, "关键发现", limit=6) if _line_is_formal_report_ready(line)][:4]
    if findings:
        return findings
    bullets: list[str] = []
    positive_rate = _positive_rate(context)
    if positive_rate is not None:
        bullets.append(f"样本中的目标发生率约为 {_pct(positive_rate)}。")
    features = _top_explainability_features(context, limit=3)
    if features:
        bullets.append(f"模型最依赖的变量主要包括：{'、'.join(features)}。")
    best_model, metrics = _best_model_metrics(context)
    if best_model and metrics:
        primary_metric = "test_f1_weighted" if context.get("task") == "classification" else "test_r2"
        if primary_metric in metrics:
            bullets.append(f"最佳模型为 {_friendly_model_name(best_model)}，核心评分约为 {_fmt(metrics[primary_metric])}。")
    task = context.get("task")
    if task == "regression" and best_model and metrics:
        if metrics.get("test_neg_root_mean_squared_error") is not None:
            bullets.append(f"回归任务的 RMSE 约为 {_fmt(abs(metrics['test_neg_root_mean_squared_error']))}，说明预测误差仍需结合业务量纲理解。")
    if task in {"experiment", "ab-test"}:
        experiment = context.get("experiment_report") or {}
        decision = experiment.get("decision") or {}
        metric_name, metric_details = _experiment_primary_metric(context)
        status = EXPERIMENT_STATUS_LABELS.get(decision.get("status"), "需要结合原始实验结果复核")
        bullets.append(f"实验总体判断为“{status}”。")
        if metric_name and metric_details.get("relative_lift") is not None:
            bullets.append(f"主指标 {metric_name} 的相对提升约为 {_pct(metric_details['relative_lift'])}。")
    if task in {"did", "rd", "synthetic-control", "iv", "dml", "dr", "psm", "orthogonal", "uplift", "cate", "causal"}:
        estimate_label, estimate_value, p_value = _causal_estimate_snapshot(context)
        if estimate_label:
            bullets.append(f"{estimate_label} 约为 {_fmt(estimate_value)}。")
        if p_value is not None:
            bullets.append(f"对应 p_value 约为 {_fmt(p_value)}，仍需结合识别假设判断可解释性。")
    if task in {"descriptive", "time-series"}:
        rows_count, cols_count = _cleaning_shape(context)
        bullets.append(f"本次描述性结果覆盖 {rows_count} 行、{cols_count} 列数据。")
        bullets.append(f"报告共纳入 {_chart_count(context)} 张图表辅助阅读。")
    return bullets


def _recommendations(context: dict[str, Any]) -> list[str]:
    business = [line for line in _section_lines(context, "业务/公共卫生解释", limit=8) if _line_is_formal_report_ready(line)]
    recommendations: list[str] = []
    for polished in business:
        if polished.startswith("业务含义："):
            polished = polished.replace("业务含义：", "建议动作：")
        if len(polished) > 8:
            recommendations.append(polished)
    if recommendations:
        return recommendations[:4]
    best_model, metrics = _best_model_metrics(context)
    if context.get("task") in {"classification", "regression"} and not best_model and not metrics:
        return [
            "若要继续，请先确认样本/全量口径、抽样策略以及预计耗时，再进入模型训练阶段。",
            "若暂不继续，当前报告可作为预建模复核版本，重点用于确认数据质量、目标分布和后续模型选择方向。",
            "建议在下一轮继续时优先比较轻量基线模型，再按结果决定是否上更重模型。",
        ]
    if context.get("task") == "classification":
        return [
            "将模型优先用于高风险人群分层和干预优先级排序，而不是直接用于个体级最终判定。",
            "围绕最稳定的风险信号设计后续运营动作，例如慢病管理、健康行为干预和高风险人群随访。",
            "下一轮应结合更细粒度样本和业务标签，评估召回率是否满足实际筛查要求。",
        ]
    if context.get("task") == "regression":
        return [
            "将回归结果优先用于排序、配额分配和趋势判断，不要直接把单点预测当成确定值。",
            "围绕误差较大的样本区间补充字段，优先提升模型对极端值或关键分段的解释能力。",
            "上线前先与业务基线或人工规则做并行对比，确认增量价值。",
        ]
    if context.get("task") in {"experiment", "ab-test"}:
        return [
            "若主指标和护栏指标同时通过，再考虑放量或全量上线，不要只凭 lift 做决策。",
            "保留实验日志与分流配置，便于复核 SRM、显著性和分群差异。",
            "若结果边界显著，优先补样本或延长实验周期，而不是过早下结论。",
        ]
    if context.get("task") in {"did", "rd", "synthetic-control", "iv", "dml", "dr", "psm", "orthogonal", "uplift", "cate", "causal"}:
        return [
            "先复核平行趋势、重叠性、工具变量强度等识别前提，再将处理效应用于业务动作。",
            "把因果估计和业务可执行性拆开看，显著结果仍需要结合实施成本与风险。",
            "如需正式决策，建议补做稳健性分析或替代识别方法交叉验证。",
        ]
    if context.get("task") in {"descriptive", "time-series"}:
        return [
            "将当前描述性结果作为范围收敛工具，先锁定最值得深入分析的指标、分群或时间窗口。",
            "对差异最大的维度继续补充业务口径与事件背景，避免把表面相关误读为因果。",
            "若需要下一步预测或实验，先根据这轮描述性结果定义清晰目标变量与评价标准。",
        ]
    return ["建议结合业务场景补充更细维度数据，再做下一轮深入分析。"]


def _risk_items(context: dict[str, Any]) -> list[str]:
    risks = [line for line in _section_lines(context, "风险与限制", limit=None) if _line_is_formal_report_ready(line)]
    cluster_size_summary = _cluster_size_summary(context)
    smallest_share = cluster_size_summary.get("smallest_share")
    if smallest_share is not None and float(smallest_share) < 0.03:
        risks.append("当前分群中存在极小群组，说明一部分结果更接近特殊国家组合，解读时应避免直接泛化。")
    experiment = context.get("experiment_report") or {}
    if (experiment.get("sample_ratio_mismatch") or {}).get("is_mismatch"):
        risks.append("样本比例失衡（SRM）提示实验分流可能异常，因此结果存在失真风险。")
    runtime = (context.get("environment") or {}).get("runtime") or {}
    for warning in runtime.get("warnings", []) or []:
        if "PDF 文本级质检能力有限" in warning:
            risks.append("当前环境对 PDF 只能做有限质检，最终分发前建议人工抽检页面内容。")
            break
    if risks:
        deduped = list(dict.fromkeys(risks))
        return deduped[:4]
    read_plan = context.get("read_plan") or {}
    return list(read_plan.get("warnings", []))[:3] or ["当前报告基于现有 run 目录中的产物整理而成，应结合原始数据口径复核。"]


def _artifact_index(context: dict[str, Any]) -> list[list[str]]:
    rows = [["文件", "类型", "建议用途"]]
    for path in context.get("json_files", []):
        rows.append([path.name, "JSON", "作为机器可读主结果，适合复核和二次解释。"])
    for path in context.get("markdown_files", []):
        rows.append([path.name, "Markdown", "作为文字摘要、叙事说明或辅助说明。"])
    for path in context.get("png_files", []):
        rows.append([path.name, "PNG", "作为图表证据，应结合对应 JSON 一起阅读。"])
    return rows


def _chart_plan_file_meta(context: dict[str, Any]) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    chart_plan = context.get("chart_plan") or {}
    charts = chart_plan.get("charts") or []
    order: dict[str, int] = {}
    meta: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(charts):
        if not isinstance(item, dict):
            continue
        file_name = item.get("file")
        if not file_name:
            continue
        order[str(file_name)] = index
        meta[str(file_name)] = item
    return order, meta


def _cluster_size_summary(context: dict[str, Any]) -> dict[str, float | int | None]:
    analysis = context.get("analysis_report") or {}
    cluster_sizes = analysis.get("cluster_sizes") or []
    if not cluster_sizes:
        return {"cluster_count": None, "total_rows": None, "largest_share": None, "smallest_share": None}
    counts = [max(int(item.get("country_count", 0)), 0) for item in cluster_sizes]
    total_rows = sum(counts)
    if total_rows <= 0:
        return {"cluster_count": len(counts), "total_rows": 0, "largest_share": None, "smallest_share": None}
    return {
        "cluster_count": len(counts),
        "total_rows": total_rows,
        "largest_share": max(counts) / total_rows,
        "smallest_share": min(counts) / total_rows,
    }


def _chart_candidate_rows(context: dict[str, Any]) -> list[dict[str, Any]]:
    payload = context.get("chart_candidates") or {}
    rows = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


def _report_audience(context: dict[str, Any], decision: dict[str, Any] | None = None) -> str:
    if isinstance(decision, dict) and decision.get("report_audience"):
        return str(decision["report_audience"])
    chart_candidates = context.get("chart_candidates") or {}
    if isinstance(chart_candidates, dict) and chart_candidates.get("report_audience"):
        return str(chart_candidates["report_audience"])
    return "management"


def _candidate_lookup_maps(context: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_file: dict[str, dict[str, Any]] = {}
    for item in _chart_candidate_rows(context):
        chart_id = item.get("chart_id")
        file_name = item.get("file")
        if chart_id:
            by_id[str(chart_id)] = item
        if file_name:
            by_file[str(file_name)] = item
    return by_id, by_file


def _candidate_path(context: dict[str, Any], file_name: str | None) -> Path | None:
    if not file_name:
        return None
    for path in context.get("png_files", []):
        if path.name == file_name:
            return path
    return None


def _candidate_title(candidate: dict[str, Any], plan_meta: dict[str, Any] | None = None) -> str:
    return str(
        candidate.get("title")
        or (plan_meta or {}).get("title")
        or candidate.get("file")
        or candidate.get("chart_type")
        or "图表"
    )


def _candidate_to_chart_block(context: dict[str, Any], candidate: dict[str, Any], *, index: int | None = None) -> dict[str, Any] | None:
    file_name = str(candidate.get("file") or "")
    path = _candidate_path(context, file_name)
    if path is None:
        return None
    _, custom_meta = _chart_plan_file_meta(context)
    plan_meta = custom_meta.get(file_name, {})
    meta = IMAGE_EXPLANATIONS.get(file_name, {})
    return {
        "index": index,
        "path": path,
        "chart_id": candidate.get("chart_id"),
        "file": file_name,
        "title": _candidate_title(candidate, plan_meta),
        "chart_type": candidate.get("chart_type") or plan_meta.get("chart") or meta.get("chart") or "chart",
        "chart_intent": candidate.get("chart_intent") or candidate.get("section_role"),
        "section_role": candidate.get("section_role"),
        "source_fields": candidate.get("source_fields") or [],
        "source_field_labels": candidate.get("source_field_labels") or [],
        "audience_fit": candidate.get("audience_fit") or {},
        "diagnostic_only": bool(candidate.get("diagnostic_only")),
        "allow_in_formal_body": bool(candidate.get("allow_in_formal_body")),
        "selection_rationale": _normalize_report_text(candidate.get("selection_rationale") or ""),
        "how_to_read": candidate.get("how_to_read") or plan_meta.get("how_to_read") or meta.get("how_to_read") or "先看整体结构，再结合对应 JSON 指标理解。",
        "meaning": candidate.get("meaning") or plan_meta.get("meaning") or plan_meta.get("reason") or meta.get("meaning") or "这张图用于补充展示本次分析结果。",
    }


def _role_priority_for_audience(audience: str) -> dict[str, int]:
    if audience == "operator":
        return {"decision_support": 0, "core_evidence": 1, "context": 2, "risk_boundary": 3, "mechanism": 4, "diagnostic": 5}
    if audience == "analyst":
        return {"core_evidence": 0, "mechanism": 1, "context": 2, "risk_boundary": 3, "decision_support": 4, "diagnostic": 5}
    return {"core_evidence": 0, "decision_support": 1, "context": 2, "risk_boundary": 3, "mechanism": 4, "diagnostic": 5}


def _eligible_body_candidate_rows(context: dict[str, Any], audience: str | None = None) -> list[dict[str, Any]]:
    chosen_audience = audience or _report_audience(context)
    priorities = _role_priority_for_audience(chosen_audience)
    eligible: list[dict[str, Any]] = []
    for item in _chart_candidate_rows(context):
        file_name = item.get("file")
        if not file_name or _candidate_path(context, str(file_name)) is None:
            continue
        if not bool(item.get("rendered", True)):
            continue
        if bool(item.get("diagnostic_only")):
            continue
        if not bool(item.get("allow_in_formal_body")):
            continue
        audience_fit = item.get("audience_fit") or {}
        if audience_fit.get(chosen_audience) == "low":
            continue
        eligible.append(item)
    eligible.sort(
        key=lambda item: (
            priorities.get(str(item.get("section_role") or item.get("chart_intent") or "diagnostic"), 9),
            -int(item.get("suitability_score") or 0),
            -int(item.get("business_value_score") or 0),
            str(item.get("chart_id") or ""),
        )
    )
    selected: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    seen_field_roles: set[tuple[tuple[str, ...], str]] = set()
    for item in eligible:
        file_name = str(item.get("file") or "")
        if not file_name or file_name in seen_files:
            continue
        source_fields = tuple(str(field) for field in (item.get("source_fields") or []) if field)
        section_role = str(item.get("section_role") or item.get("chart_intent") or "")
        key = (source_fields, section_role)
        if source_fields and key in seen_field_roles:
            continue
        selected.append(item)
        seen_files.add(file_name)
        if source_fields:
            seen_field_roles.add(key)
        if len(selected) >= MAX_FORMAL_REPORT_CHARTS:
            break
    return selected


def _legacy_chart_blocks(context: dict[str, Any]) -> list[dict[str, Any]]:
    order = {name: index for index, name in enumerate(IMAGE_ORDER)}
    custom_order, custom_meta = _chart_plan_file_meta(context)
    paths = sorted(
        context.get("png_files", []),
        key=lambda path: (custom_order.get(path.name, 1000), order.get(path.name, 1000), path.name),
    )
    blocks: list[dict[str, Any]] = []
    for path in paths:
        plan_meta = custom_meta.get(path.name, {})
        meta = IMAGE_EXPLANATIONS.get(path.name, {})
        title = plan_meta.get("title") or meta.get("title") or path.stem.replace("_", " ")
        how_to_read = plan_meta.get("how_to_read") or meta.get("how_to_read") or "先看整体结构，再结合对应 JSON 指标理解。"
        meaning = plan_meta.get("meaning") or plan_meta.get("reason") or meta.get("meaning") or "这张图用于补充展示本次分析结果。"
        blocks.append(
            {
                "path": path,
                "title": title,
                "chart_type": plan_meta.get("chart") or meta.get("chart") or "chart",
                "chart_id": None,
                "how_to_read": how_to_read,
                "meaning": meaning,
                "diagnostic_only": False,
                "allow_in_formal_body": True,
                "selection_rationale": "",
            }
        )
    return blocks


def _candidate_default_blocks(context: dict[str, Any], audience: str | None = None) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for index, item in enumerate(_eligible_body_candidate_rows(context, audience=audience), start=1):
        block = _candidate_to_chart_block(context, item, index=index)
        if block is not None:
            blocks.append(block)
    return blocks


def _chart_blocks(context: dict[str, Any], decision: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if isinstance(decision, dict):
        selected = decision.get("selected_charts")
        if isinstance(selected, list) and selected:
            blocks: list[dict[str, Any]] = []
            for index, item in enumerate(selected, start=1):
                if not isinstance(item, dict):
                    continue
                block = _candidate_to_chart_block(context, item, index=index)
                if block is None and item.get("file"):
                    block = _candidate_to_chart_block(context, {"file": item.get("file"), "title": item.get("title")}, index=index)
                if block is None:
                    continue
                if item.get("title"):
                    block["title"] = str(item["title"])
                block["selection_rationale"] = _normalize_report_text(item.get("selection_rationale") or "")
                blocks.append(block)
            if blocks:
                return blocks
    candidate_blocks = _candidate_default_blocks(context)
    if candidate_blocks:
        return candidate_blocks
    if _chart_candidate_rows(context):
        return []
    return _legacy_chart_blocks(context)


def _ensure_sentence(text: str | None) -> str:
    cleaned = _normalize_report_text(text)
    if not cleaned:
        return ""
    if cleaned.endswith(("。", "！", "？")):
        return cleaned
    return f"{cleaned}。"


def _chart_kind_label(chart_type: str | None) -> str:
    if not chart_type:
        return "图表"
    return CHART_KIND_LABELS.get(chart_type, "图表")


def _technical_chart_note_hint(block: dict[str, Any]) -> str:
    haystack = " ".join(
        [
            str(block.get("title", "")),
            str(block.get("how_to_read", "")),
            str(block.get("meaning", "")),
            str(block.get("path", "")),
        ]
    ).lower()
    matches = [label for term, label in TECHNICAL_TERM_LABELS.items() if term.lower() in haystack]
    deduped = list(dict.fromkeys(matches))
    if not deduped:
        return ""
    if len(deduped) == 1:
        return deduped[0]
    return "；".join(deduped[:3])


def _pending_chart_review(chart_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "draft",
        "source": "awaiting-agent-second-pass",
        "overall_summary": "",
        "charts": [
            {
                "index": index + 1,
                "file": block["path"].name,
                "title": block["title"],
                "interpretation": "",
                "implication": "",
                "caption_note": "",
            }
            for index, block in enumerate(chart_blocks)
        ],
    }


def _pending_report_chart_decision(context: dict[str, Any], chart_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    audience = _report_audience(context)
    _, candidate_by_file = _candidate_lookup_maps(context)
    selected_rows: list[dict[str, Any]] = []
    for index, block in enumerate(chart_blocks, start=1):
        candidate = candidate_by_file.get(block["path"].name, {})
        selected_rows.append(
            {
                "index": index,
                "chart_id": candidate.get("chart_id"),
                "file": block["path"].name,
                "title": block["title"],
                "section_role": candidate.get("section_role") or block.get("section_role"),
                "source_fields": candidate.get("source_fields") or block.get("source_fields") or [],
                "selection_rationale": "",
                "interpretation": "",
                "implication": "",
                "caption_note": "",
            }
        )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "draft",
        "source": "awaiting-agent-chart-selection",
        "report_audience": audience,
        "selected_charts": selected_rows,
        "overall_summary": "",
    }


def _build_formal_report_draft_markdown(context: dict[str, Any], title: str, chart_blocks: list[dict[str, Any]]) -> str:
    lines = [
        f"# {title}",
        "",
        "> 报告状态：草稿版，正文图选择与图表解读区均需 agent 结合 report_context.json、report_chart_decision.pending.json 与 PNG 做二次回写后再定稿。",
        "",
        "## 执行摘要",
        _executive_conclusion(context),
        "",
        "## 关键发现",
    ]
    lines.extend([f"- {item}" for item in _key_findings(context)])
    lines.extend(
        [
            "",
            "## 分析背景与方法",
            _method_summary(context),
            "",
            "## 业务解释",
        ]
    )
    lines.extend([f"- {item}" for item in _plain_section_rows(context, "业务/公共卫生解释", limit=6) or _recommendations(context)])
    lines.extend(["", "## 风险提示"])
    lines.extend([f"- {item}" for item in _risk_items(context)])
    lines.extend(["", "## 正文图与回写清单"])
    for index, block in enumerate(chart_blocks, start=1):
        lines.extend(
            [
                f"### 图 {index}：{block.get('title', '图表')}",
                f"- 文件名：{block['path'].name}",
                f"- 图表类型：{_chart_kind_label(str(block.get('chart_type')))}",
                f"- 角色：{block.get('section_role') or block.get('chart_intent') or '未标注'}",
                f"- 回写要求：先确认它是否仍应留在正文，再重新阅读 PNG，写入 selection_rationale / interpretation / implication / caption_note。",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _report_context_payload(context: dict[str, Any], title: str, chart_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    audience = _report_audience(context)
    candidates = _chart_candidate_rows(context)
    chart_manifest: list[dict[str, Any]] = []
    for index, block in enumerate(chart_blocks, start=1):
        chart_manifest.append(
            {
                "index": index,
                "chart_id": block.get("chart_id"),
                "file": block["path"].name,
                "title": block["title"],
                "chart_type": _chart_kind_label(str(block.get("chart_type"))),
                "section_role": block.get("section_role") or block.get("chart_intent"),
                "source_fields": block.get("source_fields") or [],
                "caption_note_hint": _technical_chart_note_hint(block),
                "chart_plan_hint": block.get("meaning", ""),
                "selection_rationale_hint": block.get("selection_rationale") or "",
            }
        )
    candidate_manifest: list[dict[str, Any]] = []
    for item in candidates:
        file_name = str(item.get("file") or "")
        candidate_manifest.append(
            {
                "chart_id": item.get("chart_id"),
                "file": file_name,
                "title": item.get("title") or file_name or item.get("chart_type"),
                "chart_type": item.get("chart_type"),
                "section_role": item.get("section_role"),
                "source_fields": item.get("source_fields") or [],
                "source_field_labels": item.get("source_field_labels") or [],
                "audience_fit": item.get("audience_fit") or {},
                "diagnostic_only": bool(item.get("diagnostic_only")),
                "allow_in_formal_body": bool(item.get("allow_in_formal_body")),
                "rendered": bool(item.get("rendered", True)),
                "evidence_links": item.get("evidence_links") or [],
                "business_value_score": item.get("business_value_score"),
                "suitability_score": item.get("suitability_score"),
                "why_this_chart": item.get("meaning") or "",
            }
        )
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "report_title": title,
        "report_stage": "draft",
        "chart_review_status_hint": "awaiting-agent-second-pass",
        "report_audience": audience,
        "task": _friendly_task_label(context.get("task")),
        "executive_conclusion": _executive_conclusion(context),
        "key_findings": _key_findings(context),
        "recommendations": _recommendations(context),
        "risk_items": _risk_items(context),
        "method_summary": _method_summary(context),
        "analysis_scope": _plain_section_rows(context, "分析范围", limit=6),
        "model_lines": _plain_section_rows(context, "模型结果", limit=6),
        "explain_lines": _plain_section_rows(context, "可解释性结论", limit=6),
        "business_lines": _plain_section_rows(context, "业务/公共卫生解释", limit=6),
        "source_and_scope_rows": _source_and_scope_rows(context),
        "data_quality_rows": _data_quality_rows(context),
        "metric_commentary_rows": _metric_commentary(context),
        "chart_manifest": chart_manifest,
        "governed_chart_candidates": candidate_manifest,
        "chart_selection_rules": [
            "优先从 allow_in_formal_body=true 且 diagnostic_only=false 的候选图中选择正文图。",
            "management 受众优先核心证据、决策支撑和背景基线；operator 受众优先决策支撑；analyst 受众可保留少量机制解释图。",
            "不要把 audience_fit 对当前受众为 low 的图放进正文，除非有非常明确的补充说明且无更好替代。",
            "同一原始业务字段不要在正文里重复占位；如果已有更直接的核心证据图，就不要再放重复表达的诊断图。",
            "one-hot 派生特征图、diagnostic_only 图、allow_in_formal_body=false 图默认不能进入正文。",
        ],
        "chart_review_writing_rules": [
            "把每张图写成可直接贴入正式报告的两段中文，不要写成图表说明书或提示语。",
            "第一段直接说明图中当前出现了什么情况，尽量点出具体对象、方向、高低差异或数值背景。",
            "第二段说明这背后意味着什么，以及为什么值得管理层、业务方或研究读者关注。",
            "避免套话，例如“这张图围绕……展开”“帮助读者理解”“用于说明本次分析”等。",
            "不要写“怎么看”“本图结论”之类小标题，也不要复述文件名。",
            "如果图中有英文指标、缩写，或中文专业名词对基础读者有理解门槛，再补充注释；没有就留空字符串。",
            "不得把脚本默认说明、图表类型描述或文件名改写成正式结论；必须基于图片本身重新观察后写作。",
        ],
        "expected_report_chart_decision_schema": {
            "report_audience": audience,
            "selected_charts": [
                {
                    "chart_id": "<优先填写，来自 governed_chart_candidates>",
                    "file": "target_distribution.png",
                    "title": "目标分布图",
                    "selection_rationale": "<必填：为什么这张图适合当前受众并应该进入正文>",
                    "interpretation": "<选填：如果已完成二次读图，可直接回填正式解读；否则留空字符串>",
                    "implication": "<选填：解释这张图对决策或理解意味着什么；否则留空字符串>",
                    "caption_note": "<选填：如需解释英文指标/缩写/专业名词，写一句简短注释>",
                }
            ],
            "overall_summary": "<选填：如已完成正文图整体串联，可写一段总体解读；否则留空字符串>",
        },
        "expected_chart_review_schema": {
            "charts": [
                {
                    "file": "target_distribution.png",
                    "title": "目标分布图",
                    "interpretation": "<必填：直接写图中当前看到的情况，不要写成说明书>",
                    "implication": "<必填：写这张图意味着什么，以及为什么值得关注>",
                    "caption_note": "<选填：如需解释英文指标/缩写/专业名词，写一句简短注释；否则留空字符串>",
                }
            ],
            "overall_summary": "<必填：用一段正式报告口吻的中文，把所有关键图表串起来，说明整体情况和背后意义>",
        },
    }


def _load_chart_review(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else None


def _load_report_chart_decision(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else None


def _normalize_report_chart_decision(context: dict[str, Any], decision: dict[str, Any] | None) -> dict[str, Any]:
    default_blocks = _chart_blocks(context, decision=None)[:MAX_FORMAL_REPORT_CHARTS]
    if decision is None:
        return _pending_report_chart_decision(context, default_blocks)

    by_id, by_file = _candidate_lookup_maps(context)
    input_rows = decision.get("selected_charts")
    if not isinstance(input_rows, list):
        input_rows = decision.get("charts")
    if not isinstance(input_rows, list):
        raise ValueError("Invalid report chart decision JSON: selected_charts must be a list.")

    normalized_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, row in enumerate(input_rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"selected_charts[{index}] 不是对象。")
            continue
        candidate = None
        chart_id = row.get("chart_id")
        file_name = row.get("file")
        if chart_id:
            candidate = by_id.get(str(chart_id))
        if candidate is None and file_name:
            candidate = by_file.get(str(file_name))
        if candidate is None:
            if by_id or by_file:
                errors.append(f"selected_charts[{index}] 无法匹配 candidate：chart_id={chart_id!r}, file={file_name!r}。")
                continue
            if not file_name:
                errors.append(f"selected_charts[{index}] 缺少 file。")
                continue
            if _candidate_path(context, str(file_name)) is None:
                errors.append(f"selected_charts[{index}] 指定的 PNG 不存在：{file_name}。")
                continue
            candidate = {"file": file_name, "title": row.get("title"), "chart_type": row.get("chart_type")}
        if by_id or by_file:
            if bool(candidate.get("diagnostic_only")):
                errors.append(f"selected_charts[{index}] 不能把 diagnostic-only 图放入正文：{candidate.get('file')}.")
            if not bool(candidate.get("allow_in_formal_body")):
                errors.append(f"selected_charts[{index}] 不是允许进入正文的候选图：{candidate.get('file')}.")
            audience_fit = candidate.get("audience_fit") or {}
            audience = _report_audience(context, decision)
            if audience_fit.get(audience) == "low":
                errors.append(f"selected_charts[{index}] 对 {audience} 受众不适合：{candidate.get('file')}.")
        if _candidate_path(context, str(candidate.get("file") or file_name or "")) is None:
            errors.append(f"selected_charts[{index}] 对应的 PNG 不存在：{candidate.get('file') or file_name}.")
            continue
        normalized_rows.append(
            {
                "index": index,
                "chart_id": candidate.get("chart_id") or chart_id,
                "file": str(candidate.get("file") or file_name),
                "title": str(row.get("title") or candidate.get("title") or candidate.get("file") or "图表"),
                "chart_type": candidate.get("chart_type"),
                "section_role": candidate.get("section_role"),
                "source_fields": candidate.get("source_fields") or [],
                "source_field_labels": candidate.get("source_field_labels") or [],
                "selection_rationale": _ensure_sentence(row.get("selection_rationale")),
                "interpretation": _ensure_sentence(row.get("interpretation")),
                "implication": _ensure_sentence(row.get("implication")),
                "caption_note": _ensure_sentence(row.get("caption_note") or "").rstrip("。"),
                "diagnostic_only": bool(candidate.get("diagnostic_only")),
                "allow_in_formal_body": bool(candidate.get("allow_in_formal_body", True)),
                "audience_fit": candidate.get("audience_fit") or {},
            }
        )
    if errors:
        raise ValueError("Invalid report chart decision JSON: " + " | ".join(errors))

    overall_summary = _ensure_sentence(decision.get("overall_summary"))
    prose_complete = bool(normalized_rows) and all(
        len(_normalize_report_text(item.get("selection_rationale") or "")) >= 18
        and len(_normalize_report_text(item.get("interpretation") or "")) >= 28
        and len(_normalize_report_text(item.get("implication") or "")) >= 28
        for item in normalized_rows
    ) and len(_normalize_report_text(overall_summary)) >= 40
    requested_status = str(decision.get("status") or "").strip().lower()
    if requested_status == "final" and not prose_complete:
        raise ValueError("Invalid report chart decision JSON: status=final 但 selected_charts 的正式解读或 overall_summary 不完整。")
    status = "final" if prose_complete else "draft"
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "source": str(decision.get("source") or "agent-chart-selection"),
        "report_audience": _report_audience(context, decision),
        "selected_charts": normalized_rows,
        "overall_summary": overall_summary,
    }


def _chart_review_from_decision(chart_blocks: list[dict[str, Any]], decision: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(decision, dict):
        return None
    if str(decision.get("status") or "").strip().lower() != "final":
        return None
    rows = decision.get("selected_charts")
    if not isinstance(rows, list):
        return None
    by_file = {str(item.get("file")): item for item in rows if isinstance(item, dict) and item.get("file")}
    charts: list[dict[str, Any]] = []
    for index, block in enumerate(chart_blocks, start=1):
        item = by_file.get(block["path"].name)
        if not item:
            return None
        charts.append(
            {
                "index": index,
                "file": block["path"].name,
                "title": block["title"],
                "interpretation": _ensure_sentence(item.get("interpretation")),
                "implication": _ensure_sentence(item.get("implication")),
                "caption_note": _ensure_sentence(item.get("caption_note") or "").rstrip("。"),
            }
        )
    overall_summary = _ensure_sentence(decision.get("overall_summary"))
    if len(_normalize_report_text(overall_summary)) < 40:
        return None
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "final",
        "source": str(decision.get("source") or "agent-chart-selection"),
        "overall_summary": overall_summary,
        "charts": charts,
    }


def _normalize_chart_review(chart_blocks: list[dict[str, Any]], review: dict[str, Any] | None) -> dict[str, Any]:
    if review is None:
        return _pending_chart_review(chart_blocks)
    review_status = str(review.get("status") or "").strip().lower() if isinstance(review, dict) else ""
    if review_status and review_status != "final":
        return _pending_chart_review(chart_blocks)

    candidate_rows = review.get("charts") if isinstance(review, dict) else None
    review_by_file: dict[str, dict[str, Any]] = {}
    review_by_index: dict[int, dict[str, Any]] = {}
    if isinstance(candidate_rows, list):
        for item in candidate_rows:
            if not isinstance(item, dict):
                continue
            if item.get("file"):
                review_by_file[str(item["file"])] = item
            if item.get("index"):
                try:
                    review_by_index[int(item["index"])] = item
                except (TypeError, ValueError):
                    continue

    errors: list[str] = []
    normalized_charts: list[dict[str, Any]] = []
    for index, block in enumerate(chart_blocks, start=1):
        item = review_by_file.get(block["path"].name) or review_by_index.get(index)
        if not item:
            errors.append(f"缺少图 {index}（{block['path'].name}）的回写内容。")
            item = {}
        interpretation = _ensure_sentence(item.get("interpretation"))
        implication = _ensure_sentence(item.get("implication"))
        if len(_normalize_report_text(interpretation)) < 28:
            errors.append(f"图 {index}（{block['path'].name}）的 interpretation 过短。")
        if len(_normalize_report_text(implication)) < 28:
            errors.append(f"图 {index}（{block['path'].name}）的 implication 过短。")
        normalized_charts.append(
            {
                "index": index,
                "file": block["path"].name,
                "title": block["title"],
                "interpretation": interpretation,
                "implication": implication,
                "caption_note": _ensure_sentence(item.get("caption_note") or "").rstrip("。"),
            }
        )

    overall_summary = _ensure_sentence((review or {}).get("overall_summary"))
    if len(_normalize_report_text(overall_summary)) < 40:
        errors.append("overall_summary 过短，无法承担图表总体解读作用。")
    if errors:
        raise ValueError("Invalid chart review JSON: " + " | ".join(errors))

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "final",
        "source": str(review.get("source") or "agent-second-pass"),
        "overall_summary": overall_summary,
        "charts": normalized_charts,
    }


def _chart_review_markdown(review: dict[str, Any]) -> str:
    lines = [
        "# 图表解读回填结果",
        "",
        f"- 生成时间：{review.get('generated_at', 'N/A')}",
        f"- 来源：{review.get('source', 'N/A')}",
        f"- 状态：{review.get('status', 'N/A')}",
        f"- 报告阶段：{_report_stage_label(review.get('status'))}",
    ]
    if review.get("status") != "final":
        lines.extend(
            [
                "",
                "## 当前状态",
                "图表解读仍待 agent 二次读图回写；当前文件只保留待填写结构，不再生成模板化解读。",
            ]
        )
        return "\n".join(lines).strip() + "\n"
    lines.extend(["", "## 逐图解读"])
    for item in review.get("charts", []):
        lines.extend(
            [
                "",
                f"### 图 {item.get('index', '?')}：{item.get('title', item.get('file', '图表'))}",
                item.get("interpretation", ""),
                "",
                item.get("implication", ""),
            ]
        )
        if item.get("caption_note"):
            lines.extend(["", f"注释：{item['caption_note']}"])
    lines.extend(["", "## 图表总体解读", review.get("overall_summary", "")])
    return "\n".join(lines).strip() + "\n"


def _lint_chart_review_content(review: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if not review or review.get("status") != "final":
        return warnings
    for item in review.get("charts", []):
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("file") or "图表"
        interpretation = _normalize_report_text(item.get("interpretation") or "")
        implication = _normalize_report_text(item.get("implication") or "")
        combined = f"{interpretation}\n{implication}"
        hit = next((phrase for phrase in CHART_REVIEW_META_PHRASES if phrase in combined), None)
        if hit:
            warnings.append(f"chart_review 中“{title}”仍包含偏说明书式表达，例如“{hit}”。")
        if len(interpretation) < 28:
            warnings.append(f"chart_review 中“{title}”的 interpretation 过短，像占位句。")
        if len(implication) < 28:
            warnings.append(f"chart_review 中“{title}”的 implication 过短，像占位句。")
    overall_summary = _normalize_report_text(review.get("overall_summary") or "")
    if overall_summary and any(phrase in overall_summary for phrase in ["这组图", "这些图表放在一起看"]):
        pass
    elif overall_summary and len(overall_summary) < 40:
        warnings.append("chart_review 的 overall_summary 过短，难以承担总体解读作用。")
    return warnings


def _chart_blocks_with_review(context: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    base_blocks = _chart_blocks(context, context.get("report_chart_decision"))[:MAX_FORMAL_REPORT_CHARTS]
    review = context.get("chart_review") or {}
    if str(review.get("status") or "").strip().lower() != "final":
        return [
            {
                **block,
                "interpretation": "",
                "implication": "",
                "caption_note": "",
            }
            for block in base_blocks
        ], ""
    review_by_file = {
        str(item.get("file")): item for item in review.get("charts", []) if isinstance(item, dict) and item.get("file")
    }
    rendered_blocks: list[dict[str, Any]] = []
    for block in base_blocks:
        item = review_by_file.get(block["path"].name, {})
        rendered_blocks.append(
            {
                **block,
                "interpretation": _ensure_sentence(item.get("interpretation")),
                "implication": _ensure_sentence(item.get("implication")),
                "caption_note": _normalize_report_text(item.get("caption_note") or ""),
            }
        )
    return rendered_blocks, _ensure_sentence(review.get("overall_summary"))


def _prepare_report_context(run_dir: Path, context: dict[str, Any], title: str) -> tuple[dict[str, Any], dict[str, Any]]:
    chart_blocks = _chart_blocks(context, context.get("report_chart_decision"))[:MAX_FORMAL_REPORT_CHARTS]
    draft_path = run_dir / "formal_report_draft.md"
    context_path = run_dir / "report_context.json"
    draft_markdown = _build_formal_report_draft_markdown(context, title, chart_blocks)
    pending_decision = _pending_report_chart_decision(context, chart_blocks)
    write_markdown(draft_path, draft_markdown)
    write_json(context_path, _report_context_payload(context, title, chart_blocks))
    context["json_files"] = sorted(run_dir.glob("*.json"))
    context["markdown_files"] = sorted(run_dir.glob("*.md"))
    return pending_decision, _pending_chart_review(chart_blocks)


def _persist_report_chart_decision_artifact(run_dir: Path, decision: dict[str, Any]) -> Path:
    decision_path = run_dir / "report_chart_decision.json"
    if str(decision.get("status") or "").strip().lower() != "final":
        existing = _load_report_chart_decision(decision_path)
        if isinstance(existing, dict) and str(existing.get("status") or "").strip().lower() == "final":
            decision_path = run_dir / "report_chart_decision.pending.json"
    write_json(decision_path, decision)
    return decision_path


def _persist_chart_review_artifacts(run_dir: Path, review: dict[str, Any]) -> tuple[Path, Path]:
    review_path = run_dir / "chart_review.json"
    markdown_path = run_dir / "chart_review.md"
    if str(review.get("status") or "").strip().lower() == "final":
        write_json(review_path, review)
        write_markdown(markdown_path, _chart_review_markdown(review))
        return review_path, markdown_path

    existing = _load_chart_review(review_path)
    if isinstance(existing, dict) and str(existing.get("status") or "").strip().lower() == "final":
        review_path = run_dir / "chart_review.pending.json"
        markdown_path = run_dir / "chart_review.pending.md"
    write_json(review_path, review)
    write_markdown(markdown_path, _chart_review_markdown(review))
    return review_path, markdown_path


def _resolve_chart_review(run_dir: Path, explicit_path: Path | None) -> tuple[dict[str, Any] | None, Path | None]:
    if explicit_path is not None:
        if not explicit_path.exists():
            raise FileNotFoundError(f"chart review JSON not found: {explicit_path}")
        payload = _load_chart_review(explicit_path)
        if payload is None:
            raise ValueError(f"chart review JSON is empty or invalid: {explicit_path}")
        return payload, explicit_path if payload is not None else None
    return None, None


def _resolve_report_chart_decision(run_dir: Path, explicit_path: Path | None) -> tuple[dict[str, Any] | None, Path | None]:
    if explicit_path is not None:
        if not explicit_path.exists():
            raise FileNotFoundError(f"report chart decision JSON not found: {explicit_path}")
        payload = _load_report_chart_decision(explicit_path)
        if payload is None:
            raise ValueError(f"report chart decision JSON is empty or invalid: {explicit_path}")
        return payload, explicit_path if payload is not None else None
    return None, None


def _glossary_rows(context: dict[str, Any]) -> list[list[str]]:
    rows = [["名词", "简单解释", "如何看"]]
    best_model, metrics = _best_model_metrics(context)
    used = set()
    for key in metrics:
        metric_key = key.replace("test_", "")
        if metric_key in METRIC_META and metric_key not in used:
            meta = METRIC_META[metric_key]
            rows.append([meta["label"], meta["meaning"], meta["reading"]])
            used.add(metric_key)
    analysis = context.get("analysis_report") or {}
    if context.get("task") in {"cluster", "clustering"} and "silhouette_score" not in used:
        meta = METRIC_META["silhouette_score"]
        rows.append([meta["label"], meta["meaning"], meta["reading"]])
    if context.get("task") in {"experiment", "ab-test"}:
        rows.append(["Lift", "实验组相对对照组的提升幅度。", "要同时看基线、样本量和显著性，不能只看百分比。"])
        rows.append(["Confidence Interval", "估计值可能落入的区间范围。", "区间越窄通常越稳定；若跨过 0，结论通常更不稳。"])
    if context.get("task") in {"did", "causal"}:
        rows.append(["DID", "双重差分，用于估计处理前后实验组相对对照组的额外变化。", "前提是处理前趋势可比，否则结果容易偏。"])
    if context.get("task") in {"rd"}:
        rows.append(["RD", "断点回归，利用阈值附近样本估计局部处理效应。", "只对阈值附近样本更有解释力，不宜随意外推。"])
    if context.get("task") in {"iv"}:
        rows.append(["IV", "工具变量法，用外生变量识别处理效应。", "重点看工具变量是否足够强，以及排除限制是否合理。"])
    if context.get("task") in {"dml", "dr", "psm", "orthogonal", "uplift", "cate"}:
        rows.append(["ATE/ATT/CATE", "分别表示平均处理效应、处理组平均处理效应、条件处理效应。", "要先确认重叠性与模型设定，再解读不同人群的差异。"])
    explainability = context.get("explainability_report") or {}
    if explainability:
        rows.append(["SHAP", "衡量单个变量对模型预测影响强弱的解释工具。", "值越大表示模型越依赖这个变量，但不代表因果。"])
        rows.append(["PDP", "部分依赖图，展示某个变量变化时模型预测均值如何变化。", "看曲线方向和幅度，不要把边缘样本很少的区间解读得过深。"])
    deduped_rows = [rows[0]]
    seen_terms: set[str] = set()
    for row in rows[1:]:
        term = row[0]
        if term in seen_terms:
            continue
        seen_terms.add(term)
        deduped_rows.append(row)
    return deduped_rows


def _plain_section_rows(context: dict[str, Any], section_name: str, limit: int = 6) -> list[str]:
    lines = _section_lines(context, section_name, limit=limit * 2)
    filtered = [line for line in lines if _line_is_formal_report_ready(line)]
    return filtered[:limit]


def _set_run_font(run, font_name: str = DOCX_FONT_NAME, size: float | None = None, bold: bool | None = None) -> None:
    run.font.name = font_name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold


def _add_heading(doc: Document, text: str, level: int) -> None:
    paragraph = doc.add_heading("", level=level)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.space_before = Pt(14 if level == 1 else 9)
    paragraph.paragraph_format.space_after = Pt(6 if level == 1 else 4)
    run = paragraph.add_run(text)
    _set_run_font(run, font_name=DOCX_HEADING_FONT_NAME, size=16 if level == 1 else 13 if level == 2 else 11.5, bold=True)

def _add_paragraph(
    doc: Document,
    text: str,
    size: float = 11.5,
    bold: bool = False,
    align: int | None = None,
    first_line_indent: bool = True,
    line_spacing: float = 1.45,
    space_after: float = 5.0,
    font_name: str = DOCX_FONT_NAME,
) -> None:
    paragraph = doc.add_paragraph()
    paragraph.alignment = align if align is not None else WD_ALIGN_PARAGRAPH.JUSTIFY
    paragraph.paragraph_format.line_spacing = line_spacing
    paragraph.paragraph_format.space_after = Pt(space_after)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.first_line_indent = Pt(size * 2) if first_line_indent else Pt(0)
    run = paragraph.add_run(_normalize_report_text(text))
    _set_run_font(run, font_name=font_name, size=size, bold=bold)


def _add_bullets(doc: Document, items: list[str]) -> None:
    for item in items:
        paragraph = doc.add_paragraph(style="List Bullet")
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        paragraph.paragraph_format.line_spacing = 1.3
        paragraph.paragraph_format.space_after = Pt(3)
        run = paragraph.add_run(_normalize_report_text(item))
        _set_run_font(run)


def _add_table(doc: Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    for r_index, row in enumerate(rows):
        for c_index, value in enumerate(row):
            cell = table.cell(r_index, c_index)
            cell.text = str(value)
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if r_index == 0 else WD_ALIGN_PARAGRAPH.JUSTIFY
                paragraph.paragraph_format.line_spacing = 1.2
                paragraph.paragraph_format.space_after = Pt(1)
                paragraph.paragraph_format.first_line_indent = Pt(0)
                for run in paragraph.runs:
                    _set_run_font(run, size=10.2, bold=(r_index == 0))


def _atomic_temp_output_path(output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=str(output_path.parent),
        prefix=f"{output_path.stem}.",
        suffix=output_path.suffix,
    ) as handle:
        return Path(handle.name)


def _render_docx(
    run_dir: Path,
    output_path: Path,
    context: dict[str, Any],
    title: str,
    chart_blocks: list[dict[str, Any]],
    chart_overall_summary: str,
    report_stage: str,
    report_stage_label: str,
) -> None:
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.54)
    section.bottom_margin = Cm(2.54)
    section.left_margin = Cm(2.8)
    section.right_margin = Cm(2.4)
    normal_style = doc.styles["Normal"]
    normal_style.font.name = DOCX_FONT_NAME
    normal_style._element.rPr.rFonts.set(qn("w:eastAsia"), DOCX_FONT_NAME)
    normal_style.font.size = Pt(11.5)

    _add_paragraph(doc, title, size=20.5, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, first_line_indent=False, line_spacing=1.1, space_after=7, font_name=DOCX_HEADING_FONT_NAME)
    _add_paragraph(doc, "正式中文分析报告", size=12.5, align=WD_ALIGN_PARAGRAPH.CENTER, first_line_indent=False, line_spacing=1.15, space_after=3)
    _add_paragraph(doc, f"报告类型：{_friendly_task_label(context.get('task'))}", size=10.8, align=WD_ALIGN_PARAGRAPH.CENTER, first_line_indent=False, line_spacing=1.1, space_after=1)
    _add_paragraph(doc, f"报告状态：{report_stage_label}", size=10.2, align=WD_ALIGN_PARAGRAPH.CENTER, first_line_indent=False, line_spacing=1.1, space_after=1)
    _add_paragraph(doc, f"生成日期：{date.today()}", size=10.2, align=WD_ALIGN_PARAGRAPH.CENTER, first_line_indent=False, line_spacing=1.1, space_after=8)
    doc.add_paragraph("")

    _add_heading(doc, "一、执行摘要", 1)
    _add_paragraph(doc, _executive_conclusion(context))
    _add_heading(doc, "关键发现", 2)
    _add_bullets(doc, _key_findings(context))
    _add_heading(doc, "建议动作", 2)
    _add_bullets(doc, _recommendations(context))
    _add_heading(doc, "风险提示", 2)
    _add_bullets(doc, _risk_items(context))

    _add_heading(doc, "二、分析背景与方法", 1)
    _add_paragraph(doc, _method_summary(context))
    scope_lines = _plain_section_rows(context, "分析范围", limit=4)
    if scope_lines:
        _add_heading(doc, "分析范围", 2)
        _add_bullets(doc, scope_lines)
    _add_heading(doc, "数据来源与范围", 2)
    _add_table(doc, _source_and_scope_rows(context))

    _add_heading(doc, "三、数据质量与可用性", 1)
    _add_table(doc, _data_quality_rows(context))

    _add_heading(doc, "四、图表解读", 1)
    if report_stage != "final":
        _add_paragraph(
            doc,
            "当前为首稿版：此处仅展示将纳入正式报告的关键图表。详细图表解读必须由 agent 结合 PNG 与 report_context.json 二次回写后，再重新导出正式版。",
            first_line_indent=False,
            space_after=6,
        )
    for index, block in enumerate(chart_blocks, start=1):
        _add_heading(doc, f"图 {index}：{block['title']}", 2)
        if block["path"].exists():
            doc.add_picture(str(block["path"]), width=Inches(6.0))
        if report_stage == "final":
            _add_paragraph(doc, block["interpretation"], space_after=4)
            _add_paragraph(doc, block["implication"], space_after=4)
        if report_stage == "final" and block.get("caption_note"):
            _add_paragraph(doc, f"注释：{block['caption_note']}", size=9.6, first_line_indent=False, line_spacing=1.2, space_after=6)
    if report_stage == "final" and chart_overall_summary:
        _add_heading(doc, "图表总体解读", 2)
        _add_paragraph(doc, chart_overall_summary, space_after=6)

    _add_heading(doc, _model_result_section_title(context), 1)
    _add_paragraph(doc, _model_design_paragraph(context))
    _add_heading(doc, "模型结果表", 2)
    _add_table(doc, _metric_commentary(context))
    _add_heading(doc, "结果解读", 2)
    _add_paragraph(doc, _model_result_readout_paragraph(context))
    _add_heading(doc, "模型是否可用", 2)
    _add_paragraph(doc, _model_usability_paragraph(context))
    _add_heading(doc, "后续建议", 2)
    _add_paragraph(doc, _model_next_steps_paragraph(context))

    model_lines = _plain_section_rows(context, "模型结果", limit=4)
    if model_lines:
        _add_heading(doc, "补充说明", 2)
        _add_bullets(doc, model_lines)

    explain_lines = _plain_section_rows(context, "可解释性结论", limit=6)
    if explain_lines:
        _add_heading(doc, "解释性补充说明", 2)
        _add_bullets(doc, explain_lines)

    temp_path = _atomic_temp_output_path(output_path)
    doc.save(temp_path)
    temp_path.replace(output_path)


def _build_pdf_styles() -> dict[str, ParagraphStyle]:
    pdf_font_name = _ensure_pdf_font()
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ZH-Title",
            parent=styles["Title"],
            fontName=pdf_font_name,
            fontSize=19.5,
            leading=26,
            alignment=1,
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ZH-Heading1",
            parent=styles["Heading1"],
            fontName=pdf_font_name,
            fontSize=15,
            leading=20,
            spaceBefore=10,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ZH-Heading2",
            parent=styles["Heading2"],
            fontName=pdf_font_name,
            fontSize=12.2,
            leading=17,
            spaceBefore=7,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ZH-Body",
            parent=styles["BodyText"],
            fontName=pdf_font_name,
            fontSize=10.1,
            leading=16.4,
            spaceAfter=5,
            alignment=4,
            firstLineIndent=18,
            wordWrap="CJK",
            splitLongWords=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ZH-List",
            parent=styles["BodyText"],
            fontName=pdf_font_name,
            fontSize=10.1,
            leading=15.2,
            spaceAfter=3.5,
            alignment=4,
            wordWrap="CJK",
            splitLongWords=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ZH-Meta",
            parent=styles["BodyText"],
            fontName=pdf_font_name,
            fontSize=10.0,
            leading=13.5,
            alignment=1,
            spaceAfter=2.5,
            wordWrap="CJK",
            splitLongWords=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ZH-Small",
            parent=styles["BodyText"],
            fontName=pdf_font_name,
            fontSize=8.9,
            leading=12.5,
            spaceAfter=4,
            textColor=colors.HexColor("#666666"),
            wordWrap="CJK",
            splitLongWords=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ZH-Table",
            parent=styles["BodyText"],
            fontName=pdf_font_name,
            fontSize=8.4,
            leading=10.6,
            spaceAfter=0,
            wordWrap="CJK",
            splitLongWords=True,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ZH-TableHeader",
            parent=styles["BodyText"],
            fontName=pdf_font_name,
            fontSize=8.8,
            leading=10.8,
            spaceAfter=0,
            wordWrap="CJK",
            splitLongWords=True,
        )
    )
    return styles


def _ensure_pdf_font() -> str:
    registered = set(pdfmetrics.getRegisteredFontNames())
    if PDF_FONT_NAME in registered:
        return PDF_FONT_NAME
    font_path = detect_cjk_font_path(
        [
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Songti.ttc",
        ]
    )
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, font_path))
            return PDF_FONT_NAME
        except Exception:
            pass
    if PDF_FONT_FALLBACK not in registered:
        pdfmetrics.registerFont(UnicodeCIDFont(PDF_FONT_FALLBACK))
    return PDF_FONT_FALLBACK


def _pdf_cell_paragraph(text: Any, style: ParagraphStyle) -> Paragraph:
    normalized = _normalize_report_text(str(text))
    return Paragraph(escape(normalized), style)


def _pdf_table(rows: list[list[str]], styles: dict[str, ParagraphStyle], col_widths: list[float] | None = None) -> Table:
    converted_rows: list[list[Any]] = []
    for row_index, row in enumerate(rows):
        style = styles["ZH-TableHeader"] if row_index == 0 else styles["ZH-Table"]
        converted_rows.append([_pdf_cell_paragraph(value, style) for value in row])
    table = Table(converted_rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), styles["ZH-Table"].fontName),
                ("FONTSIZE", (0, 0), (-1, -1), 8.4),
                ("LEADING", (0, 0), (-1, -1), 10.6),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCEAF3")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#A0A0A0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ]
        )
    )
    return table


def _pdf_summary_card_rows(context: dict[str, Any]) -> list[list[str]]:
    positive_rate = _positive_rate(context)
    best_model, metrics = _best_model_metrics(context)
    top_features = _top_explainability_dimensions(context, limit=2)
    cleaning = context.get("cleaning_report") or {}
    if context.get("task") in {"cluster", "clustering"}:
        analysis = context.get("analysis_report") or {}
        cluster_size_summary = _cluster_size_summary(context)
        feature_names = _compact_feature_names(list(analysis.get("feature_columns") or []), limit=2)
        return [
            ["样本规模", str(cleaning.get("shape", {}).get("rows", "N/A")), "分群数量", str(analysis.get("n_clusters", "N/A"))],
            ["轮廓系数", _fmt(analysis.get("silhouette_score")), "最小群占比", _pct(cluster_size_summary.get("smallest_share"))],
            ["关键维度", feature_names, "任务类型", _friendly_task_label(context.get("task"))],
        ]
    if context.get("task") == "regression":
        return [
            ["样本规模", str(cleaning.get("shape", {}).get("rows", "N/A")), "最佳模型", _friendly_model_name(best_model)],
            ["R2", _fmt(metrics.get("test_r2")), "RMSE", _fmt(abs(metrics["test_neg_root_mean_squared_error"])) if metrics.get("test_neg_root_mean_squared_error") is not None else "N/A"],
            ["关键变量", "、".join(top_features) if top_features else "N/A", "任务类型", _friendly_task_label(context.get("task"))],
        ]
    if context.get("task") in {"experiment", "ab-test"}:
        experiment = context.get("experiment_report") or {}
        decision = experiment.get("decision") or {}
        metric_name, metric_details = _experiment_primary_metric(context)
        variant_counts = experiment.get("variant_counts") or {}
        total_samples = sum(int(value) for value in variant_counts.values()) if variant_counts else cleaning.get("shape", {}).get("rows", "N/A")
        return [
            ["样本规模", str(total_samples), "实验结论", EXPERIMENT_STATUS_LABELS.get(decision.get("status"), decision.get("status") or "N/A")],
            ["主指标", metric_name or "N/A", "相对提升", _pct(metric_details.get("relative_lift")) if metric_details else "N/A"],
            ["SRM p_value", _fmt((experiment.get("sample_ratio_mismatch") or {}).get("p_value")), "任务类型", _friendly_task_label(context.get("task"))],
        ]
    if context.get("task") in {"did", "rd", "synthetic-control", "iv", "dml", "dr", "psm", "orthogonal", "uplift", "cate", "causal"}:
        estimate_label, estimate_value, p_value = _causal_estimate_snapshot(context)
        causal_report = context.get("causal_report") or {}
        n_units = causal_report.get("n_units") or cleaning.get("shape", {}).get("rows", "N/A")
        return [
            ["样本规模", str(n_units), "核心效应", estimate_label or "N/A"],
            ["效应值", _fmt(estimate_value), "p_value", _fmt(p_value)],
            ["任务类型", _friendly_task_label(context.get("task")), "图表数量", str(_chart_count(context))],
        ]
    if context.get("task") in {"descriptive", "time-series"}:
        return [
            ["样本规模", str(cleaning.get("shape", {}).get("rows", "N/A")), "字段数量", str(cleaning.get("shape", {}).get("columns", "N/A"))],
            ["数值字段", str(len(cleaning.get("roles", {}).get("numeric", []))), "图表数量", str(_chart_count(context))],
            ["任务类型", _friendly_task_label(context.get("task")), "缺失列数", str(cleaning.get("missing_values", {}).get("columns_with_missing_values", "N/A"))],
        ]
    primary_metric = metrics.get("test_f1_weighted") if context.get("task") == "classification" else metrics.get("test_r2")
    return [
        ["样本规模", str(cleaning.get("shape", {}).get("rows", "N/A")), "目标发生率", _pct(positive_rate)],
        ["最佳模型", _friendly_model_name(best_model), "核心评分", _fmt(primary_metric)],
        ["关键变量", "、".join(top_features) if top_features else "N/A", "任务类型", _friendly_task_label(context.get("task"))],
    ]


def _render_pdf(
    run_dir: Path,
    output_path: Path,
    context: dict[str, Any],
    title: str,
    chart_blocks: list[dict[str, Any]],
    chart_overall_summary: str,
    report_stage: str,
    report_stage_label: str,
) -> None:
    styles = _build_pdf_styles()
    story: list[Any] = []

    story.append(Paragraph(title, styles["ZH-Title"]))
    story.append(Paragraph("正式中文分析报告", styles["ZH-Meta"]))
    story.append(Paragraph(f"报告类型：{_friendly_task_label(context.get('task'))}", styles["ZH-Meta"]))
    story.append(Paragraph(f"报告状态：{report_stage_label}", styles["ZH-Meta"]))
    story.append(Paragraph(f"生成日期：{date.today()}", styles["ZH-Meta"]))
    story.append(Spacer(1, 0.28 * cm))

    story.append(Paragraph("一句话结论", styles["ZH-Heading1"]))
    story.append(Paragraph(_executive_conclusion(context), styles["ZH-Body"]))
    story.append(Spacer(1, 0.15 * cm))
    story.append(_pdf_table(_pdf_summary_card_rows(context), styles, [2.6 * cm, 5.4 * cm, 2.6 * cm, 5.0 * cm]))
    story.append(Spacer(1, 0.24 * cm))

    story.append(Paragraph("关键发现", styles["ZH-Heading1"]))
    for item in _key_findings(context)[:4]:
        story.append(Paragraph(f"- {_normalize_report_text(item)}", styles["ZH-List"]))
    story.append(Paragraph("建议动作", styles["ZH-Heading1"]))
    for item in _recommendations(context)[:4]:
        story.append(Paragraph(f"- {_normalize_report_text(item)}", styles["ZH-List"]))
    story.append(Paragraph("风险提示", styles["ZH-Heading1"]))
    for item in _risk_items(context)[:3]:
        story.append(Paragraph(f"- {_normalize_report_text(item)}", styles["ZH-List"]))

    story.append(PageBreak())
    story.append(Paragraph("二、分析背景与方法", styles["ZH-Heading1"]))
    story.append(Paragraph(_method_summary(context), styles["ZH-Body"]))
    story.append(_pdf_table(_source_and_scope_rows(context), styles, [3.0 * cm, 12.5 * cm]))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph("三、数据质量与可用性", styles["ZH-Heading1"]))
    story.append(_pdf_table(_data_quality_rows(context), styles, [2.6 * cm, 2.4 * cm, 10.6 * cm]))

    story.append(PageBreak())
    story.append(Paragraph("四、图表解读", styles["ZH-Heading1"]))
    if report_stage != "final":
        story.append(
            Paragraph(
                "当前为首稿版：此处仅展示将纳入正式报告的关键图表。详细图表解读必须由 agent 结合 PNG 与 report_context.json 二次回写后，再重新导出正式版。",
                styles["ZH-Body"],
            )
        )
    for index, block in enumerate(chart_blocks, start=1):
        chart_story: list[Any] = [Paragraph(f"图 {index}：{block['title']}", styles["ZH-Heading2"])]
        if block["path"].exists():
            chart_story.append(Image(str(block["path"]), width=14.2 * cm, height=7.8 * cm))
            chart_story.append(Spacer(1, 0.08 * cm))
        if report_stage == "final":
            chart_story.append(Paragraph(_normalize_report_text(block["interpretation"]), styles["ZH-Body"]))
            chart_story.append(Paragraph(_normalize_report_text(block["implication"]), styles["ZH-Body"]))
        if report_stage == "final" and block.get("caption_note"):
            chart_story.append(Paragraph(f"注释：{_normalize_report_text(block['caption_note'])}", styles["ZH-Small"]))
        chart_story.append(Spacer(1, 0.18 * cm))
        story.append(KeepTogether(chart_story))
    if report_stage == "final" and chart_overall_summary:
        story.append(Paragraph("图表总体解读", styles["ZH-Heading2"]))
        story.append(Paragraph(_normalize_report_text(chart_overall_summary), styles["ZH-Body"]))
        story.append(Spacer(1, 0.18 * cm))

    story.append(Paragraph(_model_result_section_title(context), styles["ZH-Heading1"]))
    story.append(Paragraph(_model_design_paragraph(context), styles["ZH-Body"]))
    story.append(Paragraph("模型结果表", styles["ZH-Heading2"]))
    story.append(_pdf_table(_metric_commentary(context), styles, [1.7 * cm, 1.9 * cm, 2.8 * cm, 2.3 * cm, 7.1 * cm]))
    story.append(Spacer(1, 0.16 * cm))
    story.append(Paragraph("结果解读", styles["ZH-Heading2"]))
    story.append(Paragraph(_model_result_readout_paragraph(context), styles["ZH-Body"]))
    story.append(Paragraph("模型是否可用", styles["ZH-Heading2"]))
    story.append(Paragraph(_model_usability_paragraph(context), styles["ZH-Body"]))
    story.append(Paragraph("后续建议", styles["ZH-Heading2"]))
    story.append(Paragraph(_model_next_steps_paragraph(context), styles["ZH-Body"]))

    model_lines = _plain_section_rows(context, "模型结果", limit=4)
    if model_lines:
        story.append(Paragraph("补充说明", styles["ZH-Heading2"]))
        for item in model_lines:
            story.append(Paragraph(f"- {_normalize_report_text(item)}", styles["ZH-List"]))

    explain_lines = _plain_section_rows(context, "可解释性结论", limit=5)
    if explain_lines:
        story.append(Paragraph("解释性补充说明", styles["ZH-Heading2"]))
        for item in explain_lines:
            story.append(Paragraph(f"- {_normalize_report_text(item)}", styles["ZH-List"]))

    temp_path = _atomic_temp_output_path(output_path)
    document = SimpleDocTemplate(
        str(temp_path),
        pagesize=A4,
        leftMargin=1.9 * cm,
        rightMargin=1.9 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=title,
    )
    document.build(story)
    temp_path.replace(output_path)


def _artifact_freshness_warning(run_dir: Path, output_path: Path) -> str | None:
    source_candidates = [
        path
        for path in list(run_dir.glob("*.json")) + list(run_dir.glob("*.md")) + list(run_dir.glob("*.png"))
        if path.name not in {output_path.name, "formal_report_validation.json"}
    ]
    if not output_path.exists() or not source_candidates:
        return None
    latest_source_mtime = max(path.stat().st_mtime for path in source_candidates)
    if output_path.stat().st_mtime + 0.5 < latest_source_mtime:
        return f"{output_path.name} 早于部分源产物，可能不是最新导出结果。"
    return None


def _raw_identifier_candidates(context: dict[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    model_report = context.get("model_report") or {}
    identifiers.update((model_report.get("models") or {}).keys())
    explainability = context.get("explainability_report") or {}
    for row in (explainability.get("permutation_importance") or []):
        if isinstance(row, dict) and row.get("feature"):
            identifiers.add(str(row["feature"]))
    shap = explainability.get("shap") or {}
    for row in (shap.get("top_features") or []):
        if isinstance(row, dict) and row.get("feature"):
            identifiers.add(str(row["feature"]))
    analysis = context.get("analysis_report") or {}
    for name in analysis.get("feature_columns") or []:
        identifiers.add(str(name))
    return {item for item in identifiers if isinstance(item, str) and "_" in item and len(item) >= 8}


def _lint_report_text(text: str, context: dict[str, Any], medium: str) -> list[str]:
    warnings: list[str] = []
    if not text.strip():
        return [f"{medium} 文本为空或无法抽取。"]
    if re.search(r"\[[^\]]+\]\([^)]+\)", text) or "`" in text:
        warnings.append(f"{medium} 中仍存在 Markdown 链接或反引号语法。")
    raw_hits = sorted(identifier for identifier in _raw_identifier_candidates(context) if identifier in text)
    if raw_hits:
        warnings.append(f"{medium} 中仍出现原始技术标识，如 {', '.join(raw_hits[:3])}。")
    if re.search(r"\b(test_|train_|feature_columns|candidate_scores)\b", text):
        warnings.append(f"{medium} 中仍出现调试或技术字段名。")
    if _chart_count(context) > 0 and ("图 1" not in text and "图1" not in text):
        warnings.append(f"{medium} 中未明显引用图表标题或编号，需确认图表说明是否写入。")
    return warnings


def _extract_pdf_text(pdf_path: Path) -> tuple[str | None, str | None]:
    if module_available("pypdf"):
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(pdf_path))
        text = "".join((reader.pages[index].extract_text() or "") for index in range(min(3, len(reader.pages))))
        return text, None
    if command_available("pdftotext"):
        result = subprocess.run(["pdftotext", str(pdf_path), "-"], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return result.stdout, None
        return None, result.stderr.strip() or "pdftotext failed"
    return None, None


def validate_formal_report_outputs(run_dir: Path, docx_path: Path, pdf_path: Path, context: dict[str, Any]) -> dict[str, Any]:
    report_stage = str(context.get("report_stage") or "draft")
    chart_review = context.get("chart_review") or {}
    chart_review_status = str(chart_review.get("status") or "draft")
    report_chart_decision = context.get("report_chart_decision") or {}
    decision_status = str(report_chart_decision.get("status") or "draft")
    review_required = chart_review_status != "final"
    validation: dict[str, Any] = {
        "run_dir": str(run_dir),
        "report_stage": report_stage,
        "report_chart_decision": {
            "exists": bool(report_chart_decision),
            "status": decision_status,
            "warnings": [],
        },
        "chart_review": {
            "exists": bool(context.get("chart_review")),
            "status": chart_review_status,
            "review_required": review_required,
            "warnings": [],
        },
        "docx": {
            "exists": docx_path.exists(),
            "path": str(docx_path),
            "size_bytes": docx_path.stat().st_size if docx_path.exists() else 0,
            "warnings": [],
        },
        "pdf": {
            "exists": pdf_path.exists(),
            "path": str(pdf_path),
            "size_bytes": pdf_path.stat().st_size if pdf_path.exists() else 0,
            "warnings": [],
        },
        "warnings": [],
    }

    selected_blocks = context.get("selected_chart_blocks") or []
    candidate_rows = _chart_candidate_rows(context)
    _, candidate_by_file = _candidate_lookup_maps(context)
    if candidate_rows:
        for block in selected_blocks:
            if not isinstance(block, dict):
                continue
            file_name = str((block.get("path") or Path("")).name if isinstance(block.get("path"), Path) else block.get("file") or "")
            if not file_name:
                continue
            candidate = candidate_by_file.get(file_name)
            if candidate is None:
                validation["report_chart_decision"]["warnings"].append(f"正文图 {file_name} 未能在 chart_candidates.json 中找到对应候选元数据。")
                continue
            if bool(candidate.get("diagnostic_only")):
                validation["report_chart_decision"]["warnings"].append(f"正文图 {file_name} 被标记为 diagnostic-only，不应进入正式报告正文。")
            if not bool(candidate.get("allow_in_formal_body")):
                validation["report_chart_decision"]["warnings"].append(f"正文图 {file_name} 在候选元数据中不允许进入正式报告正文。")
        if report_stage == "final" and not selected_blocks:
            validation["report_chart_decision"]["warnings"].append("当前存在 governed candidates，但正式版未选入任何正文图。")

    validation["chart_review"]["warnings"].extend(_lint_chart_review_content(chart_review))
    if review_required:
        validation["chart_review"]["warnings"].append("当前为草稿版，图表解读尚未完成二次复核。")

    if docx_path.exists():
        try:
            document = Document(docx_path)
            nonempty = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
            validation["docx"]["paragraph_count"] = len(nonempty)
            validation["docx"]["sample_lines"] = nonempty[:8]
            validation["docx"]["inline_shape_count"] = len(document.inline_shapes)
            validation["docx"]["warnings"].extend(_lint_report_text("\n".join(nonempty), context, "DOCX"))
            if _chart_count(context) > 0 and len(document.inline_shapes) == 0:
                validation["docx"]["warnings"].append("DOCX 未检测到嵌入图片，需确认图表是否成功写入。")
        except Exception as exc:  # pragma: no cover - validation fallback
            validation["warnings"].append(f"DOCX 质检失败：{exc}")
    else:
        validation["warnings"].append("DOCX 文件未生成。")

    freshness_warning = _artifact_freshness_warning(run_dir, docx_path)
    if freshness_warning:
        validation["docx"]["warnings"].append(freshness_warning)

    if pdf_path.exists():
        if module_available("pypdf"):
            try:
                from pypdf import PdfReader  # type: ignore

                reader = PdfReader(str(pdf_path))
                validation["pdf"]["page_count"] = len(reader.pages)
            except Exception as exc:  # pragma: no cover - validation fallback
                validation["warnings"].append(f"PDF 页数质检失败：{exc}")
        pdf_text, pdf_error = _extract_pdf_text(pdf_path)
        if pdf_text is not None:
            validation["pdf"]["sample_text_length"] = len(pdf_text.strip())
            validation["pdf"]["warnings"].extend(_lint_report_text(pdf_text, context, "PDF"))
        elif command_available("file"):
            result = subprocess.run(["file", str(pdf_path)], capture_output=True, text=True, check=False)
            validation["pdf"]["file_summary"] = result.stdout.strip() or result.stderr.strip()
            validation["pdf"]["warnings"].append("未安装 pypdf/pdftotext，PDF 仅做文件级检查。")
        else:
            validation["pdf"]["warnings"].append("未安装 pypdf/pdftotext 且无 file 命令，PDF 仅确认文件存在。")
        if pdf_error:
            validation["pdf"]["warnings"].append(f"PDF 文本抽取失败：{pdf_error}")
    else:
        validation["warnings"].append("PDF 文件未生成。")

    freshness_warning = _artifact_freshness_warning(run_dir, pdf_path)
    if freshness_warning:
        validation["pdf"]["warnings"].append(freshness_warning)

    validation["warnings"].extend(validation["docx"]["warnings"])
    validation["warnings"].extend(validation["pdf"]["warnings"])
    validation["warnings"].extend(validation["chart_review"]["warnings"])
    validation["warnings"].extend(validation["report_chart_decision"]["warnings"])
    non_blocking_fragments = ("仅做文件级检查", "PDF 文本抽取失败")
    blocking_warnings = [warning for warning in validation["warnings"] if not any(fragment in warning for fragment in non_blocking_fragments)]
    validation["passed"] = validation["docx"].get("exists") and validation["pdf"].get("exists") and not blocking_warnings
    return validation


def export_formal_report(
    run_dir: Path,
    docx_path: Path | None = None,
    pdf_path: Path | None = None,
    title: str | None = None,
    chart_review_json_path: Path | None = None,
    report_chart_decision_json_path: Path | None = None,
) -> dict[str, Any]:
    context = _load_context(run_dir)
    report_title = title or "正式中文分析报告"
    docx_output = docx_path or (run_dir / "analysis-report-zh.docx")
    pdf_output = pdf_path or (run_dir / "analysis-report-zh.pdf")
    provided_decision, _ = _resolve_report_chart_decision(run_dir, report_chart_decision_json_path)
    normalized_decision = _normalize_report_chart_decision(context, provided_decision)
    context["report_chart_decision"] = normalized_decision
    pending_decision, pending_review = _prepare_report_context(run_dir, context, report_title)
    persisted_report_chart_decision_path = _persist_report_chart_decision_artifact(run_dir, normalized_decision if provided_decision is not None else pending_decision)
    chart_blocks = _chart_blocks(context, normalized_decision)[:MAX_FORMAL_REPORT_CHARTS]
    provided_review, _ = _resolve_chart_review(run_dir, chart_review_json_path)
    derived_review = _chart_review_from_decision(chart_blocks, normalized_decision) if provided_review is None else None
    if provided_review is not None:
        normalized_review = _normalize_chart_review(chart_blocks, provided_review)
    elif derived_review is not None:
        normalized_review = _normalize_chart_review(chart_blocks, derived_review)
    else:
        normalized_review = pending_review
    report_stage = str(normalized_review.get("status") or "draft")
    context["chart_review"] = normalized_review
    context["report_stage"] = report_stage
    context["selected_chart_blocks"] = chart_blocks
    context["report_chart_decision"] = normalized_decision if provided_decision is not None else pending_decision
    persisted_chart_review_path, persisted_chart_review_markdown_path = _persist_chart_review_artifacts(run_dir, normalized_review)
    context["json_files"] = sorted(run_dir.glob("*.json"))
    context["markdown_files"] = sorted(run_dir.glob("*.md"))
    chart_blocks, chart_overall_summary = _chart_blocks_with_review(context)
    context["selected_chart_blocks"] = chart_blocks
    _render_docx(run_dir, docx_output, context, report_title, chart_blocks, chart_overall_summary, report_stage, _report_stage_label(report_stage))
    _render_pdf(run_dir, pdf_output, context, report_title, chart_blocks, chart_overall_summary, report_stage, _report_stage_label(report_stage))
    validation = validate_formal_report_outputs(run_dir, docx_output, pdf_output, context)
    write_json(run_dir / "formal_report_validation.json", validation)
    result = {
        "docx": str(docx_output),
        "pdf": str(pdf_output),
        "validation": str(run_dir / "formal_report_validation.json"),
        "formal_report_draft": str(run_dir / "formal_report_draft.md"),
        "report_context": str(run_dir / "report_context.json"),
        "report_stage": report_stage,
        "report_chart_decision": str(persisted_report_chart_decision_path),
        "chart_review": str(persisted_chart_review_path),
        "chart_review_markdown": str(persisted_chart_review_markdown_path),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a formal Chinese DOCX and PDF report from a run directory.")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--docx-path")
    parser.add_argument("--pdf-path")
    parser.add_argument("--title")
    parser.add_argument("--chart-review-json")
    parser.add_argument("--report-chart-decision-json")
    args = parser.parse_args()

    result = export_formal_report(
        Path(args.run_dir).expanduser().resolve(),
        docx_path=Path(args.docx_path).expanduser().resolve() if args.docx_path else None,
        pdf_path=Path(args.pdf_path).expanduser().resolve() if args.pdf_path else None,
        title=args.title,
        chart_review_json_path=Path(args.chart_review_json).expanduser().resolve() if args.chart_review_json else None,
        report_chart_decision_json_path=Path(args.report_chart_decision_json).expanduser().resolve() if args.report_chart_decision_json else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
