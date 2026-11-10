#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qwen-audio-3.1-tts-next 音频生成 CLI（阿里云百炼 Model Studio，零第三方依赖）。

模型说明：qwen-audio-3.1-tts-next 是 Audiogen 模型，用自然语言提示词（可含台词、
音色描述、音效与场景指令）+ 可选参考音频，一次生成人声/多人对话/播客/音效/环境音。

示例:
    python3 tts.py "一位女性清晰地说：“你好，欢迎使用。”" --out hello.wav
    python3 tts.py "@voice1 说：“今天天气真好。”@voice2 在旁边笑。" -r a.wav -r b.wav -o dialog.mp3
    python3 tts.py --file 剧本.txt --split --out 剧本.wav       # >3000 字符自动分块+拼接
    python3 tts.py "文本" --dry-run                            # 只打印请求体，不调用
"""
import argparse
import base64
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

MODEL = "qwen-audio-3.1-tts-next"
API_PATH = "/api/v1/services/audio/tts/SpeechSynthesizer"
HOST_TMPL = "https://{workspace}.cn-beijing.maas.aliyuncs.com"
SKILL_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SKILL_DIR / ".env"
MAX_PROMPT_CHARS = 3000
MAX_REFERENCES = 3
REF_MAX_SECONDS = 30
REF_MAX_BYTES = 10 * 1024 * 1024
FORMATS = ("wav", "mp3", "pcm")
SAMPLE_RATES = (8000, 16000, 24000, 44100, 48000)
CHANNELS = (1, 2)
REF_MIME = {".wav": "audio/wav", ".mp3": "audio/mp3", ".ogg": "audio/ogg", ".opus": "audio/ogg"}
KEY_NAMES = ("DASHSCOPE_API_KEY",)
WS_NAMES = ("SFM_WORKSPACE_ID",)


def die(msg, code=1):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


def _from_env_file(names):
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() in names:
            v = v.strip().strip('"').strip("'")
            if v:
                return v
    return ""


def lookup(names):
    """环境变量优先，其次本目录 .env；找不到返回空串。"""
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return _from_env_file(names)


def load_setting(names, what):
    v = lookup(names)
    if not v:
        die(f"未找到 {what}：请把 {names[0]}=... 填进 {ENV_FILE}（或设置同名环境变量）")
    return v


def wav_seconds(path):
    """尽力从 WAV 头解析时长；非 WAV 或解析失败返回 None。"""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return None
            rate = block = 0
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    return None
                cid, csz = hdr[:4], struct.unpack("<I", hdr[4:8])[0]
                if cid == b"fmt ":
                    fmt = f.read(csz)
                    _, channels, rate, _, block_align, bits = struct.unpack_from("<HHIIHH", fmt, 0)
                    block = block_align or channels * bits // 8
                elif cid == b"data":
                    return csz / (rate * block) if (rate and block) else None
                else:
                    f.seek(csz + (csz & 1), 1)
    except (OSError, struct.error, NameError):
        return None


def build_reference(raw):
    """--reference 值 → input.references[] 元素：http(s) URL 用 audio_url，本地文件转 Base64。"""
    if raw.startswith("http://") or raw.startswith("https://"):
        return {"audio_url": raw}
    p = Path(raw).expanduser()
    if not p.is_file():
        die(f"参考音频不存在: {p}")
    size = p.stat().st_size
    if size > REF_MAX_BYTES:
        die(f"参考音频 {p.name} 大小 {size / 1024 / 1024:.1f} MB，超过单条上限 10 MB")
    secs = wav_seconds(p)
    if secs is not None and secs > REF_MAX_SECONDS:
        die(f"参考音频 {p.name} 时长 {secs:.1f} 秒，超过单条上限 {REF_MAX_SECONDS} 秒（可先用 ffmpeg 截取）")
    mime = REF_MIME.get(p.suffix.lower())
    if not mime:
        die(f"参考音频格式不受支持: {p.suffix or p.name}（仅 WAV / MP3 / OGG Opus，不支持裸 PCM）")
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return {"audio_data": f"data:{mime};base64,{b64}"}


def build_payload(args, text, references):
    inp = {
        "text_prompt": text,
        "format": args.format,
        "sample_rate": args.sample_rate,
        "channels": args.channels,
    }
    if references:
        inp["references"] = list(references)
    if args.volume is not None:
        inp["volume"] = args.volume
    if args.rate is not None:
        inp["rate"] = args.rate
    if args.seed is not None:
        inp["seed"] = args.seed
    if args.cbr:
        inp["enable_cbr"] = True
        if args.bit_rate is not None:
            inp["bit_rate"] = args.bit_rate
    elif args.quality is not None:
        inp["quality"] = args.quality
    if args.aigc_tag:
        inp["enable_aigc_tag"] = True
    return {"model": MODEL, "input": inp}


def preview_payload(payload):
    """dry-run 用：把 Base64 参考音频截断显示，避免刷屏。"""
    import copy
    data = copy.deepcopy(payload)
    for r in data["input"].get("references") or []:
        if "audio_data" in r:
            r["audio_data"] = f"<data URI base64，共 {len(r['audio_data'])} 字符>"
    return data


def split_text(text, limit=MAX_PROMPT_CHARS):
    """按句末标点分块，每块 <= limit；保持整句优先。"""
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


def resolve_endpoint(args):
    if args.base_url:
        return args.base_url.rstrip("/") + API_PATH
    ws = lookup(WS_NAMES)
    if not ws:
        die(f"未找到 SFM_WORKSPACE_ID（业务空间 ID）：端点形如 https://<该ID>.cn-beijing.maas.aliyuncs.com/"
            f"api/v1/services/audio/tts/SpeechSynthesizer，请填进 {ENV_FILE}（或用 --base-url 指定完整 base）")
    return args.base_url.rstrip("/") + API_PATH if args.base_url else HOST_TMPL.format(workspace=ws) + API_PATH


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
    req = urllib.request.Request(url, headers={"User-Agent": "qwen-audio-tts/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dest.write_bytes(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        die(f"下载音频失败: {e}")


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


def error_hint(status, body_text):
    if "IllegalEndpoint" in body_text or "Workspace endpoint is invalid" in body_text:
        return "；端点无效：检查 .env 里的 SFM_WORKSPACE_ID（业务空间 ID）是否正确，或用 --base-url 指定完整 base"
    if status == 401:
        return "；检查 .env 里的 DASHSCOPE_API_KEY 是否有效"
    if status == 404:
        return '；若 message 为 "Model not exist."，核对模型 ID、地域（华北2·北京）与账号可用范围'
    if status == 403:
        return "；账号可能需要先开通该模型调用权限"
    if status == 429:
        return "；触发限流（华北2 RPS=3），降低频率稍后重试"
    if "DataInspectionFailed" in body_text:
        return "；内容安全校验未通过，调整提示词或参考音频"
    if status == 400:
        return "；检查提示词长度、参考音频（≤3 条/各 ≤30s/≤10MB）、audio_url 与 audio_data 互斥、@voiceN 编号"
    return ""


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
    die("请提供提示词：位置参数 / --file 文件 / 标准输入（-）")


def parse_args(argv):
    epilog = """示例:
  tts.py "一位女性清晰地说：“你好，欢迎使用。”" --out hello.wav
  tts.py "@voice1 说：“今天天气真好。”" -r voice1.wav -o dialog.mp3
  tts.py --file 剧本.txt --split --out 剧本.wav
  tts.py "文本" --dry-run
