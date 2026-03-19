---
name: data-analysis
description: 面向业务、产品、增长、财务、实验与通用表格数据的端到端结构化分析技能。适用于定义分析问题、读取 CSV/Excel/Parquet/JSON/SQL 数据、清洗预处理、统计分析、基线建模、结果评估、中文图表生成、漏斗/变现分析，以及将技术结果转成业务建议。
---

# 数据分析技能

这个技能是结构化数据分析的总控入口。`SKILL.md` 负责定义工作流、边界和路由规则；具体执行时，再按需读取对应脚本与参考文档。

## 快速开始

```bash
cd /path/to/data_analysis
python3 -m pip install -r requirements.txt
python3 scripts/check_environment.py
python3 scripts/run_pipeline.py --help
```

补充说明：
- 推荐使用 `python3.13`，但下面所有命令默认都写成 `python3`，方便在其他机器上直接运行。
- 如果需要高级模型、交互式仪表盘或额外数据库驱动，再安装 `requirements-optional.txt`。
- 默认运行产物会写入 `outputs/`。
- `--output-dir` 语义：默认把它当作“输出根目录”，脚本会自动创建时间戳运行目录；如果你传入的路径本身已经是 `data-analysis-YYYYMMDD-HHMMSS` 这种运行目录名，脚本会直接复用，避免再嵌套一层。
- 长任务监控：`run_pipeline.py` 运行中会持续更新 `<run_dir>/run_status.json`（阶段、时间、任务类型），用于判断是“仍在计算”还是“异常退出”。
- 仓库中的 `assets/` 与 `outputs/` 默认只保留空目录占位，本地数据和运行结果不作为仓库内容提交。

## 工作流

任务启动前先做一次口径确认：
- 先告诉用户全量数据行数、默认样本数，以及抽样方法；默认样本建议为 `5000` 行，抽样方法默认使用 `simple random sample`，必要时再说明可切换为分层抽样。
- 如果有目标变量，先确认任务类型：二分类/多分类目标（例如 0/1 标签）优先显式传 `--task classification`，连续数值目标传 `--task regression`。不要把任务类型完全交给默认推断。
- 让用户明确选择“样本”还是“全量”；脚本层现在要求显式传 `--data-scope sample` 或 `--data-scope full`，不再允许静默默认。
- 在跑模型前，先用文字汇报已经完成了什么、初步结果大概怎样、推荐继续用哪些模型（至少给出 2-4 个候选）以及每个候选的推荐原因、预计还要多久，并明确询问是否继续。
- 对于分类/回归建模，脚本默认会在预建模 checkpoint 停下，只产出 `pre_model_recommendation.*`、`pre_model_checkpoint_summary.md` 与 `pre_model_gate.json`；只有显式加 `--continue-after-checkpoint` 才允许进入建模阶段。
- 对于分类/回归建模，若“推荐模型+推荐原因”未生成或不完整，流程应直接阻断，不得进入建模阶段（可检查 `pre_model_gate.json`）。
- 如果用户说不继续，就基于已完成内容导出报告，并截断后续尚未执行的章节。

1. 先定义分析问题，再碰数据。  
   使用 [references/workflow.md](references/workflow.md) 明确分析目标、分析单元、核心指标、时间窗口、业务背景和成功标准。

2. 先检查环境，再承诺可执行。  
   运行 `python3 scripts/check_environment.py`，并对照 [references/environment.md](references/environment.md)。  
   特别关注 `MPLCONFIGDIR` 是否可写、是否检测到中文字体、以及 PDF/DOCX 导出链路是否齐全。

3. 按数据格式和规模选择读取策略。  
   文件输入优先用 `python3 scripts/io_router.py --input-path ...`；数据库输入参考 `scripts/db_connectors.py`。  
   结合 [references/io-strategy.md](references/io-strategy.md) 在 `pandas`、`polars`、`duckdb`、SQL 下推之间做选择。  
   优先使用原生 `sqlite` 与原生 `duckdb`，再考虑额外数据库驱动。

4. 建模前先做数据画像和清洗。  
   使用 `scripts/clean_preprocess.py` 处理缺失值、重复值、异常值和预处理建议。  
   使用 `scripts/eda_stats.py` 做统计汇总、正态性检验和时间序列诊断。

5. 先选最轻的方法，再考虑更重模型。  
   先看 [references/model-selection.md](references/model-selection.md)。  
   描述性或诊断性任务优先使用 `scripts/analysis_methods.py` 与 [references/analysis-methods.md](references/analysis-methods.md)，不要一上来就用 LSTM、Prophet 或复杂集成模型。

6. 用正确的验证方式评估结果。  
   使用 `scripts/evaluate.py`。  
   时间序列任务不要用随机切分，优先 walk-forward 或 `TimeSeriesSplit`。

7. 如果问题是“干预是否有效”，走因果分析路径。  
   使用 `scripts/causal_analysis.py`、`scripts/causal_narrative.py` 以及 [references/causal-inference.md](references/causal-inference.md)。  
   适用于 DID、RDD、合成控制、工具变量、DML、DR、PSM、异质性分析等。  
   不要把相关性结果当成因果证据对外表达。

