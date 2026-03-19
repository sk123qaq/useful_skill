# 分析产物解读指南（Dashboard 导出前）

## 目的

这份文档用于解释 `data_analysis` 在 `report_dashboard.html` 导出之前生成的 JSON、Markdown、PNG 等产物。用户可以：

- 直接结合 run 目录中的文件阅读分析结果
- 把这份文档连同 JSON、PNG、Markdown 一起交给大模型，让它基于统一口径做二次解读
- 在需要正式汇报时，把这份文档作为 `docx` / `pdf` 报表生成的解释规范

重要原则：

- 不是每次 run 都会生成所有文件，是否出现取决于任务类型
- `Dashboard` 是交付层，不是唯一事实来源
- 真正的机器可复核依据仍然是 JSON、CSV、PNG、Markdown 原始产物

## 建议阅读顺序

1. `run_summary.md`
2. `read_plan.json`
3. `cleaning_report.json`
4. `stats_report.json`
5. `feature_plan.json`
6. 与任务相关的主报告：
   - `model_report.json`
   - `explainability_report.json`
   - `business_report.json`
   - `experiment_report.json`
   - `analysis_report.json`
   - `causal_report.json`
   - `causal_narrative_report.json`
   - `research_report.json`
7. 对应 PNG 图表

---

## 1. `environment.json`

### 作用

记录当前运行环境中关键依赖是否可用。

### 常见字段

- `python_version`
- `modules`
  - 例如 `pandas`、`matplotlib`、`statsmodels`、`xgboost`、`lightgbm`、`shap`

### 怎么看

- 某模块为 `false` 时，说明对应能力可能会降级或直接跳过
- 例如 `matplotlib=false` 时，通常不会输出 PNG 图
- 例如 `shap=false` 时，解释性报告里可能没有 SHAP 部分

### 解读建议

- 先确认环境是否支持该 run 所需能力
- 如果缺包，不要直接把“没有图/没有某指标”理解成“分析没有发现问题”

---

## 2. `read_plan.json`

### 作用

说明数据是怎么读取的，以及输入源有哪些风险。

### 常见字段

- `path` 或 `db_url`
- `format`
- `size_bytes` / `size_mb`
- `recommended_backend`
- `supported`
- `warnings`
- `requires`

### 怎么看

- `recommended_backend` 用于判断当前读法是否合理
- `warnings` 是优先阅读的部分，常提示 Excel 行数限制、文件过大、驱动缺失、格式脆弱等问题

### 解读建议

- 先看是否读对了文件，再看后面的分析
- 如果 `warnings` 已经提示“只读了 sample”或“建议 DuckDB”，就不要把后续结论误当作全量精确结论

---

## 3. `cleaning_report.json`

### 作用

记录数据质量体检结果。默认情况下，它是“检查报告”，不一定代表脚本已经实际改写了数据。

### 核心字段

- `shape`
  - `rows`
  - `columns`
- `roles`
  - `numeric`
  - `categorical`
  - `time`
  - `target`
- `missing_values`
  - `total_missing_cells`
  - `columns_with_missing_values`
  - `by_column`
- `duplicates`
  - `duplicate_rows`
  - `duplicate_ratio`
- `outliers_iqr`
- `outliers_zscore`
- `outliers_isolation_forest`
- `preprocessing_plan`

### 怎么看

#### `shape`

- 表示这次实际进入分析的行列数
- 如果和原始数据量不一致，通常说明做了采样、过滤或预处理

#### `roles`

- 帮你判断脚本把哪些列当成数值、类别、时间、目标
- 如果某列角色判断错了，后面的统计和建模会一起偏

#### `missing_values`

- `columns_with_missing_values=0` 不是一定好，可能只是上游已经删掉了缺失
- `missing_ratio` 高的列要重点看是否应该删、补、标记

#### `duplicates`

- `duplicate_ratio` 高时，要判断这些重复是“脏数据”还是“业务上合法的重复记录”

#### `outliers_iqr` / `outliers_zscore`

- 这是统计意义上的异常值提示，不代表一定是错误数据
- 对收入、交易额、人口这类长尾分布，异常值多不一定异常，可能是业务真实结构

#### `outliers_isolation_forest`

