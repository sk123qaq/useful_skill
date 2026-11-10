#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""StepAudio 2.5 TTS — StepFun 国际版 Step Plan 文本转语音 CLI（零第三方依赖）。

示例:
    python3 tts.py "你好，世界" --out hello.mp3
    python3 tts.py "（冷笑）你以为……" --instruction "语气极其愤怒" --out x.mp3
    python3 tts.py --file 长文.txt --split --out 长文.mp3
    python3 tts.py "文本" --subtitles --out a.mp3      # 同时输出 a.srt
    python3 tts.py "文本" --dry-run                    # 只看请求体，不调用
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://api.stepfun.ai/step_plan/v1"
MODEL = "stepaudio-2.5-tts"
SKILL_DIR = Path(__file__).resolve().parent.parent
FORMAT_EXT = {"mp3": "mp3", "wav": "wav", "flac": "flac", "opus": "opus", "pcm": "pcm"}
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


def split_text(text, limit=1000):
    """按句末标点分块，尽量保持整句；返回每块长度 <= limit 的列表。"""
    if len(text) <= limit:
        return [text]
    segs = re.split(r"(?<=[。！？!?；;…\n])", text)
    chunks, cur = [], ""
    for seg in segs:
        if not seg:
            continue
        while len(seg) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(seg[:limit])
            seg = seg[limit:]
        if len(cur) + len(seg) <= limit:
            cur += seg
        else:
            if cur:
                chunks.append(cur)
            cur = seg
    if cur:
        chunks.append(cur)
    return chunks


def build_payload(args, text):
    payload = {
        "model": MODEL,
        "input": text,
        "voice": args.voice,
        "response_format": args.format,
        "sample_rate": args.sample_rate,
    }
    if args.instruction:
        payload["instruction"] = args.instruction
    if args.speed is not None:
        payload["speed"] = args.speed
    if args.volume is not None:
        payload["volume"] = args.volume
    if args.tn:
        payload["text_normalization"] = args.tn
    if args.tone:
        payload["pronunciation_map"] = {"tone": list(args.tone)}
    if args.subtitles:
        payload["return_url"] = True
        payload["timestamp"] = True
    return payload


