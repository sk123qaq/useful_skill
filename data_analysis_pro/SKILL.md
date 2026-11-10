---
name: data-analysis-pro
description: 专业级结构化数据分析工作流。用契约固定问题，用脚本产出可复核证据，用 gate 决定证据等级；支持描述、预测、因果、实验四条分支。
---

# Data Analysis Pro

这是一个**工作流**，不是模型/脚本清单。Agent 负责语义判断，脚本负责确定性计算与校验。任何结论都必须能追溯到工件，并且通过 gate。

## 何时用

- 用户拿来一份或一组数据，要求“看看有什么”“预测一下”“为什么”“评估实验”。
- 需要可复核的统计结论，而不是一段无法追溯的叙述。
- 需要把分析过程交给别人复现或验收。

不适用：纯数据抽取/清洗交付、纯图表美化、没有数据支撑的行业研究。

## 核心原则

1. **先定问题，再看数据**。没有 `analysis_contract.json` 不进入分析。
2. **Agent 做判断，脚本做计算**。路由、特征语义、业务口径、结论取舍由 Agent 决定；排序、切分、拟合、校验由脚本完成。
3. **一切结论有工件**。`claim_registry.json` 的每条 claim 必须指向真实文件。
4. **Gate 不猜**。空输入不是 `report-ready`；缺失 baseline 不是 pass；硬泄漏一票否决。
5. **不伪造**。脚本失败就报告失败；没有跑的检验不许写进结论。

## 快速开始

```bash
SKILL=/home/shike/.agents/skills/data_analysis_pro
RUN=outputs/run-001
mkdir -p "$RUN"

python "$SKILL/scripts/check_environment.py" --output-path "$RUN/env_snapshot.json"

# 1. 契约：问题、任务、目标、时间、数据源、成功/停止条件
python "$SKILL/scripts/contract.py" init \
  --question "什么因素预测次月进口量？" \
  --task predictive \
  --target next_value \
  --time-col month \
  --unit-of-analysis "商品-月" \
  --data-source data/imports.csv \
  --success-criteria "beat dummy by 0.02 AUC 或 5% RMSE" \
  --stop-conditions "关键字段缺失>50%" \
  --output-path "$RUN/analysis_contract.json"

# 2. 数据清单：目录不猜文件，显式选择
python "$SKILL/scripts/io_router.py" manifest --input-path data/ --output-path "$RUN/data_manifest.json"

# 3. 画像 + 清洗
python "$SKILL/scripts/column_profile.py" --input-path data/imports.csv --target next_value --output-path "$RUN/profile.json"
python "$SKILL/scripts/clean.py" --input-path data/imports.csv --output-path "$RUN/clean.csv" \
  --report-path "$RUN/cleaning_report.json" --target next_value --time-col month

# 4. 特征风险（预测/因果/实验必做）
python "$SKILL/scripts/features.py" --input-path "$RUN/clean.csv" --output-path "$RUN/features.csv" \
  --report-path "$RUN/features.json" --time-col month --calendar
python "$SKILL/scripts/feature_risk.py" scan --input-path "$RUN/features.csv" \
  --contract "$RUN/analysis_contract.json" --output-path "$RUN/feature_risk_report.json"
# Agent 逐列确认（所有特征列都要列出；可标 used=false 排除时间键/ID）
python "$SKILL/scripts/feature_risk.py" confirm --report "$RUN/feature_risk_report.json" \
  --labels '{"month":{"label":"collection_artifact","used":false},"value":{"label":"safe"}}' \
  --output-path "$RUN/feature_risk_report.json"

# 5. 路由决策（Agent 写理由，脚本只校验）
python "$SKILL/scripts/route.py" init --route predictive --reasons "有目标、有时间、可回测" \
  --output-path "$RUN/route_decision.json"
```

## 工作流

```text
P1 问题定义 → contract.json
P2 数据清单/画像/清洗 → data_manifest.json, profile.json, cleaning_report.json
P3 特征风险 → features.json, feature_risk_report.json
P4 路由 → route_decision.json
P5 分支执行 → describe.json | split_plan.json + baseline_results.json |
                causal_design.json + causal_report.json | experiment_report.json
P6 gate → gate_review.json → claim_registry.json → report.md → report_lint.json
```

P4 之后只走一条分支。不要为了“更全面”同时跑预测和因果；也不要在 P3 未确认时进入 P5。

### 路由表