- 这是多变量异常检测，更偏“整体行为不像大多数样本”
- 适合做风险提示，不适合直接删数据

#### `preprocessing_plan`

- 这是脚本给出的建议，不等于已经执行

### 解读建议

- 先看缺失和重复，再看异常值
- 不要把“异常值多”直接解释成“数据差”，先判断是否长尾分布或高异质性

---

## 4. `stats_report.json`

### 作用

提供 EDA 和基础统计摘要。

### 核心字段

- `shape`
- `dtypes`
- `summary_statistics`
- `correlation_matrix`
- `normality_tests`
- `adf_test`

### 怎么看

#### `summary_statistics`

常见指标：

- `count`: 非空样本数
- `mean`: 均值
- `std`: 标准差
- `25%` / `50%` / `75%`: 分位数
- `min` / `max`

解读时重点看：

- 中位数与均值差距大不大
- 四分位距是否很宽
- 极值是否远离主体分布

#### `correlation_matrix`

- 反映线性相关，不等于因果
- 通常：
  - 绝对值接近 `1`：线性关系强
  - 接近 `0`：线性关系弱
- 对类别变量 one-hot 之前，这个矩阵通常只覆盖数值列

#### `normality_tests`

- 默认常见的是 Shapiro 检验
- `p_value < 0.05` 时，通常认为“偏离正态”
- 大样本下即使轻微偏离也很容易显著，所以不要只看 p 值

#### `adf_test`

- 时序任务才有意义
- 常用判断：
  - `p_value < 0.05`：更支持平稳
  - `p_value >= 0.05`：不支持平稳

### 解读建议

- 先看分布，再看相关，再看检验
- 不要把“显著不正态”直接理解成“数据不能用”

---

## 5. `feature_plan.json`

### 作用

说明这份数据是否适合做编码、日历特征、技术指标、PCA 等。

### 常见字段

- `numeric_columns`
- `categorical_columns`
- `recommendations`
- `available_advanced_features`
- `pca_ready`

### 怎么看

- 这是“可做什么”的建议，不一定表示已执行
- 它更像后续分析设计的提示板

### 解读建议

- 如果 `categorical_columns` 很多，说明后面模型性能会高度依赖编码方式
- 如果 `pca_ready=true`，说明数值维度足够多，可以考虑降维

---

## 6. `chart_plan.json`

### 作用

说明脚本为什么想画这些图，以及这些图分别回答什么问题。

### 常见字段

- `task`
- `charts`
  - `chart`
  - `x`
  - `y`
  - `reason`

### 怎么看

- `reason` 很重要，它直接说明图的阅读目的
- 如果实际 PNG 少于这里计划的图，通常表示某些图在运行时因为数据条件不满足或依赖缺失而未画出
- 它仍然偏“分析阶段想画什么”，不等于正式报告正文最终一定放什么

---

## 6A. `chart_candidates.json`

### 作用

把已计划或已渲染的图转换成“正式报告可治理的候选池”。

### 常见字段

- `report_audience`
- `candidates`
  - `chart_id`
  - `file`
  - `section_role`
  - `source_fields`
  - `audience_fit`
  - `diagnostic_only`
  - `allow_in_formal_body`
  - `business_value_score`
  - `suitability_score`

### 怎么看

- 这是“哪些图有资格进入正文”的约束层，不是最终入选结果
- `diagnostic_only=true` 说明它更适合过程审阅、附录或分析师复核，不适合作为正式报告正文主图
- `allow_in_formal_body=false` 是硬约束，后续 agent 不应把这类图直接选进正文
- `source_fields` 比编码后的模型列更重要，它表示这张图应该回到哪个原始业务字段去理解

### 解读建议

- 优先看 `section_role` 和 `audience_fit`，判断它更适合给谁看、承担什么角色
- 如果看到 `source_fields=["age_group"]`，而文件却是 `pdp_age_group_80.png`，要意识到这张图在业务语义上属于“年龄组”这个原始字段，而不是只属于某个 one-hot 列
- 正式报告正文图的多样性应发生在候选池内部，而不是脱离这个约束层随意改选

---

## 6B. `report_chart_decision.json`

### 作用

记录正式报告正文图的最终选择结果，以及它们的顺序、受众和入选理由。

