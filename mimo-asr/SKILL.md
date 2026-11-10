---
name: mimo-asr
description: >
  Use when 转录音频/视频为文字（录音、会议、播客、访谈、字幕稿）with 小米 MiMo 开放平台，
  尤其是中英混说 + 中国方言（粤语/吴语/闽南语/四川话）或歌词转写；长音频自动降采样、按静音点切片、
  逐块调用并拼接。MUST USE when the user mentions mimo-v2.5-asr / MiMo ASR / 小米语音识别 /
  小米 Token Plan 转写, or hands over a long recording to transcribe. Covers the provider's hard
  per-request limits (inline base64 ≤10 MB, 8K context, RPM/TPM) and the silent-truncation trap
  that makes >300s chunks lose content. NOT for TTS (use mimo-tts), and not for services that
  take a public audio URL (this API takes inline base64 only).
argument-hint: '"<audio.mp3>" [--lang en|zh|auto] [--chunk 180]'
---

# MiMo ASR — 长音频转写（小米 MiMo 开放平台）

把音频/视频转写成文字。模型只有 `mimo-v2.5-asr`；OpenAI 兼容协议，但**音频必须以内联 Base64 data URL 传入**（不支持公网 URL、不支持文件上传通道）。

**长音频必须切片**——见下方「硬限制」。脚本 `scripts/asr.py` 已内建：转单声道 → 找静音点对齐切片 → 逐块调用（自带 TPM 限速与退避重试）→ 拼接输出。

## When to Use

- 录音/会议/播客/视频 → 文字，尤其是要**中英混说 + 方言**（粤语、吴语、闽南语、四川话）或歌词转写。
- 用户已有小米 MiMo Token Plan 额度（Token Plan **覆盖 ASR**：30M Credits / 音频小时；Lite 套餐 4.1B Credits/月 ≈ 136 音频小时）。
- 不要用于：TTS；实时麦克风流（虽然支持 stream，但脚本按整块处理）；只认公网 URL 的场景（本模型不收 URL）。

## Prerequisites

- `ffmpeg` / `ffprobe`（切片与时长校验）。
- Key 查找顺序：环境变量 `MIMO_API_KEY` → 文件 `~/.config/mimo/api_key` → 文件 `~/.config/mimo-asr/api_key`（旧路径，兼容保留）。
- Base URL 查找顺序：`MIMO_BASE_URL` → `~/.config/mimo/base_url` → `~/.config/mimo-asr/base_url` → 默认 `https://token-plan-cn.xiaomimimo.com/v1`。
  - **Token Plan 用 `https://token-plan-cn.xiaomimimo.com/v1`**，Key 形如 `tp-xxxxx`（个人版）/ `ttp-xxxxx`（团队版）。
  - 按量付费用 `https://api.xiaomimimo.com/v1`，Key 形如 `sk-xxxxx`。两套额度不互通。
- 一次性配置（**让用户自己执行，不要把 key 贴进聊天** —— 聊天里的 key 会留在会话记录里）：
  ```bash
  mkdir -p ~/.config/mimo
  printf '%s\n' '<你的key>' > ~/.config/mimo/api_key
  chmod 600 ~/.config/mimo/api_key
  ```
- 脚本查不到 key 时直接报错退出：先把上面这条配置命令给用户，其余部分（切片、体积预算）可以先备好，不必空等。

## 硬限制（官方文档，决定必须切片）

| 限制 | 值 | 后果 |
|---|---|---|
| 音频格式 | 仅 mp3 / wav | 其他格式先转码 |
| Base64 串上限 | **10 MB**（≈ 7.5 MB 原始音频） | 128kbps 立体声只有 ~8 分钟 |
| 上下文 / 最大输出 | 8K / **2K tokens** | 输出 2K ≈ 1300 英文词 ≈ 8–9 分钟语音；超了 `finish_reason=length` 会**静默截断** |
| RPM / TPM | 100 / **10K** | 连续快发会 429，需按 TPM 限速 |
| 音频 token 换算 | ≈ 6.25 tokens/秒（实测：13s → 76 audio tokens ≈ 5.9/s） | 3 分钟 ≈ 1050 tokens |

**结论：默认切片 180 秒（不要超过 300 秒）** —— 见 Pitfalls 第一条：>300s 的块会被静默丢内容，比 10MB / 2K 输出这两道「文档里写了的墙」更早撞上。
参考体积：16kHz 单声道 32kbps mp3 ≈ 4 KB/s → 3 分钟 ≈ 0.7 MB → base64 ≈ 0.95 MB（远低于 10 MB）。

> **实测（65 分钟英文播客，128kbps 立体声源，本机全流程跑通）**：180s 切片 → 22 块，每块 0.6–0.8 MB、密度稳定 12.6–16.0 字符/秒；总耗时约 4 分钟（含 TPM 限速等待），无 429。`api-key` 头 + data URL + `asr_options` 的调用路径已确认可用（`tp-` Token Plan 与 `sk-` 按量两种 Key 走不同 Base URL）。

## How to Run

