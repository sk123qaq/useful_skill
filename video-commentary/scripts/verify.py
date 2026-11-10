#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""成片自检：把"核对矩阵"里能自动化的部分一次跑完（交付前必须全绿）。

用法:
  python3 scripts/verify.py --film 成片.mp4 --plan out/resolved.json --ass out/narration.ass \
      --source 原片.mp4 --dlg-srt 原片.srt --out-dir out

查什么:
  1. 成片时长 = resolved 计划
  2. 整片可解码（ffmpeg -f null -）
  3. selfcheck.txt 里没有「末点后镜头 < min-tail」
  4. 解说段 vs 原声段电平差（<1.5dB 才安全；差多少、往哪调一起告诉你）
  5. 原声窗 ∩ 解说字幕 必须为空（白字幕不该盖在放原声的地方）
  6. 原声窗里黄色对白字幕的覆盖率（听不懂英语的观众靠它）
  7. ASS PlayRes = 视频尺寸
  8. 峰值有没有顶到 0dBFS（AAC 会削）
  9. 抽 5 帧拼一张图（标题条/字幕位置/水印，给人眼最后确认）

退出码：0 = 全绿（允许警告），1 = 有硬失败。
"""
import argparse
import json
import os
import re
import subprocess
import sys


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def dur(p):
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p])
    return float(r.stdout.strip() or 0)


def probe_size(src):
    r = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height", "-of", "csv=p=0:s=x", src])
    m = re.match(r"\s*(\d+)\s*[x,]\s*(\d+)", r.stdout or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def mean_volume(film, start, length):
    """SS 后取一段量 RMS（volumedetect 的 mean_volume 其实是 RMS）。"""
    r = sh(["ffmpeg", "-hide_banner", "-v", "info", "-ss", f"{max(0.0, start):.3f}",
            "-t", f"{length:.3f}", "-i", film, "-vn", "-af", "volumedetect", "-f", "null", "-"])
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    x = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    return (float(m.group(1)) if m else None, float(x.group(1)) if x else None)


def ts2s(t):
    t = t.strip().replace(",", ".")
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_ass(path):
    ev = []
    if not path or not os.path.exists(path):
        return ev, None
    head = open(path, encoding="utf-8", errors="replace").read(4000)
    w = re.search(r"PlayResX:\s*(\d+)", head)
    h = re.search(r"PlayResY:\s*(\d+)", head)
    for ln in open(path, encoding="utf-8", errors="replace"):
        if not ln.startswith("Dialogue:"):
            continue
        p = ln.split(",", 9)
        try:
            ev.append((ts2s(p[1]), ts2s(p[2]), p[3].strip(),
                       re.sub(r"\{[^}]*\}", "", p[9]).strip()))
        except Exception:
            continue
    return ev, ((int(w.group(1)), int(h.group(1))) if w and h else None)


def overlap(a1, a2, b1, b2):
    return max(0.0, min(a2, b2) - max(a1, b1))


def census_windows(items, key, span_cap=8.0, min_span=1.2):
    """每段取一个中段窗（该段最长的那个窗，最多 span_cap 秒）——**全片普查**。

    与 pick_windows 的区别：不做"只取时长最长的 N 段"的抽样。
    动机（实测）：原片逐场电平能差 7 dB（本例 −18.0 ~ −25.5），抽 4 个窗的均值
    噪声可达 ±2.5 dB —— 一个混得很平的成片（全片普查 +0.06dB）会被
    误报成"解说比原声响 2.4dB"，照它调反而把真实平衡推向另一侧。
    两个类别的样本数、样本段应尽量一致，否则差值里混进了选段偏差。
    """
    out = []
    for it in sorted(items, key=lambda x: x["start"]):
        spans = [s for s in it.get(key, []) if s[1] - s[0] >= min_span]
        if not spans:
            continue
        s, e = max(spans, key=lambda x: x[1] - x[0])
        ln = min(span_cap, e - s)
        out.append((it["start"] + (s + e) / 2 - ln / 2, ln, it["name"]))
    return out


def pick_windows(items, key, span_cap=8.0, samples=4, min_span=1.2):
    """从 resolved.items 里挑若干个"中段窗口"（成片绝对时间）：key='orig' 或 'narr_mask'。"""
    out = []
    for it in sorted(items, key=lambda x: -x["dur"]):
        spans = [s for s in it.get(key, []) if s[1] - s[0] >= min_span]
        if not spans:
            continue
        s, e = max(spans, key=lambda x: x[1] - x[0])
        mid = (s + e) / 2
        ln = min(span_cap, e - s)
        out.append((it["start"] + mid - ln / 2, ln, it["name"]))
        if len(out) >= samples:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--film", required=True)
    ap.add_argument("--plan", required=True, help="resolved.json")
    ap.add_argument("--ass", help="narration.ass（查字幕位置/覆盖）")
    ap.add_argument("--source", help="原片（比对分辨率）")
    ap.add_argument("--dlg-srt", help="原片外挂 SRT（查原声窗的对白覆盖率）")
    ap.add_argument("--dlg-skip", default="",
                    help="对白表里要跳过的 idx（标题/水印），逗号分隔；与 timeline.py 同名同义。"
                         "不传也安全：read_dlg_srt 会自行丢弃字幕组信息/水印行")
    ap.add_argument("--out-dir", default="./out")
    ap.add_argument("--min-tail", type=float, default=1.5)
    ap.add_argument("--max-db-diff", type=float, default=1.5, help="解说段/原声段电平差上限")
    ap.add_argument("--frames", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    plan = json.load(open(a.plan, encoding="utf-8"))
    items, total = plan["items"], plan["total"]
    res, hard, soft = [], [], []

    def add(name, ok, detail, level="hard"):
        res.append((name, "PASS" if ok else ("FAIL" if level == "hard" else "WARN"), detail))
        if not ok:
            (hard if level == "hard" else soft).append(f"{name}: {detail}")

    # 1 时长
    got = dur(a.film)
    add("时长", abs(got - total) <= 0.5, f"成片 {got:.2f}s / 计划 {total:.2f}s")
    # 2 可解码
    r = sh(["ffmpeg", "-v", "error", "-i", a.film, "-f", "null", "-"])
    add("可解码", not r.stderr.strip(), (r.stderr.strip().splitlines() or [""])[0][:120] or "无告警")
    # 3 selfcheck
    sc = os.path.join(a.out_dir, "selfcheck.txt")
    if os.path.exists(sc):
        bad = []
        for ln in open(sc, encoding="utf-8").read().splitlines()[1:]:
            c = ln.split("\t")
            if len(c) >= 5 and c[4].endswith("s"):
                try:
                    if float(c[4][:-1]) < a.min_tail - 0.05:
                        bad.append(f"{c[0]} 末点后 {c[4]}")
                except ValueError:
                    pass
        add("末镜时长", not bad, "；".join(bad[:3]) if bad else f"所有片段末点后镜头 ≥{a.min_tail}s")
    else:
        add("末镜时长", False, f"缺 {sc}（跑过 timeline.py 才有）", level="soft")
    # 4 电平（解说段 vs 原声段）——全片普查，不用 4 段抽样（见 census_windows 注释）
    ow = census_windows(items, "orig")
    nw = census_windows(items, "narr_mask")
    if ow and nw:
        om = [(mean_volume(a.film, s, d)[0], n) for s, d, n in ow]
        nm = [(mean_volume(a.film, s, d)[0], n) for s, d, n in nw]
        om = [x for x in om if x[0] is not None]
        nm = [x for x in nm if x[0] is not None]
        if om and nm:
            oa = sum(x[0] for x in om) / len(om)
            na = sum(x[0] for x in nm) / len(nm)
            diff = na - oa
            sp = lambda v: f"{min(x[0] for x in v):.1f}~{max(x[0] for x in v):.1f}"
            detail = (f"解说 {na:.1f}dB（{len(nm)} 窗，{sp(nm)}）/ 原声 {oa:.1f}dB"
                      f"（{len(om)} 窗，{sp(om)}）；差 {diff:+.1f}dB")
            add("响度平衡", abs(diff) <= a.max_db_diff, detail,
                level="hard" if abs(diff) > 3 else "soft")
            if abs(diff) > a.max_db_diff:
                adj = ("原声太轻：render.py --volume-orig +%.1fdB（或 --volume-narr %.1fdB）"
                       % (diff, -diff)) if diff > 0 else \
                      ("原声太响：render.py --volume-orig %.1fdB" % diff)
                soft.append("响度调整建议：" + adj)
    else:
        add("响度平衡", False, "resolved.json 里没有 orig/narr_mask 窗口（旧版产物？）", level="soft")
    # 5/6 字幕
    ev, playres = parse_ass(a.ass)
    if ev:
        nar_ev = [x for x in ev if x[2].startswith("Nar")]
        dlg_ev = [x for x in ev if x[2].startswith("Dlg")]
        hits = []
        for it in items:
            for s, e in it.get("orig", []):
                sa, sb = it["start"] + s, it["start"] + e
                ov = sum(overlap(sa, sb, x[0], x[1]) for x in nar_ev)
                if ov > 0.15:
                    hits.append(f"{it['name']} 原声窗 {sa:.1f}-{sb:.1f}s 被白字幕盖 {ov:.2f}s")
        add("字幕不压原声窗", not hits, "；".join(hits[:3]) if hits else
            f"{len(nar_ev)} 条白字幕、{len(dlg_ev)} 条黄字幕，均未压原声窗")
        if a.dlg_srt and os.path.exists(a.dlg_srt):
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import timeline as T                                       # noqa: N813
            cues = T.read_dlg_srt(a.dlg_srt,
                                  {int(x) for x in a.dlg_skip.split(",") if x.strip()})
            miss = []
            for it in items:
                # SRT 台词是源片时间，原声窗是成片时间——必须先按该片段的
                # 源 a ↔ 成片 start 平移再比（旧版直接比，跨段越远错得越多，
                # 末段窗口甚至被错报 49% 覆盖，其实黄字幕一条不缺）。
                off = it["start"] - it["a"]
                for s, e in it.get("orig", []):
                    sa, sb = it["start"] + s, it["start"] + e
                    if sb - sa < 1.0:
                        continue
                    ins = [(c[0] + off, c[1] + off) for c in cues
                           if overlap(c[0] + off, c[1] + off, sa, sb) > 0.3]
                    if not ins:
                        continue
                    need = sum(overlap(c[0], c[1], sa, sb) for c in ins)
                    covd = sum(overlap(max(c[0], sa), min(c[1], sb), max(x[0], sa), min(x[1], sb))
                               for c in ins for x in dlg_ev)
                    if need > 0 and covd / need < 0.5:
                        miss.append(f"{it['name']} {sa:.1f}-{sb:.1f}s 覆盖 {covd / need:.0%}")
            add("原声窗对白覆盖", not miss, "；".join(miss[:3]) if miss else "每个原声窗都有中文对白")
        if playres:
            if a.source:
                sz = probe_size(a.source)
                add("ASS PlayRes", sz is None or playres == sz,
                    f"ASS {playres[0]}x{playres[1]}" +
                    (f" / 视频 {sz[0]}x{sz[1]}" if sz else "（没读到原片尺寸）"))
    else:
        add("字幕检查", False, "没有给 --ass 或文件里没有 Dialogue", level="soft")
    # 7 峰值
    _, mx = mean_volume(a.film, 0, dur(a.film))
    add("峰值余量", mx is None or mx < -0.2, f"全片最大 {mx}dB（接近 0 说明 AAC 会削）", level="soft")
    # 8 抽帧
    stamps = [0.5]
    for w in (nw[:1] + ow[:2]):
        stamps.append(w[0] + w[1] / 2)
    stamps.append(max(0.0, total - 1.5))
    stamps = sorted({round(x, 2) for x in stamps})[:a.frames]
    fdir = os.path.join(a.out_dir, "verify_frames")
    os.makedirs(fdir, exist_ok=True)
    pngs = []
    for t in stamps:
        p = os.path.join(fdir, f"f_{t:08.2f}.png")
        sh(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", a.film, "-frames:v", "1", p])
        if os.path.exists(p):
            pngs.append(p)
    if pngs:
        sheet = os.path.join(fdir, "拼图.jpg")
        # 用 tile 拼网格：xstack 的 layout 行高写死会和 scale 后的实际高度不符
        # （既有行间重叠，未覆盖区在 ffmpeg 8.x 还会填成绿色，看着像成片里有绿帧）
        sh(["ffmpeg", "-v", "error", "-y"] + sum([["-i", p] for p in pngs], []) +
           ["-filter_complex", "".join(f"[{i}:v]scale=480:-1[v{i}];" for i in range(len(pngs))) +
            "".join(f"[v{i}]" for i in range(len(pngs))) +
            f"concat=n={len(pngs)}:v=1:a=0[cat];[cat]tile=3x2[out]",
            "-map", "[out]", "-frames:v", "1", sheet])
        add("抽帧", True, f"{len(pngs)} 帧 → {sheet if os.path.exists(sheet) else fdir}")
    else:
        add("抽帧", False, "一帧都没抽出来", level="soft")

    if a.json:
        print(json.dumps(dict(checks=[dict(name=n, status=s, detail=d) for n, s, d in res],
                              hard=hard, soft=soft), ensure_ascii=False, indent=1))
        return 1 if hard else 0
    print(f"成片自检：{a.film}\n" + "-" * 78)
    for n, s, d in res:
        mark = {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}[s]
        print(f"{mark} {n:14s} {d}")
    print("-" * 78)
    print(f"{sum(1 for _, s, _ in res if s == 'PASS')} 通过 / {len(soft)} 警告 / {len(hard)} 失败")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