8. 在写建议前先解释模型和发现。  
   监督学习任务用 `scripts/model_explainability.py` 与 [references/explainability.md](references/explainability.md) 生成特征重要性、Permutation Importance、PDP、SHAP。  
   再用 `scripts/explain_viz.py` 与 [references/chart-selection.md](references/chart-selection.md) 组织成 `背景 -> 发现 -> 建议 -> 风险` 的表达，而不是只丢指标。

9. 运行结束后导出可复核报告。  
   使用 `scripts/report_export.py` 和 [references/reporting.md](references/reporting.md) 生成结果导向的 `report_dashboard.html`。  
   同时使用 `scripts/full_process_report_export.py` 生成全流程追踪的 `report_process.html`（数据读取、缺失值、异常值、EDA、建模、图表、结论）。  
   再用 `scripts/report_index.py` 刷新 `outputs/` 下的 `run_index.html`、`run_index.json` 和各任务对比页。  
   如果需要交互式浏览，可运行 `streamlit run scripts/streamlit_dashboard.py -- --outputs-root <outputs_dir>`。

10. 如果用户要正式中文报告，再走报告导出链。  
    先读 [references/report-artifact-interpretation-zh.md](references/report-artifact-interpretation-zh.md) 与 [references/report-delivery-templates-zh.md](references/report-delivery-templates-zh.md)。  
    然后根据交付物选择 [templates/analysis-report-docx-template.md](templates/analysis-report-docx-template.md) 或 [templates/analysis-report-pdf-template.md](templates/analysis-report-pdf-template.md)。  
    若要一键在分析完成后同时产出 Dashboard HTML + Process HTML + DOCX + PDF，可直接运行：  
    `python3 scripts/run_pipeline.py ... --data-scope sample --sample-rows 5000 --formal-report --report-title "..."`  
    或  
    `python3 scripts/run_pipeline.py ... --data-scope full --formal-report --report-title "..."`  
    
    正式报告里的图表解读必须做二次视觉复核，不能停留在脚本导出的首稿：
    - 第一步：先运行 `python3 scripts/formal_report_export.py --run-dir <run_dir>` 生成排版稳定的首稿 DOCX / PDF，以及 `formal_report_draft.md` 和 `report_context.json`。
    - 第二步：由 agent 读取 `report_context.json`、首稿报告和对应 PNG；如果 DOCX/PDF 中图片不方便直接读取，就回到 run 目录读取对应 PNG。
    - 第三步：agent 必须结合前文已经写好的执行摘要、数据质量、核心指标、方法说明、业务解释，一张图一张图地写“详细图表解读”，并输出结构化 `chart_review.json`。
    - `chart_review.json` 的 `charts` 数组长度必须与最终纳入报告的图表数量一致；4 张图就写 4 段，5 张图就写 5 段。
    - 每个图对象至少包含 `file`、`title`、`interpretation`、`implication`、`caption_note`；另写一个 `overall_summary` 串起全部图表。
    - 每张图至少回答三个问题：这张图现在展示了什么、当前情况说明了什么、这背后可能意味着什么。
    - 图表解读必须面向分析基础较弱的读者：少用黑话，第一次出现的术语要顺手解释，不要假设读者知道 SHAP、PDP、lift、p_value 等词。
    - 图表解读要写成可直接放进正式报告的段落，不要写成“这张图围绕……展开”“帮助读者理解……”这类说明书式句子。
    - 图表解读区不要再写“怎么看”或“本图结论”这类模板化小标题，改成自然语言段落。
    - 如果图里出现英文指标、英文图例、英文坐标、缩写，或者中文专业名词对基础读者有理解门槛，要在图下注释补一行简短解释，例如“Accuracy（准确率）”“轮廓系数（衡量聚类是否分得清楚的指标）”。
    - 在所有单图解读之后，再补一段“图表总体解读”，用一段完整中文把几张图串起来，说明整体情况和背后意义。
    - 回填时不要直接改 DOCX / PDF 版式；应把 `chart_review.json` 作为参数传回 `python3 scripts/formal_report_export.py --run-dir <run_dir> --chart-review-json <path>`，由脚本把文字放回正式报告对应位置。
    - `formal_report_export.py` 现在不会再自动生成或自动复用模板化 `chart_review` 文案；没有显式传入 agent 回写的 `--chart-review-json` 时，报告只能保持 `draft`。
    - 脚本首稿的图表章节只保留图片与回写提示，不再用文件名、图表类型或默认说明去拼装“伪解读”。
    - 如果用户在跑模前或跑模中明确表示“不继续了”，就导出当前已完成部分的报告，并把后续尚未执行的建模、解释和结论章节省略或截断，且把该报告标记为草稿或部分完成。

11. 本地数据不足时，再启用外部研究。  
    使用 [references/web-research-rules.md](references/web-research-rules.md) 与 `scripts/source_research_adapter.py`。  
    这个适配器本身可以直接调用 `Bing`、`Google` 等搜索路径；`web-search-pro` 只是可选协同 skill，不是本技能的硬依赖实现。  
    换句话说，`web-search-pro` 的实现变更不应该直接阻断本技能的主分析流程。

