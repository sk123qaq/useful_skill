# BRFSS 2024 肥胖预测分析中文报告

## 1. 执行摘要

本次分析使用 `data_analysis_V2` skill 对 BRFSS 2024 的肥胖建模样本进行了完整的 V2 流程分析，目标变量为 `obese`，任务类型为二分类预测。数据共 60,000 行、18 列，目标变量中 `obese=1` 的样本为 20,344 条，占比约 33.91%，`obese=0` 为 39,656 条，占比约 66.09%。

本次运行被系统路由到 `predictive` 路径，并顺序完成了分析合同确认、数据 scout 审计、特征风险审计、基线模型阶梯、可解释性产物生成、gate 审核、证据分级与正式报告导出。最终，最佳模型为 `logistic_regression`，平均准确率约为 `0.6900`，优于 dummy baseline 的 `0.6609`，提升约 `2.91` 个百分点；稳定性 gate 与特征风险 gate 也均通过，因此本次 run 的最高证据等级被评为 `report-ready`。

但需要强调的是，这里的“可报告”仅表示当前模型在既定规则下存在可以陈述的预测信号，不表示可以把这些变量直接解释为因果因素，也不表示可以把模型输出直接用于医疗诊断、因果干预或个体级高风险决策。

## 2. 本次分析实际执行了什么

本次运行实际完成了以下步骤：

1. 建立分析合同 `analysis_contract.json`
2. 对输入数据执行 scout 审计 `scout_report.json`
3. 对全部候选特征执行风险审计 `feature_risk_report.json`
4. 根据任务和数据状态进行问题路由 `route_decision.json`
5. 执行基线优先建模 `baseline_results.json`
6. 生成受保护的可解释性产物 `explainability_guarded.json`
7. 执行四类 gate 审核 `gate_review.json`
8. 生成证据等级与叙事边界 `judgment_bundle.json`
9. 生成 claim registry 与报告 bundle
10. 导出英文简版正式报告 `formal_report_v2.md`
11. 导出本中文报告 `formal_report_v2_zh.md`

## 3. 分析合同与任务定义

本次分析合同如下：

- 业务问题：`Predict obesity risk from BRFSS survey features and report only evidence-safe conclusions.`
- 任务类型：`classification`
- 目标变量：`obese`
- 数据范围：`full`
- 时间列：无
- checkpoint 行为：已显式允许继续通过 scout 与 baseline 两个检查点

这意味着本次不是描述性分析，也不是因果分析，而是一个明确目标变量驱动的监督学习预测任务。

## 4. 数据概览

### 4.1 数据规模

- 总行数：60,000
- 总列数：18
- 重复行数：437
- 重复率：0.7283%
- 缺失值：所有字段缺失率均为 0

### 4.2 字段清单

本次用于分析的字段包括：

- `state`
- `sex`
- `age_group`
- `general_health`
- `physical_unhealthy_days_bucket`
- `mental_unhealthy_days_bucket`
- `personal_doctor`
- `medical_cost_barrier`
- `recent_checkup`
- `exercise_past_30d`
- `leisure_time_activity`
- `ever_smoked_100`
- `income_bracket`
- `education_level`
- `diabetes_status`
- `heart_disease`
- `asthma_status`
- `obese`

其中，除 `obese` 外，其余 17 个字段均作为候选预测特征。

### 4.3 类别层级数量

- `state`: 53
- `sex`: 2
- `age_group`: 14
- `general_health`: 6
- `physical_unhealthy_days_bucket`: 6
- `mental_unhealthy_days_bucket`: 6
- `personal_doctor`: 4
- `medical_cost_barrier`: 3
- `recent_checkup`: 6
- `exercise_past_30d`: 3
- `leisure_time_activity`: 3
- `ever_smoked_100`: 3
- `income_bracket`: 12
- `education_level`: 7
- `diabetes_status`: 5
- `heart_disease`: 3
- `asthma_status`: 3

### 4.4 目标变量分布

- `obese=0`: 39,656
- `obese=1`: 20,344
- 肥胖样本占比：33.91%

这说明数据并不是完全均衡的二分类数据，直接预测多数类就可以拿到约 66% 的准确率，因此 baseline 比较非常关键。

## 5. 路由结果

