---
name: stepaudio-tts
description: "文字转语音(TTS)时用：StepFun 国际版 StepAudio 2.5（stepaudio-2.5-tts），支持语境指令控情绪。"
version: 0.1.0
---

# StepAudio 2.5 TTS — 文本转语音（StepFun 国际版 · Step Plan）

把文本合成为真人级语音并保存为音频文件。调用 StepFun 国际版 Step Plan 专属端点
（base：`https://api.stepfun.ai/step_plan/v1`），模型 `stepaudio-2.5-tts`（Contextual TTS：
`instruction` 控制整段语气基调，文本里用 `()` 内联控制局部情绪/停顿）。支持输出中文 / 英文 / 中英混合 / 日语。
主脚本零第三方依赖（纯 Python 标准库），任何 agent 只要有终端和 python3 即可调用。

> 国际版域名是 `api.stepfun.ai`；国内版是 `api.stepfun.com`。两者 Key 与端点不通用，本 skill 面向国际版。

## When to Use
- 文本 → 语音：旁白、口播、有声书、视频配音、语音消息
- 需要指定音色 / 语速 / 音量 / 情绪语气，或需要字幕时间戳（.srt）
- Don't use for：语音转文字（用 `~/.agents/skills/stepaudio-asr`）；实时双向语音对话

## Prerequisites
- StepFun 国际版账号，已订阅 Step Plan（`stepaudio-2.5-tts` 属 Step Plan 套餐模型，按套餐额度计费）
- API Key 填入本 skill 目录的 `.env`（推荐）：
  ```
  STEPFUN_API_KEY=sk-你的key
  ```
  脚本读取优先级：环境变量 `STEPFUN_API_KEY`（或 `STEP_API_KEY`）→ 本目录 `.env`
- ffmpeg：仅文本 >1000 字符且使用 `--split` 分块拼接时需要

## How to Run
脚本：`~/.agents/skills/stepaudio-tts/scripts/tts.py`
```bash
SKILL=~/.agents/skills/stepaudio-tts
python3 $SKILL/scripts/tts.py "你好，世界！" --out hello.mp3
```

## Quick Reference
```bash
python3 $SKILL/scripts/tts.py "文本" [--out a.mp3] [--voice V] [--instruction "语气温柔，语速偏慢"]
python3 $SKILL/scripts/tts.py "（冷笑）你以为……" --instruction "语气极其愤怒，语速偏快"   # 内联+全局语境
python3 $SKILL/scripts/tts.py --file 全文.txt --split --out 全文.mp3      # >1000 字自动分块+拼接
python3 $SKILL/scripts/tts.py "文本" --subtitles --out a.mp3              # 同时产出 a.srt 字幕
python3 $SKILL/scripts/tts.py "文本" --dry-run                            # 只打印请求体，不调用
python3 $SKILL/scripts/tts.py "文本" --format wav --sample-rate 48000     # 高音质
```

## 常用参数
| 脚本参数 | API 字段 | 说明 |
| --- | --- | --- |
| `--voice` | `voice` | 音色 ID，默认 `elegantgentle-female`（国际版明列音色）；速查见 `references/voices.md` |
| `--instruction` | `instruction` | 全局语气指令 ≤200 字（仅 stepaudio-2.5-tts 支持） |
| 文本内 `()` | — | 括号内为内联指令，不发音；要念出字面量就别加括号 |
| `--format` | `response_format` | mp3(默认)/wav/flac/opus/pcm |
| `--speed` / `--volume` | `speed`/`volume` | 0.5~2.0 / 0.1~2.0 |
| `--sample-rate` | `sample_rate` | 8000/16000/22050/24000(默认)/48000 |
| `--tn` | `text_normalization` | standard(默认)/enhanced（长文播报用 enhanced） |
| `--tone` | `pronunciation_map.tone` | 注音/替换，如 `--tone "阿胶/e1胶"`，可重复 |
| `--subtitles` | `return_url+timestamp` | 词级时间戳并生成 .srt 字幕 |
| `--base-url` | — | 默认 `https://api.stepfun.ai/step_plan/v1`（可用环境变量 `STEPFUN_BASE_URL` 覆盖） |

## Procedure
1. 确认 `.env` 里已有 Key（没有时脚本会直接报错并给出路径）。
2. 文本 ≤1000 字符直接合成；超长加 `--split`（按句末标点自动分块，ffmpeg 流拷贝拼接）。
   完成标准：退出码 0，输出音频文件存在且 >0 字节。
3. 需要字幕加 `--subtitles`：脚本写 `<输出名>.srt`（切句 + 逐词时间轴，毫秒级）。
4. 交付：把音频路径给用户；长音频建议先播放/抽查一小段。

## 进阶：流式（SSE，低时延场景）
本脚本是非流式（文件合成）。要边生成边播可改用 `stream_format: "sse"`：
事件流为 `speech.audio.delta`（BASE64 音频分片）→ `speech.audio.done` → `[DONE]`；
另可配 `timestamp: true` 收到 `response.subtitle` 字幕事件。WebSocket 版：
`wss://api.stepfun.ai/step_plan/v1/realtime/audio?model=stepaudio-2.5-tts`。

## Pitfalls
- `voice_label`（emotion/style/language 标签）与 stepaudio-2.5-tts **不兼容**，传了会报错；情绪风格一律用 `instruction` + 文本内 `()`。
- `input` 括号 `()` 内内容只当指令 **不发音**；`instruction` 最长 200 字符；`input` 最长 1000 字符（超了脚本会拒绝并提示 `--split`）。
- 字幕时间戳必须配 `return_url=true`（非流式）或 `stream_format="sse"`（流式）；裸二进制流模式下请求会 400。
- mp3 分块拼接是帧级流拷贝，句子边界处可能有极短间隙；追求无缝用 `--format wav`。
- 401 = Key 无效或未订阅 Step Plan；确认用的是国际版（.ai）控制台创建的 Key。
- 官方音色 ID 跨模型通用；复刻音色用创建接口返回的 voice ID（约 3 秒参考音频即可，同样支持语境指令）。
- 国际版文档明列的系统音色为 7 个（见 `references/voices.md`）；其他音色若报音色相关错误，改用明列音色。

## Verification
- 成功：stdout 打印 `已生成: <文件> (… KB)`，退出码 0。
- 检查：`ffprobe <文件>` 时长正常；`--subtitles` 时 .srt 可被播放器加载。
- 失败：stderr 显示 `错误: HTTP <状态码>: <服务端消息>`，按提示检查 .env / 参数。
