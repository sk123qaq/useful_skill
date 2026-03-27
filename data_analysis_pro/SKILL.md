---
name: data-analysis-pro
description: 专业级结构化数据分析工具箱。采用“乐高式”原子能力设计，支持探索性数据分析（EDA）、预处理、特征发现、因果推断及基线建模。
---

# 数据分析专业版 (Data Analysis Pro)

本技能是一个面向专业数据分析的“工具箱”式 Skill。它抛弃了死板的流水线，为 Agent（大脑）提供了独立、原子的 CLI 工具，支持灵活组合以解决复杂的分析问题。

## 设计理念

- **工具箱优于流水线**：为特定任务选择特定工具，不强制所有数据都走相同的流程。
- **Agent 负责规划**：你（Agent）是分析架构师，根据数据现状决定分析路径，脚本只是你的专业仪器。
- **原子化能力**：每个脚本只做好一件事（例如 `column_profile.py` 负责画像，`causal_analysis.py` 负责因果）。
- **人机协同**：遇到业务口径或决策疑点时，及时停止并询问用户。

## 使用原则

- 先读 `SKILL.md`，再按这里明确列出的 reference 做按需阅读，不要默认扫完整个 `references/`。
- 只有具备独立分析价值的 CLI 脚本才算对外工具；纯实现模块不应当被当作主入口。
- 如果某个 reference 没在这里被声明为入口或按需参考，就不要假设它一定会在实际使用时被读取。

## 快速开始

```bash
# 1. 检查环境与中文字体
python3 data_analysis_pro/scripts/check_environment.py

# 2. 数据初步探查与画像 (QC)
python3 data_analysis_pro/scripts/io_router.py --input-path data.csv
python3 data_analysis_pro/scripts/column_profile.py --input-path data.csv --target label

# 3. 筛选重要特征与关系
python3 data_analysis_pro/scripts/relationship_screening.py --input-path data.csv --target label

# 4. 执行专项分析 (以因果推断为例)
# 支持 dml_lite 任务和自动混杂因子建议
python3 data_analysis_pro/scripts/causal_analysis.py --input-path data.csv --task dml_lite --config-json '{"outcome_col": "y", "treatment_col": "t"}'

# 5. 准入复核 (Gate Check)
python3 data_analysis_pro/scripts/gate_evaluator.py --input-path outputs/analysis_result.json

# 6. 整合产出最终报告
python3 data_analysis_pro/scripts/report_export.py --artifacts-dir outputs/my_analysis --output-path report.md
```

## 核心工具 (乐高积木)

### 1. 基础与加载
- `check_environment.py`：验证依赖项、运行时环境及中文字体可用性。参考 `references/environment.md`。
- `io_router.py`：智能解析输入路径（CSV, Parquet, Excel, ZIP, 目录），并规划读取策略。参考 `references/io-strategy.md`。

### 2. 探索与画像
- `column_profile.py`：详细的列级统计、缺失率、基数检查及异常标识。
- `eda_stats.py`：快速统计摘要、相关性矩阵及正态性检验。参考 `references/stats-and-tests.md`。
- `relationship_screening.py`：按变量类型自动做关系筛查，帮助找到最值得继续分析的字段。参考 `references/analysis-methods.md`。

### 3. 预处理与清洗
- `preprocessing.py`：统一的清洗工具，支持缺失值填充、重复检查、按业务键去重、类别编码及日历特征生成。

### 4. 专项分析
- `causal_analysis.py`：高级因果推断套件。现已支持 **`dml_lite`**（轻量化双重机器学习）任务，并提供基于变量相关性的**自动混杂因子（Confounding Factors）建议**功能。支持 DID, PSM, IV, DR, RDD, 合成控制, Uplift 等。参考 `references/causal-inference.md`。
- `causal_narrative.py`：把已有因果分析结果整理成可交付的 narrative JSON / Markdown。
- `experiment_analysis.py`：A/B 测试分析，包含显著性检验与样本量评估。参考 `references/experiment-design.md`。
- `baseline_runner.py`：用于 Python 调用的预测基线助手（分类/回归），适合和其他原子工具组合使用。参考 `references/model-selection.md`。
- `model_explainability.py`：模型可解释性分析（特征重要性、SHAP 值）。参考 `references/explainability.md`。

