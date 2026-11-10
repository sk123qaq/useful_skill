#!/usr/bin/env python3
"""Render the current-vs-target workflow diagram for data-analysis-pro.

The figure is intentionally generated from code so the workflow can be
reviewed and changed like the rest of the skill.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "workflow-current-target.png"

GREEN = ("#D5F5E3", "#1E8449")
AMBER = ("#FDEBD0", "#B9770E")
RED = ("#FADBD8", "#C0392B")
BLUE = ("#D6EAF8", "#2471A3")
PURPLE = ("#E8DAEF", "#6C3483")
GRAY = ("#EAECEE", "#566573")

plt.rcParams["font.family"] = ["DejaVu Sans", "Droid Sans Fallback"]
plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Droid Sans Fallback"]
plt.rcParams["axes.unicode_minus"] = False


def box(ax, x, y, w, h, title, detail="", colors=GRAY, dashed=False, fs=9.2, detail_offset=6.1, wrap_width=None):
    face, edge = colors
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.35,rounding_size=1.1",
        linewidth=1.25,
        edgecolor=edge,
        facecolor=face,
        linestyle=(0, (4, 3)) if dashed else "solid",
        zorder=2,
    )
    ax.add_patch(patch)
    ax.text(x + 1.6, y + h - 2.2, title, fontsize=fs, fontweight="bold",
            color="#17202A", va="top", ha="left", zorder=3)
    if detail:
        wrapped = textwrap.fill(detail, width=wrap_width or max(16, int(w * 0.82)))
        ax.text(x + 1.6, y + h - detail_offset, wrapped, fontsize=7.0,
                color="#34495E", va="top", ha="left", linespacing=1.35, zorder=3)


def arrow(ax, start, end, color="#566573", dashed=False, width=1.35, rad=0.0, label=None):
    arr = FancyArrowPatch(
        start, end,
        arrowstyle="-|>", mutation_scale=11,
        linewidth=width, color=color,
        linestyle=(0, (3, 3)) if dashed else "solid",
        connectionstyle=f"arc3,rad={rad}",
        shrinkA=2, shrinkB=2, zorder=1,
    )
    ax.add_patch(arr)
    if label:
        mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
        ax.text(mx, my + 1.2, label, fontsize=6.6, color=color,
                ha="center", va="bottom", zorder=4,
                bbox=dict(facecolor="white", edgecolor="none", pad=0.6, alpha=0.85))


def render_current(ax):
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    ax.text(0, 99, "A. 现状：有工具，没有工作流", fontsize=15, fontweight="bold", color="#17202A", va="top")
    ax.text(0, 95.2, "颜色 = 该环节的状态；箭头 = 实际可执行的衔接。红色虚线框是当前缺失、但流程必须有的工件。",
            fontsize=8.2, color="#566573", va="top")

    # Left column: preparation
    box(ax, 2, 84, 43, 8.2, "P1 问题定义", "只有 prose：目标/粒度/时间语义/停止条件都没有被锁定；没有 contract 工件。", AMBER)
    box(ax, 2, 73, 43, 8.2, "P2 加载  io_router.py", "目录自动选最大文件；Excel 只读第一个 Sheet；带 # 注释的 CSV 直接 ParserError。", AMBER)
    box(ax, 2, 62, 43, 8.2, "P2 画像  column_profile.py", "列级统计/缺失/基数可用；不校验 target 是否存在，也不列 Sheet。", GREEN)
    box(ax, 2, 51, 43, 8.2, "P2 清洗  preprocessing.py", "清洗、编码、日历、血缘混在一个脚本；无 config 时静默不写 output。", AMBER)
    box(ax, 2, 40, 43, 8.2, "P3 EDA  eda_stats.py", "接受 --time-col/--target 但完全忽略；没有时序、分组、事件窗口。", AMBER)
    box(ax, 2, 29, 43, 8.2, "P3 关系  relationship_screening.py", "排序核心可用；没有泄漏/时序/目标重复列防护，小样本会给出 V=1。", AMBER)

    # Right column: analysis
    box(ax, 55, 84, 43, 8.2, "P4 路线判断", "文档写了描述/预测/因果；没有 route_decision 工件，也没有分支准入。", RED)
    box(ax, 55, 73, 43, 8.2, "预测  baseline_runner.py", "无 CLI；del time_col 后用随机 KFold；datetime 与目标 NaN 会崩。", AMBER)
    box(ax, 55, 62, 43, 8.2, "因果  causal_analysis.py", "估计器齐全，但单文件约 97KB；没有设计/识别假设/敏感性契约。", AMBER)
    box(ax, 55, 51, 43, 8.2, "实验  experiment_analysis.py", "SRM/平衡/功效统计齐全；只 print JSON，不落工件。", AMBER)
    box(ax, 55, 40, 43, 8.2, "解释  model_explainability.py", "SHAP/PDP 可用；重新 train_test_split，和 baseline 的切分不一致。", AMBER)
    box(ax, 55, 29, 43, 8.2, "P5 准入  gate_evaluator.py", "空输入也给 report-ready；缺 baseline/feature_risk 时占位 gate 直接 passed。", AMBER)
    box(ax, 55, 18, 43, 8.2, "P6 报告  report_export.py", "固定文件扫描；忽略 baseline/EDA；Phase 缺失也照样发报告。", AMBER)

    # Missing artifacts strip
    ax.text(2, 15.2, "缺失的工件与连接（红色虚线）", fontsize=8.6, fontweight="bold", color="#C0392B")
    missing = [
        (2, "analysis_contract\n目标/粒度/停止条件"),
        (18.2, "feature_risk\n泄漏/结果后字段"),
        (34.4, "split_plan\n时间/分组切分"),
        (50.6, "describe\n时序/分组描述"),
        (66.8, "claim_registry\n结论-证据映射"),
        (83.0, "report_lint\n证据/措辞验收"),
    ]
    for x, label in missing:
        box(ax, x, 6.2, 14.2, 7.0, label, "", RED, dashed=True, fs=6.9)

    # Connections
    arrow(ax, (23.5, 84), (23.5, 81.2))
    arrow(ax, (23.5, 73), (23.5, 70.2))
    arrow(ax, (23.5, 62), (23.5, 59.2))
    arrow(ax, (23.5, 51), (23.5, 48.2))
    arrow(ax, (23.5, 40), (23.5, 37.2))
    arrow(ax, (45, 33.1), (55, 87.0), color="#7F8C8D", rad=-0.18)
    arrow(ax, (76.5, 84), (76.5, 81.2), color="#7F8C8D")
    arrow(ax, (76.5, 73), (76.5, 70.2), color="#7F8C8D")
    arrow(ax, (76.5, 62), (76.5, 59.2), color="#7F8C8D")
    arrow(ax, (76.5, 51), (76.5, 48.2), color="#7F8C8D")
    arrow(ax, (76.5, 40), (76.5, 37.2), color="#7F8C8D")
    arrow(ax, (76.5, 29), (76.5, 26.2), color="#7F8C8D")

    # Broken / missing links
    arrow(ax, (16.5, 13.2), (20, 29), color="#C0392B", dashed=True, rad=0.15)
    arrow(ax, (45, 10), (55, 33), color="#C0392B", dashed=True, rad=-0.1)
    arrow(ax, (32.5, 13.2), (60, 73), color="#C0392B", dashed=True, rad=-0.12)
    arrow(ax, (70, 13.2), (75, 18), color="#C0392B", dashed=True, rad=0.1)
    arrow(ax, (93, 13.2), (78, 18), color="#C0392B", dashed=True, rad=0.1)

    ax.text(2, 3.4,
            "注意：文档声称的 leakage check / baseline 0.02 / 20% CV 稳定性，在 gate 中没有对应实现。\n"
            "P5 的“通过”不代表证据充分，只代表空输入时占位逻辑没有报错。",
            fontsize=7.6, color="#C0392B", va="top")



def render_target(ax):
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    ax.text(0, 99, "B. 目标：脚本算，Agent 判断，工件交接", fontsize=15, fontweight="bold", color="#17202A", va="top")
    ax.text(0, 95.2, "蓝色 = Agent 的判断；绿色 = 确定性脚本；黄色 = 分支工件。脚本只校验/计算，不替 Agent 选路线。",
            fontsize=8.2, color="#566573", va="top")

    # Lane labels
    ax.text(21, 92.2, "AGENT（判断）", fontsize=8.5, fontweight="bold", color=BLUE[1], ha="center")
    ax.text(78, 92.2, "SCRIPTS（确定性计算/校验）", fontsize=8.5, fontweight="bold", color=GREEN[1], ha="center")

    # Row 1
    box(ax, 2, 82.5, 38, 7.2, "定义决策问题", "决策、对象、时间窗口、成功标准、停止条件", BLUE, detail_offset=4.9)
    box(ax, 59, 82.5, 38, 7.2, "contract.py init/validate", "写 contract.json；校验 target/time/粒度存在", GREEN, detail_offset=4.9)
    arrow(ax, (40, 86.1), (59, 86.1), label="contract.json")

    # Row 2
    box(ax, 2, 71.5, 38, 7.2, "选定数据源与粒度", "选文件/Sheet/列；确认每一行代表什么", BLUE, detail_offset=4.9)
    box(ax, 59, 71.5, 38, 7.2, "io_router.py manifest/load", "列候选，不猜；显式 --file/--sheet", GREEN, detail_offset=4.9)
    arrow(ax, (40, 75.1), (59, 75.1), label="data_manifest.json")
    arrow(ax, (21, 82.5), (21, 78.7))

    # Row 3
    box(ax, 2, 60.5, 38, 7.2, "判断数据是否够用", "样本量、缺失、粒度、偏差；不够就停", BLUE, detail_offset=4.9)
    box(ax, 59, 60.5, 38, 7.2, "profile + clean", "画像/缺失/重复；只写显式 output", GREEN, detail_offset=4.9)
    arrow(ax, (40, 64.1), (59, 64.1), label="profile.json / cleaning_report.json")
    arrow(ax, (21, 71.5), (21, 67.7))

    # Row 4
    box(ax, 2, 49.5, 38, 7.2, "确认特征风险", "逐列判定风险标签；硬泄漏否决", BLUE, detail_offset=4.9)
    box(ax, 59, 49.5, 38, 7.2, "feature_risk.py scan/confirm", "机器扫描 + 人工确认；硬泄漏一票否决", GREEN, detail_offset=4.9)
    arrow(ax, (40, 53.1), (59, 53.1), label="feature_risk_report.json")
    arrow(ax, (21, 60.5), (21, 56.7))

    # Row 5
    box(ax, 2, 38.5, 38, 7.2, "选择路线并写理由", "选路线；写理由与 blockers", BLUE, detail_offset=4.9)
    box(ax, 59, 38.5, 38, 7.2, "route_decision validate", "只校验枚举/理由/前置工件", GREEN, detail_offset=4.9)
    arrow(ax, (40, 42.1), (59, 42.1), label="route_decision.json")
    arrow(ax, (21, 49.5), (21, 45.7))

    # Branch boxes
    branches = [
        (2, "描述", "describe.py\n趋势/分组/时序", GREEN),
        (26, "预测", "split_plan.py\nbaseline_runner.py", GREEN),
        (50, "因果", "causal_design.py\ncausal_analysis.py", GREEN),
        (74, "实验", "experiment_analysis.py\nSRM/平衡/功效", GREEN),
    ]
    for x, title, detail, colors in branches:
        box(ax, x, 27.0, 22, 8.0, title, detail, colors, fs=8.6, detail_offset=4.8, wrap_width=24)
    for x in (13, 37, 61, 85):
        arrow(ax, (21, 38.5), (x, 34.4), color="#7F8C8D", rad=0.0 if x == 21 else 0.05)

    # Execution + gate
    box(ax, 2, 16.8, 94, 6.4,
        "执行分支脚本 → 产出证据工件",
        "各分支报告 + 证据路径；结论先写 claim_registry",
        GRAY, fs=8.4, detail_offset=4.9)
    for x in (13, 37, 61, 85):
        arrow(ax, (x, 27.0), (x, 23.3), color="#7F8C8D")

    box(ax, 2, 7.2, 45, 6.6, "gate_evaluator.py（硬 gate）",
        "缺工件/硬泄漏/时间倒流 = 阻断或降级", GREEN, fs=8.4, detail_offset=4.9)
    box(ax, 51, 7.2, 45, 6.6, "report_bundle.py + report_lint.py",
        "只引用 claim_registry；lint 检查证据/章节", GREEN, fs=8.4, detail_offset=4.9)
    arrow(ax, (24.5, 16.8), (24.5, 13.8))
    arrow(ax, (47, 10.5), (51, 10.5))
    ax.text(49, 9.2, "gate_review.json", fontsize=6.4, color="#566573", ha="center", va="top",
            bbox=dict(facecolor="white", edgecolor="none", pad=0.4, alpha=0.9))

    # Feedback loop
    arrow(ax, (96.8, 10.5), (96.8, 42.0), color="#C0392B", dashed=True, rad=-0.25,
          label="gate/lint 失败：退回路线或停止")
    arrow(ax, (96.5, 42.0), (97.0, 42.0), color="#C0392B", dashed=True)

    ax.text(2, 1.4,
            "连接方式：JSON 工件 + 每个脚本的前置校验。分叉方式：Agent 决策表 + route_decision.json。\n"
            "不需要“总控脚本”替 Agent 决定路线；需要每个脚本拒绝不完整输入、gate 拒绝不完整证据。",
            fontsize=7.6, color="#566573", va="top")


def main():
    fig, (left, right) = plt.subplots(1, 2, figsize=(20, 14.2), gridspec_kw={"width_ratios": [1, 1]})
    fig.patch.set_facecolor("white")
    render_current(left)
    render_target(right)
    fig.suptitle("data-analysis-pro：从“工具堆”到“可审计的分析工作流”", fontsize=18, fontweight="bold", y=0.995)
    fig.text(0.5, 0.012,
             "绿色：已有且核心可用　｜　橙色：存在但有问题　｜　红色虚线：缺失/未实现　｜　蓝色：Agent 判断　｜　灰色：执行/证据层",
             ha="center", fontsize=8.2, color="#34495E")
    fig.tight_layout(rect=(0.01, 0.04, 0.99, 0.972))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=180, bbox_inches="tight", facecolor="white")
    print(OUT)


if __name__ == "__main__":
    main()
