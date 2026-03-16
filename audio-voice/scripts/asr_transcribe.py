#!/usr/bin/env python3
"""
Qwen3 ASR - 本地语音转文字
使用 mlx_audio 库进行本地语音识别
"""

import os
import sys
import argparse

# 默认模型
DEFAULT_MODEL = "mlx-community/Qwen3-ASR-1.7B-8bit"
REQUIREMENTS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "requirements.txt")
)


def ensure_asr_dependencies():
    """延迟导入依赖，让 --help 在未安装依赖时也可用。"""
    try:
        from mlx_audio.stt.utils import load_model
        from mlx_audio.stt.generate import generate_transcription
    except ImportError:
        print("错误: 请先安装 mlx_audio 和依赖")
        print(f"运行: python3 -m pip install -r {REQUIREMENTS_PATH}")
        print("或运行: pip install mlx_audio sounddevice scipy numpy")
        sys.exit(1)
    return load_model, generate_transcription


def transcribe_audio(input_file, output_file=None, format="txt", model_name=None):
    """转写音频文件"""

    if not os.path.exists(input_file):
        print(f"错误: 文件不存在: {input_file}")
        sys.exit(1)

    load_model, generate_transcription = ensure_asr_dependencies()

    # 加载模型
    if model_name is None:
        model_name = DEFAULT_MODEL

    print(f"加载模型: {model_name}")
    model = load_model(model_name)

    print(f"转写音频: {input_file}")

    # 转写
    result = generate_transcription(
        model=model,
        audio=input_file,
        output_path=output_file,
        format=format,
        verbose=True,
    )
    
    text = result.text if hasattr(result, 'text') else str(result)

    print("\n=== 转写结果 ===")
    print(text)
    print("================\n")

    return text


def main():
    parser = argparse.ArgumentParser(description='Qwen3 本地语音转文字')
    parser.add_argument('-i', '--input', required=True, help='输入音频文件路径')
    parser.add_argument('-o', '--output', help='输出文件路径（不含扩展名）')
    parser.add_argument('-f', '--format', default='txt', choices=['txt', 'json'], help='输出格式 (默认: txt)')
    parser.add_argument('-m', '--model', default=DEFAULT_MODEL, help='模型名称')
    
    args = parser.parse_args()
    
    # 确定输出路径
    output_path = args.output
    if output_path and not output_path.endswith(f'.{args.format}'):
        output_path = f"{output_path}.{args.format}"
    
    transcribe_audio(args.input, output_path, args.format, args.model)


if __name__ == '__main__':
    main()
