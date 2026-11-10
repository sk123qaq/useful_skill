#!/usr/bin/env python3
"""MiMo-V2.5-ASR 长音频转写（小米 MiMo API 开放平台）

约束（官方文档，2026-07）：
  - 仅支持 mp3 / wav，且以 Base64 data URL 传入，Base64 串上限 10 MB（≈ 7.5 MB 原始音频）
  - 上下文 8K tokens，最大输出 2K tokens，RPM 100，TPM 10K
  => 长音频必须切片（本脚本按静音点自适应切分 + 逐块调用 + 拼接）

查 Key 顺序：
  1) 环境变量 MIMO_API_KEY
  2) 文件 ~/.config/mimo-asr/api_key
Base URL：
  1) 环境变量 MIMO_BASE_URL
  2) 文件 ~/.config/mimo-asr/base_url
  3) 默认 Token Plan：https://token-plan-cn.xiaomimimo.com/v1
     （按量付费改用 --base-url https://api.xiaomimimo.com/v1）

用法：
  python3 asr.py audio.mp3                          # 转写 → audio.txt + audio.json
  python3 asr.py audio.mp3 --lang en --chunk 180
  python3 asr.py audio.mp3 -o out.txt --keep-chunks
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://token-plan-cn.xiaomimimo.com/v1"
MODEL = "mimo-v2.5-asr"
B64_LIMIT = 9_500_000          # 官方上限 10 MB，留余量
CTX_LIMIT = 8000               # 上下文 tokens
TPM = 10_000                   # tokens / 分钟
AUDIO_TOKENS_PER_SEC = 6.25    # 实测换算（官方示例：4s → 25 audio tokens）
MAX_OUTPUT_TOKENS = 2048


def load_key(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("MIMO_API_KEY"):
        return os.environ["MIMO_API_KEY"].strip()
    for p in ("~/.config/mimo/api_key", "~/.config/mimo-asr/api_key"):
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
    for p in ("~/.config/mimo/base_url", "~/.config/mimo-asr/base_url"):
        p = os.path.expanduser(p)
        if os.path.exists(p):
            with open(p) as f:
                v = f.read().strip()
                if v:
                    return v.rstrip("/")
    return DEFAULT_BASE



def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"命令失败 {' '.join(cmd[:2])}...\n{r.stderr[-800:]}")
    return r.stdout


def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", path])
    return float(out.strip())


def to_mono_mp3(src, dst, kbps=32):
    """统一转成 16k 单声道 32kbps mp3：语音足够、体积小（≈4KB/s）。"""
    run(["ffmpeg", "-y", "-v", "error", "-i", src,
         "-ac", "1", "-ar", "16000", "-b:a", f"{kbps}k", dst])
    return dst


def find_silences(path, noise="-32dB", min_dur=0.45):
    """ffmpeg silencedetect → [(start, end), ...]"""
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-af",
                        f"silencedetect=noise={noise}:d={min_dur}", "-f", "null", "-"],
                       capture_output=True, text=True)
    sil, start = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start:\s*([0-9.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(r"silence_end:\s*([0-9.]+)", line)
        if m and start is not None:
            sil.append((start, float(m.group(1))))
            start = None
    return sil


def pick_cuts(total, target, silences, tol=75.0):
    """在离 target 倍数最近的静音中点切分（±tol 秒内），否则原地切。"""
    mids = [ (a + b) / 2 for a, b in silences ]
    cuts, n = [], 1
    while n * target < total - 30:
        t = n * target
        cand = [m for m in mids if abs(m - t) <= tol]
        cuts.append(min(cand, key=lambda m: abs(m - t)) if cand else t)
        n += 1
    return cuts


def split_audio(path, cuts, workdir):
    """按 cuts 切块，返回 [(label, path, start, dur), ...]"""
    total = duration(path)
    bounds = [0.0] + cuts + [total]
    chunks = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        out = os.path.join(workdir, f"chunk_{i:02d}.mp3")
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-i", path,
             "-t", f"{b - a:.3f}", "-ac", "1", "-ar", "16000", "-b:a", "32k", out])
        chunks.append((i, out, a, b - a))
    return chunks


def api_call(base, key, audio_path, lang="auto", stream=False, timeout=900):
    with open(audio_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    if len(b64) > B64_LIMIT:
        raise ValueError(f"base64 过大 {len(b64)/1e6:.1f}MB > {B64_LIMIT/1e6:.1f}MB，需更小切片")
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "input_audio",
             "input_audio": {"data": f"data:audio/mpeg;base64,{b64}"}}]}],
        "asr_options": {"language": lang},
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"api-key": key, "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def call_with_retry(base, key, path, lang, tries=5):
    for attempt in range(tries):
        try:
            return api_call(base, key, path, lang)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
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


class Pacer:
    """按 TPM 10K 限速：滚动 60s 窗口内 prompt+completion tokens 之和不超过 TPM。"""

    def __init__(self, tpm=TPM):
        self.tpm = tpm
        self.events = []

    def wait(self, est_tokens):
        while True:
            now = time.time()
            self.events = [(t, n) for t, n in self.events if now - t < 60]
            used = sum(n for _, n in self.events)
            if used + est_tokens <= self.tpm or not self.events:
                return
            sleep_for = 60 - (now - min(t for t, _ in self.events)) + 1
            print(f"    限速：窗口已用 {used} tokens，等 {sleep_for:.0f}s", flush=True)
            time.sleep(min(sleep_for, 65))

    def record(self, tokens):
        self.events.append((time.time(), tokens))


def transcribe_chunk(base, key, path, lang, pacer, depth=0, min_density=None, max_density=None):
    """单块转写；三种坏结果自动对半重切：
       - finish_reason=length（输出触顶 2K）
       - 字符密度过低（MiMo 在 >300s 切片上会静默丢内容；正常英文语音 12–16 字符/秒）
       - 字符密度过高（复读循环：同一段话被反复改写输出，实测 42.5 字符/秒）
       择优劣按「密度离正常区间更近」，不是取更长的那份 —— 复读版本总是更长。"""
    dur = duration(path)
    est = int(dur * AUDIO_TOKENS_PER_SEC) + 1200
    pacer.wait(min(est, CTX_LIMIT))
    data = call_with_retry(base, key, path, lang)
    usage = data.get("usage", {}) or {}
    pacer.record(int(usage.get("total_tokens", 0)))
    ch = data["choices"][0]
    text = (ch["message"].get("content") or "").strip()
    density = len(text) / max(dur, 1)
    truncated = ch.get("finish_reason") == "length"
    sparse = min_density is not None and dur > 100 and density < min_density
    looping = max_density is not None and dur > 100 and density > max_density
    if (truncated or sparse or looping) and depth < 3:
        why = ("输出触顶" if truncated else
               f"密度过低 {density:.1f}/s" if sparse else f"密度过高(疑似复读) {density:.1f}/s")
        print(f"    {why}（{len(text)} 字符 / {dur:.0f}s），对半再切…", flush=True)
        d = os.path.dirname(path)
        half = dur / 2
        parts = []
        for j, ss in enumerate([0, half]):
            sub = os.path.join(d, f"sub_{os.path.splitext(os.path.basename(path))[0]}_{j}.mp3")
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.3f}", "-i", path,
                 "-t", f"{half:.3f}", "-ac", "1", "-ar", "16000", "-b:a", "32k", sub])
            parts.append(transcribe_chunk(base, key, sub, lang, pacer, depth + 1,
                                          min_density, max_density))
        joined = " ".join(parts)
        jd = len(joined) / max(dur, 1)

        def _dist(dens):
            if min_density is not None and dens < min_density:
                return min_density - dens
            if max_density is not None and dens > max_density:
                return dens - max_density
            return 0.0

        # 取密度更接近正常区间的那份；同距取更长（避免把「音乐/静音段落」重跑成空）
        if _dist(jd) < _dist(density) or (_dist(jd) == _dist(density) and len(joined) > len(text)):
            return joined
    return text


def fmt_ts(sec):
    return f"{int(sec)//3600:02d}:{(int(sec)%3600)//60:02d}:{int(sec)%60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("-o", "--out", help="输出文本路径（默认 <audio>.txt）")
    ap.add_argument("--lang", default="auto", choices=["auto", "zh", "en"])
    ap.add_argument("--chunk", type=int, default=180, help="目标切片秒数（默认 180；不要 >300）")
    ap.add_argument("--min-density", type=float, default=None,
                    help="字符/秒 下限，低于则自动对半重切（默认 en=8，zh=3，auto=5）")
    ap.add_argument("--max-density", type=float, default=None,
                    help="字符/秒 上限，高于则判复读循环并对半重切（默认 en=22，zh=8，auto=15）")
    ap.add_argument("--api-key")
    ap.add_argument("--base-url")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--keep-chunks", action="store_true")
    args = ap.parse_args()

    if args.min_density is None:
        args.min_density = {"en": 8.0, "zh": 3.0, "auto": 5.0}[args.lang]
    if args.max_density is None:
        args.max_density = {"en": 22.0, "zh": 8.0, "auto": 15.0}[args.lang]

    key = load_key(args.api_key)
    base = load_base(args.base_url)
    src = os.path.abspath(args.audio)
    if not os.path.exists(src):
        sys.exit(f"文件不存在：{src}")

    stem = os.path.splitext(src)[0]
    out_txt = args.out or stem + ".txt"
    out_json = stem + ".asr.json"
    work = args.workdir or (stem + "_chunks")
    os.makedirs(work, exist_ok=True)

    print(f"模型: {MODEL} · base: {base} · 语言: {args.lang}")
    flat = os.path.join(work, "flat.mp3")
    print("转单声道 32kbps…", flush=True)
    to_mono_mp3(src, flat)
    total = duration(flat)
    print(f"总时长: {fmt_ts(total)} ({total:.0f}s)")

    cuts = pick_cuts(total, args.chunk, find_silences(flat))
    bounds = [0.0] + cuts + [total]
    print(f"切片 {len(bounds)-1} 段（静音点对齐）")

    pacer = Pacer()
    parts, jchunks, bad = [], [], []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        cp = os.path.join(work, f"chunk_{i:02d}.mp3")
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{a:.3f}", "-i", flat,
             "-t", f"{b-a:.3f}", "-ac", "1", "-ar", "16000", "-b:a", "32k", cp])
        mb = os.path.getsize(cp) / 1e6
        print(f"[{i+1}/{len(bounds)-1}] {fmt_ts(a)}–{fmt_ts(b)} ({mb:.1f}MB) …", flush=True)
        t0 = time.time()
        text = transcribe_chunk(base, key, cp, args.lang, pacer,
                                min_density=args.min_density, max_density=args.max_density)
        dens = len(text) / max(b - a, 1)
        print(f"    ok {time.time()-t0:.0f}s · {len(text)} 字符 ({dens:.1f}/s)")
        if dens < args.min_density or dens > args.max_density:
            bad.append(f"[{i+1}/{len(bounds)-1}] {fmt_ts(a)} {dens:.1f}/s")
        parts.append((a, text))
        jchunks.append({"index": i, "start": a, "end": b, "chars": len(text)})

    if bad:
        print("⚠️ 以下块密度仍落在正常区间外，必须单独重跑（建议拆到 ≤100s）："
              + "；".join(bad), flush=True)
    with open(out_txt, "w") as f:
        for a, text in parts:
            f.write(f"## [{fmt_ts(a)}]\n{text}\n\n")
    with open(out_json, "w") as f:
        json.dump({"model": MODEL, "language": args.lang, "duration": total,
                   "chunks": jchunks}, f, ensure_ascii=False, indent=2)
    if not args.keep_chunks:
        for fn in os.listdir(work):
            if fn.startswith(("chunk_", "sub_", "flat")):
                os.remove(os.path.join(work, fn))
        if not os.listdir(work):
            os.rmdir(work)

    print(f"\nTXT : {out_txt}\nJSON: {out_json}")


if __name__ == "__main__":
    main()
