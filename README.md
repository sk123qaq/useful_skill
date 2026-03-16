# AI Agent 实用 Skills 仓库

这是一个面向 AI Agent / Codex / Claude 工作流的实用 skill 集合仓库。仓库中的每个目录都对应一个独立 skill，通常包含 `SKILL.md`、脚本、参考资料、模板或示例输出，可用于语音处理、数据分析、网页抓取、文档解析与搜索增强等场景。

## 项目定位

- 面向 AI 助手的可复用技能库，而不是单一应用项目
- 以 `SKILL.md` 为入口，定义触发条件、能力说明和使用方式
- 以 `scripts/`、`references/`、`templates/`、`assets/` 提供落地实现
- 兼顾本地离线能力与云端 API 能力

## 仓库结构

```text
useful_skill/
├── audio-voice/
├── config-architect/
├── data_analysis/
├── lightpanda/
├── mineru-api/
├── searxng-local/
├── volc-audio-transcription/
└── web-search-pro/
```

## Skill 总览

| Skill | 主要能力 | 典型场景 | 特点 |
| --- | --- | --- | --- |
| `audio-voice` | 本地 ASR / TTS / 音频播放 | 语音转写、文本朗读、生成配音 | 本地离线，基于 Qwen3 + `mlx_audio` |
| `config-architect` | Agent 配置体系审计与重构 | 检查 USER/SOUL/TOOLS/AGENTS/MEMORY 等配置文件 | 强调 OpenClaw 配置文件层级清晰、无冲突、可迁移 |
| `data-analysis` | 结构化数据分析全流程 | 商业分析、实验分析、因果分析、正式报告输出 | 功能最完整，含脚本、模板、参考资料 |
| `lightpanda` | 轻量级无头浏览器 | 网页抓取、Markdown 转换、CDP/MCP 服务 | 轻量、高性能、适合自动化抓取 |
| `mineru-api` | 云端文档解析 | PDF/Word/PPT/图片转 Markdown/JSON/HTML | 支持 OCR、表格、公式识别 |
| `searxng-local` | 自建 SearXNG 搜索 | 双语网页检索、新闻/图片/技术搜索 | 隐私友好，可控性高 |
| `volc-audio-transcription` | 火山引擎音频转写 | 多语言转录、说话人分离、情绪检测 | 云端 ASR，适合高精度转写 |
| `web-search-pro` | 并发搜索与网页读取编排 | 多主题调研、资料收集、自动筛选网页 | 支持搜索编排与 Lightpanda 批量读取 |

## 每个 Skill 的介绍

### 1. `audio-voice`

这是一个本地语音处理 skill，覆盖语音转文字、文字转语音和播放音频三类任务。它使用 Qwen3 本地模型与 `mlx_audio`，适合不希望依赖外部 API 的场景。

适用场景：
- 将音频文件转写成文本
- 将中文或英文文本朗读为语音文件
- 基于参考音频做语音克隆

目录亮点：
- `SKILL.md`：使用说明与参数介绍
- `scripts/`：ASR、TTS、流式播放脚本
- `references/`：快速参考说明

### 2. `config-architect`

这个 skill 面向 OpenClaw / Agent 配置体系本身，核心目标不是处理业务数据，而是审计和优化配置文件架构。它聚焦 `USER.md`、`SOUL.md`、`TOOLS.md`、`AGENTS.md`、`MEMORY.md`、`HEARTBEAT.md` 等配置层，帮助识别冲突、错位、冗余和伪状态引用。

适用场景：
- 审计 Agent 配置文件是否职责清晰、是否互相冲突
- 把规则从错误文件迁移到正确层级
- 为缺失的配置文件生成模板
- 验证浏览器流程、时间敏感规则、Python 版本等关键约束是否一致

目录亮点：
- `SKILL.md`：配置架构治理方法与检查清单
- `scripts/`：自动化审计脚本

### 3. `data-analysis`

