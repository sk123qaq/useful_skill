# 因果推断

## 当前定位

这份文档保留的是因果分析的适用边界、方法选择和识别假设。

虽然 `data_analysis_pro` 中存在 `scripts/causal_analysis.py` 与 `scripts/causal_narrative.py`，而且我已修复它们的编译级 import 问题，并已用 BRFSS 样例数据成功跑通一条 `psm` 端到端 smoke test，但这仍不等于整套因果方法都已完成系统化验证。

另外，`causal_analysis.py` 中原本依赖的一些可选导出能力，现在已做成缺失时自动降级，不再因此阻塞脚本启动。

所以这份 reference 现在更适合被当成：

- 因果方法选择指南
- 配置口径参考
- 结果解读防护准则

所以它仍然不应被理解成“所有方法都已做过端到端回归验证的因果 runner 说明书”。

## 什么时候才应该走因果路径

当问题是“某项干预是否导致了结果变化”，而不仅仅是：

- 发生了什么
- 哪些变量相关
- 结果能否被预测

如果你现在只有相关数据、没有可辩护的识别策略，就不要把问题硬写成因果问题。

## 当前脚本的意图方法范围

按 `causal_analysis.py` / `causal_narrative.py` 的实现意图，当前覆盖的方法包括：

- `dml_lite` (针对连续干预，如价格折扣、时长)
- `did`
- `rd`
- `synthetic-control`
- `iv`
- `dml`
- `dr`
- `psm`
- `orthogonal`
- `uplift`
- `cate`
- `causal`

这些方法列表有参考价值，但不代表当前都能在本 skill 里稳定跑通。

---

## 自动混杂因素建议 (Auto-Confounder Suggestion)

为了降低用户配置门槛，脚本支持基于统计关联自动建议控制变量（Confounders）：

- **逻辑**：
  - **关联度分析**：通过统计指标（相关系数、互信息）自动选择与干预变量（Treatment）和结果变量（Outcome）同时相关的变量。
  - **启发式过滤**：自动排除唯一标识（ID）、原始时间戳及高度线性相关的冗余变量。
- **局限性（必须人工复核）**：
  - **选择偏误 (Collider Bias)**：脚本目前无法识别“结果后变量”，控制这类变量会导致估计严重偏误。
  - **因果机制缺失**：自动建议无法替代对业务机制的理解。如果一个变量是干预变量的中介项（Mediator），控制它会导致总效应的估计失效。
- **建议操作**：必须在 P1 问题定义阶段，结合业务背景进行变量二次确认。

---

## 方法选择提示

### DID

适合：

- 有处理组/对照组
- 有干预前后观察窗口
- 平行趋势假设有可辩护性

### RD

适合：

- 存在明确阈值
- 阈值附近不能被精确操控

### Synthetic Control

适合：

- 单个或极少数受干预单元
- 干预前轨迹可由供体池较好拟合

### IV

适合：

- 存在影响处理、但不直接影响结果的工具变量

### DML / DR / PSM

适合：

- 观测数据因果估计
- 你愿意明确讨论重叠、可忽略性、模型设定等前提

### Uplift / CATE / Orthogonal

适合：

- 你关心处理效应异质性
- 但要接受这类结果通常更脆弱、更依赖模型设定

## 配置字段可作为口径参考

当前文档中常见的配置要求仍然有参考价值，例如：

- DID:
  - `outcome_col`
  - `treatment_col`
  - `post_col`，或 `period_col + pre/post 值`
- RD:
  - `outcome_col`
  - `running_col`
  - `cutoff`
- Synthetic Control:
  - `unit_col`
  - `time_col`
  - `outcome_col`
  - `treated_unit`
  - `intervention_time`
- IV:
  - `outcome_col`
  - `treatment_col`
  - `instrument_col`
- 观测数据方法：
  - `treatment_col`
  - `outcome_col`
  - `covariate_cols` 或 `feature_cols`

但这些字段现在应被理解为“分析输入口径模板”，不是稳定 CLI 契约。

## 如果当前脚本没法运行，正确做法是什么

- 不要把 reference 当成脚本成功的证据
- 不要补写这次运行里并未真实生成的报告或叙述工件
- 可以把这份文档用于：
  - 判断方法是否合适
  - 列出识别假设
  - 设计后续需要补的数据和校验

如果最终没有形成可复核估计结果，就只能交付：

- 因果问题定义
- 可行方法候选
- 所需字段与前提
- 当前为什么还不能得出因果结论

## 防护准则

- 没有识别假设，就没有因果结论。
- 不要控制干预后变量。
- 不要把模型异质性结果写成机制证明。
- 如果多个方法给出不一致结果，应把它写成不确定性，而不是挑一个顺眼的。
- 只要脚本或诊断没有形成可复核输出，就不要把它升级成正式因果发现。
- 当前已知最小验证路径：`brfss_2024_obesity_modeling_sample.csv` 过滤 `exercise_past_30d in {yes,no}` 后，可成功跑通 `psm`、`causal_report.json` 与 `causal_narrative_report.*` 输出链。