### 5. 验证与交付
- `gate_evaluator.py`：**独立 CLI 工具**，负责对分析结论进行准入复核。支持**稳定性（Stability）**校验（如样本量、分布偏移）和**业务直觉（Intuition）**校验（如系数正负号逻辑）。参考 `references/gate-rules.md`。
- `report_export.py`：**交付引擎**。负责将过程中产生的所有 JSON 数据、图片工件（PNG/JPG）以及叙述片段自动整合为结构化的最终 Markdown 报告。参考 `references/reporting.md`。

## 按需参考

### 主流程与降级

- `references/workflow.md`：整体路由、分析顺序、最小前提与“什么时候停下来”。
- `references/failure-recovery.md`：脚本失败或条件不满足时如何降级、如何诚实交付。

### 分析与建模守则

- `references/analysis-methods.md`：关系筛查与变量类型判断。
- `references/stats-and-tests.md`：描述统计、相关与检验的使用边界。
- `references/model-selection.md`：基线建模入口建议。
- `references/modeling-policy.md`：预测路径 guardrails 与“何时不该继续加模型”。
- `references/causal-inference.md`：因果分析方法前提。
- `references/experiment-design.md`：实验分析前提与解释边界。
- `references/explainability.md`：特征重要性、PDP、SHAP 的解释边界。
- `references/gate-rules.md`：结果复核规则。

### 交付与解释

- `references/reporting.md`：默认交付结构、叙述等级、工件阅读顺序与证据解释。

### 专项场景参考

- `references/chart-selection.md`：需要补图或建议图表类型时再读。
- `references/business-metrics.md`：需要业务指标口径时再读。
- `references/report-delivery-templates-zh.md`：用户明确要正式中文 DOCX / PDF 时再读。
- `references/web-research-rules.md`：只有本地数据不足且必须补外部背景时再读。

## 内部模块

以下文件属于实现依赖，不是默认直接调用入口：

- `scripts/common.py`
- `scripts/model_catalog.py`
- `scripts/model_runner.py`
- `scripts/schemas.py`

## 推荐工作流程 (6 阶段)

1.  **问题定义 (Problem Definition)**：明确分析目标（描述/预测/因果）、核心指标（Target）以及业务决策场景。
2.  **画像与 QC (Profiling & QC)**：运行 `column_profile.py` 探查数据质量，识别缺失、异常及重复，必要时使用 `preprocessing.py` 清洗。
3.  **关系筛查 (Relationship Screening)**：通过 `relationship_screening.py` 自动化探索变量间的关联，识别驱动因素。
4.  **专项分析 (Specialized Analysis)**：根据目标选择 `causal_analysis.py`（因果归因）、`experiment_analysis.py`（实验评估）或 `baseline_runner.py`（预测建模）。
5.  **准入复核 (Gate Review)**：强制执行 `gate_evaluator.py`，确保结论在统计上稳定且符合业务直觉，防止过度解读。
6.  **报告交付 (Report Delivery)**：运行 `report_export.py` 整合所有过程工件，产出报告素材。
    - **【强制自动化指令：双代理协作】**：在出具最终 Markdown 报告时，主 Agent 必须**自动且无需用户提示地**启动两个子进程/角色：
      1. **生成器 (Report Generator)**：基于 `report_export.py` 提供的素材和 `REPORT_SPEC.md` 编写包含业务洞察的初稿。
      2. **验收器 (Report Validator)**：严格对照 `REPORT_SPEC.md` 的要求进行审核。只有当验收器通过后，主 Agent 才能将最终报告输出给用户。如果未通过，生成器需自动重写。

## 约束与原则

- **非黑盒化**：如果脚本报错，请阅读其代码。它们被设计为可读且易于按需修改。
- **显式目标**：对于任何非平凡任务，必须明确定义 `target`（目标变量）。
- **先确认行粒度再去重**：去重前必须先说明“每一行代表什么”，并优先按业务键检查重复。
- **大文件处理**：对于超过 1GB 的数据，在探索阶段建议使用 `--sample-rows` 采样以保持响应速度。
