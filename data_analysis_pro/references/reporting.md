# 报告与交付

## 当前定位

`data_analysis_pro` 当前不自带稳定的 HTML / DOCX / PDF 导出器，也没有统一的运行目录报告系统。

默认交付物应是：

- 一个面向用户的 Markdown 工作报告 `.md` 文件
- 与结论直接相关的 JSON / PNG / CSV 工件路径

当前不要假设存在稳定的 HTML / DOCX / PDF 导出器、索引页或统一运行目录系统。

## 叙述等级

- `report-ready`：证据足够支持面向决策的判断。
- `exploratory`：发现值得继续跟进，但不能包装成可直接执行的业务结论。
- `not_usable`：当前结果不足以支持有效判断，必须明确说明原因。

### 何时可以写成 `report-ready`

至少同时满足下面几条：

- 问题定义清楚，目标或核心指标清楚。
- 关键脚本实际运行成功，而不是引用了不存在的工具。
- 方法和数据口径能自洽，不存在明显的泄露、后验字段或样本失真。
- 主要结论能指回具体输出，而不是模板化总结。
- 已经写明主要限制和剩余不确定性。

### 禁止的叙述

- 严禁根据预测性特征进行因果性表述。
- 严禁根据 `post_outcome` 或 `hard_leakage` 特征提供干预建议。
- 严禁在没有可核对基线结果的情况下宣称模型具有实用价值。
- 严禁把脚本失败、样本不足、口径不清的分析写成确定性结论。
- 严禁为了“报告完整”而补写未运行章节。

### 推荐写法

- 如果证据偏弱：写成 `exploratory`，明确“这是一条线索，不是结论”。
- 如果关键前提不成立：直接写成 `not_usable`，说明阻断原因。
- 如果是预测结果：强调“预测相关”，不要偷换成“干预有效”。

## 默认交付写法

默认工作报告不应预先写死“必须有哪些固定章节内容”。

更合适的做法是：

- 按本次实际工作过程来写，从开始读取数据到当前阶段为止，真实做了什么就写什么。
- 只写本次实际执行过的步骤、实际生成过的工件、实际得到的发现。
- 如果某一步没有做，就不要用模板化章节硬补；必要时只需明确说明“本阶段未执行”。
- 如果中途调整过分析方向，可以按时间顺序或逻辑顺序把这些变化整合进报告。

可以保留的是样式和组织规则，例如：

- 报告应有清晰标题与分段。
- 段落顺序应能反映工作推进过程。
- 图表应紧跟对应解读。
- 关键判断应能回指到实际工件或实际运行结果。
- 不要把报告写成脱离本次运行过程的通用模板。

## 工件阅读顺序

如果这些输出都真实存在，推荐顺序如下：

1. `io_router.py` 的输出
2. `column_profile.py` 的输出
3. `preprocessing.py` 的输出
4. `eda_stats.py` 的输出
5. `relationship_screening.py` 的输出
6. `baseline_runner.py` 保存出的 `baseline_results.json`
7. `model_explainability.py` 保存出的 `explainability_report.json`
8. 对应的 PNG 图和 CSV
9. `experiment_analysis.py`、`causal_analysis.py`、`causal_narrative.py` 的输出

如果实验或因果脚本实际运行失败，就只能把对应部分写成“未形成可复核结果”，不能补写成结论。

## 按任务类型优先引用的工件

### 数据读取与质量

- `io_router.py` 的读取计划
- `column_profile.py` 的列画像
- `preprocessing.py` 的清洗报告

怎么读：

- 先确认 `io_router.py` 的 `path`、`format`、`kind`、`warnings` 是否符合预期。
- `column_profile.py` 重点看 `missing_rate`、`unique_count`、`dominant_share`、`flags`。
- `preprocessing.py` 的 `duplicates.count` 是“完全相同行”的重复数，不等于“业务上重复记录”。
- 如果传入了业务键检查，优先看 `duplicates.key_duplicates`，它更接近业务口径上的重复风险。
- `cleaning.actions` 里没有出现的动作，不要假设已经做了。

