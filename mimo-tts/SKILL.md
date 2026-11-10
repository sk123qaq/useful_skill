---
name: mimo-tts
description: >
  Use when 把文字变成语音/配音/朗读（文字转语音、TTS、有声书、播客配音、视频旁白、口播）with 小米 MiMo 开放平台
  MiMo-V2.5-TTS 系列：预置精品音色（冰糖/茉莉/苏打/白桦/Mia/Chloe/Milo/Dean）、
  用一段文字设计音色（voicedesign）、用音频样本复刻音色（voiceclone），支持自然语言风格指令与内联音频标签，
  长文按句切块后自动拼接。MUST USE when the user mentions mimo-v2.5-tts / MiMo TTS / 小米语音合成 /
  小米 Token Plan 配音, or asks 用小米的音色念/读出来. NOT for 语音识别（用 mimo-asr），
  and not for music generation.
argument-hint: '"<文本>" -o out.mp3 [--voice 冰糖] [--style "语速稍快，播客感"]'
---

# MiMo TTS — 语音合成（小米 MiMo 开放平台）

脚本：`scripts/tts.py`（纯标准库 + ffmpeg 做时长校验）。OpenAI 兼容协议，`POST {base}/chat/completions`，
认证头是 **`api-key`**。音频以 **base64 放在响应里**（`choices[0].message.audio.data`），直接落盘。

## When to Use

- 文字→语音：配音、朗读、口播、有声书、播客/视频旁白、课程音频；要指定音色或语气时尤其合适。
- 用户提到 MiMo TTS / mimo-v2.5-tts / 小米语音合成 / 「用小米那个音色念一下」。
- 需要**定制音色**：用一段文字描述设计音色（voicedesign），或用几秒音频样本复刻音色（voiceclone）。
- 不要用于：语音识别/转写（用 `mimo-asr`）；音乐生成；需要逐字时间戳的唱词对齐（返回的是整段音频，无时间戳）。

三款模型（同一 `mimo-v2.5-tts` 家族，只能选其一）：

| 模型 | 用途 | `audio.voice` | 注意 |
|---|---|---|---|
| `mimo-v2.5-tts` | **预置音色**（默认） | 可选，默认 `mimo_default` | 支持 `(唱歌)` 标签 |
| `mimo-v2.5-tts-voicedesign` | 用**一段文字描述**设计音色 | **不支持该字段** | `user` 消息＝音色描述（必填） |
| `mimo-v2.5-tts-voiceclone` | 用**音频样本**复刻音色 | 必填，`data:audio/mpeg;base64,...` | 仅 mp3/wav 样本，base64 ≤10 MB |

## 最关键的一条：文本放哪条消息

- **要合成的目标文本必须放在 `role: "assistant"` 的消息里**。放进 `user` 会被当成风格指令，**不会被念出来**。
- `role: "user"` 的消息是**风格指令**（自然语言，如"语速稍快，像播客主播""低沉的四十岁男声"），内容不出现在语音里；不用时传空串即可。
- 也可以在 `assistant` 文本里用**内联标签**精细控制：开头 `(风格)`，例如 `(低语)…`、`(唱歌)歌词`。

## 预置音色

| 音色名 | Voice ID | 语言/性别 |
|---|---|---|
| 默认 | `mimo_default` | 中国集群＝`冰糖`，其他集群＝`Mia` |
| 冰糖 / 茉莉 | `冰糖` / `茉莉` | 中文·女 |
| 苏打 / 白桦 | `苏打` / `白桦` | 中文·男 |
| Mia / Chloe | `Mia` / `Chloe` | 英文·女 |
| Milo / Dean | `Milo` / `Dean` | 英文·男 |

`python3 scripts/tts.py --list-voices` 可打印这张表。

## Prerequisites

- `ffmpeg`（用于时长/丢块校验；不装也能出音频，只是少一层校验）。
- Key 解析顺序：`MIMO_API_KEY` → `~/.config/mimo/api_key` → `~/.config/mimo-tts/api_key`。
- Base URL 解析顺序：`MIMO_BASE_URL` → `~/.config/mimo/base_url` → `~/.config/mimo-tts/base_url` → 默认 `https://token-plan-cn.xiaomimimo.com/v1`。
  - Token Plan Key 形如 `tp-xxxxx`（个人版）/ `ttp-xxxxx`（团队版）；按量付费 Key 形如 `sk-xxxxx`，用 `https://api.xiaomimimo.com/v1`。两套不通用。
  - **TTS 目前限时免费，不消耗 Token Plan 的 Credits**（官方定价页）。