| 问题 | route | 最低工件 |
|---|---|---|
| 分布、趋势、结构、分组差异 | `descriptive` | `describe.json` |
| 预测/分类/排序 | `predictive` | `split_plan.json` + `baseline_results.json` |
| 处理/政策/事件的效果 | `causal` | `causal_design.json` + `causal_report.json` |
| A/B、分流、SRM、功效 | `experiment` | `experiment_report.json` |
| 数据不足/口径不清/泄漏不可修复 | `stop_and_report` | `gate_review.json` |

## 脚本

| 脚本 | 作用 | 关键规则 |
|---|---|---|
| `contract.py` | 写/校验分析契约 | 无契约不分析；预测/因果/实验必须有 target |
| `io_router.py` | 列文件、列 Sheet、显式加载 | 目录只列候选，不自动选；CSV 注释要显式 `--comment` |
| `column_profile.py` | 列级画像 | target 不存在直接失败 |
| `clean.py` | 去重、缺失处理、类型整理 | 输出清洗报告；不静默改口径 |
| `features.py` | 日历/编码/列筛选 | 只生成声明过的特征；记录生成规则 |
| `feature_risk.py` | 泄漏/结果变量/代理变量扫描与确认 | 硬泄漏阻断；每列必须确认 |
| `route.py` | 记录/校验 Agent 的路由决策 | 只校验，不替 Agent 选路 |
| `split_plan.py` | 时间/扩展/滚动/KFold/Group 切分 | 时间序列默认 temporal；随机 KFold 只用于非时序 |
| `describe.py` | 描述统计、分组、时间序列、异常 | 不做因果措辞；样本量不足要写进局限 |
| `baseline_runner.py` | 预测基线 CLI | 必须和 dummy 比；稳定性看 CV 离散度，不看 train/test 单次差 |
| `causal_design.py` | 锁定 estimand/处理/结果/识别假设 | 假设未写清不进入估计 |
| `causal_analysis.py` | DID/PSM/IV/DML/RDD/合成控制等 | 大套件；先 design 后估计；结果必须回到 gate |
| `experiment_analysis.py` | 两臂实验、SRM、功效、校正 | 分流比例异常先停，不解释主效应 |
| `model_explainability.py` | 特征重要性/PDP/SHAP | 解释不是因果；记录 fit_scope |
| `gate_evaluator.py` | 九道硬 gate | 空目录=`not_usable`；缺 baseline/硬泄漏=blocker |
| `report_bundle.py` | 按 claim 组装报告 | 不发明结论；缺 claim 只给模板 |
| `report_lint.py` | 报告/claim/gate 一致性 | claim 无证据、等级越级、章节缺失都失败 |
| `check_environment.py` | 依赖/字体检查 | 只读；快照路径显式 |

内部模块：`common.py`、`workflow.py`、`schemas.py`、`model_catalog.py`、`model_runner.py`、`preprocessing.py`。它们不是主入口。

## 分支打法

### 描述性

1. `describe.py` 出数值/分类/时间序列/分组。
2. Agent 只写“看到了什么”，不写“导致了什么”。
3. 结论进 claim，证据指向 `describe.json` 或图。

### 预测

1. 先 `split_plan.py create`。时间列必须 temporal/expanding/rolling；禁止随机 KFold。
2. `baseline_runner.py` 至少 dummy + 一个非 dummy；分类看提升≥0.02，回归看误差下降≥5%。
3. 稳定性看各折 std/mean≤0.2；不满足只能标 exploratory。
4. 不要用同一批特征做目标泄漏；`feature_risk.py` 未确认不跑。

```bash
python "$SKILL/scripts/split_plan.py" create --input-path "$RUN/features.csv" \
  --time-col month --target value --strategy temporal --n-splits 4 --output-path "$RUN/split_plan.json"
python "$SKILL/scripts/baseline_runner.py" --input-path "$RUN/features.csv" \
  --output-path "$RUN/baseline_results.json" --target value --task regression \
  --time-col month --split-plan "$RUN/split_plan.json" \
  --models dummy_mean,linear_regression,random_forest_regressor --max-level 2
```

### 因果

1. `causal_design.py init` 写清 estimand、treatment、outcome、识别假设、调整集。
2. 没有重叠/平行趋势/排除性约束等假设，不得进入估计。
3. `causal_analysis.py` 的 task/config 必须与 design 对齐；结果写 `causal_report.json`。
4. 估计显著不等于识别成立；claim 里必须带假设与局限。