"""
    ap = argparse.ArgumentParser(
        description="qwen-audio-3.1-tts-next 音频生成（阿里云百炼 Model Studio）",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=epilog)
    ap.add_argument("text", nargs="?", help="自然语言提示词/待合成文本（与 --file 二选一；- 表示从 stdin 读）")
    ap.add_argument("-f", "--file", help="从文件读取提示词（UTF-8）")
    ap.add_argument("-o", "--out", help="输出音频路径（默认 speech.<格式>）")
    ap.add_argument("--format", default="wav", choices=list(FORMATS),
                    help="输出格式：wav(默认)/mp3/pcm（本模型不支持 opus/flac）")
    ap.add_argument("--sample-rate", type=int, default=48000, dest="sample_rate",
                    choices=list(SAMPLE_RATES), help="采样率 Hz（默认 48000）")
    ap.add_argument("--channels", type=int, default=2, choices=list(CHANNELS),
                    help="声道数：1/2（默认 2）")
    ap.add_argument("--volume", type=int, help="音量 0~100（不传用服务端默认 50）")
    ap.add_argument("--rate", type=float, help="语速 0.5~2.0（默认 1.0；不改变计费时长）")
    ap.add_argument("--seed", type=int, help="随机种子（不传用服务端默认 42；固定可复现）")
    ap.add_argument("-r", "--reference", action="append", metavar="A", dest="reference",
                    help='参考音频：本地文件(自动转 Base64)或 http(s) URL，最多 3 条；'
                         '提示词中用 @voice1/@voice2/@voice3 按顺序引用（可重复此参数）')
    ap.add_argument("--cbr", action="store_true", help="MP3 恒定码率（CBR，默认 VBR）")
    ap.add_argument("--bit-rate", type=int, dest="bit_rate", help="MP3 CBR 码率 kbps（仅 --cbr 生效）")
    ap.add_argument("--quality", type=int, help="MP3 VBR 质量 0~9，0 最高（仅非 --cbr 生效）")
    ap.add_argument("--aigc-tag", action="store_true", dest="aigc_tag",
                    help="在生成音频中添加 AIGC 标识水印")
    ap.add_argument("--split", action="store_true", help=f"提示词 >{MAX_PROMPT_CHARS} 字符时按句分块生成并拼接")
    ap.add_argument("--base-url", default=os.environ.get("QWEN_AUDIO_BASE_URL", ""), dest="base_url",
                    help=f"API base，默认 {HOST_TMPL}（可用环境变量 QWEN_AUDIO_BASE_URL 覆盖）")
    ap.add_argument("--timeout", type=float, default=300.0, help="单次请求超时秒数（默认 300）")
    ap.add_argument("--dry-run", action="store_true", help="只打印请求体与端点，不调用 API")
    ap.add_argument("--keep-chunks", action="store_true", help="分块时保留中间文件")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    text = read_text(args).strip()
    if not text:
        die("文本为空")
    if len(text) > MAX_PROMPT_CHARS and not args.split:
        die(f"提示词 {len(text)} 字符，超过单次上限 {MAX_PROMPT_CHARS}；加 --split 自动按句分块生成并拼接")
    if args.cbr and args.format != "mp3":
        die("--cbr/--bit-rate 仅 MP3 生效")
    if args.quality is not None and args.cbr:
        die("--quality 仅 VBR 生效，与 --cbr 互斥")
    if args.quality is not None and not (0 <= args.quality <= 9):
        die("--quality 范围 0~9（0 为最高质量）")
    if args.volume is not None and not (0 <= args.volume <= 100):
        die("--volume 范围 0~100")
    if args.rate is not None and not (0.5 <= args.rate <= 2.0):
        die("--rate 范围 0.5~2.0")

    references = []
    for r in args.reference or []:
        references.append(build_reference(r))
    if len(references) > MAX_REFERENCES:
        die(f"最多 {MAX_REFERENCES} 条参考音频，已传 {len(references)} 条")
    if references and not re.search(r"@voice[123]", text):
        print("警告: 传了参考音频，但提示词中未见 @voice1/@voice2/@voice3 引用（按列表顺序分配）",
              file=sys.stderr)

    chunks = split_text(text) if args.split else [text]
    url = resolve_endpoint(args)

    if args.dry_run:
        print(f"POST {url}")
        for i, ch in enumerate(chunks, 1):
            print(f"# chunk {i}/{len(chunks)} ({len(ch)} 字符)")
            print(json.dumps(preview_payload(build_payload(args, ch, references)),
                             ensure_ascii=False, indent=2))
        return 0

    key = load_setting(KEY_NAMES, "DASHSCOPE_API_KEY")
    ext = args.format
    out_path = Path(args.out) if args.out else Path(f"speech.{ext}")
    if args.out and not out_path.suffix:
        out_path = out_path.with_suffix("." + ext)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    tmpdir = Path(tempfile.mkdtemp(prefix="qwen-audio-tts-"))
    try:
        parts, total_sec = [], 0.0
        total = len(chunks)
        for i, ch in enumerate(chunks):
            if total > 1:
                print(f"[{i + 1}/{total}] 生成 {len(ch)} 字符 …", file=sys.stderr)
            status, body = post_json(url, key, build_payload(args, ch, references), args.timeout)
            if status != 200:
                err = body.decode("utf-8", errors="replace")[:800]
                die(f"HTTP {status}: {err}{error_hint(status, err)}")
            try:
                data = json.loads(body)
                audio = data["output"]["audio"]
                sub_url = audio["url"]
                duration = audio.get("duration") or 0
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                die(f"响应解析失败（{e}）；原始响应前 500 字: {body[:500]!r}")
            apath = tmpdir / f"chunk_{i:03d}.{ext}"
            download(sub_url, apath, args.timeout)
            total_sec += duration
            parts.append(apath)

        if len(parts) == 1:
            shutil.copyfile(parts[0], out_path)
        else:
            concat_audio(parts, out_path, args.format)

        size_kb = out_path.stat().st_size / 1024
        seg_note = f", {total} 段" if total > 1 else ""
        dur_note = f", 时长 {total_sec:g}s" if total_sec else ""
        print(f"已生成: {out_path} ({size_kb:.1f} KB{seg_note}{dur_note})")
        if args.keep_chunks:
            print(f"分块文件保留在: {tmpdir}")
        return 0
    finally:
        if not args.keep_chunks:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
