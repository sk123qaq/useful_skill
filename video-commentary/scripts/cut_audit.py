#!/usr/bin/env python3
"""切点体检 / 修版辅助（按需使用，默认不跑；正常出片流程见 SKILL.md 第 3、6 阶段）

用来处理用户看片后反馈的这类问题：
  A「字幕在、声音不全」——段末切在句子中间，末句被啃掉半句，黄色字幕还被夹头显示
  B「声音多留了一小截」——段末切在下一句的开头，多冒出一句没有字幕的声音
两种都是「切点落在台词里」，修法相同：把段末挪到一句完整话音之后的换气缝里。

判据（三条同时满足才算合格）：
  ① 不切词 / 不多留：段末落在 >=0.3s 的「无语音缝」里。
     阈值自动标定：取窗口内帧峰值的 85 分位作为「说话电平」，再减 9dB
     （对白峰值一般 -5~-12dB、环境声 -20~-30dB，两者之间就是缝）；
     也可 --thr 手工指定。**不要用 SRT 的起止时间当语音边界**——字幕组的
     行间隔常常只有 0.17s，且起止比真实语音早/晚 0.2~1.1s。
  ② 不闪字幕：段末前 0.15s 内不能有 SRT 行起始，否则出现一句
     「有字幕、没声音」的短闪（正是用户投诉的现象）。
  ③ 字幕拖尾 <=0.45s：末条字幕结束点比该句语音结束点晚不超过 0.45s
     （字幕比语音早退是 SRT 自身的时偏，只提示、不算故障）。

**末段实裁（自动）**：全片最后一段（或 SRT 末行横跨切点）且判据不干净时，
自动对切点附近做 3 个不同位置的窗外 ASR 采样、取末句止的最大值——切点之后还有话音
就是啃句，句子在切点前说完就把 ✗ 推翻。为什么必须这么做：S3E05 全剧最后一句
"Yes, Minister!" 被分块 ASR 吞成 "Yes."，「下一句起点 − 切点」判据对全剧
最后一句没有下一句、vacuously 通过；SRT 末行跨切点的 ✗ 又被「本季 SRT 偏早」
的结论连带驳回——窗外 ASR 是唯一客观判据。多样本是因为 ASR 对「句尾混着音乐」
的窗有方差（单发可能假阴性）。（--no-asr 关掉，纯离线。）

用法：
  # 体检：逐段报告是否合格
  python3 cut_audit.py --plan out/resolved.json --source 原片.mp4 --srt 原片.srt
  # 体检 + 给修法：列出每个段末附近可选的语音缝和建议的 pe
  python3 cut_audit.py --plan out/resolved.json --source 原片.mp4 --srt 原片.srt --suggest
  # 用成片本身查（--source 传成片即可，时间轴就是成片时间）
  python3 cut_audit.py --plan out/resolved.json --source 成片.mp4 --srt 成片对应的srt

修法（体检报 ✗ 之后）：
  1. 按 --suggest 挑一个缝，把它折算成 pe（= 缝中心 - 0.35），改 plan.json 里该段
     punch 的第二个数；挑完复查 b < 下一段的起点。
  2. 重跑 timeline.py 时加 --snap-cut 0.3：默认 1.55s 会把段末吸到附近的镜头
     切点上，常常又吸回台词里（吸附优先于句末+0.35s）。
  3. timeline → fix_subs_punct → calibrate → render → verify，然后用
     probe.py 对新切点前 2.6s 做 ASR 复听，确认末句完整。
  4. 参数卡记一笔：根因、改了哪几段、片长增量。
"""
import argparse, hashlib, json, math, os, re, subprocess, sys, tempfile, wave

DEFAULT_ASR = os.environ.get("COMMENTARY_ASR",
                             os.path.join(os.path.dirname(os.path.abspath(__file__)), "asr_qwen.py"))

TAIL = 0.35          # timeline.py 的 tail 参数（句末 + tail）
MIN_GAP = 0.30       # 语音缝最短时长
FLASH = 0.15         # 段末前多久不准有字幕行起始
LINGER = 0.45        # 字幕比语音最多多留多久
P85_DROP = 9.0       # 自动阈值 = 帧峰值85分位 - 9dB
TAIL_PRE = 2.5       # 末段窗外 ASR：切点前看这么久
TAIL_POST = 6.0      # 末段窗外 ASR：切点后看这么久
# 多样本（切点前, 切点后）：ASR 对「句尾混着音乐」的窗有方差——实测同一种窗
# 有时把尾词并进句子、有时整段判成非语音（S3E05 尾句：4s/12s 窗拿到 1721.88/
# 1722.32，20s 窗只回 1720.37）。多样本取最大值，杜绝单发假阴性。
TAIL_SAMPLES = ((2.5, 6.0), (1.5, 7.0), (3.5, 5.0))


