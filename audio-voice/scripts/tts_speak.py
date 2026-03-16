#!/usr/bin/env python3
"""
Qwen3 TTS - 本地文字转语音
使用 mlx_audio 库进行本地语音合成
"""

import os
import sys
import argparse
import subprocess
import shutil


# 默认模型
DEFAULT_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
REQUIREMENTS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "requirements.txt")
)

# 支持的语音
VOICES = {
    # 中文语音
    'Vivian': '女声，温柔',
    'Serena': '女声，成熟',
    'Uncle_Fu': '男声，稳重',
    'Dylan': '男声，北京方言',
    'Eric': '男声，四川方言',
    # 英文语音
    'Ryan': '男声',
    'Aiden': '男声',
}


def show_voices():
    """显示支持的语音"""
    print("\n=== 支持的语音 ===")
    for voice_id, desc in VOICES.items():
        print(f"  {voice_id}: {desc}")
    print("================\n")


def ensure_tts_dependencies():
    """延迟导入依赖，让 --help / --list-voices 在未安装依赖时也可用。"""
    try:
        import numpy as np
        from scipy.io import wavfile
        from mlx_audio.tts.utils import load_model
    except ImportError:
        print("错误: 请先安装 mlx_audio 和依赖")
        print(f"运行: python3 -m pip install -r {REQUIREMENTS_PATH}")
        print("或运行: pip install mlx_audio sounddevice scipy numpy")
        sys.exit(1)
    return np, wavfile, load_model


def text_to_speech(text, voice='Vivian', output_file='output.wav',
                   ref_audio=None, model_name=None, play=False):
    """将文字转换为语音"""

    if not text:
        print("错误: 请输入要转换的文字")
        sys.exit(1)

    if ref_audio and not os.path.exists(ref_audio):
        print(f"错误: 参考音频不存在: {ref_audio}")
        sys.exit(1)

    if not ref_audio and voice not in VOICES:
        print(f"错误: 不支持的语音: {voice}")
        show_voices()
        sys.exit(1)

    np, wavfile, load_model = ensure_tts_dependencies()

    # 加载模型
    if model_name is None:
        model_name = DEFAULT_MODEL

    print(f"加载模型: {model_name}")
    model = load_model(model_name)

    print(f"文字转语音...")
    print(f"  文本: {text[:50]}..." if len(text) > 50 else f"  文本: {text}")
    print(f"  语音: {voice}")
    print(f"  输出: {output_file}")

    # 生成参数
    generate_kwargs = {
        'text': text,
        'voice': voice,
        'stream': False,
        'temperature': 0.9,
        'top_k': 50,
        'top_p': 1.0,
        'max_tokens': 4096,
        'verbose': True,
    }
    
    # 如果有参考音频，使用语音克隆
    if ref_audio and os.path.exists(ref_audio):
        print(f"  参考音频: {ref_audio} (语音克隆)")
        generate_kwargs['ref_audio'] = ref_audio

    # 生成
    results = model.generate(**generate_kwargs)

    # 收集音频
    audio_data = None
    for result in results:
        if result.audio is not None:
            if audio_data is None:
                audio_data = result.audio
            else:
                audio_data = np.concatenate([audio_data, result.audio])
    
    if audio_data is None:
        print("错误: 生成失败，未获取到音频数据")
        sys.exit(1)

    # 确保音频数据格式正确
    if len(audio_data.shape) > 1:
        audio_data = audio_data.squeeze()

    # 归一化到 int16
    audio_int16 = np.clip(audio_data * 32767, -32768, 32767).astype('int16')

    wavfile.write(output_file, model.sample_rate, audio_int16)

    print(f"\n✓ 音频已生成: {output_file}")
    file_size = os.path.getsize(output_file)
    print(f"  文件大小: {file_size} bytes")
    print(f"  采样率: {model.sample_rate} Hz")

    # 播放
    if play:
        play_audio(output_file)

    return output_file


def play_audio(file_path):
    """播放音频文件"""
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在: {file_path}")
        return False
    
    print(f"播放音频: {file_path}")
    
    commands = []
    if shutil.which('afplay'):
        commands.append(['afplay', file_path])
    if shutil.which('ffplay'):
        commands.append(['ffplay', '-nodisp', '-autoexit', file_path])
    if sys.platform == 'darwin' and shutil.which('open'):
        commands.append(['open', file_path])
    if sys.platform.startswith('linux') and shutil.which('xdg-open'):
        commands.append(['xdg-open', file_path])

    for cmd in commands:
        try:
            subprocess.run(cmd, check=True)
            return True
        except subprocess.CalledProcessError:
            continue

    if os.name == 'nt':
        try:
            os.startfile(file_path)
            return True
        except OSError:
            pass

    print("错误: 未找到可用音频播放器，请手动打开生成的音频文件")
    return False


def main():
    parser = argparse.ArgumentParser(description='Qwen3 本地文字转语音')
    parser.add_argument('-t', '--text', help='要转换的文字')
    parser.add_argument('-v', '--voice', default='Vivian', help='语音类型 (默认: Vivian)')
    parser.add_argument('-o', '--output', default='output.wav', help='输出音频文件 (默认: output.wav)')
    parser.add_argument('-r', '--ref-audio', help='参考音频路径（用于语音克隆）')
    parser.add_argument('-m', '--model', default=DEFAULT_MODEL, help='模型名称')
    parser.add_argument('--play', action='store_true', help='生成后自动播放')
    parser.add_argument('--list-voices', action='store_true', help='显示支持的语音')
    
    args = parser.parse_args()
    
    if args.list_voices:
        show_voices()
        sys.exit(0)
    
    if not args.text:
        print("错误: 请输入要转换的文字 (-t 或 --text)")
        parser.print_help()
        sys.exit(1)
    
    # 生成音频
    text_to_speech(
        text=args.text,
        voice=args.voice,
        output_file=args.output,
        ref_audio=args.ref_audio,
        model_name=args.model,
        play=args.play,
    )


if __name__ == '__main__':
    main()
