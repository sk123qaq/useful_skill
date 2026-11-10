#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写稿后、配音前的文本体检：把只有配音之后才会暴露的问题提前报出来。

用法:
  python3 scripts/lint_narration.py --dir narration            # 报告；只有 ERROR 才退出 1
  python3 scripts/lint_narration.py --dir narration --strict   # WARN 也退出 1

检查项与阈值（依据第六集 38 段实测，见 references/pipeline-notes.md）：
  ERROR  空段、字数少于 4
  WARN   过短（<24 单位）：拉伸风险。第六集里 16–18 单位的段 atempo 偏到 0.83 / 1.13
  WARN   子句过长（无逗号/句号的一段 >=22 单位，约 4.1 秒）：TTS 易连成一口气，
         第六集 21 单位以内的子句都没有超过 4 秒，超过的段要靠插停顿兜底
  INFO   子句接近上限（18–21）、单句较长（>=60）、大数字（万/亿）：只提示，不影响配音

字数口径与 narration.py units() 一致：汉字 + 字母 + 数字。
"""
import argparse
import json
import os
import re
import sys

CLAUSE_PUN = "，、；：。！？,;:.!?"
SENT_END = "。！？!?"
BIG_NUM = re.compile(r"(?:\d+(?:\.\d+)?|[零〇一二三四五六七八九十百千两]+)[万亿]")
RATE = 5.35          # 与 narration.py --target-artic 默认值一致，只用来换算秒数


def units(t):
    return len(re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]", t))


def longest(text, pat):
    segs = [s for s in re.split(pat, text) if s.strip()]
    return max((units(s) for s in segs), default=0)


def check(name, text):
    out = []
    n = units(text)
    if n == 0:
        out.append(("ERROR", "空段"))
        return n, 0, 0, out
    if n < 4:
        out.append(("ERROR", f"字数只有 {n}，确认不是漏写"))
    if n < 24:
        out.append(("WARN", f"过短（{n}<24）：拉伸风险，与相邻段合并或扩写到 24 单位以上"))
    mc = longest(text, "[" + re.escape(CLAUSE_PUN) + "]")
    ms = longest(text, "[" + re.escape(SENT_END) + "]")
    if mc >= 22:
        out.append(("WARN", f"子句 {mc} 单位（约 {mc / RATE:.1f} 秒）无停顿标点，可能超过 4 秒连续发声："
                            "在合适处加逗号，或拆成句号"))
    elif mc >= 18:
        out.append(("INFO", f"子句 {mc} 单位，接近 22 的上限"))
    if ms >= 60:
        out.append(("INFO", f"单句 {ms} 单位较长：读起来吃力时用句号拆开（配音本身不会因此失败）"))
    bigs = BIG_NUM.findall(text)
    if bigs:
        out.append(("INFO", f"大数字 {'、'.join(sorted(set(bigs)))}：canon 已双向归一，ASR 写成阿拉伯数字也能匹配"))
    return n, mc, ms, out


def main():
    ap = argparse.ArgumentParser(description="解说词文本体检（配音前）")
    ap.add_argument("--dir", default="./narration", help="解说词目录（每段一个 .txt）")
    ap.add_argument("--strict", action="store_true", help="WARN 也算失败（退出码 1）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args()
    if not os.path.isdir(a.dir):
        sys.exit(f"找不到目录 {a.dir}")
    rows, counts = [], {"ERROR": 0, "WARN": 0, "INFO": 0}
    for f in sorted(os.listdir(a.dir)):
        if not f.endswith(".txt"):
            continue
        text = open(os.path.join(a.dir, f), encoding="utf-8").read().strip()
        n, mc, ms, issues = check(f[:-4], text)
        for lvl, msg in issues:
            counts[lvl] += 1
        rows.append(dict(name=f[:-4], units=n, max_clause=mc, max_sentence=ms,
                         issues=[dict(level=l, msg=m) for l, m in issues]))
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        print(f"{'段名':8s}{'单位':>5s}{'子句':>5s}{'单句':>5s}  等级  说明")
        for r in rows:
            if not r["issues"]:
                continue
            for i, iss in enumerate(r["issues"]):
                head = (f"{r['name']:8s}{r['units']:5d}{r['max_clause']:5d}{r['max_sentence']:5d}"
                        if i == 0 else " " * 24)
                print(f"{head}  {iss['level']:5s} {iss['msg']}")
        clean = sum(1 for r in rows if not r["issues"])
        print(f"→ {len(rows)} 段：无问题 {clean} 段；ERROR {counts['ERROR']}、WARN {counts['WARN']}、"
              f"INFO {counts['INFO']}")
    if counts["ERROR"] or (a.strict and counts["WARN"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