- 一次性配置（让用户自己执行，别把 key 贴进聊天）：
  ```bash
  mkdir -p ~/.config/mimo
  printf '%s\n' '<你的key>' > ~/.config/mimo/api_key
  chmod 600 ~/.config/mimo/api_key
  ```
  ASR/TTS 共用这份配置（`mimo-asr` 技能读同一个文件）。

## How to Run

```bash
S=~/.agents/skills/mimo-tts/scripts/tts.py

python3 $S "要合成的话" -o out.wav                          # 默认音色，输出 wav
python3 $S -f article.txt -o out.mp3 --voice 苏打 --style "语速稍快，像播客主播"
python3 $S "文本" --model mimo-v2.5-tts-voicedesign --style "低沉的四十岁男声，语速舒缓，深夜电台感"
python3 $S "文本" --voice-sample voice.mp3 -o out.wav       # 音色复刻（自动切到 voiceclone）
python3 $S --list-voices
```

- 输出容器由 `-o` 后缀决定（`wav` / `mp3`），**接口原生支持 mp3**，不是本地转码。
- 长文自动按句末标点切块（默认每块 1200 字），wav 用 stdlib `wave` 拼接、mp3 按字节续接。
- 结束时打印成品时长与「逐块合计」，两者不一致会告警（判断拼接是否丢块）。
- 音色/风格怎么挑、内联标签怎么用、语速怎么调：见 `references/style-and-voice-selection.md`。

## Pitfalls

- **文本放错消息角色 = 合成出空音频/念了指令**（最常见）：目标文本必须放 `assistant`。
- **voicedesign 模型不接受 `voice` 字段**，且 `user` 消息必填（就是音色描述文本）；`optimize_text_preview: true` 时才可以省略 `assistant` 文本。
- **voiceclone 的 `voice` 必须自带 MIME 前缀** `data:audio/mpeg;base64,...`（或 `audio/wav`），样本 base64 ≤10 MB，只吃 mp3/wav。
- **拼接 wav 时比较参数不能带 `nframes`**：每块帧数天然不同，把它算进一致性比较会误报"参数不一致"（本脚本曾踩此坑）。
- **mp3 拼接后没有 Xing/Info 帧头，`ffprobe` 报的时长会明显偏短**（实测 500.1s vs 真实 531.5s）。要真时长必须**解码计数**（`ffmpeg -f s16le -` 数字节），脚本的 `measure_duration()` 已这么做。
- **返回规格固定**：wav = 24 kHz / 单声道 / `pcm_s16le`；≈48 KB/秒（3.5 分钟 ≈ 10 MB，注意很多播放/上传场景的体积上限）。
- **中文口播语速实测 ≈4.4 汉字/秒**，可用来估时长并校验是否漏合成（脚本会在偏差 >35% 时告警）；英文语速不同，别套这个系数。
- **单次请求有 8K 上下文**：约 1200 字的中文一次调用没问题（实测 1200 字 → 241.6 s 音频、无截断），更长的文本请让脚本切块，别硬塞。
- 合成耗时（含网络）约 **40–50 秒/千字**，长文请后台跑；流式接口目前对 voicedesign/voiceclone 是降级兼容模式，本脚本默认走非流式。
- 计费与额度：TTS 限时免费；但**重复跑会重复消耗时间与配额**，先存好产物再调参。

## Verification

- 成功：stdout 有 `SAVED: <path>`、`时长: x.xs（逐块合计 x.xs）`，且文件大小 > 0。
- **两块一致性**：成品时长应与逐块合计一致（差 >2s 即告警）；时长还应 ≈ 中文字数/4.4。
- **规格核对**：`ffprobe -show_entries stream=codec_name,sample_rate,channels` 应为 `pcm_s16le` / 24000 / 1。
- **回译校验（最强的一条）**：把生成音频喂给 `mimo-asr` 转写，与原文做字符级比对；实测相似度 99.53%（4 处差异全是 ASR 同音误听）。这是确认"真的念对了、没漏段"的可靠手段。

## 相关

- 反方向（音频 → 文字）：`mimo-asr`（同一套 Key/Base URL 配置）；`qwen-audio-tts` / `stepaudio-tts` 是同类替代服务。
- 做播客/口播视频：`podcast-download`（取素材）、`video-commentary`（配音 + 剪辑）。
