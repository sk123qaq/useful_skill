# Workflow

## 0. 入口

先确认三件事，缺一不可：

1. 决策问题是什么（不是“分析一下”，而是“要决定什么”）。
2. 每一行代表什么（商品-月、会员-日、国家-月……）。
3. 有没有可用的结果变量和时间变量。

写不出 `analysis_contract.json`，就不要开始跑脚本。

## 1. 工件顺序

```text
analysis_contract.json
        │
        ├── data_manifest.json
        ├── profile.json
        ├── cleaning_report.json
        ├── features.json
        ├── feature_risk_report.json
        ├── route_decision.json
        │
        ├── describe.json                         (descriptive)
        ├── split_plan.json + baseline_results.json (predictive)
        ├── causal_design.json + causal_report.json (causal)
        └── experiment_report.json                (experiment)
        │
        └── gate_review.json
                │
                ├── claim_registry.json
                ├── report.md
                └── report_lint.json
```

每个工件都必须能独立打开、独立复核。不要用“上一个脚本的 stdout”当唯一记录。

## 2. 路由

| 条件 | 路由 |
|---|---|
| 只想看分布/趋势/结构 | `descriptive` |
| 有明确 target，且要预测未见样本 | `predictive` |
| 有处理/对照，且要估计效应 | `causal` |
| 有随机分流/实验 | `experiment` |
| 数据不够、口径不清、泄漏不可修复 | `stop_and_report` |

路由由 Agent 决定，写进 `route_decision.json`，理由和 blockers 都要写。脚本不替 Agent 选路。

## 3. 分叉口

- **目录 vs 文件**：`io_router.py manifest` 只列候选；Agent 显式选 `--input-path`，不自动选最大文件。
- **多 Sheet**：`manifest` 列出 Sheet；Agent 显式选 `--sheet`。
- **时间序列 vs 横截面**：有时间列且要做预测/因果 → `split_plan.py` 用 temporal/expanding/rolling；无时间列才允许 KFold。
- **预测 vs 因果**：预测只看可复现的泛化误差；因果必须先写识别假设。不要用预测模型的重要性代替因果效应。
- **继续 vs 停止**：gate 出 `not_usable` 就停；出 `exploratory` 可以交付，但必须降级措辞。

## 4. 停止条件

出现以下任一情况，停止当前分支，写 `stop_and_report`：

- target 缺失率 >50%，或关键字段不存在。
- 时间列无法解析（有效值 <80%）。
- 硬泄漏无法排除（target 副本、未来变量、结果变量）。
- 预测分支没有非 dummy 模型，或 CV 极不稳定（std/mean>0.2）。
- 因果分支识别假设不成立（无重叠、平行趋势不成立、工具变量不满足排除性）。
- 实验 SRM p≤0.001 或分流比例异常。

停止不是失败；把“为什么不能继续”写清楚，比硬编一个结论更有价值。

## 5. 交付前

- `gate_review.json` 存在且等级明确。
- `claim_registry.json` 每条 claim 有 `supported_by`。
- `report_lint.py` 通过。
- 最终答复先给结论，再给证据路径和局限；不要只给“报告见附件”。