def frame_levels(src, t0, dur):
    """20ms 帧峰值（dB）。"""
    p = tempfile.mktemp(suffix=".wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t0), "-t", str(dur),
                    "-i", src, "-ac", "1", "-ar", "16000", "-f", "wav", p], check=True)
    w = wave.open(p); n = w.getnframes(); fr = w.getframerate(); d = w.readframes(n); w.close()
    os.unlink(p)
    step = max(1, int(fr * 0.02)); out = []
    for i in range(0, n - step, step):
        mx = 1
        for j in range(i, i + step):
            v = abs(int.from_bytes(d[2 * j:2 * j + 2], "little", signed=True))
            if v > mx:
                mx = v
        out.append((t0 + i / fr, 20 * math.log10(mx / 32768) if mx > 0 else -99.0))
    return out


def auto_thr(levels):
    vs = sorted(db for _, db in levels)
    p85 = vs[int(len(vs) * 0.85)] if vs else -20.0
    return round(p85 - P85_DROP, 1)


def gaps_of(levels, thr, ms=MIN_GAP):
    out, run = [], None
    for t, db in levels:
        if db < thr:
            run = [t, t] if run is None else [run[0], t]
        else:
            if run and run[1] - run[0] >= ms:
                out.append((round(run[0], 2), round(run[1], 2)))
            run = None
    if run and run[1] - run[0] >= ms:
        out.append((round(run[0], 2), round(run[1], 2)))
    return out