def post_json(url, key, payload, timeout):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def download(url, dest, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "stepaudio-tts/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dest.write_bytes(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        die(f"下载音频失败: {e}")


def ms_to_srt_ts(ms):
    ms = int(ms)
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def subtitles_to_cues(subtitles, offset_ms=0):
    """把服务端 subtitles 数组转成 (start_ms, end_ms, text) 列表，可整体平移。"""
    cues = []
    for sub in subtitles:
        items = sub.get("items") or []
        if not items:
            continue
        start = (items[0].get("start_time") or 0) + offset_ms
        end = (items[-1].get("end_time") or 0) + offset_ms
        text = (sub.get("text") or "").strip()
        if text:
            cues.append((start, end, text))
    return cues


def cues_to_srt(cues):
    blocks = []
    for i, (start, end, text) in enumerate(cues, 1):
        blocks.append(f"{i}\n{ms_to_srt_ts(start)} --> {ms_to_srt_ts(end)}\n{text}\n")
    return "\n".join(blocks)


def chunk_audio_ms(subtitles):
    """用字幕推算该段音频时长（取最大的 end_time，毫秒）。"""
    mx = 0
    for sub in subtitles:
        for it in sub.get("items") or []:
            end = it.get("end_time")
            if end:
                mx = max(mx, end)
    return mx


def concat_audio(paths, out_path, fmt):
    if fmt == "pcm":
        out_path.write_bytes(b"".join(p.read_bytes() for p in paths))
        return
    if not shutil.which("ffmpeg"):
        die("多段音频拼接需要 ffmpeg（安装后重试，或改用 --format pcm）")
    listfile = paths[0].parent / "concat.txt"
    listfile.write_text("".join(f"file '{p.as_posix()}'\n" for p in paths), encoding="utf-8")
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", str(listfile), "-c", "copy", str(out_path)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        die(f"ffmpeg 拼接失败: {r.stderr.strip()[:400]}")


def read_text(args):
    if args.file:
        p = Path(args.file)
        if not p.is_file():
            die(f"文本文件不存在: {p}")
        return p.read_text(encoding="utf-8")
    if args.text is not None and args.text != "-":
        return args.text
    if args.text == "-" or not sys.stdin.isatty():
        return sys.stdin.read()
    die("请提供文本：位置参数 / --file 文件 / 标准输入（-）")


def parse_args(argv):
    ap = argparse.ArgumentParser(
        description="StepAudio 2.5 TTS（StepFun 国际版 Step Plan，POST /audio/speech）")
    ap.add_argument("text", nargs="?", help="要合成的文本（与 --file 二选一；- 表示从 stdin 读）")
    ap.add_argument("-f", "--file", help="从文件读取文本（UTF-8）")
    ap.add_argument("-o", "--out", help="输出音频路径（默认 speech.<格式>）")
    ap.add_argument("--voice", default="elegantgentle-female",
                    help="音色 ID（默认 elegantgentle-female，国际版明列音色见 references/voices.md）")
    ap.add_argument("--instruction", help="全局语境指令（≤200 字，仅 stepaudio-2.5-tts）")
    ap.add_argument("--format", default="mp3", choices=["mp3", "wav", "flac", "opus", "pcm"],
                    help="音频格式（默认 mp3）")
    ap.add_argument("--sample-rate", type=int, default=24000,
                    choices=[8000, 16000, 22050, 24000, 48000], dest="sample_rate")
    ap.add_argument("--speed", type=float, help="语速 0.5~2.0（默认 1.0）")
    ap.add_argument("--volume", type=float, help="音量 0.1~2.0（默认 1.0）")
    ap.add_argument("--tn", choices=["standard", "enhanced"],
                    help="文本归一化（默认 standard；长文播报可 enhanced）")
    ap.add_argument("--tone", action="append", metavar="规则",
                    help='发音替换，如 --tone "阿胶/e1胶"（可重复）')
    ap.add_argument("--split", action="store_true", help="文本 >1000 字符时按句分块合成并拼接")
    ap.add_argument("--subtitles", action="store_true", help="请求词级时间戳并输出 .srt 字幕")
    ap.add_argument("--srt", help="字幕输出路径（默认与音频同名 .srt）")
    ap.add_argument("--base-url", default=os.environ.get("STEPFUN_BASE_URL", DEFAULT_BASE),
                    dest="base_url", help=f"API base（默认 {DEFAULT_BASE}）")
    ap.add_argument("--timeout", type=float, default=120.0, help="单次请求超时秒数（默认 120）")
    ap.add_argument("--dry-run", action="store_true", help="只打印请求体，不调用 API")
    ap.add_argument("--keep-chunks", action="store_true", help="分块时保留中间文件")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    text = read_text(args).strip()
    if not text:
        die("文本为空")
    if len(text) > 1000 and not args.split:
        die(f"文本 {len(text)} 字符，超过单次上限 1000；加 --split 自动按句分块合成并拼接")
    if args.instruction and len(args.instruction) > 200:
        die("--instruction 最长 200 字符")
    if args.speed is not None and not (0.5 <= args.speed <= 2.0):
        die("--speed 范围 0.5~2.0")
    if args.volume is not None and not (0.1 <= args.volume <= 2.0):
        die("--volume 范围 0.1~2.0")

    chunks = split_text(text) if args.split else [text]

    if args.dry_run:
        for i, ch in enumerate(chunks, 1):
            print(f"# chunk {i}/{len(chunks)} ({len(ch)} 字符)")
            print(json.dumps(build_payload(args, ch), ensure_ascii=False, indent=2))
        return 0

    key = load_api_key()
    url = args.base_url.rstrip("/") + "/audio/speech"
    ext = FORMAT_EXT[args.format]
    out_path = Path(args.out) if args.out else Path(f"speech.{ext}")
    if args.out and not out_path.suffix:
        out_path = out_path.with_suffix("." + ext)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    tmpdir = Path(tempfile.mkdtemp(prefix="stepaudio-tts-"))
    try:
        audio_paths, all_cues, offset = [], [], 0
        total = len(chunks)
        for i, ch in enumerate(chunks):
            if total > 1:
                print(f"[{i + 1}/{total}] 合成 {len(ch)} 字符 …", file=sys.stderr)
            status, body = post_json(url, key, build_payload(args, ch), args.timeout)
            if status != 200:
                err = body.decode("utf-8", errors="replace")[:800]
                hint = "；检查 .env 里的 STEPFUN_API_KEY 是否有效且已订阅 Step Plan" if status == 401 else ""
                die(f"HTTP {status}: {err}{hint}")
            apath = tmpdir / f"chunk_{i:03d}.{ext}"
            if args.subtitles:
                try:
                    data = json.loads(body)
                    sub_url = data["data"]["url"]
                    subs = data["data"].get("subtitles") or []
                except (json.JSONDecodeError, KeyError, TypeError) as e:
                    die(f"字幕模式响应解析失败（{e}）；原始响应前 500 字: {body[:500]!r}")
                all_cues.extend(subtitles_to_cues(subs, offset))
                offset += chunk_audio_ms(subs)
                download(sub_url, apath, args.timeout)
            else:
                apath.write_bytes(body)
            audio_paths.append(apath)

        if len(audio_paths) == 1:
            shutil.copyfile(audio_paths[0], out_path)
        else:
            concat_audio(audio_paths, out_path, args.format)

        size_kb = out_path.stat().st_size / 1024
        seg_note = f", {total} 段" if total > 1 else ""
        print(f"已生成: {out_path} ({size_kb:.1f} KB{seg_note})")
        if args.subtitles:
            if not all_cues:
                print("警告: 服务端未返回可用的逐词时间戳", file=sys.stderr)
            srt_path = Path(args.srt) if args.srt else out_path.with_suffix(".srt")
            srt_path.write_text(cues_to_srt(all_cues), encoding="utf-8")
            print(f"字幕: {srt_path} ({len(all_cues)} 条)")
        if args.keep_chunks:
            print(f"分块文件保留在: {tmpdir}")
        return 0
    finally:
        if not args.keep_chunks:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
