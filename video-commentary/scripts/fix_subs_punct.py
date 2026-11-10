#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字幕标点归位外科：把落在行首的标点（，。、；：！？）”等）回移到上一行行尾，
孤立标点行并入上一行并删除；行内 `\\N` 后的行首标点也挪回上一行。只改文本、不动时间轴。

用法:
  python3 fix_subs_punct.py out/narration.ass
  python3 fix_subs_punct.py out/narration.ass --manual manual.json
  # manual.json: {"《是，": "《是，大臣》", "下午，": null}
  #   键 = 手术前该行的文本（按内容匹配，不是行号！），值 = 新文本；null = 删除该行。

两条边界
--------
1. **只动白字幕**（Nar / NarLow）。ASS 里黄色对白字幕（Dlg）排在全白字幕之后，
   旧版不区分样式，会把 Dlg 行首的标点搬到"上一条 Dialogue"——也就是最后一条白字幕
   的尾巴上（实测复现）。黄字幕本来就不该被这个脚本碰。
2. 回移只在**同一样式**内进行；跨样式（Nar ↔ NarLow）宁可不搬，也不搬错位置。

为什么 manual 的键用文本而不是行号
----------------------------------
timeline.py 每跑一次，解说字幕的切分行数就可能变（文本改了、字号改了、某段停顿结构
变了导致吸附点移位）。用行号的话，manual 会静默指向另一行——改错的字幕看起来完全正常，
只有看片子的时候才发现。按文本匹配则要么命中、要么明确告警"没找到"，不会悄悄改错。

匹配规则：键等于该行去空格后的完整文本；找不到就再按"以此文本开头"试一次；
两者都不中就在结尾列出未命中项（不报错，因为可能是上游确实变了）。
"""
import argparse
import json
import re
import sys

MOVE = '，。、；：！？）》」』】”'


def parse(ln):
    parts = ln.split(",", 9)
    return parts, re.sub(r"\{[^}]*\}", "", parts[9]).strip()


def style_of(ln):
    return ln.split(",", 9)[3].strip() if ln.startswith("Dialogue:") else ""


def is_nar(style):
    return style.startswith("Nar")          # Nar / NarLow 都是白字幕


def main():
    ap = argparse.ArgumentParser(description="字幕行首标点归位（只动白字幕、不动时间轴）")
    ap.add_argument("ass", help="narration.ass（原地修改）")
    ap.add_argument("--manual", help="按文本匹配的特例：{\"《是，\": \"《是，大臣》\", \"下午，\": null}")
    a = ap.parse_args()
    ass = a.ass
    manual = json.load(open(a.manual, encoding="utf-8")) if a.manual else {}

    lines = open(ass, encoding="utf-8").read().splitlines()
    idx = [i for i, ln in enumerate(lines) if is_nar(style_of(ln))]
    if not idx:
        print(f"⚠ {ass} 里没有 Nar/NarLow 字幕行，什么都没做", file=sys.stderr)
        sys.exit(0)

    # ---------- 第一遍：行内 `\N` 后的行首标点挪回上一行 ----------
    inline = 0
    for li in idx:
        parts, _ = parse(lines[li])
        new = re.sub(r"\\N([" + re.escape(MOVE) + r"]+)", r"\1\\N", parts[9])
        if new != parts[9]:
            parts[9] = new
            lines[li] = ",".join(parts)
            inline += 1

    # ---------- 第二遍：manual 特例（按文本匹配，只认白字幕行） ----------
    newtxt, drop, missed = {}, set(), []
    for key, val in manual.items():
        key = key.strip()
        hit = None
        for li in idx:                                  # 先试完整相等
            _, t = parse(lines[li])
            if t == key:
                hit = li
                break
        if hit is None:                                 # 再试"以此开头"
            for li in idx:
                _, t = parse(lines[li])
                if t and t.startswith(key):
                    hit = li
                    break
        if hit is None:
            missed.append(key)
            continue
        if val is None:
            drop.add(hit)
        else:
            parts, _ = parse(lines[hit])
            parts[9] = val
            lines[hit] = ",".join(parts)
            newtxt[hit] = val

    # ---------- 第三遍：通用回移（限同一样式内） ----------
    moved, cross = 0, 0
    for pos, li in enumerate(idx):
        if li in drop:
            continue
        parts, txt = parse(lines[li])
        if not txt or txt[0] not in MOVE:
            continue
        prev_li = None
        for pli in idx[max(0, pos - 1)::-1]:
            if pli not in drop:
                prev_li = pli
                break
        if prev_li is None:
            continue
        if style_of(lines[prev_li]) != style_of(lines[li]):
            cross += 1
            continue
        ch = txt[0]
        p = lines[prev_li].split(",", 9)
        p[9] = p[9].rstrip() + ch
        lines[prev_li] = ",".join(p)
        moved += 1
        rest = txt[1:]
        if rest:
            parts[9] = rest
            lines[li] = ",".join(parts)
        else:
            drop.add(li)

    out = [ln for i, ln in enumerate(lines) if i not in drop]
    open(ass, "w").write("\n".join(out) + "\n")
    print(f"行内标点回移 {inline} 处；manual 命中 {len(manual) - len(missed)}/{len(manual)}；"
          f"跨行回移 {moved} 处；删除孤立行 {len(drop)} 行；剩余白字幕 "
          f"{len([i for i in idx if i not in drop])} 条")
    if cross:
        print(f"  （{cross} 处行首标点因前后样式不同而保留原样）")
    if missed:
        print("⚠ manual 未命中（上游字幕可能变了，请核对）:")
        for k in missed:
            print(f"    {k!r}")

    # ---------- 复查 ----------
    bad = 0
    for ln in out:
        if not is_nar(style_of(ln)):
            continue                                    # 黄字幕不归本脚本管
        _, t = parse(ln)
        if t and (t[0] in MOVE or all(c in MOVE for c in t)):
            print("残留:", t[:40])
            bad += 1
    print(f"剩余疑似问题 {bad} 处")
    sys.exit(2 if missed else 0)


if __name__ == "__main__":
    main()
