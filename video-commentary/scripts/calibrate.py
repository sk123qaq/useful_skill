#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""响度 A/B 校准：把"解说"和"原片"两类声音调平（**渲染前**就能算）。

用法:
  python3 scripts/calibrate.py --plan out/resolved.json --narration out/narration.wav \\
      --source 原片.mp4
  # 已经渲染过一版的话，同时看混完之后的残差：
  python3 scripts/calibrate.py --plan out/resolved.json --narration out/narration.wav \\
      --source 原片.mp4 --film 成片.mp4

为什么不能跳过这一步：narration.py 的 `--target-db` 只保证"解说自己"的响度；
原片的响度是素材自带的（1980s BBC 翻录能比现代音源轻 15 dB）。两边不调平，用户第一轮
反馈一定是"配音调好后原片声音太小"（S1E1 实测差 14.2 dB）。本脚本量两组窗口：
  * 解说窗中段 8s  → 解说音轨（narration.wav）
  * 原声窗中段 8s  → 原片同一时间段（源时间 = item.a + 段内相对时间）
给出 render.py 的 --volume-orig / --volume-narr，并检查原声会不会撞限幅器。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify as V                                                        # noqa: E402


def orig_samples(items, span, samples):
    """原声窗样本，量在原片上（返回源时间）。

    samples=0（默认）→ **每段取一窗**（全片普查）；>0 → 只取时长最长的 N 段。
    与解说窗用同一批片段、同一种选法，差值里才不会混进选段偏差
    （实测：只取最长的 4 段，原声场恰好都偏轻，结论能差 2.4dB）。
    """
    rows = []
    for it in items:
        spans = [s for s in it.get("orig", []) if s[1] - s[0] >= 1.0]
        if not spans:
            continue
        s, e = max(spans, key=lambda x: x[1] - x[0])
        ln = min(span, e - s)
        rows.append((it["a"] + (s + e) / 2 - ln / 2, ln, it["name"], e - s))
    if samples > 0:
        rows.sort(key=lambda x: -x[3])
        rows = rows[:samples]
    return [(t, ln, n) for t, ln, n, _ in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, help="out/resolved.json")
    ap.add_argument("--narration", required=True, help="out/narration.wav（timeline.py --track）")
    ap.add_argument("--source", required=True, help="原片（原声窗从这里量）")
    ap.add_argument("--film", help="已渲染的成片：顺带量混完之后的残差")
    ap.add_argument("--target-db", type=float,
                    help="两类声音都要落到的目标电平；默认取解说实测均值（即解说不动）")
    ap.add_argument("--samples", type=int, default=0,
                    help="原声/解说取样窗个数：0（默认）= 全片普查（每个片段取一窗）；"
                         ">0 = 只取时长最长的 N 段（旧行为，快速试看）。"
                         "实测：原片逐场电平差 7dB，抽 4 段会把混得很平的成片误报 2.4dB")
    ap.add_argument("--span", type=float, default=8.0)
    ap.add_argument("--max-diff", type=float, default=1.5, help="可接受的残差（dB）")
    ap.add_argument("--peak-headroom", type=float, default=1.5,
                    help="原声峰值离 0dBFS 至少保留多少 dB（否则限幅器会啃掉瞬态）")
    ap.add_argument("--duck-db", type=float, default=12.0,
                    help="render.py 的 sidechain 闪避深度估计值：解说窗里还叠着被压过的原声，"
                         "算能量和时要用到（默认 12dB，与默认 --duck 参数一致）")
    ap.add_argument("--write-args", help="把结果写成文件，方便直接贴进 render.py 命令")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    plan = json.load(open(a.plan, encoding="utf-8"))
    items = plan["items"]

    nw = (V.census_windows(items, "narr_mask", a.span) if a.samples <= 0
          else V.pick_windows(items, "narr_mask", a.span, a.samples))
    owin = orig_samples(items, a.span, a.samples)
    if not nw:
        sys.exit("resolved.json 里没有解说窗（narr_mask）——先跑 timeline.py（旧版产物没有这些字段）")
    if not owin:
        sys.exit("resolved.json 里没有原声窗（orig）——这段片子全是解说？")

    # narration.wav 与成片时间轴一一对应（timeline --track 按 resolved 拼的）
    nm = [(V.mean_volume(a.narration, s, d), s, n) for s, d, n in nw]
    nm = [x for x in nm if x[0][0] is not None]
    # 原声窗量在**原片**上（源时间）。
    om = []
    for src_t, ln, name in owin:
        mv, pk = V.mean_volume(a.source, src_t, ln)
        if mv is not None:
            om.append((mv, pk, src_t, f"{name}（量了 {ln:.1f}s）"))
    if not om:
        sys.exit("没找到可用的原声窗样本（原声窗都短于 1.0s）")

    n_mean = sum(x[0][0] for x in nm) / len(nm)
    o_mean = sum(x[0] for x in om) / len(om)
    o_peak = max(x[1] for x in om if x[1] is not None) if any(x[1] is not None for x in om) else None
    target = a.target_db if a.target_db is not None else n_mean
    g_orig = target - o_mean
    capped = False
    if o_peak is not None and o_peak + g_orig > -a.peak_headroom:
        g_orig = -a.peak_headroom - o_peak
        capped = True
    # 解说窗里听到的其实是 amix(解说, 被闪避的原声)：不能只把两个纯素材的均值拉平，
    # 否则出片后解说段会比原声段响 2–4dB。解一下能量方程：
    #   10^((n+g_n)/10) + 10^((o+g_o-duck)/10) = 10^((o+g_o)/10)
    import math
    g_narr = (o_mean + g_orig) + 10 * math.log10(max(1e-6, 1 - 10 ** (-a.duck_db / 10))) - n_mean
    pred_n = 10 * math.log10(10 ** ((n_mean + g_narr) / 10)
                             + 10 ** ((o_mean + g_orig - a.duck_db) / 10))
    pred_o = o_mean + g_orig

    out = dict(narration_mean=round(n_mean, 2), orig_mean=round(o_mean, 2),
               orig_peak=(round(o_peak, 2) if o_peak is not None else None),
               target_db=round(target, 2), volume_narr=round(g_narr, 2),
               volume_orig=round(g_orig, 2), capped=capped,
               pred_narr=round(pred_n, 2), pred_orig=round(pred_o, 2),
               pred_residual=round(pred_n - pred_o, 2),
               samples_narr=[(round(x[0][0], 2), round(x[1], 2), x[2]) for x in nm],
               samples_orig=[(round(x[0], 2), round(x[1], 2) if x[1] is not None else None,
                              round(x[2], 2), x[3]) for x in om])
    if a.film and os.path.exists(a.film):
        # 残差一律用全片普查量：模型可能用子样本（--samples>0），两者不一致时能看出选段偏差
        fn = [x[0][0] for x in [(V.mean_volume(a.film, s, d), s, n)
                                for s, d, n in V.census_windows(items, "narr_mask", a.span)]
              if x[0] is not None]
        fo = [V.mean_volume(a.film, s, d)[0]
              for s, d, n in V.census_windows(items, "orig", a.span)]
        fo = [x for x in fo if x is not None]
        if fn and fo:
            out["film_narr"] = round(sum(fn) / len(fn), 2)
            out["film_orig"] = round(sum(fo) / len(fo), 2)
            out["film_diff"] = round(out["film_narr"] - out["film_orig"], 2)

    args = f"--volume-orig {g_orig:+.2f}dB --volume-narr {g_narr:+.2f}dB"
    if a.json:
        out["render_args"] = args
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    print(f"解说样本（narration.wav）：{[(x[0][0], x[2]) for x in nm]}")
    print(f"原声样本（原片）：      {[(x[0], x[3]) for x in om]}")
    print(f"\n解说均值 {n_mean:.2f}dB ／ 原声均值 {o_mean:.2f}dB（差 {n_mean - o_mean:+.2f}dB）"
          f"{f'；原声峰值 {o_peak:.1f}dB' if o_peak is not None else ''}")
    print(f"目标电平 {target:.2f}dB → 建议  render.py {args}")
    print(f"预计混完：解说窗 {pred_n:.2f}dB / 原声窗 {pred_o:.2f}dB"
          f"（残差 {pred_n - pred_o:+.2f}dB，已把 {a.duck_db:g}dB 闪避算进去）")
    if capped:
        print(f"⚠ 原声提升被限到 {g_orig:+.1f}dB：再高会顶到限幅器（峰值 {o_peak:.1f}dB）。"
              f"如果还是觉得原声轻，宁可把解说压低或用 --duck 加大闪避量")
    if abs(g_narr) > 3:
        print(f"⚠ 解说要动 {g_narr:+.1f}dB：说明 narration.py 的 --target-db 与本素材不匹配，"
              f"下次配音可以直接用 --target-db {target:.1f}")
    if "film_diff" in out:
        d = out["film_diff"]
        print(f"\n混完实测：解说段 {out['film_narr']}dB / 原声段 {out['film_orig']}dB"
              f"（残差 {d:+.2f}dB）{'✓ 达标' if abs(d) <= a.max_diff else '✗ 仍超标'}")
    if a.write_args:
        open(a.write_args, "w", encoding="utf-8").write(args + "\n")
        print(f"→ {a.write_args}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
