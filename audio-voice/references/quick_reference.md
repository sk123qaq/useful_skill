# 快速参考

## 安装依赖

```bash
cd /path/to/audio-voice
python3 -m pip install -r requirements.txt
```

## 常用命令

### 文字转语音 (TTS)

```bash
cd /path/to/audio-voice

# 基本用法
python3 scripts/tts_speak.py -t "你好世界" -v Vivian -o hello.wav

# 生成后自动播放
python3 scripts/tts_speak.py -t "你好世界" -v Vivian -o hello.wav --play

# 使用其他语音
python3 scripts/tts_speak.py -t "你好世界" -v Serena -o hello.wav
python3 scripts/tts_speak.py -t "你好世界" -v Uncle_Fu -o hello.wav
python3 scripts/tts_speak.py -t "你好世界" -v Dylan -o hello.wav  # 北京方言
python3 scripts/tts_speak.py -t "你好世界" -v Eric -o hello.wav    # 四川方言

# 英文语音
python3 scripts/tts_speak.py -t "Hello World" -v Ryan -o hello.wav
python3 scripts/tts_speak.py -t "Hello World" -v Aiden -o hello.wav

# 语音克隆（使用参考音频）
python3 scripts/tts_speak.py -t "这是克隆的声音" -r reference.wav -o cloned.wav

# 查看支持的语音
python3 scripts/tts_speak.py --list-voices
```

### 语音转文字 (ASR)

```bash
cd /path/to/audio-voice

# 基本用法
python3 scripts/asr_transcribe.py -i recording.mp3 -o transcript.txt

# 指定输出格式
python3 scripts/asr_transcribe.py -i audio.wav -o result -f json
```

### 播放音频

```bash
# 使用 macOS 自带播放器
afplay output.wav

# 或使用默认应用打开
open output.wav
```

## 语音选择

### 中文语音

| 语音 | 说明 |
|------|------|
| Vivian | 女声，温柔 |
| Serena | 女声，成熟 |
| Uncle_Fu | 男声，稳重 |
| Dylan | 男声，北京方言 |
| Eric | 男声，四川方言 |

### 英文语音

| 语音 | 说明 |
|------|------|
| Ryan | 男声 |
| Aiden | 男声 |

## 模型信息

- **TTS 模型**: `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit`
- **ASR 模型**: `mlx-community/Qwen3-ASR-1.7B-8bit`

首次运行会自动从 HuggingFace 下载模型。

## 备注

- 主要适用于 `macOS + Apple Silicon`
- 若未开启 `--play` 或自动播放失败，可手动打开生成的 `.wav` 文件