```bash
SKILL=~/.agents/skills/mimo-asr
python3 $SKILL/scripts/asr.py "/path/episode.mp3"                 # → episode.txt + episode.asr.json
python3 $SKILL/scripts/asr.py ep.mp3 --lang en --chunk 180        # 明确英文能提准确率（默认 180）
python3 $SKILL/scripts/asr.py ep.mp3 -o out.txt --keep-chunks
```

输出：`<name>.txt` 每块带 `## [hh:mm:ss]` 头（便于定位原片位置），`<name>.asr.json` 记每块起止与字符数。切片文件默认清理。**跑完会有一行 `⚠️ 密度仍在正常区间外` 列出可疑块 —— 那些块必须单独重跑，别直接拿去写摘要。**

先探针后全量：切一段 10–15 秒音频跑单次调用，确认 Key / Base URL / 认证头都对（`api-key` 头写错直接 401），再提交整段；探针返回的 `usage.prompt_tokens_details.audio_tokens` 还能校准 audio tokens/秒。

## Pitfalls

- **⚠️ 切片 >300 秒会静默丢内容（本技能最重要的坑）**：同一段音频，360–370s 整块转写只出 500–2500 字符（1.4–6.8 字符/秒），拆成 120s 后同样内容出 1500–1900 字符（12.8–16 字符/秒）。官方文档没有这条限制（10MB / 8K context 都还用不到），`finish_reason` 照样是 `stop`，**不报错、不缺文件，只是正文缺一大段**。默认 180s 切片，不要超过 300s。
- **必须做双侧密度校验**：英文语音正常约 **12–16 字符/秒**（中文约 3–5）。**偏低 = 静默丢内容；偏高 = 复读循环**（同一段话被反复改写输出，实测 42.5 字符/秒、`finish_reason=length`）。脚本按 en 8–22（zh 3–8）区间判坏块 → 对半重切，且只在重切结果密度更靠近正常区间时才采用。只信 `finish_reason` 会漏掉偏低那条，只设下限会漏掉复读那条。
- **复读循环别指望用文本去重修**：重复段落是改写过措辞的（不是逐字重复），按句/按 n-gram 去重抓不到。唯一可靠修法是把该块拆到 ≤100 秒重转；转写跑完先扫一遍整段重复，有就重跑那块，再动手写摘要。
- **先降采样再切片**：拿 128kbps 立体声原始文件直接按 6 分钟切，每块 ≈ 6 MB 音频 → base64 ≈ 8 MB，已经贴着 10 MB 上限；先 `-ac 1 -ar 16000 -b:a 32k` 降到 ~4 KB/s（脚本默认已做，「体积小」和「token 少」是同一件事的两面）。
- **返回文本可能带杂标签**：偶尔在正文前插入 `think>` / `<chinese>` 之类前缀（模型自身标记泄漏），引用/总结前先 strip。
- **`finish_reason=length` 是另一种静默截断**（输出触顶 2K）：脚本同样自动对半重切。
- **audio 字段必须带 MIME 前缀**：`data:audio/mpeg;base64,...`；只给裸 Base64 时必须另传 `format: "mp3"`。
- **认证头是 `api-key`**（不是 `Authorization: Bearer`）；用 `Authorization` 会 401。
- **Token Plan 与按量付费 Base URL / Key 前缀不通用**，混用会 401/额度报错。
- **切片要落在静音点**：硬切会切掉半个词。脚本用 `silencedetect=noise=-32dB:d=0.45` 在目标点 ±75s 内找最近静音中点；找不到才原地切。
- **TPM 10K 是每分钟口径**：11 块 ≈ 24K 音频 tokens，一次快发必 429；脚本的 `Pacer` 用滚动 60s 窗口控制。
- 计费按**输入音频时长**（精确到秒折算小时），与语言/切片数无关；重复跑会重复计费，先存好结果再重试。
- 中文标点自动生成，无需后处理；返回的是纯文本，**没有时间戳**（要时间戳只能按切片起点自制，粒度=切片长度）。

## Verification

- 成功：stdout 每块 `ok <秒>s · <字符数> (<密度>/s)`，最后给 TXT/JSON 路径。
- **密度是主判据**：英文 12–16 字符/秒、中文 3–5；哪块明显偏低、日志里又没出现「密度过低…对半再切」，说明阈值设松了。
- 成本核对：`usage.seconds` 之和应 ≈ 音频总时长（180s×22 块 ≈ 3933s，吻合）。
- **回译对鼋**：把转写稿反过来喂 `mimo-tts` 合成语音、再转写回来做字符级对比，相似度应 >99%（实测 99.53%，差异全是同音误听）——这是验证“没丢段、没读错”的最强手段。
- **用现成清单当完整性核对表**：材料自带 show notes / 字幕 / 议程时逐条对一遍；列了但正文完全没有的话题，就是某块被静默丢了内容（比 `finish_reason` 更早暴露）。

## 相关

- 反方向（文字 → 语音）：`mimo-tts`（同一套 Key / Base URL 配置，脚本在 `~/.agents/skills/mimo-tts/`）。
- 拿播客音频：`podcast-download`；要出中文要点稿时，交付形状看那个技能自带的 chinese-digest-format 参考文件。
- 同类替代服务（按可用性/成本选）：`qwen-asr`（千问 AI，长音频异步任务）、`stepaudio-asr`（StepFun，流式）。
