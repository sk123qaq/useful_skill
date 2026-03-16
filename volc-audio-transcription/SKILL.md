---
name: volc-audio-transcription
description: |
  火山引擎录音文件识别 (ByteDance Volcano Engine Audio Transcription).
  Use when user needs to transcribe audio files (.mp3, .wav, .ogg) using ByteDance's ASR service.
  Supports: Chinese (mandarin, Cantonese, Shanghainese, Minnan, Sichuan, Shaanxi), English, Japanese, Korean, and 10+ other languages.
  Features: speaker diarization, punctuation, ITN, language identification, emotion detection, dual-channel, VAD segmentation.
---

# 火山引擎录音文件识别

使用 ByteDance 火山引擎的录音文件识别服务进行音频转写。

## 环境配置

### 1. 安装依赖

```bash
cd /path/to/volc-audio-transcription
python3 -m pip install -r requirements.txt
```

### 2. 设置环境变量

```bash
export VOLC_APP_KEY="你的APP_KEY"
export VOLC_ACCESS_KEY="你的ACCESS_KEY"
```

或在每次运行时传入参数。

说明：
- `scripts/volc_transcriber.py` 支持参数或环境变量两种方式
- `scripts/transcribe_local.py` 也支持读取环境变量，不再强制命令行显式传入

### 3. 音频 URL 要求

**重要**: 火山引擎服务器需要能访问公网 URL，不能使用本地文件路径或 localhost。

#### 本地文件处理流程:

1. 启动本地 HTTP 服务器:
   ```bash
   cd /你的音频目录
   python3 -m http.server 8888
   ```

2. 使用 ngrok 做内网穿透:
   ```bash
   ngrok http 8888
   ```

3. 获取公网 URL 后调用 API

## 使用方法

### 命令行

```bash
cd /path/to/volc-audio-transcription
python3 scripts/volc_transcriber.py \
  --url "https://公网可访问的音频URL" \
  --format mp3 \
  --language zh-CN \
  --poll
```

如果你更习惯显式传参：

```bash
cd /path/to/volc-audio-transcription
python3 scripts/volc_transcriber.py \
  --url "https://公网可访问的音频URL" \
  --app-key "你的APP_KEY" \
  --access-key "你的ACCESS_KEY" \
  --format mp3 \
  --language zh-CN \
  --poll
```

### Python 代码

```python
from scripts.volc_transcriber import VolcAudioTranscriber

client = VolcAudioTranscriber(app_key="APP_KEY", access_key="ACCESS_KEY")

# 提交任务
result = client.submit_task(
    audio_url="https://example.com/audio.mp3",
    format="mp3",
    language="zh-CN"
)

# 轮询等待结果
transcription = client.wait_for_result(result["request_id"])
print(transcription["result"]["text"])
```

### 本地文件一键转写

如果你只有本地音频文件，可以使用附带脚本自动启动 HTTP 服务并通过 `ngrok` 暴露公网 URL：

```bash
cd /path/to/volc-audio-transcription
python3 scripts/transcribe_local.py --file /path/to/audio.mp3 --output result.txt
```

前提：
- 已安装 `ngrok`
- `ngrok` 在 PATH 中可直接调用
- 已配置 `VOLC_APP_KEY` 和 `VOLC_ACCESS_KEY`

## 常用参数

| 场景 | 参数 |
|------|------|
| 中文转写 | `language="zh-CN"` |
| 中英文混合 | `language=None` (默认) |
| 标点符号 | `enable_punc=True` |
| 说话人分离 | `enable_speaker_info=True` |
| 语种识别 | `enable_lid=True` |
| 情绪检测 | `enable_emotion_detection=True` |
| **默认资源ID** | `volc.seedasr.auc` (豆包录音文件识别模型2.0) |

## 错误排查

### 45000006 - Invalid audio URI

- 原因: 火山引擎无法访问音频 URL
- 解决: 确保音频 URL 是公网可访问的，使用 ngrok 做内网穿透

### 45000001 - Invalid argument

- 原因: 请求参数错误
- 解决: 检查 JSON 格式是否正确（需要嵌套在 `audio` 和 `request` 下）

### 超时

- 原因: 轮询次数不足或间隔太短
- 解决: 增加 `max_retries` 或 `interval` 参数

## 完整参数列表

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| audio_url | str | 必填 | 音频链接 (公网可访问) |
| format | str | mp3 | 音频格式: raw/wav/mp3/ogg |
| language | str | None | 语言: zh-CN/en-US/ja-JP 等 |
| enable_punc | bool | False | 启用标点 |
| enable_speaker_info | bool | False | 启用说话人分离 |
| enable_itn | bool | True | 启用文本规范化 |

详细 API 参考见 [api_reference.md](references/api_reference.md)

## 快速自检

```bash
cd /path/to/volc-audio-transcription
python3 scripts/volc_transcriber.py --help
python3 scripts/transcribe_local.py --help
```
