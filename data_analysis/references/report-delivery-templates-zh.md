# 中文 DOCX / PDF 分析报表交付规范

## 目的

这份文档定义 `data_analysis` 在正式输出中文报表时的统一格式。它面向两种交付物：

- 中文 `.docx` 分析报表
- 中文 `.pdf` 分析报表

设计目标：

- 让非技术读者可以读懂
- 保留足够多的技术依据，便于复核
- 对专业名词给出简短解释
- 对关键指标明确写出“数值怎么看、是好是坏、为什么”

## 何时使用

当用户明确要求以下任一交付物时，使用这套规范：

- 正式汇报版分析报告
- Word 版分析报告
- PDF 版分析报告
- 可发给管理层、客户、合作方的分析报告

## 推荐工作流

1. 先完成正常 `run_pipeline`，拿到 JSON、PNG、Markdown 原始产物
2. 读取 [report-artifact-interpretation-zh.md](report-artifact-interpretation-zh.md)
3. 按 [analysis-report-docx-template.md](../templates/analysis-report-docx-template.md) 组织正文
4. 如需 `.docx`，调用 `docx` skill 生成正式 Word 文档
5. 如需 `.pdf`，优先基于同一份正文调用 `pdf` skill 生成固定版式 PDF

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
- 业务解释
- 风险与建议
- 名词解释
- 数值解释

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

## 数值解释要求

每个关键结果表格或图表旁边，都要预留“数值说明”区块。

标准格式：

- 指标名
- 本次值
- 指标含义
- 一般怎么看
- 这次值偏好还是偏坏
- 需要结合什么上下文

### 示例

- `F1 = 0.66`
- 含义：综合衡量 precision 和 recall 的平衡
- 一般怎么看：越高越好，但要与 baseline 比较
- 这次怎么理解：如果 baseline 只有 0.55，那么 0.66 有明显提升；如果 baseline 已有 0.64，则提升有限

## 文风要求

- 默认中文
- 先结论后细节
- 避免只贴技术术语不解释
- 每个章节尽量回答“所以呢”

## 图表要求

- 图题必须为中文
- 图下注释必须说明：
  - 图展示了什么
  - 应该怎么看
  - 本图在这次报告中的结论是什么

## DOCX 与 PDF 的差异化要求

## DOCX

- 适合可编辑、可批注、可继续修改
- 章节更完整
- 表格更详细
- 附录可以更长

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