### 常见字段

- `status`
- `report_audience`
- `selected_charts`
  - `chart_id`
  - `file`
  - `selection_rationale`
  - `interpretation`
  - `implication`
  - `caption_note`
- `overall_summary`

### 怎么看

- 这是“最终正文图决策层”，比 `chart_plan.json` 和 `chart_candidates.json` 更接近正式交付
- `status=draft` 表示正文图草稿已选，但逐图解读未必写完
- `status=final` 通常表示正文图和逐图解读都已完成二次回写

### 解读建议

- 如果 `selected_charts` 很少，不代表分析没做够，可能只是受众不需要看到全部图
- 如果同一 run 在不同会话里出现不同的正文图组合，先看 `report_audience` 和 `selection_rationale` 是否发生了变化
- 一旦 `selection_rationale` 说不清“为什么这张图属于正文”，就说明这张图大概率应降回过程报告或附录

---

## 7. `model_report.json`

### 作用

保存监督学习或基线模型的评估结果。

### 常见字段

- `task`
- `n_rows_used`
- `n_features_used`
- `models`

`models` 下通常按模型名分组，每个模型下是一组指标。

### 分类任务常见指标

#### `accuracy`

- 含义：预测正确的比例
- 方向：越高越好
- 不能单独看，因为类别不平衡时会误导

#### `precision_weighted`

- 含义：预测为某类的样本里，真正属于该类的比例
- 方向：越高越好
- 更关注“误报成本”

#### `recall_weighted`

- 含义：真实属于某类的样本里，被模型找回来的比例
- 方向：越高越好
- 更关注“漏报成本”

#### `f1_weighted`

- 含义：Precision 和 Recall 的折中
- 方向：越高越好
- 当你希望兼顾误报和漏报时，通常比单看 accuracy 更稳

### 回归任务常见指标

#### `rmse`

- 含义：均方根误差
- 方向：越低越好
- 对大误差更敏感

#### `mae`

- 含义：平均绝对误差
- 方向：越低越好
- 比 RMSE 更容易直接理解

#### `mape`

- 含义：平均绝对百分比误差
- 方向：越低越好
- 当真实值接近 0 时容易失真

#### `r2`

- 含义：模型解释方差能力
- 方向：越高越好
- `1` 接近完美，`0` 约等于均值基线，负数表示比均值基线更差

### 怎么看“好不好”

- 不能脱离 baseline、样本难度、类别分布和业务成本看
- 一般建议：
  - 先和简单 baseline 比
  - 再看是否达到业务可用阈值
  - 最后看解释性和稳定性

---

## 8. `explainability_report.json`

### 作用

解释模型为什么这么判断。

### 常见字段

- `model_name`
- `native_feature_importance`
- `permutation_importance`
- `partial_dependence_features`
- `partial_dependence_artifacts`
- `shap`
- `train_rows`
- `test_rows`
- `n_features`

### 怎么看

#### `native_feature_importance`

- 来自模型自身的特征重要性
- 读取快，但有时会偏向某些模型特性

#### `permutation_importance`

- 更推荐优先看它
- 含义：把某个特征打乱后，模型性能掉多少
- 掉得越多，说明模型越依赖这个特征

#### `partial_dependence_features`

- 表示后面 PNG 会重点画哪些变量

#### `shap`

- `top_features`：从 SHAP 角度看最影响预测的变量
- `artifact`：SHAP 图文件

### 解读建议

- 重要性不等于因果
- 一个变量重要，只能说明模型大量使用它，不代表它一定是“真正原因”

---

## 9. `business_report.json`

### 作用

保存业务模板分析结果，例如：

- 漏斗
- 付费
- 留存
- cohort
- LTV

### 常见内容

- 转化率
- 付费率
- ARPU / ARPPU
- 留存曲线
- cohort retention matrix
- cohort LTV

### 解读建议

- 这类指标一定要结合分母口径
- 如果口径、时间窗、用户定义没讲清楚，数值本身没有意义

---

## 10. `experiment_report.json`

### 作用

保存 A/B 实验结果。

### 常见内容

- `decision`
- `metrics`
- `srm_check`
- `balance_checks`
- `multiple_testing`
- `sequential_monitoring`
- `power_analysis`

