---
name: qwen-audio-tts
description: "文字转语音/音频生成(Audiogen)时用：阿里云百炼 qwen-audio-3.1-tts-next。用自然语言提示词＋参考音频，一次生成人声、多人对话、播客、音效与环境音。"
version: 0.1.0
---

# qwen-audio-3.1-tts-next — 音频生成（阿里云百炼 · Audiogen）

把一段自然语言提示词（人物、台词、音色描述、情绪、背景音效）合成为音频文件。模型不是
传统 TTS：没有音色 ID，音色来自提示词描述或参考音频（`@voice1/@voice2/@voice3`），
一次生成可包含人声、音效、环境音，适合播客、有声书、广播剧、游戏配音、多语种（中/英）口播。
主脚本零第三方依赖（纯 Python 标准库），任何 agent 只要有终端和 python3 即可调用。

> 端点为百炼专属格式：`https://<SFM_WORKSPACE_ID>.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer`
> （华北2·北京）。本 skill 非流式：返回完整音频文件，经 `output.audio.url` 下载（24 小时有效）。

## When to Use
- 文本 → 音频场景生成：旁白、口播、播客、有声书、广播剧、影视/游戏配音、短视频配音
- 需要一次生成完整声音场景（人声＋音效＋环境音）、多人对话，或用参考音频指定音色
- Don't use for：只要固定文本转人声、不需要音效 → 用语音合成（Qwen-TTS/CosyVoice，支持系统音色 ID）；
  实时流式/双向语音对话 → qwen-audio-3.1-realtime；语音转文字 → `~/.agents/skills/stepaudio-asr`

## Prerequisites
- 阿里云百炼账号，充值并开通 `qwen-audio-3.1-tts-next`（华北2·北京地域）
- API Key 和业务空间 ID 填入本 skill 目录的 `.env`（推荐）：
  ```
  DASHSCOPE_API_KEY=sk-你的key
  SFM_WORKSPACE_ID=你的业务空间ID
  ```
  脚本读取优先级：环境变量（同名）→ 本目录 `.env`
- ffmpeg：仅提示词 >3000 字符且使用 `--split` 分块拼接时需要

## How to Run
脚本：`~/.agents/skills/qwen-audio-tts/scripts/tts.py`
```bash
SKILL=~/.agents/skills/qwen-audio-tts
python3 $SKILL/scripts/tts.py "一位女性清晰地说：“你好，欢迎使用。”" --out hello.wav
```

## Quick Reference
```bash
python3 $SKILL/scripts/tts.py "文本" --out a.wav                       # 默认 wav/48k/双声道
python3 $SKILL/scripts/tts.py "@voice1 说：“……。”" -r v1.wav -r v2.wav -o d.mp3  # 参考音频定音色
python3 $SKILL/scripts/tts.py --file 剧本.txt --split --out 剧本.wav   # >3000 字分块+拼接
python3 $SKILL/scripts/tts.py "文本" --rate 1.2 --volume 80 --out a.wav
python3 $SKILL/scripts/tts.py "文本" --seed 7 --out a.wav              # 固定种子复现
python3 $SKILL/scripts/tts.py "文本" --dry-run                         # 只打印请求体，不调用
python3 $SKILL/scripts/tts.py "文本" --format mp3 --cbr --bit-rate 192 --out a.mp3
```

## 常用参数
| 脚本参数 | API 字段 | 说明 |
| --- | --- | --- |
| 提示词（位置参数） | `input.text_prompt` | 自然语言描述，≤3000 字符；台词用引号，`@voiceN` 引用参考音频 |
| `-r/--reference` | `input.references[]` | 最多 3 条：本地文件自动转 Base64，或 http(s) URL；各 ≤30s、≤10MB、WAV/MP3/OGG Opus |
| `--format` | `input.format` | wav(默认)/mp3/pcm；**不支持 opus/flac** |
| `--sample-rate` | `input.sample_rate` | 8000/16000/24000/44100/48000(默认) |
| `--channels` | `input.channels` | 1 单声道 / 2 双声道(默认) |
| `--volume` | `input.volume` | 0~100 整数（服务端默认 50） |
| `--rate` | `input.rate` | 语速 0.5~2.0，不改计费时长 |
| `--seed` | `input.seed` | 随机种子（默认 42）；固定可复现 |
| `--cbr/--bit-rate` | `enable_cbr/bit_rate` | 仅 MP3；CBR kbps 8~320（受采样率约束） |
| `--quality` | `quality` | 仅 MP3 VBR；0~9，0 最高 |
| `--aigc-tag` | `enable_aigc_tag` | 音频加 AIGC 水印 |
| `--split` | — | >3000 字符按句分块生成并拼接（ffmpeg 流拷贝） |
| `--base-url` | — | 默认按 `.env` 的 `SFM_WORKSPACE_ID` 拼端点；环境变量 `QWEN_AUDIO_BASE_URL` 可覆盖 |

## Procedure
1. 确认 `.env` 已有 `DASHSCOPE_API_KEY` 和 `SFM_WORKSPACE_ID`（缺失时脚本报错并给出路径）。
2. 按场景写好提示词（人物＋音色＋台词＋情绪＋背景音效，写法见 `references/voices.md`）。
3. 提示词 ≤3000 字符直接生成；超长加 `--split`。
   完成标准：退出码 0，输出音频文件存在且 >0 字节，stdout 打印 `已生成: <文件> (… KB, 时长 …s)`。
4. 交付：把音频路径给用户；长音频建议先播放/抽查一小段。

## Pitfalls
- **没有音色 ID，也没有 `voice` 字段**：音色只能 (a) 在提示词里描述（"成年男性，嗓音低沉"），
  或 (b) 传参考音频（`-r`）并在提示词用 `@voice1/2/3` 按顺序引用；传 voice 字段会 400。
- 参考音频：URL 必须公网可达；`audio_url` 与 Base64 二选一；最多 3 条、各 ≤30s/≤10MB；
  支持 WAV/MP3/OGG Opus，**不支持裸 PCM**。
- `text_prompt` 上限 3000 字符；单次生成时长：播客 ≤240s（4 分钟）、其他场景 ≤120s；超了加 `--split`。
- 输出格式只有 wav/mp3/pcm；MP3 CBR 码率区间受采样率约束（48k 采样下 32~320 kbps）。
- 限流 3 RPS（华北2）：并发/循环调用会 429，需退避；多分块时脚本已顺序合成。
- 401 InvalidApiKey → Key 无效；403 AccessDenied → 未开通模型；404 "Model not exist." → 模型/地域/账号范围。
- `--split` 拼接为帧级流拷贝，句子边界可能有极短间隙；追求无缝就把分块写在同一请求的提示词内。
- 下载 URL（`output.audio.url`）有效期仅 24 小时；脚本已自动下载到本地，无需手动保存。
- 计费：按输入/输出 Token 计费，调语速不改变计费时长；支持语种为中文、英文。

## Verification
- 成功：stdout 打印 `已生成: <文件> (… KB, 时长 …s)`，退出码 0。
- 检查：`ffprobe <文件>` 时长与格式符合预期；`--dry-run` 可复核请求体再实调。
- 失败：stderr 显示 `错误: HTTP <状态码>: <服务端消息> + 排查提示`，按提示检查 `.env` / 参数。
