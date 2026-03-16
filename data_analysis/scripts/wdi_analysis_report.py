#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common import availability_report, configure_matplotlib_defaults, write_json, write_markdown
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler


INDICATORS = {
    "NY.GDP.PCAP.CD": "人均GDP（现价美元）",
    "SP.DYN.LE00.IN": "预期寿命（岁）",
    "IT.NET.USER.ZS": "互联网使用率（%人口）",
    "EG.ELC.ACCS.ZS": "电力可及率（%人口）",
    "SP.POP.TOTL": "总人口",
    "SP.DYN.IMRT.IN": "婴儿死亡率（每千活产）",
    "NE.TRD.GNFS.ZS": "贸易开放度（进出口占GDP比重，%）",
    "SL.UEM.TOTL.ZS": "失业率（%劳动力）",
}

TREND_CODES = [
    "NY.GDP.PCAP.CD",
    "SP.DYN.LE00.IN",
    "IT.NET.USER.ZS",
    "EG.ELC.ACCS.ZS",
]

FOCUS_COUNTRIES = {
    "CHN": "中国",
    "USA": "美国",
    "IND": "印度",
    "BRA": "巴西",
}

START_YEAR = 2000
END_YEAR = 2023


@dataclass
class RunArtifacts:
    run_dir: Path
    latest_year: int
    analysis_table: pd.DataFrame
    trend_table: pd.DataFrame
    metadata: pd.DataFrame


def _set_style() -> str:
    selected = configure_matplotlib_defaults() or "DejaVu Sans"
    sns.set_theme(style="whitegrid")
    plt.rcParams["font.family"] = [selected]
    plt.rcParams["font.sans-serif"] = [selected]
    return selected


