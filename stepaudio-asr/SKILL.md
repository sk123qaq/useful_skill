---
name: stepaudio-asr
description: "录音转写/语音转文字时用：StepFun 国际版 StepAudio 2.5 ASR（stepaudio-2.5-asr），SSE 流式返回。"
version: 0.1.0
---

# StepAudio 2.5 ASR — 语音识别 / 录音转写（StepFun 国际版 · Step Plan）

把音频文件转写成文字。`POST {base}/audio/asr/sse` 一次性提交 Base64 音频，服务端以 SSE 流式返回
增量文本（`transcript.text.delta`）与完整文本（`transcript.text.done`）。模型 `stepaudio-2.5-asr`
（4B MTP，极快：1 小时音频约 19 秒）。主脚本零第三方依赖；非 mp3/ogg/wav/m4a/pcm 的输入自动用
ffmpeg 转 16kHz 单声道 wav 再提交。

> 国际版域名是 `api.stepfun.ai`；国内版是 `api.stepfun.com`。两者 Key 与端点不通用，本 skill 面向国际版。
> Step Plan 下目前只有这一个 HTTP+SSE 识别端点（没有 WebSocket 双向流式）。

## When to Use
- 录音 / 会议 / 视频 / 播客 → 文字；语音消息转文字；字幕稿
- 需要词句级时间戳或热词提示
- Don't use for：文字转语音（用 `~/.agents/skills/stepaudio-tts`）；实时双向语音（Step Plan 不支持）

## Prerequisites
- StepFun 国际版账号，已订阅 Step Plan
- API Key 填入本 skill 目录的 `.env`（推荐）：
  ```
  STEPFUN_API_KEY=sk-你的key
  ```
  脚本读取优先级：环境变量 `STEPFUN_API_KEY`（或 `STEP_API_KEY`）→ 本目录 `.env`
- ffmpeg：非 mp3/ogg/wav/m4a/pcm 输入时需要

## How to Run
脚本：`~/.agents/skills/stepaudio-asr/scripts/asr.py`
```bash
SKILL=~/.agents/skills/stepaudio-asr
python3 $SKILL/scripts/asr.py 录音.m4a                 # 转写，stdout 输出纯文本
```

## Quick Reference
```bash
python3 $SKILL/scripts/asr.py a.mp3                                             # 纯文本
python3 $SKILL/scripts/asr.py a.mp3 -o a.txt --json a.json --timestamps         # 落盘 + 时间戳
python3 $SKILL/scripts/asr.py a.mp3 --language zh --hotwords "阶跃,StepFun" --verbose
python3 $SKILL/scripts/asr.py a.pcm --rate 16000 --bits 16 --channel 1          # 裸 PCM 需指明参数
python3 $SKILL/scripts/asr.py a.flac --dry-run                                  # 先看格式探测与请求体
```

## 支持的输入
| 输入扩展名 | 处理方式 |
| --- | --- |
| mp3 / ogg / wav / m4a | 原样 Base64 提交 |
| pcm | 必须 `--rate / --bits / --channel` 指明原始参数（如 16000 16 1） |
| 其他（flac、aac、mp4…） | ffmpeg 自动转 16kHz 单声道 wav 再提交 |

## 常用参数
| 脚本参数 | API 字段 | 说明 |
| --- | --- | --- |
| `--language` | `transcription.language` | 语言提示，如 `zh`；不传则由模型判断 |
| `--hotwords` | `transcription.hotwords` | 逗号分隔热词，提升专名识别率 |
| `--no-itn` | `transcription.enable_itn` | ITN 文本规范化默认开启（数字/符号） |
| `--timestamps` | `transcription.enable_timestamp` | 返回词句级时间戳（毫秒） |
| `--json` | — | 保存 `{"text": …, "segments": […]}` |
| `--base-url` | — | 默认 `https://api.stepfun.ai/step_plan/v1`（可用环境变量 `STEPFUN_BASE_URL` 覆盖） |

## Procedure
1. 确认音频文件存在、格式受支持（不确定先 `--dry-run` 看探测结果与请求体）。
2. 运行脚本，服务端流式返回；结束输出完整文本。完成标准：退出码 0 且 stdout 有文本。
3. 交付：文本直接给用户；长转写建议落盘（`-o out.txt`）；要字幕/校对加 `--timestamps --json`。
4. 失败时读 stderr 的 HTTP 状态码与 error 事件消息。

## Pitfalls
- 音频要 Base64 塞进 JSON，请求体约为文件的 1.33 倍；超大文件（>1 小时）建议先 ffmpeg 切段再逐段转写。
- 请求头必须带 `Accept: text/event-stream`（脚本已带）；缺了可能被拒。
- `.pcm` 裸流若 rate/bits/channel 给错，会得到乱码或空文本；拿不准就换 wav/mp3 输入。
- SSE 端点不支持 `full_rerun_on_commit`（二遍纠错），传了会被服务端忽略。
- 401 = Key 无效或未订阅 Step Plan；确认用的是国际版（.ai）控制台创建的 Key。
- 完整文本以 `transcript.text.done.text` 为准；`--timestamps` 的 segments 来自 delta 事件（逐句/逐词）。

## Verification
- 成功：退出码 0，stdout 文本非空；`--json` 文件含 `text` 字段。
- 可用 `ffprobe` 先看音频时长，与转写结果人工抽检。
- 失败：stderr 含 `错误: HTTP <码> …` 或 `错误: 服务端识别失败: …`。
