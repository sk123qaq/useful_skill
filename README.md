# AI Agent 实用 Skills 仓库

面向 AI Agent（Claude Code / Codex / pi / Hermes 等）的可复用 skills 集合。每个一级目录是一个独立 skill，
以自己的 `SKILL.md` 作为入口：`description` 决定什么时候被调用，正文写流程与判据，`scripts/` 承载确定性逻辑，
`references/` 放按需读取的长文细节。

仓库不绑定任何特定 agent —— 只要运行环境能读文件、跑 `bash` / `python3`，就能按 `SKILL.md` 的步骤执行。

## 目录结构

```text
useful_skill/
├── a-share-financials/   A 股财报查询：指标、三大报表、单季同环比、批量名单出表
├── data_analysis_pro/    结构化数据分析工作流：契约 → 脚本证据 → gate 定级
├── ebook-to-md/          电子书拆章转 Markdown，保留图片，默认省略前后杂项
├── mimo-asr/             小米 MiMo 语音识别：长音频切片、中英混说与方言
├── mimo-tts/             小米 MiMo 语音合成：预置音色 / 文字设计音色 / 声音复刻
├── mineru/               MinerU 云端文档解析：PDF / Office / 扫描件 → Markdown
├── podcast-download/     按标题 / Apple 链接 / RSS 下载播客单集并核对
├── qwen-audio-tts/       阿里云百炼 qwen-audio-3.1-tts-next 音频生成
├── stepaudio-asr/        StepFun 国际版 StepAudio 2.5 语音识别（SSE 流式）
├── stepaudio-tts/        StepFun 国际版 StepAudio 2.5 语音合成（语境指令控情绪）
└── video-commentary/     外语影视长视频 → 中文解说成片（ASR / 写稿 / TTS / ffmpeg 剪辑）
```

## Skill 清单

| Skill | 什么时候用 | 主要入口 |
|---|---|---|
| `a-share-financials` | 查 A 股财报：财务指标、三大报表、单季同比环比、按名单批量出表 | `scripts/fetch_a_share_financials.py` |
| `data_analysis_pro` | 拿到一份或一组数据要「看看有什么 / 预测 / 归因 / 评估实验」；要可复核、可追溯的结论 | `scripts/workflow.py`、`scripts/gate_evaluator.py` |
| `ebook-to-md` | 把 EPUB / MOBI / AZW3（或有文字层的 PDF）拆成按章的 Markdown，保留图片、合并合集、核对章节映射 | `scripts/ebook_to_md.py` |
| `mimo-asr` | 录音 / 会议 / 播客 / 访谈转文字，尤其中英混说、粤语吴语闽南语四川话、歌词 | `scripts/`（`MIMO_API_KEY`） |
| `mimo-tts` | 文字转语音：有声书、播客配音、视频旁白；预置音色、音色设计、声音复刻 | `scripts/tts.py` |
| `mineru` | 需要高保真结构（版式、表格、公式、扫描件 OCR）的文档转 Markdown，本地库搞不定的 PDF | `scripts/` + MinerU 云 API |
| `podcast-download` | 从标题、Apple Podcasts 链接或 RSS 定位并下载单集音频 | `scripts/podcast_download.py` |
| `qwen-audio-tts` | 用自然语言提示词生成人声 / 多人对话 / 播客 / 音效与环境音 | `scripts/`（纯标准库） |
| `stepaudio-asr` | 音频转写文字，要快（1 小时音频约 19 秒） | `scripts/asr.py`（纯标准库） |
| `stepaudio-tts` | 文本合成真人级语音，需要整段语气基调 + 句内内联情绪控制 | `scripts/tts.py`（纯标准库） |
| `video-commentary` | 外语影视做中文解说成片：定位原片台词、写解说词、配音、按彩蛋反推剪辑点、闪避原声、烧字幕 | `scripts/`、`tests/run.sh` |

## 凭据与配置

需要外部 API 的 skill 一律**只读环境变量或本地 `.env`**，仓库内不含任何真实 key
（真实 `.env` 已在源头排除，只提交空值 `.env.example`）：

| Skill | 变量 | 从哪里拿 |
|---|---|---|
| `qwen-audio-tts` | `DASHSCOPE_API_KEY`、`SFM_WORKSPACE_ID` | 阿里云百炼控制台 |
| `stepaudio-asr` / `stepaudio-tts` | `STEPFUN_API_KEY` | platform.stepfun.ai（国际版，国内 .com 的 key 不通用） |
| `mimo-asr` / `mimo-tts` | `MIMO_API_KEY` | 小米 MiMo 开放平台 |
| `mineru` | `MINERU_API_KEY` / `MINERU_TOKEN` | OpenDataLab |
| `a-share-financials` | 无（公开数据源） | — |

用法：`cp .env.example .env` 后填入自己的值；同名环境变量优先级更高。`.env`、`*.key`、`*.pem` 已在 `.gitignore` 中。

## 约定

- 每个 skill 自包含：脚本用相对自身目录的路径，不依赖仓库根。
- 主脚本尽量零第三方依赖；需要重依赖（torch、pdf 工具链等）的 skill 在 `SKILL.md` 里写明安装方式。
- 大文件不入仓：测试生成的音频、成片、中间产物在 `tests/tmp/`、`outputs/`，已被忽略。
- `video-commentary/tests/fixture/` 由 `tests/make_fixture.py` 现生成（含合成素材），不入仓；
  `sh video-commentary/tests/run.sh` 会先造夹具再跑全链冒烟（不要把它当真实素材检出）。

## 许可

各 skill 以自身 `SKILL.md` / 目录内声明为准。