系统路由结果为 `predictive`，原因是：

- 目标变量 `obese` 已明确定义
- 用户问题本身是预测型问题
- 特征风险审计未发现必须立即停止的 `hard_leakage`

因此，本次没有走 `descriptive`、`causal` 或 `stop_and_report` 分支，而是进入了监督学习 baseline ladder。

## 6. 特征风险审计

### 6.1 审计结果概览

- `safe`: 15 个
- `soft_proxy`: 2 个
- `post_outcome`: 0 个
- `hard_leakage`: 0 个
- `collection_artifact`: 0 个

### 6.2 被标记为 `soft_proxy` 的字段

- `physical_unhealthy_days_bucket`
- `mental_unhealthy_days_bucket`

它们没有被系统认定为硬泄漏，但被视为“可能间接代理目标状态”的字段，因此需要在解释阶段保持谨慎，避免把它们直接翻译成可操作的因果建议。

### 6.3 审计结论

本次特征风险审计没有发现会直接阻断建模的高风险字段，因此允许继续进入 baseline 建模阶段。

## 7. 基线优先建模结果

### 7.1 模型运行顺序

V2 按既定阶梯顺序运行了 3 个模型：

1. `dummy_most_frequent`
2. `logistic_regression`
3. `random_forest_classifier`

这符合 V2 的 baseline-first 规则，即先验证“是否真的优于简单多数类规则”，再讨论更复杂模型。

### 7.2 主要指标

主指标为 `accuracy`，优化方向为 `max`。

#### dummy baseline

- 模型：`dummy_most_frequent`
- 平均准确率：`0.6609`
- 平均 `f1_macro`：`0.3979`
- `accuracy` 标准差：`0.0000`

解释：
这个模型只预测多数类，但由于数据中非肥胖样本占比约 66%，所以它已经能达到约 66% 的准确率。任何“有用的”模型都至少要稳健地超过这个门槛。

#### logistic regression

- 模型：`logistic_regression`
- 平均准确率：`0.6900`
- 平均 `f1_macro`：`0.5906`
- `accuracy` 标准差：`0.0049`

解释：
逻辑回归是本次表现最好的模型。与 dummy 相比，准确率提升约 `0.0291`，也就是 `2.91` 个百分点。同时，宏平均 F1 从 `0.3979` 提升到 `0.5906`，说明它不仅整体准确率更高，对两类样本的综合区分能力也明显优于纯多数类预测。

#### random forest

- 模型：`random_forest_classifier`
- 平均准确率：`0.6747`
- 平均 `f1_macro`：`0.5789`
- `accuracy` 标准差：`0.0044`

解释：
随机森林也优于 dummy，但不如逻辑回归，说明在当前这组离散问卷特征上，更复杂的树模型并没有带来额外收益。

### 7.3 五折结果

#### logistic regression 五折准确率

- Fold 1: `0.6876`
- Fold 2: `0.6854`
- Fold 3: `0.6911`
- Fold 4: `0.6990`
- Fold 5: `0.6870`

#### random forest 五折准确率

- Fold 1: `0.6757`
- Fold 2: `0.6693`
- Fold 3: `0.6778`
- Fold 4: `0.6806`
- Fold 5: `0.6701`

从折间表现看，逻辑回归各折波动不大，稳定性较好。

## 8. 可解释性输出

本次 explainability 产物的前五个高权重字段如下：

1. `general_health`
2. `diabetes_status`
3. `age_group`
4. `exercise_past_30d`
5. `leisure_time_activity`

这些字段都被标记为 `safe`，没有进入 `post_outcome` 或 `hard_leakage` 区域，因此在当前 V2 规则下可以作为“预测依赖”的描述对象。

但这部分输出有一个明确限制：

- 它们只能被表述为“对预测有帮助的变量”
- 不能被表述为“导致肥胖的因素”
- 不能被直接上升为政策、医疗或个体干预建议

V2 生成的原始安全说明是：

`These feature rankings describe predictive reliance, not causal leverage.`

翻成中文就是：

“这些变量排序描述的是模型在做预测时依赖了哪些信息，不代表这些变量对肥胖具有因果推动作用。”

## 9. Gate 审核结果

### 9.1 Baseline Gate