### 核心指标解释

#### `p_value`

- 含义：在“无效应”假设成立时，观察到当前或更极端结果的概率
- 常见阅读：
  - `< 0.05`：统计上更支持存在差异
  - `>= 0.05`：证据不够
- 不代表“结果为真的概率”
- 也不代表“业务上值得做”

#### `confidence_interval`

- 含义：估计效应的不确定区间
- 如果跨过 0，通常说明方向还不稳

#### `lift`

- 含义：相对提升
- 要同时看绝对提升和样本量

#### `SRM`

- 含义：样本比例失配
- 如果 SRM 异常，实验分流本身就可能有问题，后续 lift 要谨慎

### 解读建议

- 先看 SRM 和 balance，再看 lift 和 p 值，再看 power
- “显著”不等于“值得上线”

---

## 11. `analysis_report.json`

### 作用

保存描述性或诊断性分析结果，例如：

- 聚类
- Apriori
- ANOVA
- root-cause

### 常见任务解读

#### 聚类

常见字段：

- `n_clusters`
- `candidate_scores`
- `cluster_sizes`
- `cluster_profiles`

关键指标：

- `silhouette_score`
  - 越高越好
  - 粗略经验：
    - `> 0.5`：聚类分离较清晰
    - `0.25 ~ 0.5`：可用但一般
    - `< 0.25`：结构较弱

#### Apriori

常见字段：

- `support`
- `confidence`
- `lift`

解读：

- `support`：规则出现频率
- `confidence`：前件出现时后件也出现的概率
- `lift`
  - `> 1`：正相关
  - `≈ 1`：接近独立
  - `< 1`：负相关

#### ANOVA

关键看：

- `test`
- `p_value`
- `posthoc`

解读：

- `p_value < 0.05` 通常说明组间均值并不完全相同
- 但仍需要 posthoc 看“到底哪几组不同”

#### Root-cause

关键看：

- `top_positive_drivers`
- `top_negative_drivers`

解读：

- 不是严格因果，更像“贡献拆解”
- 适合用来定位“哪几个 segment 解释了 KPI 变化”

---

## 12. `causal_report.json`

### 作用

保存因果分析的原始技术结果，例如：

- DID
- RD
- synthetic control
- IV
- DML
- DR
- PSM
- uplift
- CATE

### 怎么看

- 先看主效应估计
- 再看诊断项是否支持识别假设
- 最后看风险提示

### 解读建议

- 这里优先配合 `causal_narrative_report.json` 和 `causal_narrative_report.md` 一起看
- 不建议只盯一个系数或一个 p 值

---

## 13. `causal_narrative_report.json` / `causal_narrative_report.md`

### 作用

把因果分析翻译成业务可读的叙事报告。

### 常见结构

- `Question`
- `Design`
- `Identification Assumptions`
- `Key Estimate`
- `Diagnostics`
- `Business Interpretation`
- `Risks and Limits`
- `Recommendation`

### 解读建议

- 面向非技术读者时，优先读这个
- 面向复核和追问时，再回到 `causal_report.json`

---

## 14. `research_report.json`

### 作用

保存外部研究与资料搜集结果。

### 常见内容

- 请求次数
- 去重后的 source records
- 冲突定义
- metric / unit / date / url / confidence

### 解读建议

- 先检查来源质量，再看数值
- 同一指标如果口径不同，不要直接合并

---

## 15. `run_summary.md`

### 作用

是这次 run 的快速摘要入口。

### 一般包含

- Task
- Context
- Insight
- Recommendation
- Risk

### 解读建议

- 适合先快速读
- 不能替代原始 JSON

---

## PNG 图表解释方法

## 1. `target_distribution.png`

- 看目标变量分布是否偏斜、是否双峰、是否极不平衡
- 分类任务里如果正负样本极不平衡，只看 accuracy 很容易误导

## 2. `time_series.png`

- 看趋势、季节性、异常点、结构断点
- 如果波动大但无趋势，不要轻易做趋势外推

## 3. `shap_bar.png`

- 横轴越大，表示平均绝对 SHAP 影响越强
- 只能看“重要程度”，不能直接看正负方向

## 4. `pdp_*.png`