12. 常见公共数据集优先走专用适配器。  
    对于 WDI 这类公开打包数据，优先用：  
    `python3 scripts/run_pipeline.py --dataset wdi --input-path <WDI_csv.zip>`  
    或  
    `python3 scripts/wdi_analysis_report.py --zip-path <WDI_csv.zip>`

## 约束与原则

- 优先处理结构化数据任务。纯 NLP、CV、分布式 Spark 类任务默认不在本技能主范围内。
- Excel 单个工作表最多 `1,048,576` 行；如果用户说 Excel 有几千万行，先把它当成数据物流问题，而不是直接分析问题。
- 缺依赖时要明确说明缺口，并给出安装命令，不能假装已经执行成功。
- 结果要可复现，机器可读产物和 Markdown 摘要要并存。
- 描述性、诊断性、预测性、实验性工作流要分开，不要把所有问题都硬塞进预测模型。
- 始终遵循 baseline-first：正确验证下的强基线，优先于带泄漏风险的重模型。
- `requirements.txt` 是默认安装基线；`requirements-optional.txt` 只在任务需要时再装。
- 正式报告里必须解释术语，并说明关键指标怎么读，不能裸扔 `accuracy`、`F1`、`p_value`、`RMSE`、`R2` 等数值。
- DOCX / PDF 报告应以原始 JSON / PNG / Markdown 产物为真源，Dashboard 只是复核层。
- 正式报告里要把技术标识转成业务可读中文，比如优先写“糖尿病状态”，而不是 `diabetes_status_no`。
- 正式报告里的图表解读必须经过一次基于图片本身的复写；只根据文件名、脚本默认说明或图表类型猜测，不足以直接交付。
- 正式报告导出应采用临时文件 + 原子替换，避免重复导出时残留旧内容。

## 核心脚本

- `scripts/check_environment.py`：检查依赖、运行时环境和导出能力
- `scripts/run_pipeline.py`：统一 CLI 入口，支持 `--formal-report` 与 `--dataset wdi`
- `scripts/io_router.py`：按格式与规模选择读取方案
- `scripts/db_connectors.py`：数据库读取、驱动检测与连接规划
- `scripts/db_smoke_test.py`：SQLite / DuckDB 本地烟雾测试，以及可选的远端数据库探测
- `scripts/clean_preprocess.py`：清洗、缺失值、异常值与预处理建议
- `scripts/eda_stats.py`：EDA 与统计检验
- `scripts/feature_engineering.py`：特征工程辅助
- `scripts/analysis_methods.py`：聚类、关联规则、ANOVA / Kruskal、根因贡献分析
- `scripts/causal_analysis.py`：因果分析主流程
- `scripts/causal_narrative.py`：把因果结果转成业务可读叙述
- `scripts/model_runner.py`：基线模型选择与运行
- `scripts/model_explainability.py`：监督学习可解释性
- `scripts/evaluate.py`：评估指标、交叉验证与验证策略
- `scripts/explain_viz.py`：图表规划和可视化输出
- `scripts/report_export.py`：导出静态 HTML Dashboard
- `scripts/full_process_report_export.py`：导出全流程 HTML 报告（report_process.html）
- `scripts/formal_report_export.py`：导出正式中文 DOCX / PDF 报告
- `scripts/wdi_analysis_report.py`：WDI 数据集专用适配器
- `scripts/report_index.py`：导出多次运行的静态索引与比较页
- `scripts/streamlit_dashboard.py`：交互式运行浏览器
- `scripts/business_templates.py`：漏斗、变现、留存、cohort、LTV 等业务模板
- `scripts/experiment_analysis.py`：A/B 实验与实验设计分析
- `scripts/source_research_adapter.py`：外部研究规划、执行、去重、冲突检测与标准化

## 参考文档

- `references/workflow.md`：分析合同与输出预期
- `references/environment.md`：依赖与环境准备
- `references/io-strategy.md`：数据读取路由
- `references/stats-and-tests.md`：统计检验选择
- `references/model-selection.md`：模型选择规则
- `references/analysis-methods.md`：描述性 / 诊断性方法说明
- `references/causal-inference.md`：因果分析路径与约束
- `references/explainability.md`：可解释性输出规范
- `references/experiment-design.md`：实验设计与实验分析规则
- `references/business-metrics.md`：业务指标口径
- `references/chart-selection.md`：图表选择与中文字体提示
- `references/reporting.md`：Dashboard 与正式报告导出规则
- `references/report-artifact-interpretation-zh.md`：正式报告前的产物解读指南
- `references/report-delivery-templates-zh.md`：中文正式报告交付规则
- `references/web-research-rules.md`：外部研究何时启用、如何启用
- `templates/analysis-report-docx-template.md`：中文 DOCX 报告模板
- `templates/analysis-report-pdf-template.md`：中文 PDF 报告模板