def asr_window(src, t0, dur, lang, asr, keep, fresh=False):
    """切 [t0, t0+dur] 做短窗 ASR，返回 (文本, [(起, 止, 文本), …]绝对秒)。

    末段实裁专用：台词表/SRT 都判不了「全剧最后一句有没有说完」时，只有越过
    切点的窗外 ASR 能给客观答案。结果落缓存（键 = 片源/窗口/语言），重跑免费。
    """
    os.makedirs(keep, exist_ok=True)
    key = hashlib.sha1(f"{os.path.abspath(src)}|{os.path.getsize(src)}|"
                        f"{t0:.2f}|{dur:.2f}|{lang}".encode()).hexdigest()[:16]
    cp = os.path.join(keep, f"cutaudit_{key}.json")
    if not fresh and os.path.exists(cp):
        d = json.load(open(cp, encoding="utf-8"))
        return d["text"], [tuple(x) for x in d.get("sents") or []]
    aud = os.path.join(keep, f"cutaudit_{key}.mp3")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t0):.3f}",
                    "-t", f"{dur:.3f}", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
                    "-b:a", "64k", aud], check=True)
    cmd = [sys.executable, asr, aud] + (["--language", lang] if lang else []) \
        + ["--json", cp + ".asr.json"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    txt = (r.stdout or "").strip()
    sents = []
    if os.path.exists(cp + ".asr.json"):
        try:
            for s in json.load(open(cp + ".asr.json", encoding="utf-8")).get("sents") or []:
                sents.append((round(t0 + s["start"], 3), round(t0 + s["end"], 3),
                              s.get("text", "")))
        except Exception:
            pass
    json.dump(dict(text=txt, sents=[list(x) for x in sents]),
              open(cp, "w", encoding="utf-8"), ensure_ascii=False)
    return txt, sents


def read_srt(path):
    if not path or not os.path.exists(path):
        return []
    def t2s(t):
        t = t.replace(",", "."); a = t.split(":")
        return int(a[0]) * 3600 + int(a[1]) * 60 + float(a[2])
    E, lines, i = [], [l.rstrip("\n") for l in open(path, encoding="utf-8")], 0
    while i < len(lines):
        if re.match(r"^\d+$", lines[i].strip()):
            idx = int(lines[i]); i += 1
            s, e = [t2s(x) for x in lines[i].split(" --> ")]; i += 1
            txt = []
            while i < len(lines) and lines[i].strip():
                txt.append(lines[i].strip()); i += 1
            E.append((idx, s, e, " ".join(txt)))
        else:
            i += 1
    return E


def load_items(plan):
    """吃两种 plan：resolved.json（有 a/b）或 plan.json（punch/fixed 两元组）。"""
    d = json.load(open(plan))
    items = d["items"] if isinstance(d, dict) else d
    out = []
    for it in items:
        name = it.get("name", "?")
        if name == "S00":          # 钩子是 fixed 段，没有可调的彩蛋终点
            continue
        ab = None
        if "a" in it and "b" in it:
            ab = (float(it["a"]), float(it["b"]))
        elif "punch" in it:
            ab = (float(it["punch"][0]), float(it["punch"][1]))
        elif "fixed" in it:
            ab = (float(it["fixed"][0]), float(it["fixed"][1]))
        if ab:
            out.append((name, ab[0], ab[1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, help="out/resolved.json（或 plan.json）")
    ap.add_argument("--source", required=True, help="原片 mp4（也可传成片）")
    ap.add_argument("--srt", default="", help="对白 SRT（不给就只查音频）")
    ap.add_argument("--thr", type=float, default=None, help="静音阈值 dB，缺省自动标定")
    ap.add_argument("--min-gap", type=float, default=MIN_GAP)
    ap.add_argument("--tail", type=float, default=TAIL, help="timeline.py 的 tail（折算 pe 用）")
    ap.add_argument("--window", type=float, default=14.0, help="段末后看多远的候选缝")
    ap.add_argument("--suggest", action="store_true", help="给出每个段末可选的缝和建议 pe")
    ap.add_argument("--asr", default=DEFAULT_ASR,
                    help="末段实裁用的 ASR 脚本（默认 asr_qwen.py；可用 COMMENTARY_ASR 覆盖）")
    ap.add_argument("--asr-lang", default=os.environ.get("QWEN_ASR_LANG") or None,
                    help="末段实裁的 ASR 语言提示（默认读 QWEN_ASR_LANG）")
    ap.add_argument("--keep", default="/tmp/commentary_cutaudit", help="末段实裁的音频/缓存目录")
    ap.add_argument("--tail-win", type=float, default=TAIL_POST,
                    help=f"末段窗外 ASR：切点后看多久（默认 {TAIL_POST:g}s；切点前固定 {TAIL_PRE:g}s）")
    ap.add_argument("--no-asr", action="store_true",
                    help="不做末段窗外 ASR 实裁（纯离线；末段 ✗ 失去客观判据）")
    ap.add_argument("--fresh", action="store_true", help="忽略缓存重问 ASR")
    a = ap.parse_args()

    raw = json.load(open(a.plan))
    if isinstance(raw, dict) and raw.get("items") and "punch" in (raw["items"][1] if len(raw["items"]) > 1 else {}):
        print("⚠ 传入的是 plan.json（配音前的 pe）；要看成片真实切点请用 out/resolved.json\n")
    items = load_items(a.plan)
    E = read_srt(a.srt)
    if a.srt and not E:
        print("⚠ 没读到 SRT 字幕行，只按音频判（第②③条跳过）")
    bad = warn = 0
    for k, (name, s0, b) in enumerate(items):
        nxt = items[k + 1][1] if k + 1 < len(items) else None
        levels = frame_levels(a.source, max(0.0, b - 6), 13.0)
        thr = a.thr if a.thr is not None else auto_thr(levels)
        g = gaps_of(levels, thr, a.min_gap)
        inside = [x for x in g if x[0] <= b <= x[1]]
        flash = [e[0] for e in E if b - FLASH < e[1] <= b]
        m = inside[0] if inside else None
        cover_now = []
        if m:
            cover = [e for e in E if e[1] <= m[0] <= e[2]]
            tail = round(min(cover[0][2], b) - m[0], 2) if cover else None
            note = (f"末条字幕 {cover[0][0]} 语音止 {m[0]} 字幕止 {min(cover[0][2], b)}（拖尾 {tail}s）"
                    if cover else f"语音止 {m[0]}，附近无字幕行（笑声/环境声）")
            ok = (not flash) and (tail is None or -0.6 <= tail <= LINGER)
        else:
            tail = None
            cover_now = [e[0] for e in E if e[1] <= b <= e[2]]      # 字幕行横跨切点
            if cover_now:
                ok, note = False, f"✗ 切点落在台词里（啃句或多留一截）：字幕行 {cover_now}"
            else:
                ok, note = True, "⚠ 切点处无字幕行（笑声/音乐，或字幕组缺行）；若此处有人声请人工确认"
                warn += 1
        # ---- 末段实裁：全片最后一段（或 SRT 末行横跨切点）且判据不干净时，
        #      窗外 ASR 是唯一客观判据；✗ 不许用「SRT 偏早」一律驳回。----
        srt_last = bool(cover_now and E and cover_now[0] == E[-1][0])
        if (nxt is None or srt_last) and (not ok or (m is None and not cover_now)) \
                and not a.no_asr:
            # 多样本取最大：单发窗可能把切点后的尾词整段判成非语音（假阴性）
            ends, saw = [], 0
            for pre, post in TAIL_SAMPLES:
                txt, sents = asr_window(a.source, b - pre, pre + post, a.asr_lang,
                                        a.asr, a.keep, a.fresh)
                es = [e for _, e, _ in sents]
                ends += es
                saw += sum(1 for e in es if e > b + 0.3)
            last_end = max(ends) if ends else None
            if last_end is None:
                print(f"      └ 末段窗外 ASR（{len(TAIL_SAMPLES)} 个采样窗）没返回句级时间戳："
                      f"人工复听切点后 {a.tail_win:g}s")
            elif last_end > b + 0.3:
                ok = False
                note += (f"；✗ 窗外 ASR 实裁：末句止 {last_end:.2f} > 切点 {b:.2f}，"
                         f"这句没说完（pe 至少要到 {last_end:.2f}；{saw}/{len(ends)} "
                         f"个采样窗见到切点后话音）")
            elif not ok:
                # ASR 采样都干净 → 还要 SRT 不反对才推翻 ✗。横跨切点的字幕行止点超出
                # 切点 >0.3s 时保守按啃句：ASR 对「句尾混着音乐」的窗有方差，假 ✗
                # 只需人工复听一句，假 OK 是把没说完的结尾直接交付给用户。
                over = max((e[2] for e in E if e[1] <= b <= e[2]), default=None)
                if over is not None and over > b + 0.3:
                    note += (f"；⚠ SRT 行止 {over:.2f} 仍跨切点 {over - b:.2f}s，但 "
                             f"{len(TAIL_SAMPLES)} 个 ASR 采样窗都没见到切点后话音"
                             f"（引擎方差）→ 保守按啃句，人工复听切点后 3s")
                else:
                    ok = True
                    note += (f"；✓ 窗外 ASR 实裁：{len(TAIL_SAMPLES)} 个采样窗都显示末句止 "
                             f"{last_end:.2f} ≤ 切点 {b:.2f}，句子完整（✗ 是 SRT 时偏假阳性）")
            else:
                note += f"；✓ 窗外 ASR：切点后无话音（末句止 {last_end:.2f}）"
        if not ok:
            bad += 1
        seg = f"{name} b={b:8.2f}"
        gm = (f"缝 {m[0]}-{m[1]}({m[1]-m[0]:.2f}s) 前余{b-m[0]:.2f} 后余{m[1]-b:.2f}"
              if m else "无语音缝")
        print(f"{'OK ' if ok else '✗✗'} {seg}｜{gm}｜闪字幕 {flash or '无'}｜{note}")
        if a.suggest:
            cands = [x for x in g if b - 2.0 <= x[0] <= b + a.window]
            for s, e in cands:
                c = round((s + e) / 2, 2)
                pe = round(c - a.tail, 2)
                room = "" if nxt is None else (f"｜b 距下一段起点 {nxt - c:+.2f}s" if nxt - c > 0 else "｜✗ 越过下一段起点")
                print(f"      候选缝 {s}-{e}({e-s:.2f}s) → 切点 {c} → pe={pe}{room}")
            if not cands:
                print(f"      （{b:.2f} 前后 {a.window}s 内没有 >= {a.min_gap}s 的缝：改用 --min-gap 0.2 或换个段末）")
    tail_txt = f"，另 {warn} 处需人工确认（笑声/缺行）" if warn else ""
    print(f"\n{bad} 个切点不合格{tail_txt}" if bad else f"\n全部切点合格：没啃句、没多留、没闪字幕{tail_txt}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
