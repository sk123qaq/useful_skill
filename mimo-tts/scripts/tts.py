#!/usr/bin/env python3
"""MiMo-V2.5-TTS 语音合成（小米 MiMo API 开放平台）

三款模型：
  mimo-v2.5-tts             预置音色（默认）；支持唱歌标签
  mimo-v2.5-tts-voicedesign 用一段文字描述设计音色（user 消息 = 音色描述）
  mimo-v2.5-tts-voiceclone  用音频样本复刻音色（voice = data:audio/...;base64,...）

关键约束（官方文档）：
  - 要合成的**目标文本必须放在 role=assistant 的消息**里，不能放 user
  - user 消息是**风格指令**（自然语言），不出现在语音里
  - 上下文 8K / 最大输出 8K tokens → 长文按句切块，本脚本自动拼接
  - 音频从 choices[0].message.audio.data 取（base64）

用法：
  python3 tts.py "要合成的话" -o out.wav
  python3 tts.py -f article.txt -o out.mp3 --voice 苏打 --style "语速稍快，像播客主播"
  python3 tts.py "文本" --model mimo-v2.5-tts-voicedesign --style "低沉的四十岁男声，语速舒缓"
  python3 tts.py "文本" --voice-sample voice.mp3 -o out.wav   # 音色复刻
  python3 tts.py --list-voices
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave

DEFAULT_BASE = "https://token-plan-cn.xiaomimimo.com/v1"
MODEL_PRESET = "mimo-v2.5-tts"
MODEL_VOICEDESIGN = "mimo-v2.5-tts-voicedesign"
MODEL_VOICECLONE = "mimo-v2.5-tts-voiceclone"

VOICES = [
    ("mimo_default", "默认音色（中国集群=冰糖，其他集群=Mia）"),
    ("冰糖", "中文·女"),
    ("茉莉", "中文·女"),
    ("苏打", "中文·男"),
    ("白桦", "中文·男"),
    ("Mia", "英文·女"),
    ("Chloe", "英文·女"),
    ("Milo", "英文·男"),
    ("Dean", "英文·男"),
]

# 每块目标字符数：8K 上下文下留足余量（中文 1200 字仍很安全）
CHUNK_CHARS = 1200


def load_key(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("MIMO_API_KEY"):
        return os.environ["MIMO_API_KEY"].strip()
    for p in ("~/.config/mimo/api_key", "~/.config/mimo-tts/api_key"):
        p = os.path.expanduser(p)
        if os.path.exists(p):
            with open(p) as f:
                return f.read().strip()
    sys.exit("缺少 API Key：请设置 MIMO_API_KEY 或写入 ~/.config/mimo/api_key")


def load_base(explicit=None):
    if explicit:
        return explicit.rstrip("/")
    if os.environ.get("MIMO_BASE_URL"):
        return os.environ["MIMO_BASE_URL"].strip().rstrip("/")
    for p in ("~/.config/mimo/base_url", "~/.config/mimo-tts/base_url"):
        p = os.path.expanduser(p)
        if os.path.exists(p):
            with open(p) as f:
                v = f.read().strip()
                if v:
                    return v.rstrip("/")
    return DEFAULT_BASE


def split_text(text, limit=CHUNK_CHARS):
    """按句末标点切块，尽量不切在句中；超长单句再按逗号/硬切兜底。"""
    text = text.strip()
    if len(text) <= limit:
        return [text]
    parts = re.split(r"(?<=[。！？!?；;…\n])", text)
    chunks, cur = [], ""
    for p in parts:
        if len(cur) + len(p) <= limit:
            cur += p
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        while len(p) > limit:
            cut = max(p.rfind("，", 0, limit), p.rfind(",", 0, limit))
            cut = cut + 1 if cut > limit * 0.5 else limit
            chunks.append(p[:cut])
            p = p[cut:]
        cur = p
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c.strip()]


def api_call(base, key, model, chunks_text, style=None, voice=None,
             fmt="wav", stream=False, timeout=600):
    msgs = []
    if style:
        msgs.append({"role": "user", "content": style})
    else:
        msgs.append({"role": "user", "content": ""})
    msgs.append({"role": "assistant", "content": chunks_text})
    audio = {"format": fmt}
    if voice:
        audio["voice"] = voice
    body = {"model": model, "messages": msgs, "audio": audio}
    if stream:
        body["stream"] = True
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"api-key": key, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def call_with_retry(*a, tries=5, **kw):
    for attempt in range(tries):
        try:
            return api_call(*a, **kw)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                wait = 5 * (2 ** attempt)
                print(f"    HTTP {e.code}，{wait}s 后重试 · {detail[:160]}", flush=True)
                time.sleep(wait)
                continue
            raise SystemExit(f"HTTP {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < tries - 1:
                print(f"    网络错误 {e}，重试…", flush=True)
                time.sleep(5 * (2 ** attempt))
                continue
            raise


def decode_audio(data):
    msg = data["choices"][0]["message"]
    audio = msg.get("audio") or {}
    b64 = audio.get("data")
    if not b64:
        raise SystemExit(f"响应里没有音频：{json.dumps(data)[:400]}")
    return base64.b64decode(b64), data.get("usage") or {}


def concat_wavs(paths, out):
    """把同参数的 wav 首尾相接（stdlib wave）。

    注意：只能比较 (声道数, 采样位宽, 采样率) —— nframes 每块必然不同，把它算进比较会误判。
    """
    with wave.open(paths[0], "rb") as w0:
        params = w0.getparams()
    key = params[:3]
    with wave.open(out, "wb") as wout:
        wout.setparams(params)
        for p in paths:
            with wave.open(p, "rb") as w:
                if w.getparams()[:3] != key:
                    sys.exit(f"分块音频参数不一致，无法拼接：{p} "
                             f"({w.getparams()[:3]} vs {key})")
                wout.writeframes(w.readframes(w.getnframes()))


def measure_duration(path, fmt):
    """真实时长：wav 用 wave 帧数；其他容器用 ffmpeg 解码计数（mp3 无 Xing 头时
    ffprobe 按平均码率估算会偏短，不能信）。"""
    if fmt == "wav":
        try:
            with wave.open(path, "rb") as w:
                return w.getnframes() / w.getframerate()
        except Exception:
            pass
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ar", "24000",
                              "-ac", "1", "-f", "s16le", "-"],
                             capture_output=True).stdout
        if raw:
            return len(raw) / (24000 * 2)
    except Exception:
        pass
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="要合成的文本（或用 -f 读文件）")
    ap.add_argument("-f", "--file", help="从文件读取文本")
    ap.add_argument("-o", "--out", default="tts_out.wav")
    ap.add_argument("--model", default=MODEL_PRESET,
                    choices=[MODEL_PRESET, MODEL_VOICEDESIGN, MODEL_VOICECLONE])
    ap.add_argument("--voice", help="预置音色 ID（默认 mimo_default）")
    ap.add_argument("--voice-sample", help="音色复刻用的音频样本（mp3/wav）")
    ap.add_argument("--style", help="自然语言风格指令（放进 user 消息，不出现在语音里）")
    ap.add_argument("--format", default=None, help="输出容器：wav/mp3（默认按 -o 后缀）")
    ap.add_argument("--chunk", type=int, default=CHUNK_CHARS)
    ap.add_argument("--api-key")
    ap.add_argument("--base-url")
    ap.add_argument("--list-voices", action="store_true")
    args = ap.parse_args()

    if args.list_voices:
        for vid, desc in VOICES:
            print(f"{vid:14s} {desc}")
        return

    text = open(args.file).read() if args.file else (args.text or "")
    text = text.strip()
    if not text and args.model != MODEL_VOICEDESIGN:
        sys.exit("没有文本可合成")

    key, base = load_key(args.api_key), load_base(args.base_url)
    voice = args.voice
    if args.voice_sample:
        with open(args.voice_sample, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        mime = "audio/mpeg" if args.voice_sample.lower().endswith((".mp3",)) else "audio/wav"
        if len(b64) > 10_000_000:
            sys.exit("音色样本 base64 超过 10 MB，请压缩样本")
        voice = f"data:{mime};base64,{b64}"
        if args.model == MODEL_PRESET:
            args.model = MODEL_VOICECLONE
    if args.model == MODEL_PRESET and not voice:
        voice = "mimo_default"
    if args.model == MODEL_VOICEDESIGN:
        voice = None  # 该模型不支持 voice 字段

    chunks = split_text(text, args.chunk)
    print(f"模型: {args.model} · base: {base} · 音色: {voice if args.model != MODEL_VOICECLONE else '(sample)'}"
          f" · {len(text)} 字 → {len(chunks)} 块")

    out = os.path.abspath(args.out)
    fmt = (args.format or os.path.splitext(out)[1].lstrip(".") or "wav").lower()
    if fmt not in ("wav", "mp3"):
        fmt = "wav"

    tmpdir = tempfile.mkdtemp(prefix="mimo_tts_")
    parts, total_usage = [], {}
    for i, c in enumerate(chunks):
        print(f"[{i+1}/{len(chunks)}] {len(c)} 字 …", flush=True)
        t0 = time.time()
        # 官方接口原生支持 format=mp3，直接要目标格式，省掉一次转码
        data = call_with_retry(base, key, args.model, c, style=args.style,
                               voice=voice, fmt=fmt)
        raw, usage = decode_audio(data)
        p = os.path.join(tmpdir, f"part_{i:02d}.{fmt}")
        with open(p, "wb") as f:
            f.write(raw)
        parts.append(p)
        for k, v in usage.items():
            if isinstance(v, (int, float)):
                total_usage[k] = total_usage.get(k, 0) + v
        print(f"    ok {time.time()-t0:.1f}s · {len(raw)/1024:.0f} KB")

    # 先量各块真实时长（单块时下一步会把它 move 走，之后再量就量不到了）
    sum_parts = sum(measure_duration(p, fmt) for p in parts)

    if len(parts) == 1:
        os.replace(parts[0], out)
    elif fmt == "wav":
        concat_wavs(parts, out)
    else:
        # mp3 逐帧编码，按字节续接即可（不写 ID3 头，播放器按码率估算时长）
        with open(out, "wb") as o:
            for p in parts:
                with open(p, "rb") as f:
                    o.write(f.read())

    # 时长与规格校验：成品时长应等于逐块真实时长之和（拼接是否丢帧的判据）
    dur = measure_duration(out, fmt)
    expect = len(text) / 4.4          # 中文口播实测约 4.4 汉字/秒（英文另计）
    print(f"\nSAVED: {out}\n时长: {dur:.1f}s（逐块合计 {sum_parts:.1f}s）· {os.path.getsize(out)/1024:.0f} KB"
          f"\nusage: {json.dumps(total_usage, ensure_ascii=False)}")
    if abs(dur - sum_parts) > 2:
        print(f"⚠️ 拼接后时长与逐块合计差 {dur - sum_parts:.1f}s，检查是否有块丢失")
    if re.search(r"[\u4e00-\u9fff]", text) and abs(dur - expect) > 0.35 * expect:
        print(f"⚠️ 时长与「字数/4.4」估算({expect:.0f}s)相差较大，确认文本是否被截断")



if __name__ == "__main__":
    main()
