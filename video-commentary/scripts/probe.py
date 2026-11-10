#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定位台词：把某句台词钉到 ±1 秒（可再到 ±0.2 秒），或整片分块转写建台词表。

用法:
  # ① 整片分块转写 → 台词表（idx/起/止/文本，可直接喂 timeline.py --dlg-subs）
  #    ASR 给句级时间戳时（qwen 默认给）每行是一句、起止是真实句时间；没时间戳才按块一行
  python3 probe.py --source 片.mp4 --transcribe --chunk-sec 300 -o transcript.tsv -j 4
  #    --transcribe 自带「尾部覆盖检查」：长块 ASR 会在块尾吞句（S3E05 事故：全剧最后
  #    一句 "Yes, Minister!" 被吞成 "Yes."，末句终点少 1.5s → 彩蛋 pe 短 1.5s → 成片把
  #    最后一个词切掉半截）。任一块转写止于块末 >--tail-gap（默认 8s）前，自动用 ≤20s
  #    短窗补测空缺段并合回台词表；--no-tail-fix 可关掉（不推荐）。

  # ② 粗定位：在若干时间点抽短窗做 ASR
  python3 probe.py --source 片.mp4 104.5 180 282.1 --dur 2 -j 4
  python3 probe.py --source 片.mp4 --scan 540:560:4 --dur 3        # 扫描一段找金句

  # ③ 精确定句：给一个粗时间点，用能量谷点 + 短窗 ASR 把整句钉到 ±0.2s
  python3 probe.py --source 片.mp4 --pin 105.0 --expect "你能保守秘密吗"
  #   → [105.18, 107.42]  "你能保守秘密吗？"

所有模式的 ASR 结果都缓存在 --keep 目录（键 = 片源路径/mtime/区间），重跑免费。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import wave
from concurrent.futures import ThreadPoolExecutor

DEFAULT_ASR = os.environ.get("COMMENTARY_ASR",
                             os.path.join(os.path.dirname(os.path.abspath(__file__)), "asr_qwen.py"))
CN = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
      "六": 6, "七": 7, "八": 8, "九": 9}


def canon(s):
    """比较用：只留汉字/字母/数字（小写），去掉标点与空白"""
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", s or "").lower()


# ---------------------------------------------------------------- 缓存
def src_id(src):
    try:
        st = os.stat(src)
        return f"{os.path.abspath(src)}|{int(st.st_mtime)}|{st.st_size}"
    except OSError:
        return os.path.abspath(src)


def cache_file(keep, src, start, dur, lang, tag):
    key = hashlib.sha1(f"{src_id(src)}|{start:.3f}|{dur:.3f}|{lang}|{tag}".encode()).hexdigest()[:16]
    return os.path.join(keep, f"asr_{tag}_{key}.json")


def asr_cached(asr, src, audio, start, dur, lang, keep, tag="q", fresh=False, ts=False):
    """抽窗 + ASR，结果落缓存。返回 (文本, 是否命中缓存, 句级时间戳列表)。

    ts=True 时多传 --json 要时间戳（qwen filetrans 有句级/词级真值）；引擎不认
    --json 就退化为纯文本调用，sents 给空、调用方按块级时间兜底。
    sents 元素 = {"start","end","text"}，时间已换算成片源绝对秒。
    """
    cp = cache_file(keep, src, start, dur, lang, tag)
    if not fresh and os.path.exists(cp):
        try:
            d = json.load(open(cp, encoding="utf-8"))
            return d["text"], True, d.get("sents") or []
        except Exception:
            pass
    jout = cp + ".asr.json" if ts else None
    def call(with_json):
        cmd = [sys.executable, asr, audio] + (["--language", lang] if lang else [])
        if with_json:
            cmd += ["--json", jout]
        return subprocess.run(cmd, capture_output=True, text=True)
    r = call(ts)
    if ts and r.returncode != 0 and not r.stdout.strip():     # 引擎不支持 --json
        jout, r = None, call(False)
    txt = r.stdout.strip() or ("ERR:" + r.stderr.strip()[:200])
    sents = []
    if jout and os.path.exists(jout):
        try:
            sents = [{"start": round(start + s["start"], 3), "end": round(start + s["end"], 3),
                      "text": s["text"]}
                     for s in json.load(open(jout, encoding="utf-8")).get("sents") or []]
        except Exception:
            sents = []
    try:
        json.dump(dict(text=txt, start=start, dur=dur, lang=lang, tag=tag,
                       src=src_id(src), sents=sents),
                  open(cp, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:
        pass
    return txt, False, sents


# ---------------------------------------------------------------- 音频工具
def cut(src, start, dur, out):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, start):.3f}",
                    "-t", f"{dur:.3f}", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
                    "-b:a", "64k", out], check=True)
    return out