这是仓库中最完整、最重型的 skill，提供从问题定义、数据读取、清洗、建模、评估、可视化到正式报告导出的全流程能力。它适合业务分析、增长分析、实验分析、因果推断、解释性分析等场景。

适用场景：
- CSV / Excel / JSON / Parquet / 数据库分析
- 漏斗、留存、LTV、营收等商业指标分析
- A/B Test、显著性检验、CUPED、序贯监测
- DID、RDD、PSM、DML 等因果分析
- 输出 HTML、DOCX、PDF 报告

目录亮点：
- `scripts/`：分析主流程与核心工具脚本
- `references/`：方法论、图表选择、实验设计、报告规范
- `templates/`：正式报告模板
- `outputs/`：运行产物与示例结果

### 4. `lightpanda`

这是一个轻量级无头浏览器 skill，适合做网页抓取与内容抽取，也可以启动 CDP 或 MCP 服务供其他工具接入。它非常适合 AI Agent 工作流中的“先抓网页，再结构化处理”环节。

适用场景：
- 抓取网页 HTML、Markdown 或语义树
- 为其他浏览器自动化工具提供 CDP 服务
- 作为 MCP 服务接入 AI 助手

能力特点：
- 支持清理 JS/CSS/UI 噪音
- 支持 iframe 内容抓取
- 输出格式适合 LLM 进一步消费

### 5. `mineru-api`

这个 skill 通过 MinerU 云端 API 解析文档，适合处理版式复杂的 PDF、Word、PPT、图片和 HTML。它可以输出 Markdown、JSON、HTML 等结构化结果，并支持 OCR、表格识别和公式识别。

适用场景：
- 批量解析 PDF 或 Office 文档
- 将复杂文档转为 Markdown 供后续处理
- 保留版式结构进行信息抽取

目录亮点：
- `scripts/parse_local.py`：本地文件快速解析入口
- `scripts/mineru_client.py`：API 封装
- `references/api_docs.md`：接口说明

### 6. `searxng-local`

这是一个围绕自建 SearXNG 实例设计的搜索 skill，强调双语搜索、隐私友好与可控的检索体验。与公有搜索 API 相比，它更适合对可控性、可重复性和中英文并行检索有要求的工作流。

适用场景：
- 同时检索中文和英文结果
- 做新闻、技术文档、图片、学术等分类搜索
- 为后续网页抓取提供候选链接

能力特点：
- 提供 Docker 快速部署方式
- 支持 `json` / `html` / `rss` 输出
- 强调中英双语并行搜索的最佳实践

### 7. `volc-audio-transcription`

这个 skill 使用火山引擎录音文件识别服务做音频转写，适合需要更强云端识别能力的场景。它支持多种中文方言和多国语言，并可开启标点、说话人分离、语种识别、情绪检测等高级功能。

适用场景：
- 会议录音、访谈录音的高精度转写
- 多人对话音频的说话人分离
- 中英混合或多语言转录

注意事项：
- 音频必须通过公网 URL 提供给火山引擎访问
- 使用前需要配置 `VOLC_APP_KEY` 和 `VOLC_ACCESS_KEY`

### 8. `web-search-pro`

这是一个面向研究型任务的搜索编排 skill，通过 Orchestrator 脚本把“多短语搜索、自动筛选、批量抓取网页内容”串成一个高性能闭环。它尤其适合信息搜集、主题研究和多阶段资料整理。

适用场景：
- 竞争研究、行业调研、主题扫描
- 多个关键词并发搜索
- 自动去重、加权排序并抓取网页正文

能力特点：
- 支持多短语并发查询
- 内置域名去重、关键词加权、时间窗口匹配
- 可联动 `lightpanda` 自动抓取网页 Markdown

## 如何使用这个仓库

1. 先进入目标 skill 目录，阅读对应的 `SKILL.md`
2. 优先按 skill 内文档安装依赖、配置环境变量并执行自检命令
3. 需要云端服务的 skill，请自行准备 API Token、账号或服务实例
4. 建议将本仓库作为“skill 集合”管理，而不是把所有脚本都当成一个统一应用运行
