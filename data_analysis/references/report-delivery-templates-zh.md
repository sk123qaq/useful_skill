# 中文 DOCX / PDF 分析报表交付规范

## 目的

这份文档定义 `data_analysis` 在正式输出中文报表时的统一格式。它面向两种交付物：

- 中文 `.docx` 分析报表
- 中文 `.pdf` 分析报表

设计目标：

- 让非技术读者可以读懂
- 保留足够多的技术依据，便于复核
- 对专业名词给出简短解释
- 对关键指标明确写出“当前数值说明什么、它重要在哪里、背后意味着什么”

## 何时使用

当用户明确要求以下任一交付物时，使用这套规范：

- 正式汇报版分析报告
- Word 版分析报告
- PDF 版分析报告
- 可发给管理层、客户、合作方的分析报告

## 推荐工作流

1. 先完成正常 `run_pipeline`，拿到 JSON、PNG、Markdown 原始产物
2. 读取 [report-artifact-interpretation-zh.md](report-artifact-interpretation-zh.md)
3. 先运行 `python3 scripts/formal_report_export.py --run-dir <run_dir>` 生成首稿 DOCX / PDF，并同时产出 `formal_report_draft.md` 与 `report_context.json`
4. 首稿生成后，agent 必须重新阅读 `report_context.json`、整份报告和对应 PNG，一起做一轮视觉复核
5. 基于这轮视觉复核，为每张图补写详细图表解读，并把结果输出为结构化 `chart_review.json`
6. 再运行 `python3 scripts/formal_report_export.py --run-dir <run_dir> --chart-review-json <path>`，由脚本把 `chart_review.json` 回填到固定版式 DOCX / PDF
7. 如需 `.docx`，以脚本导出的 Word 文档作为正式可编辑版本
8. 如需 `.pdf`，优先基于同一份回填内容导出固定版式 PDF

推荐默认路径：

- `DOCX` 作为可编辑源文件
- `PDF` 作为固定版式分发文件

## 报表必须满足的内容要求

每份正式报表必须包含以下几类信息：

- 问题定义
- 数据来源与口径
- 数据质量与限制
- 方法说明
- 结果展示
- 图表解读
- 风险与建议
- 数值解释

补充说明：

- 建议动作可以放在执行摘要中，不必单独拉出文末“业务解释”章节
- 术语解释应尽量嵌入核心指标表、图下注释或正文，不再默认单独追加“名词解释”区块

## 名词解释要求

每次正式交付，凡是出现以下类型词语，默认都要附一句简短解释：

- 统计学名词
  - `p_value`
  - `confidence interval`
  - `normality`
  - `ANOVA`
  - `ADF`
- 机器学习名词
  - `accuracy`
  - `precision`
  - `recall`
  - `F1`
  - `RMSE`
  - `R2`
  - `SHAP`
  - `PDP`
- 因果与实验名词
  - `DID`
  - `RD`
  - `IV`
  - `CUPED`
  - `uplift`
  - `CATE`
- 业务分析名词
  - `ARPU`
  - `ARPPU`
  - `retention`
  - `LTV`
  - `conversion rate`

解释风格要求：

- 一句话
- 尽量不用公式
- 先说“它是什么”，再说“怎么理解”
- 优先写在核心指标表、图下注释或正文段落中，而不是另起附录表格

## 数值解释要求

每个关键结果表格或图表旁边，都要预留“数值说明”区块。

标准格式：

- 指标名
- 本次值
- 指标含义
- 当前值代表什么
- 这次值偏好还是偏弱
- 需要结合什么上下文

### 示例

- `F1 = 0.66`
- 含义：综合衡量 precision 和 recall 的平衡
- 当前值代表什么：说明模型兼顾了查准和查全，但还不是特别强
- 这次怎么理解：如果 baseline 只有 0.55，那么 0.66 有明显提升；如果 baseline 已有 0.64，则提升有限

## 文风要求

- 默认中文
- 先结论后细节
- 避免只贴技术术语不解释
- 每个章节尽量回答“所以呢”

## 图表要求

- 图题必须为中文
- 图表解读必须结合图像本身和报告前文，不得只复述文件名或图表类型
- 每张图下方至少要有两段自然语言：
  - 第一段：说明图里当前出现了什么情况
  - 第二段：说明这对业务、研究对象或决策意味着什么
- 图表解读应直接写观察到的情况和意义，不要写成“这张图围绕……展开”“帮助读者理解……”这类说明书式表达
- 如果图中出现英文指标、英文图例、英文坐标、英文缩写，或中文专业名词对基础读者有理解门槛，图下注释必须补充简短解释
- 多张图之后必须追加一段“图表总体解读”，把整组图的共同信息串起来
- 图表解读内容应由 agent 产出 `chart_review.json`，再由脚本回填；不要直接手改最终 DOCX / PDF 版式

## DOCX 与 PDF 的差异化要求

## DOCX

- 适合可编辑、可批注、可继续修改
- 章节更完整
- 表格更详细
- 末尾不再默认追加附录表格

## PDF

- 适合固定版式分发
- 执行摘要更靠前
- 每页信息密度更高
- 图表和结论需要更凝练

## 输出文件命名建议

- `analysis-report-zh.docx`
- `analysis-report-zh.pdf`

如果是具体项目或 run，可命名为：

- `brfss-obesity-analysis-report-zh.docx`
- `brfss-obesity-analysis-report-zh.pdf`

## 生成报表时，大模型必须遵守的规则

- 默认中文输出
- 默认解释专业名词
- 默认解释关键数值的好坏
- 默认说明限制与风险
- 默认引用 run 目录中的原始 JSON / PNG / Markdown
- 不得只复制 dashboard 文本，必须结合原始产物重新组织
- 图表章节必须在首稿后再做一次视觉复核，再回填逐图解读和总体解读
- 图表章节不得保留“怎么看”“本图结论”这类模板化占位语
- `chart_review.json` 中每张图至少包含 `file`、`title`、`interpretation`、`implication`、`caption_note`
- 当前正式导出默认在“图表总体解读”后结束，不再单独追加“业务解释与建议”“名词解释”“原始产物清单”等尾部章节
