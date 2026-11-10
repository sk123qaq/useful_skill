#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""StepAudio 2.5 ASR — StepFun 国际版 Step Plan 语音识别（HTTP+SSE）CLI，零第三方依赖。

示例:
    python3 asr.py 录音.m4a
    python3 asr.py a.mp3 -o a.txt --json a.json --timestamps
    python3 asr.py a.pcm --rate 16000 --bits 16 --channel 1
    python3 asr.py a.flac --dry-run
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://api.stepfun.ai/step_plan/v1"
MODEL = "stepaudio-2.5-asr"
SKILL_DIR = Path(__file__).resolve().parent.parent
DIRECT_TYPES = {"mp3", "ogg", "wav", "m4a"}
KEY_NAMES = ("STEPFUN_API_KEY", "STEP_API_KEY")


def die(msg, code=1):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


def load_api_key():
    for name in KEY_NAMES:
        v = os.environ.get(name, "").strip()
        if v:
            return v
    env_file = SKILL_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() in KEY_NAMES:
                v = v.strip().strip('"').strip("'")
                if v:
                    return v
    die(f"未找到 API Key：请把 STEPFUN_API_KEY=sk-... 填进 {env_file}（或设置同名环境变量）")


def prepare_audio(path, args):
    """探测/转换输入音频。返回 (音频字节, format 字典, 待清理的临时目录列表)。"""
    ext = path.suffix.lower().lstrip(".")
    tmpdirs = []
    if ext in DIRECT_TYPES:
        return path.read_bytes(), {"type": ext}, tmpdirs
    if ext == "pcm":
        if args.rate is None or args.bits is None or args.channel is None:
            die("pcm 裸流必须用 --rate/--bits/--channel 指明原始采样参数，例如 16000 16 1")
        fmt = {"type": "pcm", "codec": "pcm_s16le",
               "rate": args.rate, "bits": args.bits, "channel": args.channel}
        return path.read_bytes(), fmt, tmpdirs
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        die(f"输入格式 .{ext} 不受支持且未找到 ffmpeg；请先转成 mp3/wav/ogg/m4a，或对 pcm 用 --rate/--bits/--channel")
    d = Path(tempfile.mkdtemp(prefix="stepaudio-asr-"))
    wav = d / "audio.wav"
    r = subprocess.run(
        [ffmpeg, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(path), "-ar", "16000", "-ac", "1", str(wav)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        die(f"ffmpeg 转码失败: {r.stderr.strip()[:400]}")
    tmpdirs.append(d)
    return wav.read_bytes(), {"type": "wav"}, tmpdirs


def iter_sse(resp):
    """把 SSE 响应行流解析为事件字典序列。"""
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                yield json.loads(payload)
            except json.JSONDecodeError:
                continue


def process_events(events, verbose=False, want_ts=False):
    """把事件序列折叠为 (完整文本, 时间戳片段, 错误消息)。"""
    parts, segs, err = [], [], None
    final_text = None
    for ev in events:
        etype = ev.get("type")
        if etype == "transcript.text.delta":
            delta = ev.get("delta", "") or ""
            parts.append(delta)
            if verbose and delta:
                print(delta, end="", file=sys.stderr, flush=True)
            if want_ts and ev.get("start_time") is not None:
                segs.append({"text": delta, "start_ms": ev.get("start_time"), "end_ms": ev.get("end_time")})
        elif etype == "transcript.text.done":
            final_text = ev.get("text")
        elif etype == "error":
            err = ev.get("message") or "unknown error"
    if verbose:
        print(file=sys.stderr)
    text = final_text if final_text is not None else "".join(parts)
    return text, segs, err


def run_asr(url, key, audio_bytes, fmt, args, verbose=False):
    transcription = {"model": MODEL, "enable_itn": not args.no_itn}
    if args.language:
        transcription["language"] = args.language
    if args.hotwords:
        transcription["hotwords"] = [w.strip() for w in args.hotwords.split(",") if w.strip()]
    if args.timestamps:
        transcription["enable_timestamp"] = True
    body = {"audio": {
        "data": base64.b64encode(audio_bytes).decode("ascii"),
        "input": {"transcription": transcription, "format": fmt},
    }}
    if args.dry_run:
        preview = {"audio": {
            "data": f"<BASE64, {len(body['audio']['data'])} 字符>",
            "input": body["audio"]["input"],
        }}
        print(f"# POST {url}")
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return None, [], None

    req = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            return process_events(iter_sse(resp), verbose=verbose, want_ts=args.timestamps)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:800]
        hint = "；检查 .env 里的 STEPFUN_API_KEY 是否有效且已订阅 Step Plan" if e.code == 401 else ""
        die(f"HTTP {e.code}: {err_body}{hint}")


def parse_args(argv):
    ap = argparse.ArgumentParser(
        description="StepAudio 2.5 ASR（StepFun 国际版 Step Plan，POST /audio/asr/sse）")
    ap.add_argument("audio", help="音频文件路径")
    ap.add_argument("-o", "--out", help="把识别文本写入该文件（默认只打印到 stdout）")
    ap.add_argument("--json", dest="json_path", help="保存 JSON 结果（text + segments）")
    ap.add_argument("--language", help="语言提示，如 zh / en；不传由模型判断")
    ap.add_argument("--hotwords", help='热词，逗号分隔，如 "阶跃,StepFun"')
    ap.add_argument("--timestamps", action="store_true", help="返回词句级时间戳（enable_timestamp）")
    ap.add_argument("--no-itn", action="store_true", help="关闭 ITN 文本规范化（默认开启）")
    ap.add_argument("--rate", type=int, help="pcm 采样率（仅 .pcm 输入需要）")
    ap.add_argument("--bits", type=int, help="pcm 位深（仅 .pcm 输入需要）")
    ap.add_argument("--channel", type=int, help="pcm 声道数（仅 .pcm 输入需要）")
    ap.add_argument("--base-url", default=os.environ.get("STEPFUN_BASE_URL", DEFAULT_BASE),
                    dest="base_url", help=f"API base（默认 {DEFAULT_BASE}）")
    ap.add_argument("--timeout", type=float, default=600.0, help="请求超时秒数（默认 600）")
    ap.add_argument("--verbose", action="store_true", help="增量文本实时打印到 stderr")
    ap.add_argument("--dry-run", action="store_true", help="只打印格式探测结果与请求体，不调用 API")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    path = Path(args.audio)
    if not path.is_file():
        die(f"音频文件不存在: {path}")
    audio_bytes, fmt, tmpdirs = prepare_audio(path, args)
    url = args.base_url.rstrip("/") + "/audio/asr/sse"
    try:
        if args.dry_run:
            print(f"# 输入: {path} | 探测格式: {json.dumps(fmt, ensure_ascii=False)} | 音频字节数: {len(audio_bytes)}")
            run_asr(url, None, audio_bytes, fmt, args, verbose=False)
            return 0
        key = load_api_key()
        text, segs, err = run_asr(url, key, audio_bytes, fmt, args, verbose=args.verbose)
        if err:
            die(f"服务端识别失败: {err}")
        text = text or ""
        print(text)
        if not text.strip():
            print("（未识别到文本）", file=sys.stderr)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8")
            print(f"已写入: {out}", file=sys.stderr)
        if args.json_path:
            payload = {"text": text}
            if args.timestamps:
                payload["segments"] = segs
            jp = Path(args.json_path)
            jp.parent.mkdir(parents=True, exist_ok=True)
            jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"已写入: {jp}", file=sys.stderr)
        return 0
    finally:
        for d in tmpdirs:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
