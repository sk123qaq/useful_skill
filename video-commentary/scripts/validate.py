#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plan.json 校验器：在渲染之前把"计划写错"这类问题一次报全。

用法:
  python3 scripts/validate.py --plan plan.json --narration-dir narration --audio-dir norm
  python3 scripts/validate.py --plan plan.json --stage plan          # 只查结构（配音前就能跑）
  python3 scripts/validate.py --plan plan.json --audio-dir norm --source 原片.mp4 --cuts out/cuts.txt
  python3 scripts/validate.py ... --json                             # 机器可读

为什么需要它：文档里的事故清单大半是 plan 写错——彩蛋窗被顺延、blocks 游标推进到起点、
解说窗压在原声窗上、unit 名字打错、片段比解说短。这些在 resolved.json 里看不出来，
只有抽帧或看片子才发现。这里把能断言的都断言掉。

它复用 timeline.py 的 build_plan，所以校验的就是真实剪辑（不会出现"校验通过但排出来两样"）。
退出码：0 = 只读警告，1 = 有必须修的问题。
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import timeline as T                                                  # noqa: E402
import skillcfg                                                     # noqa: E402


def check_structure(cfg, problems, warnings):
    if not isinstance(cfg, dict) or "items" not in cfg:
        problems.append("顶层必须是 {\"items\": [...]}")
        return []
    items = cfg["items"]
    if not isinstance(items, list) or not items:
        problems.append("items 是空的")
        return []
    seen = {}
    for i, it in enumerate(items):
        tag = f"items[{i}]"
        if not isinstance(it, dict):
            problems.append(f"{tag} 不是对象")
            continue
        name = it.get("name")
        if not name:
            problems.append(f"{tag} 缺 name")
            name = tag
        elif name in seen:
            problems.append(f"{tag} 的 name 「{name}」和第 {seen[name]} 个片段重名（成片/自检表会串）")
        else:
            seen[name] = i
        modes = [k for k in ("fixed", "punch", "blocks") if k in it]
        if len(modes) != 1:
            problems.append(f"{name}: 三种模式必须恰好有一种，现在有 {modes or '零种'}"
                            f"（fixed=固定片段 / punch=彩蛋反推 / blocks=解说原声交替）")
            continue
        m = modes[0]
        if m == "fixed":
            a, b = it["fixed"] if len(it["fixed"]) == 2 else (None, None)
            if a is None:
                problems.append(f"{name}: fixed 必须是 [起, 止] 两个数")
            elif not (b > a):
                problems.append(f"{name}: fixed 的止 {b} 不大于起 {a}")
        elif m == "punch":
            ps, pe = it["punch"] if len(it["punch"]) == 2 else (None, None)
            if ps is None:
                problems.append(f"{name}: punch 必须是 [句起, 句止] 两个数")
            elif not (pe > ps):
                problems.append(f"{name}: punch 的句止 {pe} 不大于句起 {ps}")
            elif pe - ps < 0.6:
                problems.append(f"{name}: 彩蛋窗只有 {pe - ps:.2f}s（<0.6s）——"
                                f"要么这句话被切了，要么这不是一句台词")
            if it.get("lead"):
                warnings.append(f"{name}: lead={it['lead']} 会在片段开头留白，确认是有意的")
        else:
            a, b = it.get("a"), it.get("b")
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                problems.append(f"{name}: blocks 模式需要在条目上直接给 a / b（原片秒）")
            elif not (b > a):
                problems.append(f"{name}: blocks 的 b {b} 不大于 a {a}")
            blks = it.get("blocks")
            if not isinstance(blks, list) or not blks:
                problems.append(f"{name}: blocks 不能为空")
                continue
            for j, blk in enumerate(blks):
                if not isinstance(blk, list) or not blk or blk[0] not in ("narr", "orig"):
                    problems.append(f"{name}.blocks[{j}] 必须是 [\"narr\", 段名] 或 [\"orig\", 起, 止]")
                    continue
                if blk[0] == "narr":
                    if len(blk) != 2:
                        problems.append(f"{name}.blocks[{j}]: narr 只接一个段名")
                else:
                    if len(blk) != 3:
                        problems.append(f"{name}.blocks[{j}]: orig 需要 [\"orig\", 起, 止]")
                    elif not isinstance(a, (int, float)) or not (blk[1] < blk[2]):
                        problems.append(f"{name}.blocks[{j}]: orig 的止 {blk[2]} 不大于起 {blk[1]}")
                    elif isinstance(a, (int, float)) and not (a <= blk[1] < blk[2] <= b):
                        problems.append(f"{name}.blocks[{j}]: 原声窗 {blk[1]}-{blk[2]} 不在片段 "
                                        f"{a}-{b} 内")
            if not any(blk[0] == "orig" for blk in blks if isinstance(blk, list) and blk):
                warnings.append(f"{name}: blocks 里一个 orig 都没有，等价于一段纯解说（那就用 "
                                f"fixed/units 更简单）")
        unknown = set(it) - {"name", "units", "fixed", "punch", "blocks", "a", "b", "lead", "cps"}
        if unknown:
            warnings.append(f"{name}: 有没用的字段 {sorted(unknown)}（拼错了？）")
    return items


