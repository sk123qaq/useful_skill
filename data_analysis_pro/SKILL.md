---
name: data-analysis-pro
description: 专业级结构化数据分析工具箱。采用“乐高式”原子能力设计，支持探索性数据分析（EDA）、预处理、特征发现、因果推断及基线建模。
---

# 数据分析专业版 (Data Analysis Pro)

本技能是一个面向专业数据分析的“工具箱”式 Skill。它抛弃了死板的流水线，为 Agent（大脑）提供了独立、原子的 CLI 工具，支持灵活组合以解决复杂的分析问题。

## 设计理念

- **工具箱优于流水线**：为特定任务选择特定工具，不强制所有数据都走相同的 12 步流程。
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

# 2. 数据初步探查
python3 data_analysis_pro/scripts/io_router.py --input-path data.csv
python3 data_analysis_pro/scripts/column_profile.py --input-path data.csv --target label

# 3. 筛选重要特征与关系
python3 data_analysis_pro/scripts/relationship_screening.py --input-path data.csv --target label

# 4. 执行专项分析
# 因果推断: did, psm, iv, dml, dr, rd, synthetic-control, uplift
python3 data_analysis_pro/scripts/causal_analysis.py --input-path data.csv --task psm --config-json '{"outcome_col": "y", "treatment_col": "t", "covariate_cols": ["x1", "x2"]}'
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
- `causal_analysis.py`：高级因果推断套件（支持 DID, PSM, IV, DML, DR, RDD, 合成控制, Uplift 等）。参考 `references/causal-inference.md`。
- `causal_narrative.py`：把已有因果分析结果整理成可交付的 narrative JSON / Markdown。
- `experiment_analysis.py`：A/B 测试分析，包含显著性检验与样本量评估。参考 `references/experiment-design.md`。
- `baseline_runner.py`：用于 Python 调用的预测基线助手（分类/回归），适合和其他原子工具组合使用。参考 `references/model-selection.md`。
- `model_explainability.py`：模型可解释性分析（特征重要性、SHAP 值）。参考 `references/explainability.md`。

### 5. 验证与评估
- `gate_evaluator.py`：用于 Python 调用的结果复核助手，帮助检查结论是否过度解读。参考 `references/gate-rules.md`。

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

只有在阅读代码、排查实现或按需扩展脚本时，才需要进入这些模块。

## 推荐工作方式

1. **明确问题**：在开始前，确定目标是“描述性”、“预测性”还是“因果性”。
2. **数据画像**：优先运行 `column_profile.py`。若数据脏乱，使用 `preprocessing.py` 进行清洗。
3. **深入分析**：
   - 现状是什么？使用 `eda_stats.py` 和 `relationship_screening.py`。
   - 为什么会这样？使用 `causal_analysis.py` 进行因果归因。
4. **合成结论**：将当前阶段已经产出的 JSON、PNG、CSV 等工件整理成一个工作报告 `.md` 文件，明确写出问题定义、已执行步骤、当前发现、限制、以及下一步建议；不要补写未运行内容。

## 约束与原则

- **非黑盒化**：如果脚本报错，请阅读其代码。它们被设计为可读且易于按需修改。
- **显式目标**：对于任何非平凡任务，必须明确定义 `target`（目标变量）。
- **先确认行粒度再去重**：去重前必须先说明“每一行代表什么”，并优先按业务键（如 `user_id + date`、`order_id`）检查重复；完全相同的两行不一定是脏数据，也可能是两次真实观测。
- **大文件处理**：对于超过 1GB 的数据，在探索阶段建议使用 `--sample-rows` 采样以保持响应速度。

## 重复值处理建议

- 默认先做“检查”，不要因为看见重复行就立即删除。
- 如果只是想评估风险，可在 `--config-json` 中提供 `duplicate_check.key_columns`，让 `preprocessing.py` 按业务键统计重复组。
- 只有在确认“重复代表录入/抽取错误”后，再启用 `drop_duplicates`。
- `drop_duplicates` 既支持布尔值，也支持对象配置；更推荐显式写出 `subset`。

示例：

```bash
# 只检查按业务键的重复，不删除
python3 data_analysis_pro/scripts/preprocessing.py \
  --input-path data.csv \
  --config-json '{"duplicate_check": {"key_columns": ["user_id", "event_date"]}}'

# 确认口径后，按业务键去重
python3 data_analysis_pro/scripts/preprocessing.py \
  --input-path data.csv \
  --config-json '{"drop_duplicates": {"subset": ["order_id"], "keep": "first"}}'
```
