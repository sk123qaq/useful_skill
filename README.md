# AI Agent 实用 Skills 仓库

这是一个面向 AI Agent / Codex / Claude 工作流的本地 skills 集合仓库。仓库里的每个一级目录通常对应一个独立 skill，目录内一般会包含 `SKILL.md`、`scripts/`、`references/`、模板或示例文件，用来支持语音、搜索、数据分析、文档解析与浏览器自动化等任务。

## 当前目录结构

当前仓库以这些目录为主：

```text
useful_skill/
├── audio-voice/
├── config-architect/
├── data_analysis_pro/
├── lightpanda/
├── mineru-api/
├── output/
├── outputs/
├── searxng-local/
├── volc-audio-transcription/
└── web-search-pro/
```

说明：

- `audio-voice/`：本地 ASR / TTS / 音频播放相关 skill
- `config-architect/`：Agent 配置架构检查与整理
- `data_analysis_pro/`：结构化数据分析工具箱
- `lightpanda/`：轻量级无头浏览器与抓取工具
- `mineru-api/`：云端文档解析
- `searxng-local/`：本地搜索与检索增强
- `volc-audio-transcription/`：火山引擎音频转写
- `web-search-pro/`：并发搜索与网页读取编排
- `output/`、`outputs/`：本地分析产物、下载文件、临时结果目录，不纳入 GitHub

## 仓库定位

- 这是一个“技能库”，不是单一应用
- 每个 skill 以自己的 `SKILL.md` 作为入口
- 实际能力通常由 `scripts/`、`references/`、`templates/`、`assets/` 等目录承载
- 仓库同时包含本地运行能力和依赖外部 API 的能力

## 主要 Skills

| Skill | 主要能力 | 典型场景 |
| --- | --- | --- |
| `audio-voice` | 本地 ASR / TTS / 播放 | 音频转写、语音生成、试听 |
| `config-architect` | Agent 配置治理 | 检查和整理配置层级 |
| `data_analysis_pro` | 结构化数据分析 | EDA、关系筛查、因果分析、基线建模 |
| `lightpanda` | 轻量浏览器抓取 | 网页抓取、内容抽取、浏览器服务 |
| `mineru-api` | 文档解析 | PDF / Office / 图片转 Markdown / JSON |
| `searxng-local` | 本地搜索 | 双语检索、候选结果发现 |
| `volc-audio-transcription` | 云端音频转写 | 会议录音、多语音频识别 |
| `web-search-pro` | 搜索编排 | 多主题调研、自动筛选网页 |

## 使用方式

1. 进入目标 skill 目录。
2. 阅读对应的 `SKILL.md`。
3. 按 skill 自身说明安装依赖、配置环境变量并执行自检。
4. 需要云端服务的 skill，准备相应 API Token、账号或服务实例。

## GitHub 上传约定

当前仓库里有一些本地开发和运行产物，不应该上传到 GitHub。默认忽略项包括：

- `output/`
- `outputs/`
- `.venv-data-analysis/`
- `.pytest_cache/`
- `LOCAL_GITHUB_UPLOAD_GUIDE.md`

这些内容都属于本地环境、缓存、下载数据或运行结果，保留在本机即可。
