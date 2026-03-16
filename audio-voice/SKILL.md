---
name: audio-voice
description: |
  本地语音转文字 (ASR) 和文字转语音 (TTS) 服务。使用 Qwen3 本地模型 (mlx_audio)。
  支持：
  - ASR: 使用 Qwen3-ASR 本地模型将音频文件转写为文字
  - TTS: 使用 Qwen3-TTS 本地模型将文字转换为语音并生成音频文件
  - 播放: 生成音频后自动播放
  当用户需要语音转文字、文字转语音、播放音频时使用此技能。
capabilities:
  - asr
  - stt
  - tts
  - audio-playback
trigger_keywords:
  - 音频
  - 语音
  - 转写
  - 转文字
  - 字幕
  - 朗读
priority_when_matched: high
---

# Audio Voice - 本地语音转文字 & 文字转语音

本技能使用 Qwen3 本地模型（mlx_audio），无需 API 密钥，完全离线工作。

## 适用平台

- 主要面向 `macOS + Apple Silicon` 环境
- 首次运行需要联网从 HuggingFace 下载模型，因此并非“完全离线初始化”；模型下载完成后可离线使用
- 推荐使用系统可用的 `python3`；如果你的环境固定为 `python3.13`，也可以直接替换下文命令

## 仓库内文件

- `scripts/asr_transcribe.py`：语音转文字
- `scripts/tts_speak.py`：文字转语音
- `references/quick_reference.md`：快速命令参考
- `requirements.txt`：Python 依赖

## 快速开始

```bash
cd /path/to/audio-voice
python3 -m pip install -r requirements.txt
```

## 环境配置

### 1. 安装 mlx_audio

```bash
python3 -m pip install -r requirements.txt
```

### 2. 模型自动下载

首次运行时会自动从 HuggingFace 下载模型：
- ASR: `mlx-community/Qwen3-ASR-1.7B-8bit`
- TTS: `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit`

## 支持的语音

### TTS 语音（通过 voice 参数指定）

| 语音ID | 描述 |
|--------|------|
| `Vivian` | 女声，温柔 |
| `Serena` | 女声，成熟 |
| `Uncle_Fu` | 男声，稳重 |
| `Dylan` | 男声，北京方言 |
| `Eric` | 男声，四川方言 |

### 英文语音

| 语音ID | 描述 |
|--------|------|
| `Ryan` | 男声 |
| `Aiden` | 男声 |

**注意**: Qwen3-TTS 支持使用参考音频克隆语音！详见下方高级用法。

## 使用方法

### ASR - 语音转文字

将本地音频文件转换为文字：

```bash
cd /path/to/audio-voice
python3 scripts/asr_transcribe.py --input /path/to/audio.mp3 --output result.txt
```

参数：
- `--input` 或 `-i`: 输入音频文件路径（支持 mp3, wav, ogg, m4a）
- `--output` 或 `-o`: 输出文本文件路径（可选，默认输出到终端）
- `--format`: 输出格式 (txt/json，默认 txt)

### TTS - 文字转语音

将文字转换为语音并生成音频文件：

```bash
cd /path/to/audio-voice
python3 scripts/tts_speak.py --text "你好世界" --voice Vivian --output hello.wav
```

参数：
- `--text` 或 `-t`: 要转换的文字
- `--voice` 或 `-v`: 语音类型（默认 Vivian）
- `--output` 或 `-o`: 输出音频文件路径（默认 output.wav）
- `--ref-audio`: 参考音频路径（用于语音克隆）
- `--play`: 生成后自动播放

### 播放音频

生成音频后自动播放（使用 --play 参数），或手动播放：

```bash
# macOS
afplay output.wav

# macOS 备用方式
open output.wav

# Linux 桌面环境
xdg-open output.wav
```

## 高级用法

### 语音克隆

使用参考音频克隆特定声音：

```bash
cd /path/to/audio-voice
python3 scripts/tts_speak.py \
  --text "这是克隆的声音" \
  --ref-audio /path/to/reference.wav \
  --output cloned.wav \
  --play
```

### 查看支持的语音

```bash
cd /path/to/audio-voice
python3 scripts/tts_speak.py --list-voices
```

## 注意事项

1. **Apple Silicon**: 需要 Mac M系列芯片
2. **首次运行**: 模型较大（~3-4GB），首次运行需要下载
3. **内存**: 建议 16GB+ 内存以获得流畅体验
4. **音频格式**: ASR 支持 mp3, wav, ogg, m4a; TTS 输出为 wav
5. **自动播放**: 脚本会优先尝试系统播放器；若失败，可手动打开生成的音频文件