def collect_units(items):
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        for u in it.get("units", []) or []:
            out.append((it.get("name", "?"), u))
        for blk in it.get("blocks", []) or []:
            if isinstance(blk, list) and blk and blk[0] == "narr":
                out.append((it.get("name", "?"), blk[1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--narration-dir", default="./narration", help="解说词目录（<段名>.txt）")
    ap.add_argument("--audio-dir", help="narration.py 归一后的 wav 目录（有 manifest 更好）")
    ap.add_argument("--source", help="原片（用于停顿吸附/切点检测，校验结果与剪辑一致）")
    ap.add_argument("--cuts", help="镜头切点文件；给了就一并校验「末镜 ≥ min-tail」")
    ap.add_argument("--min-tail", type=float, default=1.5)
    ap.add_argument("--snap-cut", type=float, default=1.55)
    ap.add_argument("--narr-tail", type=float, default=0.30)
    ap.add_argument("--gap", type=float, default=skillcfg.gap_default(),
                    help="与 timeline.py 一致，默认来自 profile.json")
    ap.add_argument("--fixed-tail", type=float, default=2.0,
                    help="fixed 段解说后原片再留几秒（与 timeline.py 一致）")
    ap.add_argument("--target-min", type=float, default=7.0, help="目标片长下限（分钟）")
    ap.add_argument("--target-max", type=float, default=13.0, help="目标片长上限（分钟）")
    ap.add_argument("--stage", choices=["auto", "plan", "cut"], default="auto",
                    help="plan=只查结构（配音前就能跑）；cut=连剪辑排布一起查（默认 auto）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    problems, warnings = [], []
    cfg = json.load(open(a.plan, encoding="utf-8"))
    items = check_structure(cfg, problems, warnings)
    units = collect_units(items)
    if not items:
        return report(a, problems, warnings, None)

    # ---------- 段名 / 文本 / 音频 ----------
    for owner, u in units:
        tp = f"{a.narration_dir}/{u}.txt"
        if not os.path.exists(tp):
            problems.append(f"{owner}: 找不到解说词 {tp}")
        elif not open(tp, encoding="utf-8").read().strip():
            problems.append(f"{owner}: {tp} 是空的")
    used = [u for _, u in units]
    dup = sorted({u for u in used if used.count(u) > 1})
    if dup:
        warnings.append(f"同一个解说段被用了多次：{dup}（原声/画面变了但台词一样，是有意的吗？）")
    orphan = sorted(f[:-4] for f in os.listdir(a.narration_dir)
                    if f.endswith(".txt") and f[:-4] not in used) if os.path.isdir(a.narration_dir) else []
    if orphan:
        warnings.append(f"{len(orphan)} 段解说词没被任何片段引用：{orphan[:8]}"
                        f"{'…' if len(orphan) > 8 else ''}")

    # ---------- 剪辑排布（复用 timeline.build_plan） ----------
    stage = a.stage
    if stage == "auto":
        stage = "cut" if a.audio_dir and os.path.isdir(a.audio_dir) else "plan"
    layout = None
    if stage == "cut":
        if not a.audio_dir:
            problems.append("--stage cut 需要 --audio-dir")
        else:
            u = T.Units(a.audio_dir, allow_unverified=True)
            cuts = []
            if a.cuts and os.path.exists(a.cuts):
                cuts = T.load_cuts(a.cuts)
            elif a.source:
                cuts = T.detect_cuts(a.source, os.path.join("/tmp", "validate_cuts.txt"), 0.35)
            items2, total = T.build_plan(cfg, cuts, a.source, a.audio_dir, a.min_tail,
                                         a.snap_cut, a.narr_tail, a.gap, udur=u.dur,
                                         fixed_tail=None if a.fixed_tail is not None
                                         and a.fixed_tail < 0 else a.fixed_tail)
            layout = dict(items=items2, total=total, cuts=cuts)
            for p in dict.fromkeys(u.problems):
                problems.append(f"音频：{p}")
            for it in items2:
                nm = it["name"]
                nb = T.narration_windows(it)
                # 注意：nb 已夹到 [0,dur]——超出片段的部分会被无声夹掉，所以另拿未夹的原始区间查。
                raw_s = min([(g - it["start"]) for _, g, _ in it["narr"]], default=0.0)
                raw_e = max([(g - it["start"] + d) for _, g, d in it["narr"]], default=0.0)
                if raw_s < -0.01 or raw_e > it["dur"] + 0.01:
                    problems.append(f"{nm}: 解说排在 {raw_s:.2f}–{raw_e:.2f}s，超出片段 0–"
                                    f"{it['dur']:.2f}s——这段装不下解说（加长片段、删句、或换短段）")
                for i in range(len(nb) - 1):
                    if nb[i][1] > nb[i + 1][0] + 0.01:
                        problems.append(f"{nm}: 解说窗重叠 {nb[i]} × {nb[i + 1]}——"
                                        f"该片段装不下这些解说（加长片段或删句）")
                narr_s = sum(e - s for s, e in nb)
                if narr_s > it["dur"] + 0.01:
                    problems.append(f"{nm}: 解说 {narr_s:.2f}s 比片段 {it['dur']:.2f}s 还长")
                if it["dur"] - narr_s < 0.8:
                    warnings.append(f"{nm}: 片段里只剩 {it['dur'] - narr_s:.2f}s 原声/留白，"
                                    f"听感会像连播解说")
                if not it.get("orig"):
                    warnings.append(f"{nm}: 没有任何原声窗（纯解说段）")
                if it["why"].startswith("解说/原声交替") and "顺延避开解说" in it["why"]:
                    warnings.append(f"{nm}: 有原声窗被顺延（{it['why'].split('｜')[-1][:60]}）——"
                                    f"顺延等于切掉了那句话的开头，最好缩短该句解说")
            # 开头：本项目要求「上来直接讲」——不要片头卡/标题条，第一句解说从 0 起
            first = items2[0]
            if first["narr"]:
                t0 = min(g - first["start"] for _, g, _ in first["narr"])
                if t0 > 1.5:
                    warnings.append(f"开头 {t0:.1f}s 才出第一句解说——观众容易划走；"
                                    f"建议把第一段解说的起点排到 0（items[0] 用 fixed + units）")
            else:
                warnings.append(f"第一个片段「{first['name']}」{first['dur']:.1f}s 里没有任何解说："
                                f"开头是纯原声。本项目要求「上来直接讲」，"
                                f"建议 items[0] = {{\"fixed\":[0,片头长度], \"units\":[钩子解说]}}")
            if first["dur"] > 8:
                cov = sum(e - s for s, e in T.narration_windows(first))
                if cov < first["dur"] * 0.4:
                    warnings.append(f"第一个片段 {first['dur']:.1f}s 里解说只有 {cov:.1f}s，"
                                    f"开头太空（钩子段要密一点）")
            if cuts:
                for it in items2:
                    prev = max([c for c in cuts if c <= it["b"] + 0.001], default=0)
                    if it["b"] - prev < a.min_tail - 0.05:
                        problems.append(f"{it['name']}: 末点后只有 {it['b'] - prev:.2f}s "
                                        f"(< {a.min_tail}s) 会看到碎镜头")
            mins = total / 60.0
            if mins < a.target_min or mins > a.target_max:
                warnings.append(f"预计成片 {total:.1f}s（{mins:.1f} 分钟）超出 "
                                f"{a.target_min:g}-{a.target_max:g} 分钟；"
                                f"解说词长度是主变量，别为凑时数注水")
    return report(a, problems, warnings, layout)


def report(a, problems, warnings, layout):
    if a.json:
        print(json.dumps(dict(problems=problems, warnings=warnings, layout=layout),
                         ensure_ascii=False, indent=1))
        return 1 if problems else 0
    if layout:
        items = layout["items"]
        print(f"预计成片 {layout['total']:.2f}s（{layout['total'] / 60:.2f} 分钟）；"
              f"{len(items)} 个片段；切点 {len(layout['cuts'])} 个")
        print(f"{'片段':8s} {'源片段':>16s} {'成片位置':>13s} {'时长':>7s} {'解说':>7s} "
              f"{'原声':>7s}  求解方式")
        for it in items:
            nb = T.narration_windows(it)
            narr = sum(e - s for s, e in nb)
            print(f"{it['name'][:8]:8s} {it['a']:7.2f}-{it['b']:7.2f} "
                  f"{it['start']:13.2f} {it['dur']:7.2f} {narr:7.2f} {it['dur'] - narr:7.2f}  "
                  f"{it['why'][:70]}")
        print()
    for w in warnings:
        print(f"⚠ {w}")
    for p in problems:
        print(f"✗ {p}")
    print(f"\n{len(problems)} 个必须修的 ／ {len(warnings)} 个提醒")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