def probe_one(args, t):
    src, dur, off, keep, lang, asr, fresh = args
    start = max(0.0, t + off)
    out = os.path.join(keep, f"p_{t:g}_{dur:g}_{off:g}.mp3")
    if not os.path.exists(out):
        cut(src, start, dur, out)
    txt, hit, _ = asr_cached(asr, src, out, start, dur, lang, keep, tag="probe", fresh=fresh)
    return t, start, start + dur, txt, hit


# ---------------------------------------------------------------- 能量定句
def rms_profile(path, win=320, hop=160):
    """20ms 窗 / 10ms 跳的 RMS 序列（采样点间隔 10ms）。"""
    with wave.open(path) as f:
        import array
        sr = f.getframerate()
        data = array.array("h", f.readframes(f.getnframes()))
        if sys.byteorder == "big":
            data.byteswap()
    n = max(0, (len(data) - win) // hop)
    return [((sum(x * x for x in data[i * hop:i * hop + win]) / win) ** 0.5, i * hop / sr)
            for i in range(n)]


def gaps(prof, min_gap=0.06):
    """能量谷点区间 [(起,止)]：低于段内中位数 0.28 倍且够长。

    不用 silencedetect 的绝对阈值——情景喜剧有笑声和室内底噪，-38dB 常常找不到停顿。
    """
    if not prof:
        return []
    med = sorted(r for r, _ in prof)[len(prof) // 2] or 1.0
    low = [r < 0.28 * med for r, _ in prof]
    out, i = [], 0
    while i < len(low):
        if low[i]:
            j = i
            while j + 1 < len(low) and low[j + 1]:
                j += 1
            if (j - i + 1) * 0.01 >= min_gap:
                out.append((prof[i][1], prof[j][1]))
            i = j + 1
        else:
            i += 1
    return out


def pin_sentence(args_a, t, expect=""):
    """把 t 附近的整句钉到 ±0.2s：向前找停顿 = 句首，向后找停顿 = 句尾，再 ASR 复核。"""
    src, W, keep, lang, asr, fresh = args_a
    win = os.path.join(keep, f"pin_{t:g}.wav")
    cut(src, t - W, 2 * W, win)
    prof = rms_profile(win)
    if not prof:
        return None, "无法分析音频"
    gs = gaps(prof)
    rel = t - W                                        # 窗口起点对应的时间
    before = [b for _, b in gs if rel + b <= t + 0.30]
    after = [a for a, _ in gs if rel + a >= t - 0.30]
    st = max(before) + rel if before else rel
    en = min(after) + rel if after else rel + 2 * W
    if en - st < 0.4:
        return None, f"找到的句子太短（{en - st:.2f}s），把 --window 调大或换个时间点"
    aud = os.path.join(keep, f"pin_span_{t:g}.mp3")
    cut(src, st, en - st, aud)
    txt, hit, _ = asr_cached(asr, src, aud, st, en - st, lang, keep, tag="pin", fresh=fresh)
    note = ""
    if expect:
        e, g = canon(expect), canon(txt)
        if e and g:
            # 允许 ASR 前后多说/漏字：拿期望串的前 4 字在结果里找
            head = e[:4]
            if head not in g:
                note = f" ⚠ 与 --expect 不匹配（期望含 {head!r}，实得 {g[:24]!r}）"
    return (st, en, txt, hit), note


# ---------------------------------------------------------------- 分块转写
TAIL_GAP = 8.0        # 块内「已转写末尾 → 块末」空缺超过这么久 → 判定吞尾，触发短窗补测
TAILFIX_WIN = 12.0    # 补测窗长：长块吞尾处换短窗仍出内容（实测 4s/12s 窗拿到被吞句尾，
                      # 20s 窗同样会漏——窗里音乐越多越容易整段判成非语音，别用长窗）


def merge_sents(rows, new):
    """把补测句子并入台词表（补测区间都在块尾，新句只可能碰末尾几行）。

    规则：
      - 与既有行**同文本**且重叠/邻接 → 取更宽的边界（补测常给出更完整的句尾）；
      - 与既有行重叠且**文本不同** → 只替换它最后触碰的那一行——整窗 ASR 会把
        "…inquiry? Yes." 并成一句，不能让它把前面的问句行吃掉；
      - 完全不重叠 → 按时间序插入。
    """
    for s, e, t in sorted(new):
        s, e = round(s, 2), round(e, 2)
        strict = [i for i, (rs, re_, rt) in enumerate(rows) if s < re_ and e > rs]
        if strict:
            i = strict[-1]
            rs, re_, rt = rows[i]
            same = canon(t) == canon(rt)
            rows[i] = (min(rs, s), max(re_, e), rt if same else t)
            continue
        near = [i for i, (rs, re_, rt) in enumerate(rows)
                if canon(t) == canon(rt) and s <= re_ + 0.3 and e >= rs - 0.3]
        if near:
            i = near[-1]
            rs, re_, rt = rows[i]
            rows[i] = (min(rs, s), max(re_, e), rt)
            continue
        pos = next((k for k, (rs, _, _) in enumerate(rows) if rs > e), len(rows))
        rows.insert(pos, (s, e, t))
    return sorted(rows)


def tail_fix(a, rows, chunk_cov, notes):
    """长块 ASR 吞尾修复：任一块「已转写末尾 → 块末」空缺 > --tail-gap，就用 ≤20s
    短窗把空缺段重转写一遍并合回台词表。

    为什么单做：qwen filetrans 在长块上会吞掉结尾的一小段——S3E05 全剧最后一句
    "Yes, Minister!" 被吞成 "Yes."（末句终点少 1.5s），彩蛋 pe 随之少 1.5s，成片
    把最后一个词切掉半截。同一位置换短窗仍转得出内容（实测 12s 窗拿到完整句尾）。
    没有句级时间戳的引擎（块级兜底行覆盖整块）查不了覆盖，跳过。
    局限：只查**块尾**覆盖；块中段被吞只能靠 cut_audit 的 SRT/能量判据兜。
    """
    for st, d, spans, ts_ok in chunk_cov:
        if not ts_ok or not spans:
            continue
        cend = max(e for _, e, _ in spans)
        gap = (st + d) - cend
        if gap <= a.tail_gap:
            continue
        t0, t1 = max(0.0, cend - 2.0), st + d
        print(f"⚠ 块 {st:.2f}-{t1:.2f} 转写止于 {cend:.2f}，尾部空缺 {gap:.1f}s"
              f"（长块 ASR 吞尾）→ 短窗补测", file=sys.stderr, flush=True)
        new, t = [], t0
        while t < t1 - 0.5:
            w = min(TAILFIX_WIN, t1 - t)
            out = os.path.join(a.keep, f"tailfix_{t:.0f}.mp3")
            if not os.path.exists(out):
                cut(a.source, t, w, out)
            _, _, sents = asr_cached(a.asr, a.source, out, t, w, a.language, a.keep,
                                     tag="tailfix", fresh=a.fresh, ts=True)
            new += [(s["start"], s["end"], s["text"]) for s in sents]
            t += w
        n0 = len(rows)
        rows = merge_sents(rows, new)
        still = (st + d) - (rows[-1][1] if rows else 0.0)
        note = (f"块 {st:.0f}-{t1:.0f} 尾部补测：空缺 {gap:.1f}s → "
                f"台词表 {n0}→{len(rows)} 行，现末句止 {rows[-1][1]:.2f}")
        if still > a.tail_gap:
            note += (f"\n  ⚠ 补测未捞回（仍空缺 {still:.1f}s，ASR 有方差）：末个彩蛋的 pe 必须用"
                     f"**越过 pe 的窗外 ASR** 人工核（probe.py --pin <pe> --window 6）")
        notes.append(note)
    return rows


def transcribe(a):
    dur_total = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.source],
        capture_output=True, text=True).stdout.strip() or 0)
    chunks = []
    t = 0.0
    while t < dur_total - 0.5:
        chunks.append((round(t, 2), round(min(a.chunk_sec, dur_total - t), 2)))
        t += a.chunk_sec
    print(f"分块转写：{len(chunks)} 块 × {a.chunk_sec}s（总 {dur_total:.1f}s），并发 {a.jobs}",
          file=sys.stderr)

    def job(i_ck):
        i, (st, d) = i_ck
        out = os.path.join(a.keep, f"chunk_{i:03d}.mp3")
        if not os.path.exists(out):
            cut(a.source, st, d, out)
        txt, hit, sents = asr_cached(a.asr, a.source, out, st, d, a.language, a.keep,
                                     tag="chunk", fresh=a.fresh, ts=True)
        # ASR 给句级时间戳（qwen filetrans 就给）→ 台词表逐句建；否则整块一行兜底
        spans = [(s["start"], s["end"], s["text"]) for s in sents] if sents \
            else [(st, st + d, txt)]
        return i, st, d, txt, hit, spans, bool(sents)

    rows, hits, n_sent = [], 0, 0
    chunk_cov = []
    with ThreadPoolExecutor(a.jobs) as ex:
        for i, st, d, txt, hit, spans, ts_ok in ex.map(job, list(enumerate(chunks))):
            hits += 1 if hit else 0
            if ts_ok:
                n_sent += len(spans)
            for s, e, t in spans:
                # 块边界会把一句话切成两半：与上一行文本相同且时间重叠的丢掉
                if rows and canon(rows[-1][2]) == canon(t) and s < rows[-1][1]:
                    continue
                rows.append((round(s, 2), round(e, 2), t))
            chunk_cov.append((st, d, spans, ts_ok))
            print(f"  [{i + 1:02d}/{len(chunks)}] {st:7.2f}-{st + d:7.2f}s "
                  f"{'（缓存）' if hit else ''} {txt[:70]}", flush=True)
    notes = []
    if not a.no_tail_fix:
        rows = tail_fix(a, rows, chunk_cov, notes)
    if not notes:
        last_end = rows[-1][1] if rows else 0.0
        rest = dur_total - last_end
        if rest > a.tail_gap:
            notes.append(f"⚠ 末句止 {last_end:.2f} / 片源 {dur_total:.1f}s（差 {rest:.1f}s）且无法自动核"
                         f"（ASR 没给句级时间戳）——末个彩蛋的 pe 必须用越过它的窗外 ASR 人工核")
        else:
            notes.append(f"尾部覆盖 OK：末句止 {last_end:.2f} / 片源 {dur_total:.1f}s"
                         + (f"（其后 {rest:.0f}s 在容差内）" if rest > 2 else ""))
    out = a.out or "transcript.tsv"
    with open(out, "w", encoding="utf-8") as f:
        f.write("idx\tstart\tend\ttext\n")
        for n, (st, en, txt) in enumerate(rows, 1):
            f.write(f"{n}\t{st:.2f}\t{en:.2f}\t{txt}\n")
    mode = f"句级时间戳 {n_sent} 行" if n_sent else "块级时间（ASR 没给时间戳）"
    print(f"→ {out}（{len(rows)} 行，{mode}，缓存命中 {hits} 块）")
    for n in notes:
        print(f"  {n}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("times", nargs="*", type=float)
    ap.add_argument("--source", required=True, help="原片路径（或已抽出的音轨也可）")
    ap.add_argument("--scan", help="改为扫描区间 start:end:step（秒）")
    ap.add_argument("--transcribe", action="store_true",
                    help="整片分块转写，产出台词表 TSV（idx/start/end/text）")
    ap.add_argument("--chunk-sec", type=float, default=300, help="分块长度（秒，默认 300）")
    ap.add_argument("--tail-gap", type=float, default=TAIL_GAP,
                    help=f"块内转写末尾距块末超过这么久判定吞尾并短窗补测（默认 {TAIL_GAP:g}s）")
    ap.add_argument("--no-tail-fix", action="store_true",
                    help="关掉尾部吞尾补测（不推荐：末个彩蛋的句末可能被吞）")
    ap.add_argument("-o", "--out", help="--transcribe 的输出 TSV 路径")
    ap.add_argument("--pin", type=float, metavar="T",
                    help="精确定句：把 T 附近的整句钉到 ±0.2s（配合 --expect 复核）")
    ap.add_argument("--expect", default="", help="--pin 时期望听到的台词（用于自检不匹配）")
    ap.add_argument("--window", type=float, default=3.0, help="--pin 的搜索半窗（秒）")
    ap.add_argument("--dur", type=float, default=12, help="每次探测时长（秒）")
    ap.add_argument("--off", type=float, default=0, help="相对探测点的偏移；--off -6 即以该点为中心")
    ap.add_argument("--language", help="语言提示，如 en / zh；不传由模型判断")
    ap.add_argument("--asr", default=DEFAULT_ASR, help="ASR 脚本路径（换模型时指到这里）")
    ap.add_argument("-j", "--jobs", type=int, default=4, help="并发数（服务端有限流，建议 3-4）")
    ap.add_argument("--keep", default="/tmp/commentary_probe", help="中间音频目录（ASR 结果也缓存在这里）")
    ap.add_argument("--fresh", action="store_true", help="忽略缓存重新问 ASR")
    a = ap.parse_args()

    os.makedirs(a.keep, exist_ok=True)

    if a.transcribe:
        transcribe(a)
        return

    if a.pin is not None:
        got, note = pin_sentence((a.source, a.window, a.keep, a.language, a.asr, a.fresh), a.pin,
                                 a.expect)
        if not got:
            print(f"✗ {a.pin:g}s：{note}", file=sys.stderr)
            sys.exit(1)
        st, en, txt, hit = got
        print(f"[{st:.2f}, {en:.2f}]  ({en - st:.2f}s，中心 {a.pin:g}s)"
              f"{'（缓存）' if hit else ''}\n  {txt}{note}")
        return

    times = list(a.times)
    if a.scan:
        s, e, step = (float(x) for x in a.scan.split(":"))
        t = s
        while t < e:
            times.append(round(t, 2))
            t += step
    if not times:
        ap.error("给几个时间点，或用 --scan start:end:step / --transcribe / --pin T")

    with ThreadPoolExecutor(a.jobs) as ex:
        for t, s, e, txt, hit in ex.map(lambda t: probe_one(
                (a.source, a.dur, a.off, a.keep, a.language, a.asr, a.fresh), t), times):
            print(f"[{t:g}s | {s:.1f}-{e:.1f}s]{'（缓存）' if hit else ''} {txt}")


if __name__ == "__main__":
    main()
