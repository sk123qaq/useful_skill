#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""求解剪辑时间轴：由"原声彩蛋句"反推片段入出点，并产出解说音轨与字幕。

三条边界规则（自动执行）：
  ① 不掐句：彩蛋窗以整句收尾（终点 = 句末 + narr_tail）
  ② 吸附镜头切换：终点优先落在切点前 0.05s（±snap_cut 内），保证不出现"碎镜头"
  ③ 末镜 ≥ min_tail 秒：不足就延长到切点后 1.6s，或回退到上一个切点
彩蛋窗起点用能量法吸附到"上一句说完、下一句刚开口"处（--source 提供原片时启用）。

plan.json 三种条目：
  {"fixed":[a,b]}                        固定片段（片头等；解说完后原片只再留 --fixed-tail 秒，默认 2.0）
  {"punch":[句起,句止]}                   彩蛋反推（最常用）
  {"a":..,"b":..,"blocks":[["narr",段名],["orig",起,止],…]}   解说/原声交替的长段

用法:
  python3 timeline.py --plan plan.json --audio-dir norm --source 原片.mp4 --out-dir out --track
"""
import argparse, array, json, os, re, subprocess, sys, wave

import skillcfg

STYLE_FMT = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
             "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
             "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding")


def ass_head(w, h, font, size, mv, bold, outline, shadow, dlg=False, narlow_mv=None,
             name_mv=None, name_size=None):
    """拼 [Script Info] + [V4+ Styles]。

    成品样式（粗体 + 描边 + 阴影）以前是手工改 Style 行得到的，重跑 timeline 就会丢；
    现在作为参数直接生成。Dlg / NarLow / NameTag 也在这里一起出。
    注：ASS 没有「样式级淡入」，淡入淡出只能逐条写 \\fad()，见 make_subs 的 fade_ms。
    """
    def row(name, colour, m, bold_=None, border=1, out_colour="&HA0000000",
            size_=None, align=2, pad=None):
        # BorderStyle=3 时 OutlineColour 就是底色块（名牌用它做半透明底）
        return (f"Style: {name},{font},{size_ or size},{colour},&H000000FF,{out_colour},&H80000000,"
                f"{bold_ if bold_ is not None else bold},0,0,0,100,100,0,0,{border},"
                f"{pad if pad is not None else outline},{shadow},{align},40,40,{m},1")
    styles = [row("Nar", "&H00FFFFFF", mv)]
    if dlg:
        styles.append(row("Dlg", "&H0000FFFF", mv))
    if narlow_mv is not None:
        styles.append(row("NarLow", "&H00FFFFFF", narlow_mv, bold_=bold))
    if name_mv is not None:
        styles.append(row("NameTag", "&H00FFFFFF", name_mv, bold_=1, border=3,
                          out_colour="&HC0202020", size_=name_size, align=1, pad=8))
    return ("[Script Info]\nScriptType: v4.00+\n"
            f"PlayResX: {w}\nPlayResY: {h}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n" + STYLE_FMT + "\n" + "\n".join(styles) + "\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
            "Effect, Text\n")


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def dur(p):
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p])
    return float(r.stdout.strip() or 0)


def sha1_file(p, n=1 << 20):
    import hashlib
    h = hashlib.sha1()
    with open(p, "rb") as f:
        while True:
            b = f.read(n)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def probe_size(src):
    """从原片读宽高：字幕 PlayRes 必须等于视频分辨率，否则字号/边距全都不是你以为的像素。"""
    r = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height", "-of", "csv=p=0:s=x", src])
    m = re.match(r"\s*(\d+)\s*[x,]\s*(\d+)", r.stdout or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def merge_spans(spans):
    """把可能重叠/乱序的区间合并成互不相交的有序区间。"""
    out = []
    for a, b in sorted(spans):
        if b - a <= 1e-6:
            continue
        if out and a <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


MOVE_HEAD = "，。、；：！？）》」』】”…"


def char_px(c, size):
    """粗略字宽：CJK 全宽，拉丁/数字约 0.55 宽。按像素折行，别按字数。"""
    return size if ord(c) > 0x2E80 else size * 0.55


def text_px(t, size):
    return sum(char_px(c, size) for c in t)


def wrap_px(text, limit, size):
    """按像素宽度折行；断点优先落在标点后，且**断点后不留下行首标点**。

    旧版按固定字数拆（maxlen=20），两个后果：
      * 含英文/数字的行宽度不可控（字号 58 时一行 21 字就贴边了）；
      * 硬断时断点与标点无关，下一行就会以「，」「》」开头——
        fix_subs_punct.py 事后救的就是这个（源头在折行这里）。
    """
    out = []
    for p in re.split(r"(?<=[。！？])", text):
        p = p.strip()
        while p and text_px(p, size) > limit:
            cut = 1
            for i in range(1, len(p) + 1):
                if text_px(p[:i], size) > limit:
                    break
                cut = i
            m = max(p.rfind(c, 0, cut) for c in "，、；：")
            k = m + 1 if m > 0 else cut
            while k < len(p) and p[k] in MOVE_HEAD:      # 标点跟上一行走，不甩到行首
                k += 1
            out.append(p[:k].strip())
            p = p[k:].strip()
        if p:
            out.append(p)
    return out


# ---------- 产物凭据：只认 narration.py 验过的段 ----------
def load_manifest(audio_dir):
    p = os.path.join(audio_dir, "manifest.json")
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
        return d.get("segments", d) if isinstance(d, dict) else {}
    except Exception as e:
        print(f"⚠ {p} 读不了（{e}），按无 manifest 处理", file=sys.stderr)
        return None


class Units:
    """片段音频取用口。

    为什么要这层：narration.py 自检失败的段落以前会把半成品 wav 留在 norm/，
    而 timeline 只看"文件在不在"——坏段就这样静默进片了。现在 manifest 里没有、
    verified=false、或 sha1 与记录不符，都会被记成问题，默认直接拒绝出片。
    """

    def __init__(self, audio_dir, allow_unverified=False):
        self.dir = audio_dir
        self.mf = load_manifest(audio_dir)
        self.allow = allow_unverified
        self.warned = False
        self.problems = []

    def dur(self, u):
        p = f"{self.dir}/{u}.wav"
        if not os.path.exists(p):
            self.problems.append(f"缺音频 {p}（先跑 narration.py）")
            return 0.0
        if self.mf is None:
            if not self.warned:
                print(f"⚠ {self.dir} 没有 manifest.json：产物未经验证（旧目录？）", file=sys.stderr)
                self.warned = True
            return dur(p)
        row = self.mf.get(u)
        if row is None:
            self.problems.append(f"{u} 不在 manifest 里（没通过校验，或来自别的 --out 目录）")
        elif not row.get("verified"):
            self.problems.append(f"{u} 未通过校验（覆盖率低/自检失败）")
        elif row.get("sha1") and row["sha1"] != sha1_file(p):
            self.problems.append(f"{u} 与 manifest 记录的 sha1 不符（产出后被改过）")
        return dur(p)


# ---------- 镜头切换点 ----------
def load_cuts(path):
    """读切点文件。两种格式都吃：

      * 每行一个裸浮点（detect_cuts 自己写的格式）
      * ffmpeg `metadata=print` 的输出（`frame:0  pts:76800  pts_time:6.0`）
        这是 SKILL.md 早期版本第 5 阶段 5a 那条命令的产物——直接用这里的
        正则捞 pts_time，省得用户手工清洗；两者都不匹配时给出能照着改的报错。
    """
    txt = open(path, encoding="utf-8", errors="replace").read()
    times = {round(float(m.group(1)), 2) for m in re.finditer(r"pts_time:\s*([\d.]+)", txt)}
    if not times:
        for tok in re.split(r"[\s,]+", txt):
            if not tok:
                continue
            try:
                times.add(round(float(tok), 2))
            except ValueError:
                if not times:
                    raise SystemExit(
                        f"--cuts {path}: 解析失败。期望每行一个秒数（如 12.34），"
                        f"或 ffmpeg metadata=print 的输出；首个看不懂的 token = {tok!r}。"
                        f"也可以不传 --cuts，让 timeline.py 自己检测（--source 原片.mp4）。")
    return sorted(t for t in times if t > 0)


def detect_cuts(src, out_txt, scene=0.35):
    raw = out_txt + ".raw"
    sh(["ffmpeg", "-v", "error", "-y", "-i", src,
        "-vf", f"select='gt(scene,{scene})',metadata=print:file={raw}", "-an", "-f", "null", "-"])
    times = sorted({round(float(m.group(1)), 2)
                    for m in re.finditer(r"pts_time:([\d.]+)", open(raw).read())})
    open(out_txt, "w").write("\n".join(f"{t:.2f}" for t in times))
    return times


# ---------- 停顿吸附（能量法，不依赖绝对静音） ----------
def rms_profile(src, t0, dur_=2.8, sr=16000, win=320, hop=160):
    w = "/tmp/_snap.wav"
    sh(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0, t0):.3f}", "-t", f"{dur_:.3f}", "-i", src,
        "-ac", "1", "-ar", str(sr), w])
    if not os.path.exists(w):
        return []
    with wave.open(w) as f:
        data = array.array("h", f.readframes(f.getnframes()))
    n = max(0, (len(data) - win) // hop)
    return [(t0 + i * hop / sr, (sum(x * x for x in data[i * hop:i * hop + win]) / win) ** 0.5)
            for i in range(n)]


def snap_start(src, ps, back=1.7, lo=0.75, hi=0.35):
    """窗口起点吸附到上一句说完、下一句刚开口的时刻"""
    if not src:
        return ps, "未提供原片，保留估算"
    fr = rms_profile(src, ps - back)
    if not fr:
        return ps, "无法分析"
    vals = sorted(r for _, r in fr)
    med = vals[len(vals) // 2] or 1.0
    low = [r < 0.28 * med for _, r in fr]
    runs, i = [], 0
    while i < len(low):
        if low[i]:
            j = i
            while j + 1 < len(low) and (low[j + 1] or (j + 3 < len(low) and low[j + 3])):
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    cands = []
    for a, b in runs:
        if (b - a) * 0.01 < 0.06:
            continue
        k = b
        while k < len(fr) and fr[k][1] < 0.5 * med:
            k += 1
        if k < len(fr):
            cands.append(fr[k][0])
    cands = [c for c in cands if ps - lo <= c <= ps + hi]
    if not cands:
        return ps, "无停顿可吸附"
    c = min(cands, key=lambda x: abs(x - ps))
    return round(c, 2), f"起点吸附停顿 {c:.2f}s"


# ---------- 边界求解 ----------
def solve_b(cuts, pe, min_tail=1.5, snap_cut=1.55, tail=0.35):
    t = pe + tail
    cand = [c for c in cuts if pe + 0.10 <= c <= pe + snap_cut]
    if cand:
        c = min(cand, key=lambda x: abs(x - t))
        p = max([x for x in cuts if x < c - 0.01], default=-99)
        if c - p >= min_tail:
            return round(c - 0.05, 2), f"吸附切点 {c:.2f}（该镜 {c-p:.1f}s）"
    prev = max([x for x in cuts if x <= t], default=-99)
    nxt = min([x for x in cuts if x > t], default=9999)
    if t - prev >= min_tail or prev < 0:
        return round(t, 2), f"句末+{tail}s（镜内 {t-prev:.1f}s）"
    ext = prev + min_tail + 0.1
    if ext <= nxt - 0.05:
        return round(ext, 2), f"延长到 {ext:.2f}（避免碎镜头）"
    return round(prev - 0.05, 2), "回退到上一个切点"


def complement_spans(dur_, masks):
    """[0,dur] 减去 masks（已合并有序）后的补集 = 原声全音量窗（段内相对秒）。"""
    out, cur = [], 0.0
    for s, e in masks:
        if s - cur > 1e-6:
            out.append((round(cur, 3), round(s, 3)))
        cur = max(cur, e)
    if dur_ - cur > 1e-6:
        out.append((round(cur, 3), round(dur_, 3)))
    return out


def finalize_item(it):
    """把「解说遮蔽窗」与「原声全音量窗（段内相对秒）」写进条目。

    resolved.json 里有了这两个结构，validate.py / verify.py / calibrate.py 就不必再猜：
    以前只能从 why 字符串里读"原声窗 24.0→23.99"，所以"解说压在原声窗上"这类错
    只能靠抽帧才发现。
    """
    it["narr_mask"] = [list(x) for x in narration_windows(it)]
    it["orig"] = [list(x) for x in complement_spans(it["dur"], it["narr_mask"])]
    return it


def build_plan(cfg, cuts, src, units_dir, min_tail, snap_cut, narr_tail, gap, udur=None,
               fixed_tail=2.0):
    """udur(u) = 该段解说音频时长（默认走 manifest 校验过的目录）。"""
    udur = udur or Units(units_dir).dur
    items, t0 = [], 0.0
    for it in cfg["items"]:
        units = it.get("units", [])
        N = sum(udur(u) for u in units) + gap * max(0, len(units) - 1)
        if "fixed" in it:
            a, b = it["fixed"]
            why, off = "固定片段", 0.0
            # fixed 段（片头钩子/片尾收尾）解说完后：原片只再留 fixed_tail 秒就切走，
            # 不让片头字幕卡/片尾演职员表在没人声时拖节奏。想保留某张卡片就把它
            # 写进 fixed 终点（脚本只在"解说完还有富余"时才压缩，绝不越过 fixed 终点）。
            if units and fixed_tail is not None and a + N + fixed_tail < b:
                why = f"固定片段（解说 {N:.1f}s 后原片再留 {fixed_tail:g}s）"
                b = a + N + fixed_tail
        elif "blocks" in it:
            base, cur, narr, notes = 0.0, it["a"], [], []
            for blk in it["blocks"]:
                if blk[0] == "narr":
                    narr.append([blk[1], round(cur, 3), udur(blk[1])])
                    cur += udur(blk[1]) + gap
                else:
                    st, why = snap_start(src, blk[1])
                    if st < cur + 0.05:          # 与该段前面那句解说冲突 → 顺延
                        st = round(cur + gap, 2)
                        st2, why2 = snap_start(src, st + 0.65)   # 顺延后再往前吸一次停顿
                        st = st2 if st2 >= st else st
                        why = f"顺延避开解说→{st:.2f}（{why2}）"
                    notes.append(f"原声窗 {blk[1]:.1f}→{st:.2f}（{why}）")
                    cur = blk[2] + gap
            a, b = it["a"], it["b"]
            base = t0
            narr = [[u, round(base + (g - a), 3), d] for u, g, d in narr]
            items.append(finalize_item(dict(
                name=it["name"], a=a, b=b, start=round(t0, 3), dur=round(b - a, 3),
                narr=narr, why="解说/原声交替｜" + "；".join(notes))))
            t0 += b - a
            continue
        else:
            ps, pe = it["punch"]
            ps, why_ps = snap_start(src, ps)
            b, why = solve_b(cuts, pe, min_tail, snap_cut)
            off = it.get("lead", 0.0)
            a = ps - narr_tail - N - off
            why = f"{why}；{why_ps}"
        narr, cur = [], a + off
        for i, u in enumerate(units):
            if i:
                cur += gap
            narr.append([u, round(t0 + (cur - a), 3), udur(u)])
            cur += udur(u)
        items.append(finalize_item(dict(name=it["name"], a=round(a, 3), b=b, start=round(t0, 3),
                                        dur=round(b - a, 3), narr=narr, why=why)))
        t0 += b - a
    return items, round(t0, 3)


# ---------- 解说音轨 ----------
def build_track(items, total, audio_dir, out):
    segs, t = [], 0.0
    for it in items:
        for u, gs, d in sorted(it["narr"], key=lambda x: x[1]):
            if gs - t > 0.05:
                segs.append(("sil", gs - t))
            segs.append(("aud", f"{audio_dir}/{u}.wav"))
            t = gs + d
    if total - t > 0.05:
        segs.append(("sil", total - t))
    ins, labels = [], []
    for i, (k, v) in enumerate(segs):
        if k == "sil":
            ins += ["-f", "lavfi", "-t", f"{v:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        else:
            ins += ["-i", v]
        labels.append(f"[{i}:a]")
    flt = "".join(labels) + (f"concat=n={len(segs)}:v=0:a=1,aresample=48000,"
                             "aformat=channel_layouts=stereo[narr]")
    sh(["ffmpeg", "-v", "error", "-y"] + ins + ["-filter_complex", flt, "-map", "[narr]",
       "-c:a", "pcm_s16le", out])
    return dur(out)


# ---------- 字幕 ----------
def read_dlg_srt(path, skip):
    """直接读外挂 SRT（中英双语的取中文行）。skip = 要跳过的 idx（标题/水印）。

    以前要先把 SRT 手工转成 `idx\\t起\\t止\\t中文` 的 TSV，而那个转换脚本
    （build_dlg_subs.py）已经不在了——输入链断在这里，所以直接吃 SRT。
    """
    blocks = re.split(r"\n\s*\n", open(path, encoding="utf-8", errors="replace").read().strip())
    cues = []
    for blk in blocks:
        lines = [x.strip() for x in blk.splitlines() if x.strip()]
        if len(lines) < 2:
            continue
        i = 0
        if lines[0].isdigit():
            idx, i = int(lines[0]), 1
        else:
            idx = len(cues) + 1
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", lines[i])
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        st = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        en = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = lines[i + 1:]
        cn = next((x for x in body if re.search(r"[\u4e00-\u9fff]", x)), "")
        cn = strip_tags(cn)
        if not cn or idx in skip or is_non_dialogue(cn):
            continue
        cues.append((st, en, dlg_text(cn)))
    return cues


def read_dlg_cues(tsv, skip):
    """读台词表（idx\t起\t止\t中文，probe.py --transcribe 或人工整理）。"""
    cues = []
    for ln in open(tsv, encoding="utf-8").read().splitlines():
        part = ln.split("\t")
        if len(part) < 4 or not part[0].strip().isdigit():
            continue
        idx, st, en, cn = int(part[0]), float(part[1]), float(part[2]), part[3].strip()
        if idx in skip or not cn:
            continue
        cues.append((st, en, cn))
    return cues


TAG_RE = re.compile(r"\{\\[^}]*\}|<[^>]{0,40}>")
# 字幕组信息 / 压制水印行。关键词都带冒号或本身就是专有名词，不会误伤正常台词
# （"为什么要压制消息?" 不含冒号，安全）。
JUNK_RE = re.compile(r"字幕组|字幕[:：]|压制[:：]|时间轴|校对[:：]|仅供交流|严禁商用|本字幕"
                     r"|片源[:：]|招募|更多精彩|微信公众号|微博[:：]|微信[:：]")


def strip_tags(s):
    """剥掉字幕正文里夹带的样式标记：ASS 覆盖块 `{\\fs18}`、HTML 标签 `<font ...>`。

    动机（实测）：双语外挂 SRT 的中文行常写成 `{\\fs18}看过了?`。原样当字幕文本用时
    libass 会真的按 18px 渲染——样式里定 58px 也没用：实测黄色对白字幕包围盒
    136×11px，应为 439×38px，也就是对白字幕被静默压小 4 倍，样式再漂亮都白搭。
    """
    return TAG_RE.sub("", s)


def is_non_dialogue(text):
    """字幕组信息 / 水印行（含中文，所以会被"取中文行"的逻辑当成对白）。

    这类行混进来有两个后果：① 成片里冒出一条莫名其妙的黄色"对白"；
    ② verify.py 的"原声窗对白覆盖"会把片头纯音乐段判成"覆盖 0%"。
    """
    return bool(JUNK_RE.search(text))


def dlg_text(cn):
    cn = strip_tags(cn)
    cn = re.sub(r"\s{2,}", "\u3000", cn)          # 多空格 → 全角空格（双人台词分隔）
    return re.sub(r"^[-\u2013\u2014]\s*", "", cn.strip()).strip()


def dlg_wrap(cn, limit, size):
    """对白字幕折行：宽度按字号算（旧版写死 CJK 58px / 拉丁 33px，换个字号就错）。"""
    if text_px(cn, size) <= limit:
        return cn
    best = None
    for m in re.finditer(r"[，。？！、；]", cn):
        k = m.end()
        if 0 < k < len(cn):
            d = abs(text_px(cn[:k], size) - text_px(cn[k:], size))
            if best is None or d < best[0]:
                best = (d, k)
    k = best[1] if best else len(cn) // 2
    return cn[:k].rstrip() + "\\N" + cn[k:].lstrip()


def narration_windows(it, gap_before=0.1, gap_after=0.35):
    """段内相对时间的解说遮蔽窗：合并重叠、夹到 [0, dur]、按时间排序。"""
    start, dur_ = it["start"], it["dur"]
    raw = [(max(0.0, min(dur_, (g - start) - gap_before)),
            min(dur_, max(0.0, (g - start) + d + gap_after))) for _, g, d in it["narr"]]
    return merge_spans(raw)


def build_dlg_events(items, cues, gap_after=0.35, min_span=1.0, min_cue=0.35, size=46,
                     px_limit=1230):
    """把原片对白字幕落到"原声全音量窗"＝每段内解说遮蔽区之外的区间。

    以前这是独立的 build_dlg_subs.py（手工再跑一遍）。内联进来之后又发现一个坑：
    它假设解说遮蔽窗两两不重叠且已排序，于是 `sorted(起点) + sorted(终点)` 那种
    交替配对法在重叠时静默失序，能产出"整段压在解说上"的黄色字幕。现在：
      * 先把解说窗做区间合并（重叠本身会被 stderr 告警，plan 写错不用等到抽帧才发现）；
      * 再取补集当原声窗。重叠只影响告警，不影响正确性。
    """
    events = []
    for it in items:
        start, dur_, a = it["start"], it["dur"], it["a"]
        raw = [(max(0.0, min(dur_, (g - start) - 0.1)),
                min(dur_, max(0.0, (g - start) + d + gap_after))) for _, g, d in it["narr"]]
        masks = merge_spans(raw)
        # 只有真正压掉一段才算重叠：段间距 0.45 正好等于两侧余量之和（0.1 + 0.35）时，
        # 相邻两个解说窗理论上只在一个点上相接。而 manifest 里的时长按 6 位小数存，
        # 累积下来会有零点几毫秒的尾差（实测 0.15–0.56ms），那不是排布错误——
        # 第六集 p01/p12/p16/p23 就都被这样误报成「plan.json 排布不正常」，彩蛋窗其实完好。
        # 容差取 1ms：远高于尾差，又远低于任何真问题（真重叠至少几十毫秒）。
        TOL = 1e-3
        nov, pe = 0, None
        for s, e in sorted(x for x in raw if x[1] > x[0]):
            if pe is not None and s < pe - TOL:
                nov += 1
            pe = e if pe is None else max(pe, e)
        if nov:
            print(f"⚠ 片段 {it.get('name', '?')}：解说遮蔽窗有 {nov} 处重叠——"
                  f"已自动合并，但 plan.json 里该段的解说排布不正常（查 blocks 的顺延或镜头长度）",
                  file=sys.stderr)
        spans, cur = [], 0.0
        for s, e in masks:
            if s - cur >= min_span:
                spans.append((cur, s))
            cur = max(cur, e)
        if dur_ - cur >= min_span:
            spans.append((cur, dur_))
        for rs, re_ in spans:                       # 相对秒 → 原片秒
            sa, sb = a + rs, a + re_
            for st, en, cn in cues:
                os_, oe = max(st, sa), min(en, sb)
                if oe - os_ < min_cue:
                    continue
                events.append((start + (os_ - a), start + (oe - a),
                               dlg_wrap(dlg_text(cn), px_limit, size)))
    return sorted(events)


def silences(path):
    r = sh(["ffmpeg", "-hide_banner", "-i", path, "-af",
            "silencedetect=noise=-40dB:d=0.10", "-f", "null", "-"])
    out, s = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start: ([\d.]+)", line)
        if m:
            s = float(m.group(1))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and s is not None:
            out.append((s + float(m.group(1))) / 2)
            s = None
    return out


def parse_name_plates(specs, name_size):
    """解析名牌：'中文名|English|起|止' 或 '中文名|English|起-止'（成片秒）。

    10 分钟压 30 分钟的剧，观众最容易迷路的地方是"现在说话的是谁"。名牌用独立的
    NameTag 样式（左下角、半透明底、不让开字幕），跟解说/对白字幕互不干扰。
    """
    out, bad = [], []
    for sp in specs or []:
        p = [x.strip() for x in sp.split("|")]
        t0 = t1 = None
        if len(p) >= 4 and re.fullmatch(r"[\d.]+", p[-2]) and re.fullmatch(r"[\d.]+", p[-1]):
            t0, t1, p = float(p[-2]), float(p[-1]), p[:-2]
        elif len(p) >= 3 and re.fullmatch(r"[\d.]+-[\d.]+", p[-1]):
            t0, t1 = (float(x) for x in p[-1].split("-"))
            p = p[:-1]
        if not p or t0 is None or t1 <= t0:
            bad.append(f"{sp!r}")
            continue
        cn = p[0]
        en = p[1] if len(p) > 1 else ""
        text = f"{{\\fs{name_size}}}{cn}"
        if en:
            text += f"{{\\fs{max(14, round(name_size * 0.62))}\\c&H9FD0FF&}}\\N{en}"
        out.append((t0, t1, text))
    return out, bad


def write_script_timeline(items, total, nar_dir, path, title="", mode_counts=None):
    """产出交付件「解说词与时间轴.txt」：逐段给出成片时间/源片时间/解说词/原声彩蛋。

    以前这是每个项目里手写的小脚本（S1E1/S1E2/S1E3 各写一遍），现在由 timeline.py
    直接产出——resolved.json 里已经有 narr_mask / orig，不需要二次推导。
    """
    def hm(x):
        return f"{int(x // 60):02d}:{x % 60:04.1f}"

    def text_of(u):
        p = f"{nar_dir}/{u}.txt"
        return open(p, encoding="utf-8").read().strip() if os.path.exists(p) else f"(缺 {p})"

    narr_total = sum(x[2] for it in items for x in it["narr"])
    lines = [(title or "解说词与时间轴"), "=" * 62,
             f"成片总时长 {hm(total)}（{total:.1f} 秒）",
             f"结构：{len(items)} 个片段" +
             (f"（{'/'.join(mode_counts)}）" if mode_counts else "") +
             f"；解说 {narr_total:.1f}s；原声/留白 {total - narr_total:.1f}s", "",
             "【逐段表】成片时间 | 源片时间 | 解说词 | 该段原声彩蛋", "-" * 62]
    for it in items:
        lines.append(f"● {it['name']}  成片 {hm(it['start'])}–{hm(it['start'] + it['dur'])}  "
                     f"源片 {hm(it['a'])}–{hm(it['b'])}"
                     f"（{it['dur']:.1f}s；解说 {sum(x[2] for x in it['narr']):.1f}s）")
        if it["narr"]:
            txt = "".join(text_of(u) for u, _, _ in sorted(it["narr"], key=lambda x: x[1]))
            lines.append(f"  解说：{txt}")
        else:
            lines.append("  解说：（本段无解说）")
        for rs, re_ in it.get("orig", []):
            if re_ - rs >= 1.5:
                lines.append(f"  原声彩蛋：源片 {hm(it['a'] + rs)}–{hm(it['a'] + re_)}"
                             f"（{re_ - rs:.1f}s）")
        lines.append(f"  求解：{it['why']}")
        lines.append("")
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return path


def make_subs(items, nar_dir, audio_dir, ass_path, w, h, font, size, mv,
              bold=0, outline=2.4, shadow=1.2, dlg_cues=(), narlow_last=0, narlow_mv=None,
              px_limit=1230, fade_ms=0, name_plates=(), name_size=None, name_mv=None):
    cues = []
    for it in items:
        for u, gs, d in sorted(it["narr"], key=lambda x: x[1]):
            text = open(f"{nar_dir}/{u}.txt").read().strip()
            lines = wrap_px(text, px_limit, size)
            sil = [x for x in silences(f"{audio_dir}/{u}.wav") if 0.25 < x < d - 0.25]
            tot, cum, bounds, used = sum(len(l) for l in lines), 0, [], set()
            for l in lines[:-1]:
                cum += len(l)
                bounds.append(d * cum / tot)
            for i, bnd in enumerate(bounds):
                best, bd = None, 1.5
                for s in sil:
                    if s not in used and abs(s - bnd) < bd:
                        best, bd = s, abs(s - bnd)
                if best is not None:
                    bounds[i] = best
                    used.add(best)
            prev = 0.0
            for i, l in enumerate(lines):
                end = bounds[i] if i < len(bounds) else d
                st, en = gs + prev, gs + end
                if en - st < 0.5:
                    en = st + 0.5
                cues.append((st, en, l))
                prev = end

    # 片尾几条解说字幕位置放低（ NarLow，MarginV 更小）——避开片尾卡/演职员表。
    # 以前靠一个独立脚本按"文本匹配"去找那几条，这里直接按倒数第 N 条指定。
    styles = ["Nar"] * len(cues)
    if narlow_last:
        for i in range(max(0, len(cues) - narlow_last), len(cues)):
            styles[i] = "NarLow"
    dlg_events = build_dlg_events(items, dlg_cues, size=size, px_limit=px_limit) if dlg_cues else []

    def ts(x):
        return f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}"

    # 淡入淡出：ASS 样式里没有，只能逐条加（字硬闪出来是"廉价感"最大来源之一）
    fad = f"{{\\fad({fade_ms},{fade_ms})}}" if fade_ms else ""
    with open(ass_path, "w") as f:
        f.write(ass_head(w, h, font, size, mv, bold, outline, shadow,
                         dlg=bool(dlg_events), narlow_mv=narlow_mv if narlow_last else None,
                         name_mv=name_mv if name_plates else None, name_size=name_size))
        for (st, en, l), sty in zip(cues, styles):
            f.write(f"Dialogue: 0,{ts(st)},{ts(en)},{sty},,0,0,0,,{fad}{l}\n")
        for st, en, l in dlg_events:
            f.write(f"Dialogue: 0,{ts(st)},{ts(en)},Dlg,,0,0,0,,{fad}{l}\n")
        for st, en, l in name_plates:
            f.write(f"Dialogue: 0,{ts(st)},{ts(en)},NameTag,,0,0,0,,{fad}{l}\n")
    with open(re.sub(r"\.ass$", ".srt", ass_path), "w") as f:
        for i, (st, en, l) in enumerate(cues, 1):
            fmt = lambda x: f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d}," \
                            f"{int(round(x % 1 * 1000)):03d}"
            f.write(f"{i}\n{fmt(st)} --> {fmt(en)}\n{l}\n\n")
    return len(cues) + len(dlg_events) + len(name_plates)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--audio-dir", required=True, help="narration.py 归一后的 wav 目录")
    ap.add_argument("--narration-dir", default="./narration")
    ap.add_argument("--out-dir", default="./out")
    ap.add_argument("--source", help="原片（用于停顿吸附；缺 cuts 时也用它检测切点）")
    ap.add_argument("--cuts", help="镜头切换点文件：每行一个秒数，或 ffmpeg metadata=print 的输出")
    ap.add_argument("--scene", type=float, default=0.35,
                    help="自动检测切点的 scene 阈值（越高切点越少）")
    ap.add_argument("--min-tail", type=float, default=1.5)
    ap.add_argument("--snap-cut", type=float, default=1.55)
    ap.add_argument("--narr-tail", type=float, default=0.30)
    ap.add_argument("--fixed-tail", type=float, default=2.0, metavar="秒",
                    help="fixed 段解说说完后原片再留几秒（默认 2.0；不想压就设 -1）")
    ap.add_argument("--gap", type=float, default=skillcfg.gap_default(),
                    help="解说与原声窗之间的静音间距（秒），默认来自 profile.json；需与 narration_windows 的两侧余量之和一致")
    ap.add_argument("--width", type=int, help="字幕 PlayRes 宽（默认从 --source 自动探测）")
    ap.add_argument("--height", type=int, help="字幕 PlayRes 高（默认从 --source 自动探测）")
    ap.add_argument("--font", default="Noto Sans CJK SC")
    ap.add_argument("--font-size", type=int,
                    help="字号（像素）；默认按画面高 4.5%% 算（1080p ≈ 49，粗体大字可给 58）")
    ap.add_argument("--margin-v", type=int,
                    help="解说字幕距底部像素（默认画面高 10%%）；有原片烧录字幕时往上让（1080p 用 258）")
    ap.add_argument("--margin-h", type=int, default=40, help="字幕左右边距（像素，影响折行宽度）")
    ap.add_argument("--bold", type=int, default=0, help="字幕粗体：1=粗体，0=正常")
    ap.add_argument("--outline", type=float, default=3.0, help="字幕描边宽度（样式 B）")
    ap.add_argument("--shadow", type=float, default=1.0, help="字幕阴影浓度（样式 B：3.0/1.0）")
    ap.add_argument("--dlg-srt", help="原片外挂 SRT（中英双语取中文）；给了就一并生成黄色对白字幕")
    ap.add_argument("--dlg-subs", help="已解析好的台词表（idx\\t起\\t止\\t中文，probe.py --transcribe 产出）")
    ap.add_argument("--dlg-skip", default="", help="对白表里要跳过的 idx，逗号分隔（标题/字幕组信息/水印）")
    ap.add_argument("--narlow-last", type=int, default=0, help="把倒数第 N 条解说字幕改用 NarLow 样式")
    ap.add_argument("--narlow-marginv", type=int, help="NarLow 距底部像素（默认画面高 2.4%%）")
    ap.add_argument("--doc-title", default="", help="交付件「解说词与时间轴.txt」的标题")
    ap.add_argument("--fade-ms", type=int, default=140,
                    help="每条字幕的淡入淡出毫秒（0=硬切）")
    ap.add_argument("--name-plate", action="append", default=[],
                    help="名牌：'中文名|English|起|止'（成片秒），可多次；放在左下角")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="允许用没进 manifest/没通过校验的解说音频（默认拒绝：避免半成品进片）")
    ap.add_argument("--track", action="store_true", help="同时生成解说音轨")
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    # 分辨率/字号/边距：能从原片探测的就别用案例里写死的值
    det = probe_size(a.source) if a.source else None
    if det and (a.width, a.height) != det:
        if a.width or a.height:
            print(f"⚠ --width/--height 与视频实际尺寸 {det[0]}x{det[1]} 不一致（字幕按 PlayRes 缩放）",
                  file=sys.stderr)
        a.width, a.height = det
    a.width = a.width or 1426
    a.height = a.height or 1080
    size = a.font_size or max(16, round(a.height * 0.045))
    mv = a.margin_v if a.margin_v is not None else max(10, round(a.height * 0.10))
    if mv > a.height * 0.4:
        print(f"⚠ --margin-v {mv} 超过画面高 40%，字幕会跑到画面中部", file=sys.stderr)
    narlow_mv = a.narlow_marginv if a.narlow_marginv is not None else max(8, round(a.height * 0.024))
    name_size = max(14, round(size * 0.82))
    name_mv = mv + round(size * 1.35)
    plates, bad_plates = parse_name_plates(a.name_plate, name_size)
    for bp in bad_plates:
        print(f"⚠ --name-plate {bp} 解析不了（要 '中文名|English|起|止'），已跳过", file=sys.stderr)
    px_limit = max(4 * size, a.width - 2 * a.margin_h - 8)
    cfg = json.load(open(a.plan))
    cuts_path = a.cuts or f"{a.out_dir}/cuts.txt"
    if os.path.exists(cuts_path):
        cuts = load_cuts(cuts_path)
        if len(cuts) < 2:
            print(f"⚠ {cuts_path} 里只有 {len(cuts)} 个切点，镜头吸附会退化"
                  f"（删掉它并给 --source 可自动检测）", file=sys.stderr)
    elif a.source:
        cuts = detect_cuts(a.source, cuts_path, a.scene)
    else:
        cuts = []
    units = Units(a.audio_dir, a.allow_unverified)
    items, total = build_plan(cfg, cuts, a.source, a.audio_dir, a.min_tail, a.snap_cut,
                              a.narr_tail, a.gap, udur=units.dur,
                              fixed_tail=None if a.fixed_tail is not None and a.fixed_tail < 0
                              else a.fixed_tail)
    if units.problems:
        for p in dict.fromkeys(units.problems):
            print(f"✗ {p}", file=sys.stderr)
        if not a.allow_unverified:
            sys.exit(f"共 {len(set(units.problems))} 项解说音频不可信：先跑 narration.py 补齐，"
                     f"确认要带着问题出片再加 --allow-unverified")
    json.dump(dict(items=items, total=total, cuts=cuts), open(f"{a.out_dir}/resolved.json", "w"),
              ensure_ascii=False, indent=1)
    dlg_cues = []
    skip = {int(x) for x in a.dlg_skip.split(",") if x.strip()}
    for src_path, reader, tag in ((a.dlg_srt, read_dlg_srt, "SRT"),
                                  (a.dlg_subs, read_dlg_cues, "TSV")):
        if not src_path:
            continue
        dlg_cues += reader(src_path, skip)
        print(f"对白字幕候选（{tag}）{len(dlg_cues)} 条（跳过 idx {sorted(skip)}）", file=sys.stderr)
    ncue = make_subs(items, a.narration_dir, a.audio_dir, f"{a.out_dir}/narration.ass",
                     a.width, a.height, a.font, size, mv,
                     bold=a.bold, outline=a.outline, shadow=a.shadow,
                     dlg_cues=dlg_cues, narlow_last=a.narlow_last, narlow_mv=narlow_mv,
                     px_limit=px_limit, fade_ms=max(0, a.fade_ms), name_plates=plates,
                     name_size=name_size, name_mv=name_mv)
    if a.track:
        build_track(items, total, a.audio_dir, f"{a.out_dir}/narration.wav")
    modes = []
    for k in ("fixed", "punch", "blocks"):
        c = sum(1 for it in cfg["items"] if k in it)
        if c:
            modes.append(f"{c} {k}")
    write_script_timeline(items, total, a.narration_dir, f"{a.out_dir}/解说词与时间轴.txt",
                          title=a.doc_title, mode_counts=modes)

    narr_total = sum(x[2] for it in items for x in it["narr"])
    rows = ["片段\t源片段\t成片位置\t求解方式\t末点后镜头\t解说\t原声"]
    for it in items:
        prev = max([c for c in cuts if c <= it["b"] + 0.001], default=0)
        rows.append(f"{it['name']}\t{it['a']:.2f}-{it['b']:.2f}\t"
                    f"{int(it['start']//60):02d}:{it['start']%60:05.2f}-"
                    f"{int((it['start']+it['dur'])//60):02d}:{(it['start']+it['dur'])%60:05.2f}\t"
                    f"{it['why']}\t{it['b']-prev:.1f}s\t{sum(x[2] for x in it['narr']):.1f}s\t"
                    f"{it['dur']-sum(x[2] for x in it['narr']):.1f}s")
    open(f"{a.out_dir}/selfcheck.txt", "w").write("\n".join(rows) + "\n")
    print(f"总时长 {total:.2f}s = {int(total//60)}:{total%60:05.2f}；解说 {narr_total:.1f}s；"
          f"原声/留白 {total-narr_total:.1f}s；字幕 {ncue} 条；PlayRes {a.width}x{a.height}、"
          f"字号 {size}、MarginV {mv}")
    for it in items:
        print(f"  {it['name']:6s} 源{it['a']:8.2f}-{it['b']:8.2f} ({it['dur']:6.2f}s) "
              f"成片{it['start']:7.2f}  {it['why']}")
    print(f"→ {a.out_dir}/resolved.json, narration.ass, narration.srt, selfcheck.txt, 解说词与时间轴.txt"
          + (", narration.wav" if a.track else ""))


if __name__ == "__main__":
    main()