```bash
python "$SKILL/scripts/causal_design.py" init --estimand ATT --treatment treat --outcome y \
  --design psm --assumptions "conditional exchangeability,common support" \
  --adjustment "x1,x2" --data-path "$RUN/features.csv" --output-path "$RUN/causal_design.json"
python "$SKILL/scripts/causal_analysis.py" --input-path "$RUN/features.csv" --task psm \
  --output-dir "$RUN" --config-json "$RUN/causal_config.json"
```

`--output-dir` 是 run 根目录，脚本不再自动套时间戳子目录；`--config-json` 同时接受 inline JSON 和文件路径。

### 实验

1. 先查 SRM；p≤0.001 或分流比例异常 → 停。
2. 再做平衡性、主效应、功效、多重检验校正。
3. 结果写 `experiment_report.json`；不要用“显著”替代“业务上重要”。

```bash
python "$SKILL/scripts/experiment_analysis.py" --input-path "$RUN/features.csv" \
  --config-json "$RUN/experiment_config.json" --output-path "$RUN/experiment_report.json"
```

报告顶层会写 `srm_p_value`、`balance_passed`、`balance_test`、`primary_metric/effect/p_value`；`balance_passed` 用 Bonferroni 阈值（alpha/协变量数），单个协变量 p<alpha 只记为 marginal。

## Gate 与证据等级

`gate_evaluator.py --run-dir <run>` 输出 `gate_review.json`：

- `report-ready`：契约、数据、特征风险、切分、基线/因果/实验、claim、lint 都过。
- `exploratory`：有结果但基线不赢 dummy、CV 不稳、因果假设不完整、claim 缺证据。
- `not_usable`：空目录、契约缺失、数据质量不过、硬泄漏、缺切分/基线、实验 SRM 失败。

硬规则：

- 空 run dir 绝不返回 `report-ready`。
- `hard_leakage` 或 `post_outcome` 且 `used=true` → blocker。
- 时间序列用随机 KFold → blocker。
- 缺 `baseline_results.json` → blocker（预测分支）。
- claim 的 `supported_by` 必须存在；等级不能高于 gate。
- `report_lint.py` 未通过，不交付。

## 交付

1. Agent 写 `claim_registry.json`：每条一个结论，`supported_by` 指向真实工件。
2. `report_bundle.py --run-dir <run>` 生成 `report.md`（只使用 claim）。
3. `report_lint.py --run-dir <run>` 通过后，才能把报告给用户。
4. 最终答复先给 3–6 条结论，再给证据路径、局限、未做的事。

```bash
python "$SKILL/scripts/report_bundle.py" --run-dir "$RUN"
python "$SKILL/scripts/report_lint.py" --run-dir "$RUN"
```

## 失败时

- 脚本报错：保留 stderr，修输入/配置；不要改用“看起来差不多”的脚本。
- 数据不够：降级为 `descriptive` 或 `stop_and_report`，在报告里写清缺什么。
- 泄漏不可修复：停止预测/因果，输出数据审计，不输出模型结论。
- Gate 失败：按 blocker 修；修不了就降级，不改 gate 结果。

## 参考

按需读，不要一次全读：

- `references/workflow.md`：工件顺序、路由、停止条件。
- `references/io-strategy.md`：目录/Sheet/CSV 注释/编码。
- `references/analysis-methods.md`：描述、分组、时间序列、特征风险。
- `references/modeling-policy.md`：切分、基线、稳定性、何时停止加模型。
- `references/causal-inference.md`：DID/PSM/IV/DML/RDD 的识别前提。
- `references/experiment-design.md`：SRM、平衡、功效、多重检验。
- `references/gate-rules.md`：九道 gate 的通过/降级条件。
- `references/reporting.md`：claim、报告结构、证据等级。
- `references/failure-recovery.md`：失败与降级。
- `references/environment.md`：依赖与字体。
- `references/worked-examples.md`：NSW 因果（PSM/DML）与议员邮件实验的完整命令、结果和解读边界。
- `references/explainability.md`：模型解释边界。
- `references/chart-selection.md`、`references/business-metrics.md`、`references/report-delivery-templates-zh.md`、`references/web-research-rules.md`：按需的可选参考。

已废弃：`scripts/_deprecated/` 下的 `eda_stats.py`、`relationship_screening.py`、`report_export.py`、`metadata_manager.py`、`infer_business_meanings.py`。不要调用。