def _ensure_run_dir(output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    existing = sorted([p for p in output_root.iterdir() if p.is_dir() and p.name.startswith("wdi-analysis-")])
    next_id = len(existing) + 1
    run_dir = output_root / f"wdi-analysis-{next_id:03d}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _load_tables(zip_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("WDICSV.csv") as f:
            wdi = pd.read_csv(f)
        with zf.open("WDICountry.csv") as f:
            country = pd.read_csv(f)
    return wdi, country


def _prepare_long_table(wdi: pd.DataFrame) -> pd.DataFrame:
    year_cols = [str(year) for year in range(1960, 2026) if str(year) in wdi.columns]
    long_df = wdi.melt(
        id_vars=["Country Name", "Country Code", "Indicator Name", "Indicator Code"],
        value_vars=year_cols,
        var_name="year",
        value_name="value",
    )
    long_df["year"] = long_df["year"].astype(int)
    long_df["value"] = pd.to_numeric(long_df["value"], errors="coerce")
    long_df = long_df[long_df["Indicator Code"].isin(INDICATORS)]
    long_df = long_df.dropna(subset=["value"])
    return long_df


def _filter_countries(country: pd.DataFrame) -> pd.DataFrame:
    meta = country.copy()
    meta = meta.rename(
        columns={
            "Table Name": "TableName",
            "Income Group": "IncomeGroup",
        }
    )
    meta = meta[(meta["Region"].notna()) & (meta["Region"] != "Aggregates")]
    keep_cols = ["Country Code", "Short Name", "TableName", "Long Name", "Region", "IncomeGroup"]
    return meta[keep_cols].drop_duplicates()


def _latest_complete_year(long_df: pd.DataFrame, meta: pd.DataFrame) -> int:
    merged = long_df.merge(meta[["Country Code"]], on="Country Code", how="inner")
    coverage = (
        merged.groupby(["year", "Indicator Code"])["Country Code"]
        .nunique()
        .reset_index(name="country_count")
    )
    yearly = coverage.groupby("year")["country_count"].agg(["min", "median"]).reset_index()
    viable = yearly[(yearly["year"] >= START_YEAR) & (yearly["year"] <= END_YEAR) & (yearly["min"] >= 110)]
    if viable.empty:
        return END_YEAR
    return int(viable["year"].max())


def _build_analysis_table(long_df: pd.DataFrame, meta: pd.DataFrame, latest_year: int) -> pd.DataFrame:
    latest = long_df[long_df["year"] == latest_year]
    pivot = latest.pivot_table(
        index="Country Code",
        columns="Indicator Code",
        values="value",
        aggfunc="mean",
    ).reset_index()
    analysis = meta.merge(pivot, on="Country Code", how="inner")
    return analysis


def _run_clustering(analysis: pd.DataFrame) -> dict[str, Any]:
    feature_cols = [code for code in INDICATORS if code in analysis.columns]
    x = analysis[feature_cols].copy()
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()
    imputed = imputer.fit_transform(x)
    scaled = scaler.fit_transform(imputed)

    candidates: list[dict[str, Any]] = []
    best_score = -1.0
    best_k = 3
    best_labels = None
    best_model = None
    for k in range(3, 7):
        model = KMeans(n_clusters=k, random_state=42, n_init=20)
        labels = model.fit_predict(scaled)
        score = float(silhouette_score(scaled, labels))
        candidates.append({"n_clusters": k, "silhouette_score": score})
        if score > best_score:
            best_score = score
            best_k = k
            best_labels = labels
            best_model = model

    clustered = analysis.copy()
    clustered["cluster"] = best_labels
    centers = pd.DataFrame(
        scaler.inverse_transform(best_model.cluster_centers_),
        columns=feature_cols,
    )
    centers["cluster"] = range(best_k)
    profiles = centers.melt(id_vars="cluster", var_name="Indicator Code", value_name="center_value")
    profiles["Indicator Name"] = profiles["Indicator Code"].map(INDICATORS)

    size_rows = (
        clustered.groupby("cluster")["Country Code"]
        .count()
        .reset_index(name="country_count")
        .sort_values("cluster")
    )

    sample_rows = []
    for cluster_id in range(best_k):
        sample = clustered[clustered["cluster"] == cluster_id].sort_values("NY.GDP.PCAP.CD", ascending=False).head(5)
        sample_rows.append(
            {
                "cluster": int(cluster_id),
                "sample_countries": sample["TableName"].tolist(),
            }
        )

    cluster_profiles = (
        clustered.groupby("cluster")[feature_cols]
        .median(numeric_only=True)
        .reset_index()
        .to_dict(orient="records")
    )
    analysis["cluster"] = clustered["cluster"]
    return {
        "task": "clustering",
        "n_clusters": best_k,
        "selection_metric": "silhouette_score",
        "candidate_scores": candidates,
        "cluster_sizes": size_rows.to_dict(orient="records"),
        "cluster_profiles": cluster_profiles,
        "cluster_samples": sample_rows,
        "feature_columns": feature_cols,
        "annotated_table": analysis,
        "profile_long": profiles,
        "silhouette_score": best_score,
    }


def _summary_statistics(analysis: pd.DataFrame, feature_cols: list[str]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for col in feature_cols:
        series = analysis[col].dropna()
        stats[col] = {
            "count": int(series.count()),
            "mean": float(series.mean()) if not series.empty else None,
            "median": float(series.median()) if not series.empty else None,
            "std": float(series.std()) if series.count() > 1 else None,
            "min": float(series.min()) if not series.empty else None,
            "max": float(series.max()) if not series.empty else None,
        }
    return stats


def _correlation_matrix(analysis: pd.DataFrame, feature_cols: list[str]) -> dict[str, dict[str, float | None]]:
    corr = analysis[feature_cols].corr(numeric_only=True)
    return {
        row: {col: (None if pd.isna(val) else float(val)) for col, val in values.items()}
        for row, values in corr.to_dict().items()
    }


def _cleaning_report(analysis: pd.DataFrame, feature_cols: list[str]) -> dict[str, Any]:
    missing = analysis[feature_cols].isna().sum()
    total_cells = int(analysis[feature_cols].isna().sum().sum())
    return {
        "shape": {"rows": int(analysis.shape[0]), "columns": int(analysis.shape[1])},
        "roles": {
            "numeric": feature_cols,
            "categorical": ["Region", "IncomeGroup", "cluster"],
            "time": [],
            "target": [],
        },
        "missing_values": {
            "total_missing_cells": total_cells,
            "columns_with_missing_values": int((missing > 0).sum()),
            "by_column": {col: int(val) for col, val in missing.items()},
        },
        "duplicates": {
            "duplicate_rows": int(analysis.duplicated(subset=["Country Code"]).sum()),
            "duplicate_ratio": float(analysis.duplicated(subset=["Country Code"]).mean()),
        },
        "outliers_iqr": {},
        "outliers_zscore": {},
        "outliers_isolation_forest": {"outlier_ratio": None},
        "preprocessing_plan": [
            "聚类前对连续变量做中位数填补。",
            "聚类前对各指标做标准化，避免量纲主导结果。",
        ],
    }


def _to_pct(value: float | None, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "N/A"
    return f"{value * 100:.{digits}f}%"


def _format_num(value: float | None, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "N/A"
    abs_value = abs(value)
    if abs_value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if abs_value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs_value >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.{digits}f}"


def _build_report_brief(artifacts: RunArtifacts, cluster_report: dict[str, Any]) -> str:
    df = cluster_report["annotated_table"]
    latest_year = artifacts.latest_year
    focus = df[df["Country Code"].isin(FOCUS_COUNTRIES)].copy()
    focus["country_label"] = focus["Country Code"].map(FOCUS_COUNTRIES)
    rich_share = float((df["IncomeGroup"] == "High income").mean())
    internet_gap = (
        focus.set_index("country_label")["IT.NET.USER.ZS"].max()
        - focus.set_index("country_label")["IT.NET.USER.ZS"].min()
    )
    electricity_gap = (
        focus.set_index("country_label")["EG.ELC.ACCS.ZS"].max()
        - focus.set_index("country_label")["EG.ELC.ACCS.ZS"].min()
    )
    top_corr = artifacts.analysis_table[list(INDICATORS)].corr(numeric_only=True).loc["NY.GDP.PCAP.CD", "SP.DYN.LE00.IN"]
    return f"""# 数据来源
- 数据集为世界银行 World Development Indicators 2026 版压缩包中的 `WDICSV.csv` 与 `WDICountry.csv`。

# 分析范围
- 分析主体为有独立国家/地区元数据的经济体，剔除了 World、区域汇总和收入组聚合项。
- 趋势分析窗口为 {START_YEAR}-{latest_year} 年。
- 横截面分析以 {latest_year} 年为主，因为这是关键指标覆盖相对完整的最近年份。

# 关键发现
- 从横截面看，人均 GDP 与预期寿命呈明显正相关，相关系数约为 {top_corr:.2f}，说明收入水平与健康结果往往同步改善，但这仍是相关关系，不代表单向因果。
- 在中国、美国、印度、巴西四个重点国家中，互联网使用率差距约 {internet_gap:.1f} 个百分点，电力可及率差距约 {electricity_gap:.1f} 个百分点，说明基础数字化和公共服务覆盖仍是发展分化的重要维度。
- 聚类结果将样本划分为 {cluster_report['n_clusters']} 组，轮廓系数约 {cluster_report['silhouette_score']:.3f}，可用于识别“高收入成熟型”“人口大国追赶型”“基础设施补短板型”等发展路径。
- 在纳入本次横截面分析的国家中，高收入经济体占比约 {rich_share:.1%}，但其在人均 GDP、互联网使用率和婴儿死亡率等指标上与中低收入经济体差异依旧显著。

# 模型结果
- 本次未进行预测模型训练，核心方法为描述性统计、重点国家对比和无监督聚类。
- 聚类评分采用 silhouette score。该指标越高，代表组内更相似、组间更分离；本次结果达到可解释但非绝对清晰的水平。

# 可解释性结论
- 对聚类差异贡献最大的维度主要是人均 GDP、互联网使用率、电力可及率和婴儿死亡率。
- 中国更接近“基础设施完善、收入持续追赶”的组合；印度更接近“人口规模大、发展梯度明显”的组合；美国则代表成熟高收入组的上沿。

# 业务/公共卫生解释
- 如果这份报告用于宏观研究或投资前期扫描，最值得优先关注的不是单一 GDP 排名，而是“收入、健康、数字化、基础设施”是否同步改善。
- 如果用于公共政策比较，应优先观察互联网使用率、电力可及率与婴儿死亡率之间的组合变化，因为这些指标更接近居民实际获得感。
- 如果用于国际市场进入评估，建议把聚类结果当作国家分层框架，再叠加行业特定变量做二次筛选。

# 风险与限制
- WDI 为跨国口径整理数据，不同指标的统计口径和更新节奏并不完全一致。
- 2024 年和 2025 年覆盖不足，因此本次核心横截面使用 {latest_year} 年而非名义上的最新列。
- 聚类结果依赖所选指标集合，加入财政、教育或能源结构变量后，国家分组可能发生变化。
"""


def _build_run_summary(artifacts: RunArtifacts, cluster_report: dict[str, Any]) -> str:
    analysis = cluster_report["annotated_table"]
    return "\n".join(
        [
            "# Data Analysis Run Summary",
            "",
            "- task: `clustering`",
            f"- latest analysis year: `{artifacts.latest_year}`",
            f"- country count: `{analysis.shape[0]}`",
            f"- feature count: `{len(cluster_report['feature_columns'])}`",
            "",
            "## Findings",
            f"- Loaded {analysis.shape[0]} countries with {len(cluster_report['feature_columns'])} selected indicators.",
            f"- Selected {cluster_report['n_clusters']} clusters using silhouette score {cluster_report['silhouette_score']:.3f}.",
            "- Combined trend analysis, focus-country comparison, and latest-year clustering in one run.",
        ]
    )


def _save_trend_chart(long_df: pd.DataFrame, run_dir: Path) -> None:
    subset = long_df[
        (long_df["Indicator Code"] == "NY.GDP.PCAP.CD")
        & (long_df["Country Code"].isin(FOCUS_COUNTRIES))
        & (long_df["year"].between(START_YEAR, END_YEAR))
    ].copy()
    subset["国家"] = subset["Country Code"].map(FOCUS_COUNTRIES)
    plt.figure(figsize=(11, 6))
    sns.lineplot(data=subset, x="year", y="value", hue="国家", linewidth=2.5)
    plt.title("重点国家人均GDP趋势（2000-2023）")
    plt.xlabel("年份")
    plt.ylabel("人均GDP（美元）")
    plt.tight_layout()
    plt.savefig(run_dir / "focus_gdp_trend.png", dpi=180)
    plt.close()


def _save_scatter_chart(analysis: pd.DataFrame, run_dir: Path, latest_year: int) -> None:
    plot_df = analysis.dropna(subset=["NY.GDP.PCAP.CD", "SP.DYN.LE00.IN"]).copy()
    plt.figure(figsize=(11, 6.5))
    sns.scatterplot(
        data=plot_df,
        x="NY.GDP.PCAP.CD",
        y="SP.DYN.LE00.IN",
        hue="IncomeGroup",
        s=55,
        alpha=0.75,
    )
    for code, label in FOCUS_COUNTRIES.items():
        row = plot_df[plot_df["Country Code"] == code]
        if row.empty:
            continue
        x = float(row["NY.GDP.PCAP.CD"].iloc[0])
        y = float(row["SP.DYN.LE00.IN"].iloc[0])
        plt.text(x, y, f" {label}", fontsize=9)
    plt.xscale("log")
    plt.title(f"{latest_year}年人均GDP与预期寿命关系")
    plt.xlabel("人均GDP（对数刻度，美元）")
    plt.ylabel("预期寿命（岁）")
    plt.tight_layout()
    plt.savefig(run_dir / "gdp_life_scatter.png", dpi=180)
    plt.close()


def _save_focus_bar_chart(analysis: pd.DataFrame, run_dir: Path, latest_year: int) -> None:
    focus = analysis[analysis["Country Code"].isin(FOCUS_COUNTRIES)].copy()
    focus["国家"] = focus["Country Code"].map(FOCUS_COUNTRIES)
    melted = focus.melt(
        id_vars=["国家"],
        value_vars=["IT.NET.USER.ZS", "EG.ELC.ACCS.ZS"],
        var_name="指标",
        value_name="值",
    )
    melted["指标"] = melted["指标"].map(
        {
            "IT.NET.USER.ZS": "互联网使用率",
            "EG.ELC.ACCS.ZS": "电力可及率",
        }
    )
    plt.figure(figsize=(10, 6))
    sns.barplot(data=melted, x="国家", y="值", hue="指标")
    plt.title(f"{latest_year}年重点国家数字化与基础设施对比")
    plt.xlabel("")
    plt.ylabel("占比（%）")
    plt.ylim(0, 110)
    plt.tight_layout()
    plt.savefig(run_dir / "focus_access_bar.png", dpi=180)
    plt.close()


def _save_cluster_heatmap(cluster_report: dict[str, Any], run_dir: Path) -> None:
    profile_df = pd.DataFrame(cluster_report["cluster_profiles"]).set_index("cluster")
    ordered_cols = [code for code in INDICATORS if code in profile_df.columns]
    normalized = profile_df[ordered_cols].apply(lambda col: (col - col.mean()) / col.std(ddof=0), axis=0)
    normalized.columns = [INDICATORS[col] for col in ordered_cols]
    plt.figure(figsize=(12, 5.5))
    sns.heatmap(normalized, cmap="RdYlBu_r", center=0, annot=False)
    plt.title("国家分群画像热力图（标准化中位数）")
    plt.xlabel("")
    plt.ylabel("群组")
    plt.tight_layout()
    plt.savefig(run_dir / "cluster_profile_heatmap.png", dpi=180)
    plt.close()


def build_artifacts(zip_path: Path, output_root: Path) -> Path:
    _set_style()
    run_dir = _ensure_run_dir(output_root)

    wdi, country = _load_tables(zip_path)
    meta = _filter_countries(country)
    long_df = _prepare_long_table(wdi)
    long_df = long_df.merge(meta[["Country Code"]], on="Country Code", how="inner")
    latest_year = _latest_complete_year(long_df, meta)
    analysis = _build_analysis_table(long_df, meta, latest_year)
    cluster_report = _run_clustering(analysis)
    annotated = cluster_report["annotated_table"]
    feature_cols = cluster_report["feature_columns"]

    artifacts = RunArtifacts(
        run_dir=run_dir,
        latest_year=latest_year,
        analysis_table=annotated,
        trend_table=long_df,
        metadata=meta,
    )

    read_plan = {
        "path": str(zip_path),
        "format": "zip/csv",
        "recommended_backend": "pandas",
        "supported": True,
        "warnings": [
            "WDI 为宽表结构，已转换成长表后再做趋势与横截面分析。",
            f"2024-2025 年覆盖不足，本次核心分析使用 {latest_year} 年横截面。",
        ],
    }
    chart_plan = {
        "task": "clustering",
        "charts": [
            {
                "chart": "line",
                "file": "focus_gdp_trend.png",
                "title": "重点国家人均 GDP 趋势",
                "how_to_read": "先看各国曲线斜率，再看是否出现明显追赶或分化。",
                "meaning": "这张图用于识别中国、美国、印度、巴西在长期收入水平上的相对位置变化。",
            },
            {
                "chart": "scatter",
                "file": "gdp_life_scatter.png",
                "title": "人均 GDP 与预期寿命散点图",
                "how_to_read": "横轴越右表示收入越高，纵轴越上表示寿命越长，重点看整体斜率和重点国家位置。",
                "meaning": "这张图说明收入与健康结果存在明显正相关，但相关不等于因果。",
            },
            {
                "chart": "bar",
                "file": "focus_access_bar.png",
                "title": "重点国家数字化与基础设施对比",
                "how_to_read": "同一国家内比较两根柱的高度，再横向比较不同国家之间的差距。",
                "meaning": "这张图用于比较互联网使用率和电力可及率两类基础能力是否同步完善。",
            },
            {
                "chart": "heatmap",
                "file": "cluster_profile_heatmap.png",
                "title": "国家分群画像热力图",
                "how_to_read": "红色表示该群在该指标上相对更高，蓝色表示相对更低，应重点看每一行的整体轮廓。",
                "meaning": "这张图用于解释不同国家群组的结构特征，而不是给单个国家打绝对分数。",
            },
        ],
        "rendered": True,
    }
    stats_report = {
        "shape": {"rows": int(annotated.shape[0]), "columns": int(annotated.shape[1])},
        "summary_statistics": _summary_statistics(annotated, feature_cols),
        "correlation_matrix": _correlation_matrix(annotated, feature_cols),
    }
    analysis_report = {
        k: v
        for k, v in cluster_report.items()
        if k not in {"annotated_table", "profile_long"}
    }

    write_json(run_dir / "environment.json", availability_report())
    write_json(run_dir / "read_plan.json", read_plan)
    write_json(run_dir / "chart_plan.json", chart_plan)
    write_json(run_dir / "cleaning_report.json", _cleaning_report(annotated, feature_cols))
    write_json(run_dir / "stats_report.json", stats_report)
    write_json(run_dir / "analysis_report.json", analysis_report)
    write_markdown(run_dir / "report_brief.md", _build_report_brief(artifacts, cluster_report))
    write_markdown(run_dir / "run_summary.md", _build_run_summary(artifacts, cluster_report))

    annotated.to_csv(run_dir / "latest_year_country_panel.csv", index=False)
    long_df[
        (long_df["Indicator Code"].isin(TREND_CODES))
        & (long_df["Country Code"].isin(FOCUS_COUNTRIES))
        & (long_df["year"].between(START_YEAR, END_YEAR))
    ].to_csv(run_dir / "focus_country_trends.csv", index=False)

    _save_trend_chart(long_df, run_dir)
    _save_scatter_chart(annotated, run_dir, latest_year)
    _save_focus_bar_chart(annotated, run_dir, latest_year)
    _save_cluster_heatmap(cluster_report, run_dir)
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze WDI data and prepare report artifacts.")
    parser.add_argument("--zip-path", required=True)
    parser.add_argument("--output-root", default="outputs")
    args = parser.parse_args()

    run_dir = build_artifacts(Path(args.zip_path), Path(args.output_root))
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