- 看某变量变化时，模型预测平均如何变化
- 曲线很陡，说明模型对这个变量敏感
- 两端样本少时，曲线不一定稳
- 如果它来自 one-hot 派生特征，例如 `age_group_80`，业务解读时要先回到原始字段语义，不要把单个 dummy 列直接当成正文主结论
- 在 formal report 治理里，PDP 常常更适合当机制解释或附录图，而不是管理层正文主图

## 5. `cluster_sizes.png`

- 看每个 cluster 的规模是否过小
- 太小的 cluster 可能只是噪声或极端样本群

## 6. `cluster_projection.png`

- 这是降维后的可视化，不是原始空间
- 两团越分开，通常说明聚类越清晰
- 重叠多时，说明群组边界不强

## 7. `retention_curve.png`

- 看留存掉得快不快
- 早期掉得很快通常表示激活或首周体验有问题

## 8. `cohort_heatmap.png`

- 横向看同 cohort 随时间衰减
- 纵向看新老 cohort 质量差异
- 如果新 cohort 明显更差，说明近期获客质量或产品体验可能变差

## 9. `cohort_ltv.png`

- 用于比较 cohort 价值
- 一定要结合 cohort 大小，不能只看高 LTV

## 10. `experiment_primary_metric.png`

- 先看 treatment 和 control 的差值方向
- 再回到 `experiment_report.json` 看显著性、置信区间和 power

## 11. 因果图表

### `did_trend`

- 看处理组和对照组在干预前是否趋势接近

### `rd_scatter` / `rd_binned_means`

- 看 cutoff 附近是否出现局部跳跃

### `synthetic_path` / `synthetic_gap`

- 看政策前拟合好不好，政策后 gap 是否明显扩大

### `iv_first_stage`

- 看工具变量和处理变量关系够不够强

### `propensity_overlap`

- 看 treatment/control 的分布是否重叠
- 重叠差说明估计不稳

### `balance_smd`

- 看匹配或调整后协变量平衡是否改善

### `uplift_distribution` / `cate_distribution`

- 看个体效应是否高度异质

---

## 常见术语的“好坏”判断

## 分类指标

- `accuracy`
  - 越高越好
  - 但必须和类分布、baseline 一起看

- `precision`
  - 越高越好
  - 误报成本高时更重要

- `recall`
  - 越高越好
  - 漏报成本高时更重要

- `F1`
  - 越高越好
  - 更适合平衡 precision 和 recall

## 回归指标

- `RMSE`
  - 越低越好
  - 但要结合目标量纲

- `MAE`
  - 越低越好
  - 更易直观理解

- `MAPE`
  - 越低越好
  - 目标值接近 0 时要谨慎

- `R2`
  - 越高越好
  - 负数通常表示模型很差

## 统计与实验

- `p_value`
  - 小不等于效果大
  - 小也不等于业务值得做

- `confidence_interval`
  - 越窄越稳
  - 若跨 0，方向往往不稳

- `effect_size`
  - 越大通常越有业务意义
  - 但要结合成本和风险

## 聚类与关联

- `silhouette_score`
  - 越高越好

- `lift`
  - 大于 1 才说明正向关联

---

## 给大模型一起解读时，建议提供哪些文件

最少包：

- 这份文档
- `run_summary.md`
- `cleaning_report.json`
- `stats_report.json`
- 主报告 JSON
- 关键 PNG

推荐完整包：

- `run_summary.md`
- `read_plan.json`
- `cleaning_report.json`
- `stats_report.json`
- `feature_plan.json`
- `chart_plan.json`
- 任务主报告 JSON
- `causal_narrative_report.md`（如果有）
- 全部 PNG

## 建议提示词

```text
请根据我提供的“分析产物解读指南”、本次 run 的 JSON、Markdown 和 PNG 图，按以下结构解读：
1. 这次分析的目标是什么
2. 数据质量有没有明显风险
3. 最重要的 3-5 个发现是什么
4. 这些发现分别意味着什么
5. 哪些统计/模型指标值得信任，哪些需要谨慎
6. 图表分别说明了什么
7. 给非技术读者写一段业务结论
8. 对其中出现的专业名词做简短解释
9. 对关键数值说明“是好是坏、为什么”
```