### 描述性分析

- `eda_stats.py` 的统计摘要
- `relationship_screening.py` 的关系排序

怎么读：

- 先看分布，再看相关，再看检验。
- `correlation_matrix` 只反映数值字段之间的相关性，不等于因果。
- 关系筛查更像“下一步看哪里”的排序器，不是最终结论。
- 如果自变量像用户 ID、订单 ID、超高基数字段，关系分数可能虚高。
- 进入工作报告时，应从这里整理出重要的两字段关系，并按重要性从高到低依次配图和解读。

### 预测性分析

- `baseline_runner.py` 产出的基线结果
- `model_explainability.py` 产出的解释结果

怎么读：

- `baseline_runner.py` 当前更适合作为 Python 助手调用，不是稳定 CLI。
- 先看最优非 dummy 是否真的明显优于 dummy，再看折间波动是否稳定。
- 如果主指标是 `accuracy`，但类别严重不平衡，还要一起看 `balanced_accuracy`、`f1_macro`、`average_precision`。
- 原生重要性和 permutation importance 不一致时，优先谨慎看 permutation。
- PDP 只说明模型如何响应特征，不说明因果机制。
- `shap.available = false` 在当前 skill 中很常见，不要把“没有 SHAP”当作异常失败。

### 实验分析

- `experiment_analysis.py` 的输出

怎么读：

- 只解读这次实际运行生成的结果，不预设所有实验配置都经过系统化回归验证。
- 如果设计前提、样本量或分组质量有缺口，优先把结论降级成 `exploratory` 或 `not_usable`。

### 因果分析

- `causal_analysis.py` 的输出
- `causal_narrative.py` 的叙述化结果

怎么读：

- 只在脚本真跑通、关键假设有基本支撑时才进入正式结论。
- 因果脚本产出的 narrative 也是基于已有 report 的整理，不会自动弥补识别假设缺口。
- 如果方法没跑通或假设不成立，就明确停在“待验证项”。

## 图表与图像工件

当前 skill 里更可信的图形产物，通常是脚本直接生成的 PNG。

解读时至少检查：

- 图名、字段名、标题是否和实际分析对象一致。
- 图是否有对应的 JSON 或脚本上下文。
- 高基数字段、强偏态指标、小样本分组图是否被过度解读。

默认交付中的图表要求：

- 应包含当前重要的两字段关系图表，并按重要性从高到低排列。
- 图表内容默认使用中文，包括图题、坐标轴、图例和必要注释。
- 如果脚本原始输出不是中文，进入工作报告前应补成中文图题和中文解读。
- 图表下方必须紧跟自然语言解读，明确说明“图里有什么”以及“这意味着什么”。

## 正式中文报告

如果用户明确要正式中文报告，可把以下文件当作写作参考，而不是可执行工作流：

- `references/report-delivery-templates-zh.md`
- `templates/analysis-report-docx-template.md`
- `templates/analysis-report-pdf-template.md`

当前它们的角色是：

- 帮助组织正文结构
- 帮助统一中文表达风格
- 帮助把 Markdown 结论转成更正式的文档

当前不要把它们当作“本 skill 自带的导出管线”。

## 防护准则

- 先确认文件真的存在，再解读。
- 缺什么就明确写缺什么，不要把未运行章节补成模板化废话。
- 不要虚构 run directory、仪表板、索引页、正式导出文件。
- 不要把诊断性图表自动包装成管理层结论。
- 不要把内部技术字段直接翻译成业务结论。
- 不要从编码特征名直接写业务建议，优先回到原始字段语义。
- 报告里的每个关键判断都应能指回具体工件或具体输出。
- 如果某个工件只能说明“值得继续分析”，就不要把它升级成“已被证明”。
