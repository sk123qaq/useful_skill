# Gate Rules

`gate_evaluator.py --run-dir <run>` 读取固定工件，输出 `gate_review.json`。它不读 Agent 的口头解释。

## 输入

| 工件 | 必需分支 |
|---|---|
| `analysis_contract.json` | 全部 |
| `profile.json` | 全部 |
| `cleaning_report.json` | 全部（可缺省但会 warning） |
| `feature_risk_report.json` | predictive / causal / experiment |
| `split_plan.json` | predictive / causal（有时间列时） |
| `baseline_results.json` | predictive |
| `causal_design.json` + `causal_report.json` | causal |
| `experiment_report.json` | experiment |
| `claim_registry.json` | 交付前 |
| `report_lint.json` | 交付前 |

## 九道 gate

### 1. contract

- 缺文件 / 缺 `decision_question`、`task`、`unit_of_analysis`、`success_criteria`、`stop_conditions` → fail。
- `task` 不在允许集合 → fail。

### 2. data_quality

- `row_count < 30` → fail。
- target 缺失率 >0.50 → fail。
- cleaning 后 0 行 → fail。

### 3. feature_risk

- 预测/因果/实验缺 `feature_risk_report.json` → fail。
- 任一 `used=true` 且 `label=hard_leakage` 或 `post_outcome` → fail。
- 任一 `confirmed=false` → fail（Agent 必须逐列确认）。
- `collection_artifact` 且 `used=true` → fail；标 `used=false` 可过。

### 4. split

- 预测/因果缺 `split_plan.json` → fail。
- 索引越界/重叠/测试折重叠 → fail。
- 时间列存在但 strategy=`kfold` → fail。
- 时间策略训练时间 ≥ 测试时间 → fail。

### 5. baseline

- 预测分支缺 `baseline_results.json` → fail。
- 没有非 dummy 模型 → fail。
- 非 dummy 不赢 dummy（分类 <+0.02，回归 <5%）→ exploratory。
- CV std/mean >0.2 → exploratory。
- `exploratory` 可以交付，但报告不能写“可靠预测”。

### 6. causal

- 缺 design/report → exploratory。
- design 缺 estimand/treatment/outcome/identification_assumptions → exploratory。
- 识别假设不成立（由 Agent 在 design 里写）→ 应走 `stop_and_report`，不要硬估。

### 7. experiment

- 缺 report → exploratory。
- SRM p≤0.001 → fail。
- 平衡性失败 → fail。脚本按 Bonferroni 阈值 `alpha/协变量数` 判 fail；单个协变量 `p<alpha` 只记 `marginal`，不单独阻断。
- 多重检验未校正 → warning；主效应解释要降级。

### 8. claims

- claim 的 `supported_by` 路径不存在 → warning（最终由 report_lint 判 fail）。
- 等级不在 `report-ready/exploratory/not_usable` → warning。
- 没有 claim → 不阻塞 gate，但 `report_bundle` 会拒绝空 claim。

### 9. report

- `report_lint.json` 存在且 passed → pass。
- 不存在 → not_applicable；交付前必须补。

## 等级

| 等级 | 含义 | 允许措辞 |
|---|---|---|
| `report-ready` | 所有硬 gate 通过，claim 有证据 | “结果表明……” |
| `exploratory` | 有结果，但基线/稳定性/因果假设/claim 有缺口 | “初步提示……，需进一步验证” |
| `not_usable` | 数据/契约/泄漏/切分/基线缺失 | “当前数据不足以支持该结论” |

空 run dir 必须是 `not_usable`。任何“没有输入却 report-ready”的实现都是 bug。

## 修复顺序

1. 先修 blocker（契约、数据、泄漏、切分、baseline）。
2. 再补 claim 证据。
3. 最后跑 report_lint。
4. 修不了就降级，不要改 gate 结果。