- 结果：通过
- 理由：最佳非 dummy 模型在 `accuracy` 上提升约 `0.0291`

这说明模型确实学到了一些超出多数类规则的可用预测信息。

### 9.2 Stability Gate

- 结果：通过
- 理由：逻辑回归在五折中的 `accuracy` 标准差约为 `0.0049`

这说明当前模型表现不是靠某一折偶然“碰巧好”，而是整体较为稳定。

### 9.3 Feature Risk Gate

- 结果：通过
- 理由：高权重字段中没有 `hard_leakage` 或 `post_outcome` 风险项

### 9.4 Report Gate

- 结果：通过
- 理由：所有上游 gate 均通过

### 9.5 最终证据等级

- `evidence_grade`: `report-ready`
- `allowed_report_mode`: `report-ready`

## 10. 当前分析允许说什么

在当前 V2 规则下，本次分析可以安全表达的内容包括：

- 该 BRFSS 样本上存在可以被建模捕捉到的肥胖预测信号
- 逻辑回归在当前特征集上优于 dummy baseline 和随机森林
- `general_health`、`diabetes_status`、`age_group`、`exercise_past_30d`、`leisure_time_activity` 是当前模型较依赖的预测信息来源
- 当前模型已经通过 baseline、稳定性和特征风险 gate，可以作为“有一定预测价值”的结果对外汇报

## 11. 当前分析明确不能说什么

以下说法不应从本次分析中直接推出：

- 不能说“某个变量导致了肥胖”
- 不能说“改善 general_health 就一定会降低肥胖率”
- 不能说“糖尿病状态是肥胖的因果驱动因素”
- 不能说“这套模型已经适合医疗诊断或个体处置”
- 不能把 `soft_proxy` 字段直接翻译成干预建议

换句话说，这次分析证明的是“可以预测到一些模式”，而不是“已经识别出可验证的因果机制”。

## 12. 对当前结果的业务解读

如果用业务语言来总结，这次分析说明：

- 在问卷与健康状态类变量上，样本中的肥胖状态并不是完全随机的，模型能够识别出一定结构性模式
- 但模型能力目前仍然是中等水平，而不是非常强的区分能力
- 逻辑回归优于随机森林，说明当前信号更像是若干相对稳定、线性可分的风险组合，而不是复杂非线性交互主导
- 当前最值得关注的变量组合集中在自评健康、糖尿病状态、年龄分组以及运动相关变量上

这里我额外做一个谨慎推断：
由于 dummy baseline 已经有 66.09% 的准确率，而最佳模型只有 69.00%，所以“统计上有改进”和“业务上足够强”不是一回事。当前模型可以说是“优于简单基线”，但还不能自动等价为“足以支持高风险业务决策”。

## 13. 后续建议

基于当前结果，更合理的下一步是：

1. 补充更适合不平衡分类的指标，例如 precision、recall、AUC、PR-AUC、校准度
2. 增加分层切分或按州/人群切片的泛化验证
3. 检查 `state`、收入、教育等变量在不同群体上的稳定性与公平性
4. 如果目标是解释“为什么会肥胖”，应另起因果分析路径，而不是继续从预测模型里硬推因果结论
5. 如果目标是筛查高风险人群，应补充阈值分析、误报漏报成本和校准分析

## 14. 本次运行产物清单

本次分析已生成的核心文件包括：

- `analysis_contract.json`
- `scout_report.json`
- `feature_risk_report.json`
- `route_decision.json`
- `baseline_results.json`
- `explainability_guarded.json`
- `gate_review.json`
- `judgment_bundle.json`
- `claim_registry.json`
- `report_bundle.json`
- `formal_report_v2.md`
- `formal_report_v2_zh.md`

## 15. 结论

本次 BRFSS 2024 肥胖预测分析已经完整走通 `data_analysis_V2` 的监督学习流程，并通过了所有当前配置下的 gate，最终被评为 `report-ready`。这意味着本次结果可以被诚实地汇报为“存在经基线验证的预测信号”，其中逻辑回归是当前最佳模型。

同时，V2 也明确限制了结论边界：当前结果只能支持预测层面的表达，不能支持因果层面的表达，更不能直接导出行动建议或干预策略。若后续要进入政策、医疗或行为干预解释，需要单独设计因果研究路径。
