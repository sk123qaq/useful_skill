#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一条 ffmpeg 图合成成片：片段拼接 + 原声自动闪避 + 标题条/片头卡/信息条 + 字幕烧录。

用法:
  python3 render.py --source 原片.mp4 --plan out/resolved.json --narration out/narration.wav \
      --ass out/narration.ass --out 成片.mp4 \
      --title "《是，大臣》S2E2 · 荣誉问题　10分钟中文解说" \
      --top-bar 170 --intro-card "是，大臣|Yes Minister · S2E2|10 分钟中文解说::6.4" \
      --info-bar "解说：AI 配音 ｜ 素材：《是，大臣》 仅供交流::14.5::35::852::228" \
      --sub-band 1752 --sub-band-fade 60 --sub-band-accent 0xD8B26A
"""
import argparse, json, os, re, shutil, subprocess, sys

FONT = "/usr/share/fonts/google-noto-sans-cjk-vf-fonts/NotoSansCJK-VF.ttc"


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def dur(p):
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p])
    return float(r.stdout.strip() or 0)


def parse_intro(spec):
    """'行1|行2|行3::6.4' → (lines, until)"""
    until = 0.0
    if "::" in spec:
        spec, u = spec.rsplit("::", 1)
        until = float(u)
    return [x for x in spec.split("|") if x], until


def sub_band_windows(items, pad=0.10, merge=0.30, total=None):
    """从 resolved.json 的 narr_mask 推导承载带的时间窗（成片绝对时间）。

    narr_mask 就是 timeline.py 的"解说遮蔽区"（已含 gap 两侧余量）：带子只在它里面出现，
    补集（orig）里原片中英烧录字幕完整回来——任何时刻只有一种字幕。相邻过近的窗合并，
    免得带子高频闪。
    """
    wins = []
    for it in items:
        for s, e in it.get("narr_mask", []):
            a, b = it["start"] + s - pad, it["start"] + e + pad
            if b - a > 0.05:
                wins.append([max(0.0, a), b])
    wins.sort()
    out = []
    for a, b in wins:
        if out and a - out[-1][1] < merge:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    if total and out:
        out[-1][1] = min(out[-1][1], total)
    return out


def sub_band_filters(vid, k, top, fade, steps, opacity, accent, accent_h, en):
    """承载带的 drawbox 链：上沿渐变（一级一条）+ 封到底边的本体 + 可选金线。返回 (filters, vid, k)。

    两条硬规则：① 渐变各级区域**互不重叠**——重叠会让 alpha 复合，渐变变成一条条可见梯步；
    ② 本体用 `h=ih-{body}` 封到画面底边——写死高度会在底边漏出原片一道（S1E1 实测漏 54px）。
    """
    flt = []
    for i in range(max(1, steps)):
        y0 = top + fade * i // steps
        y1 = top + fade * (i + 1) // steps
        if y1 <= y0:
            continue
        al = opacity * (i + 1) / steps
        flt.append(f"[{vid}]drawbox=x=0:y={y0}:w=iw:h={y1 - y0}:"
                   f"color=black@{al:.3f}:t=fill:enable='{en}'[t{k}]")
        vid, k = f"t{k}", k + 1
    body = top + fade
    flt.append(f"[{vid}]drawbox=x=0:y={body}:w=iw:h=ih-{body}:"
               f"color=black@{opacity:.3f}:t=fill:enable='{en}'[t{k}]")
    vid, k = f"t{k}", k + 1
    if accent:
        flt.append(f"[{vid}]drawbox=x=0:y={top}:w=iw:h={accent_h}:"
                   f"color={accent}:t=fill:enable='{en}'[t{k}]")
        vid, k = f"t{k}", k + 1
    return flt, vid, k


def parse_bar(spec):
    """'文字::t0::t1::y::h' → (text, t0, t1, y, h)"""
    parts = spec.split("::")
    text = parts[0]
    t0, t1, y, h = (float(parts[1]), float(parts[2]), int(parts[3]), int(parts[4])) if len(parts) >= 5 \
        else (0.0, 0.0, 0, 0)
    return text, t0, t1, y, h


def esc(t):
    return t.replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def ass_playres(path):
    try:
        head = open(path, encoding="utf-8", errors="replace").read(4000)
    except OSError:
        return None
    w = re.search(r"PlayResX:\s*(\d+)", head)
    h = re.search(r"PlayResY:\s*(\d+)", head)
    return (int(w.group(1)), int(h.group(1))) if w and h else None


def probe_size(src):
    r = sh(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=width,height", "-of", "csv=p=0:s=x", src])
    m = re.match(r"\s*(\d+)\s*[x,]\s*(\d+)", r.stdout or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--plan", required=True, help="timeline.py 产出的 resolved.json")
    ap.add_argument("--narration", help="解说音轨 wav（timeline.py --track 产出）")
    ap.add_argument("--ass", help="解说字幕 .ass（按视频分辨率给 PlayRes，别用 srt+force_style）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="", help="顶部标题；默认 8 秒后自动淡出（见 --title-until）")
    ap.add_argument("--top-bar", type=int, default=0,
                    help="顶部黑条高度（像素），0=不铺黑条（默认；本项目出片也不用标题）")
    ap.add_argument("--title-box", action="store_true",
                    help="给标题文字加半透明衬底（默认不加：只留阴影，画面更干净）")
    ap.add_argument("--title-until", type=float, default=8.0,
                    help="标题显示到第几秒开始淡出；0=常驻")
    ap.add_argument("--title-fade", type=float, default=0.6, help="标题淡出时长（秒）")
    ap.add_argument("--intro-card", help="片头标题卡：'行1|行2|行3::显示到几秒'")
    ap.add_argument("--intro-opacity", type=float, default=0.78,
                    help="片头卡压暗程度（1=纯黑，0.5=画面透出来一半）")
    ap.add_argument("--intro-fade", type=float, default=0.6, help="片头卡文字淡入/淡出（秒）")
    ap.add_argument("--bgm", help="背景音乐文件（会被解说闪避；原声窗里保持低音量）")
    ap.add_argument("--bgm-db", default="-26dB", help="背景音乐电平（相对满刻度）")
    ap.add_argument("--bgm-duck", default="threshold=0.05:ratio=8:attack=200:release=900",
                    help="解说一响就把 BGM 压下去的 sidechaincompress 参数")
    ap.add_argument("--info-bar", action="append", default=[],
                    help="底部信息条（遮挡字幕组水印）：'文字::起::止::y::高'，可多次")
    ap.add_argument("--info-bar-opacity", type=float, default=0.93,
                    help="信息条黑底不透明度：0.93=半透明（原内容透出鬼影）；"
                         "1.0=全黑（盖烧录字幕带、解说字幕放条上时用）")
    # --- 解说字幕承载带：把"临时拿 info-bar 盖烧录字幕"变成渲染器的一等功能 ---
    # 它替代一排手写的 --info-bar "::起::止::y::高"：时间窗从 --plan 的 narr_mask 自动推导，
    # 高度封到画面底边，上沿带渐变——是版式，不是一块漂着的黑矩形。
    ap.add_argument("--sub-band", type=float, default=0.0, metavar="TOP",
                    help="解说字幕承载带：从 y=TOP 到画面底边的全黑条，只在解说窗内出现"
                         "（窗由 --plan 的 narr_mask 自动推导），解说字幕放在条上，原声窗里"
                         "原片烧录字幕完整回来。TOP 给像素；0<TOP<=1 时按画面高比例。0=关闭")
    ap.add_argument("--sub-band-fade", type=int, default=60,
                    help="承载带上沿渐变高度（像素）。渐变只发生在原片字幕带**上方**；"
                         "字幕所在的那一段永远全不透明")
    ap.add_argument("--sub-band-steps", type=int, default=18,
                    help="渐变用几级台阶近似（每级一条 drawbox，区域互不重叠）")
    ap.add_argument("--sub-band-pad", type=float, default=0.10,
                    help="解说窗两侧各放宽的秒数（与解说同步起落）")
    ap.add_argument("--sub-band-merge", type=float, default=0.30,
                    help="间隔小于此值的相邻解说窗合并成一个（防止带子闪）")
    ap.add_argument("--sub-band-opacity", type=float, default=1.0,
                    help="承载带本体不透明度。盖原片烧录字幕必须 1.0：半透明会透出鬼影"
                         "（S1E1 v3 的 0.93 就是这么被用户否掉的）")
    ap.add_argument("--sub-band-accent", default="",
                    help="带上沿强调线颜色（如 0xD8B26A，与封面金线同一支）；空=不加")
    ap.add_argument("--sub-band-accent-h", type=int, default=4, help="强调线高度（像素）")
    ap.add_argument("--font", default=FONT)
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--encoder", default="vaapi", choices=["vaapi", "x264"],
                    help="vaapi=GPU 编码（默认；软解+CPU 滤镜+h264_vaapi）。本机 AMD 实测比 x264 "
                         "wall 快 4.1 倍、CPU 少 10.7 倍、画质同档（qp20 PSNR 47.83dB vs x264 crf20 "
                         "47.34dB）。需要 /dev/dri/renderD128，**找不到或编码失败都自动回落 x264**；"
                         "x264=纯 CPU(libx264)，哪都能跑")
    ap.add_argument("--vaapi-device", default="/dev/dri/renderD128", help="VAAPI 渲染节点")
    ap.add_argument("--fade", type=float, default=1.6, help="片尾淡出秒数")
    ap.add_argument("--volume-orig", default="1dB", help="原声音量（相对）")
    ap.add_argument("--volume-narr", default="0dB", help="解说音量（相对）；与 --volume-orig 配合把两者响度调平")
    ap.add_argument("--duck", default="threshold=0.05:ratio=12:attack=15:release=400:level_sc=4",
                    help="sidechaincompress 参数：解说一响原声就压低。"
                         "level_sc=4 是 ffmpeg 8.x 必需的：detection 默认 rms，"
                         "归一后解说轨 RMS≈-25dB 恰在阈值 0.05 边缘，不加大会几乎不压（S1E5 实测）")
    ap.add_argument("--no-atomic", action="store_true",
                    help="直接写成品路径（默认先写 <out>.part.mp4，校验通过才替换）")
    ap.add_argument("--no-backup", action="store_true", help="替换时不保留上一版备份")
    a = ap.parse_args()

    if a.encoder == "vaapi" and not os.path.exists(a.vaapi_device):
        print(f"⚠ 找不到 {a.vaapi_device}，回落到 libx264（CPU）", file=sys.stderr)
        a.encoder = "x264"

    plan = json.load(open(a.plan))
    items, total = plan["items"], plan["total"]
    if a.ass and os.path.exists(a.ass):
        pr, sz = ass_playres(a.ass), probe_size(a.source)
        if not pr:
            print("⚠ ASS 没有 PlayResX/Y：libass 会按默认画布缩放，字号和位置都不是你以为的像素",
                  file=sys.stderr)
        elif sz and pr != sz:
            print(f"⚠ ASS PlayRes {pr[0]}x{pr[1]} ≠ 视频 {sz[0]}x{sz[1]}：字幕会被整体缩放"
                  f"（timeline.py 现在会从 --source 自动探测，别手工写死）", file=sys.stderr)
    n = len(items)
    flt = []
    # 每段一次输入 seek（-ss/-t + 多输入 concat），不要用一路 [0:v] 喂 N 个 trim：
    # trim 分支在 concat 顺序消费时会被解码抢跑填满（一个 60s 段 ≈7GB 帧），整条片直接 OOM
    #（S1E5 20 段实测 8–9GB，两次被杀；19 段是踩线幸存）。seek 版还顺带跳过段外解码。
    for i, it in enumerate(items):
        flt.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}]")
        d = it["dur"]
        flt.append(f"[{i}:a]asetpts=PTS-STARTPTS,"
                   f"afade=t=in:st=0:d=0.06,afade=t=out:st={d-0.06:.3f}:d=0.06[a{i}]")
    flt.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vcat]")
    flt.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[acat]")

    H = (probe_size(a.source) or (0, 1080))[1]           # 字号/位置按画面高缩放，别写死 1080p 的值
    vid, k = "vcat", 0
    if a.title:
        # 标题默认不铺常驻黑条：给文字自己加半透明衬底，8 秒后连底一起淡出。
        # （常驻黑条会白白吃掉一条画面，S1E1 用户第一轮就要求去掉）
        if a.top_bar > 0:
            flt.append(f"[{vid}]drawbox=x=0:y=0:w=iw:h={a.top_bar}:color=black@0.93:t=fill[t{k}]")
            vid = f"t{k}"; k += 1
            box, y = "", max(12, round(a.top_bar * 0.33))
        else:
            box = ":box=1:boxcolor=black@0.55:boxborderw=18" if a.title_box else ""
            y = max(12, round(H * 0.037))
        alpha = ""
        if a.title_until > 0:
            alpha = (f":alpha='if(lt(t,{a.title_until}),1,"
                     f"max(0,1-(t-{a.title_until})/{a.title_fade}))'")
        flt.append(f"[{vid}]drawtext=fontfile='{a.font}':text='{esc(a.title)}':x={max(20, round(H * 0.035))}"
                   f":y={y}:fontsize={max(16, round(H * 0.041))}:fontcolor=white"
                   f":shadowcolor=black@0.6:shadowx=1:shadowy=1{box}{alpha}[t{k}]")
        vid = f"t{k}"; k += 1
    for spec in a.info_bar:
        text, t0, t1, y, h = parse_bar(spec)
        flt.append(f"[{vid}]drawbox=x=0:y={y}:w=iw:h={h}:color=black@{a.info_bar_opacity}:t=fill:"
                   f"enable='between(t,{t0},{t1})'[t{k}]")
        vid = f"t{k}"; k += 1
        if text.strip():                    # 空文本画了也无输出，跳过省 28 次无用的 drawtext
            flt.append(f"[{vid}]drawtext=fontfile='{a.font}':text='{esc(text)}':x=(w-text_w)/2:"
                       f"y={y + int(h*0.42)}:fontsize=38:fontcolor=0xD8DEE6:"
                       f"enable='between(t,{t0},{t1})'[t{k}]")
            vid = f"t{k}"; k += 1
    if a.intro_card:
        lines, until = parse_intro(a.intro_card)
        sizes = [round(H * x) for x in (0.089, 0.044, 0.037)][:len(lines)]
        offs = [round(H * x) for x in (-0.148, -0.028, 0.065)][:len(lines)]
        cols = ["white", "0xE8E8E8", "0xB9C7D6"][:len(lines)]
        # 压暗而不是纯黑：纯黑卡像 PPT 幻灯；留一点画面，观感立刻不一样
        flt.append(f"[{vid}]drawbox=x=0:y=0:w=iw:h=ih:color=black@{a.intro_opacity}:t=fill:"
                   f"enable='lt(t,{until})'[t{k}]")
        vid = f"t{k}"; k += 1
        # 细强调线（居中、带淡入）：一行字 + 一条线，比三行字更像"片子"而不是"幻灯片"
        flt.append(f"[{vid}]drawbox=x=(iw-{round(H * 0.20)})/2:y=(ih/2)+{offs[0] + round(sizes[0] * 0.9)}"
                   f":w={round(H * 0.20)}:h={max(2, round(H * 0.004))}:color=0x5FA8D3@0.9:t=fill:"
                   f"enable='lt(t,{until})'[t{k}]")
        vid = f"t{k}"; k += 1
        for i, (txt, fs, dy, col) in enumerate(zip(lines, sizes, offs, cols)):
            # 淡入淡出：文字硬闪出来是"廉价感"的主要来源
            f0 = min(a.intro_fade, until / 3) if until > 0 else 0
            al = (f":alpha='if(lt(t,{f0}),t/{max(f0, 0.001)},"
                  f"if(lt(t,{until - f0}),1,max(0,({until}-t)/{max(f0, 0.001)})))'" if f0 else "")
            flt.append(f"[{vid}]drawtext=fontfile='{a.font}':text='{esc(txt)}':"
                       f"x=(w-text_w)/2:y=(h/2)+{dy}:fontsize={fs}:fontcolor={col}"
                       f":enable='lt(t,{until})'{al}[t{k}]")
            vid = f"t{k}"; k += 1
    if a.sub_band:
        top = int(round(H * a.sub_band)) if 0 < a.sub_band <= 1 else int(a.sub_band)
        top = max(0, min(top, H - 1))
        fade = max(0, min(a.sub_band_fade, H - top))
        body = top + fade
        wins = sub_band_windows(items, a.sub_band_pad, a.sub_band_merge, total)
        if a.sub_band_opacity < 0.98:
            print(f"⚠ 承载带不透明度 {a.sub_band_opacity}：原片烧录字幕会透出鬼影，"
                  f"盖字幕请用 1.0", file=sys.stderr)
        if not wins:
            print("⚠ --sub-band 给了，但 plan 里没有 narr_mask（没有解说窗）→ 不画", file=sys.stderr)
        else:
            en = "+".join(f"between(t,{s:.2f},{e:.2f})" for s, e in wins)
            band, vid, k = sub_band_filters(vid, k, top, fade, a.sub_band_steps,
                                            a.sub_band_opacity, a.sub_band_accent,
                                            a.sub_band_accent_h, en)
            flt += band
            print(f"承载带 y{top}-{H}（不透明从 y{top + fade} 起，上沿渐变 {fade}px/{a.sub_band_steps} 级，"
                  f"{len(wins)} 个解说窗）", file=sys.stderr)
    if a.ass:
        flt.append(f"[{vid}]subtitles='{a.ass}'[t{k}]")
        vid = f"t{k}"; k += 1
    flt.append(f"[{vid}]fade=t=in:st=0:d=0.6,fade=t=out:st={total-a.fade:.2f}:d={a.fade}[vout]")

    flt.append(f"[acat]volume={a.volume_orig}[acatv]")
    narr_idx = n                      # 输入 0..n-1 = 各段片源 seek，n = 解说轨，n+1 = BGM
    bgm_idx = n + 1 if a.narration else n
    mix = []
    if a.narration:
        # ⚠ 必须显式 asplit：把 [narr] 直接同时喂给 sidechaincompress 和 amix，实测解说会整条丢失
        #    （ffmpeg 7.x，输出只剩被压的原声）；显式分流（有 BGM 时三份）才对。
        flt.append(f"[{narr_idx}:a]asplit=3[narr_sc][narr_mx][narr_bg]" if a.bgm
                   else f"[{narr_idx}:a]asplit=2[narr_sc][narr_mx]")
        flt.append(f"[narr_sc]volume={a.volume_narr}[narr]")
        flt.append(f"[acatv][narr]sidechaincompress={a.duck}[aduck]")
        flt.append(f"[narr_mx]volume={a.volume_narr}[narr2]")
        mix += ["[aduck]", "[narr2]"]
    else:
        mix += ["[acatv]"]
    if a.bgm:
        flt.append(f"[{bgm_idx}:a]aformat=sample_fmts=fltp:channel_layouts=stereo,"
                   f"volume={a.bgm_db}[bgmv]")
        flt.append(f"[bgmv][narr_bg]sidechaincompress={a.bgm_duck}[bgmduck]" if a.narration
                   else "[bgmv]anull[bgmduck]")
        mix += ["[bgmduck]"]
    if len(mix) == 1:
        flt.append(f"{mix[0]}alimiter=limit=0.95[aout]")
    else:
        flt.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,"
                   f"volume=0.95,alimiter=limit=0.95[aout]")

    cmd = ["ffmpeg", "-hide_banner", "-v", "warning", "-stats", "-y"]
    for it in items:                       # 每段一次输入（见上面 seek 版说明）
        cmd += ["-ss", f"{it['a']:.3f}", "-t", f"{it['b'] - it['a']:.3f}", "-i", a.source]
    if a.narration:
        cmd += ["-i", a.narration]
    if a.bgm:
        cmd += ["-stream_loop", "-1", "-i", a.bgm]      # BGM 比片子短就循环铺满
    # 关键：先渲染到 .part，校验通过再替换成品——渲染中途直接写成品会让用户打不开文件
    target = a.out if a.no_atomic else a.out + ".part.mp4"
    # 防双写入：两个渲染进程同时写同一个 .part.mp4，会产出「时长对、画面全坏」的片子
    # （S1E1 实测：杀渲染只杀了 bgrun 的包装 shell，孤儿 ffmpeg 仍在写，第二次渲染又写同一
    # 路径，成片 NAL 全错、解码错误率 99.7%，而 render.py 的时长校验照样通过）。
    # 锁里记 pid：pid 还活着就拒启，pid 死了（上次崩溃残留）就放行。
    lock = target + ".lock"
    if os.path.exists(lock):
        try:
            pid = int(open(lock).read().strip())
        except ValueError:
            pid = -1
        if pid > 0 and os.path.exists(f"/proc/{pid}"):
            sys.exit(f"{target} 正在被 pid {pid} 渲染（锁文件 {lock}）；不要同时起两个渲染")
        print(f"⚠ 清掉残留锁 {lock}（pid {pid} 已不存在）", file=sys.stderr)
    open(lock, "w").write(str(os.getpid()))

    def venc(enc):
        """返回该编码器的视频参数。vaapi = 软解 + CPU 滤镜 + GPU 编码（本机实测最优）：
        滤镜（subtitles/drawtext）只有 CPU 实现，图在 CPU 上跑完，末端 format=nv12,hwupload
        把帧递回 GPU 编码。-qp 是固定量化参数，与 libx264 的 -crf 语义最接近；qp+2 ≈ crf 同档
        （本机实测 qp20 还略胜 crf20，见 references/pipeline-notes.md）。
        **不要**改成一并硬解（-hwaccel vaapi）：烧字幕要 hwdownload→CPU→hwupload 两次全帧
        拷贝，wall 反而从 5.8s 涨到 9.6s。"""
        if enc == "vaapi":
            f = flt + ["[vout]format=nv12,hwupload[voutgpu]"]
            return ["-vaapi_device", a.vaapi_device,
                    "-filter_complex", ";".join(f), "-map", "[voutgpu]", "-map", "[aout]",
                    "-c:v", "h264_vaapi", "-qp", str(a.crf + 2)]
        return ["-filter_complex", ";".join(flt), "-map", "[vout]", "-map", "[aout]",
                "-c:v", "libx264", "-preset", a.preset, "-crf", str(a.crf), "-pix_fmt", "yuv420p"]

    tail = ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
            "-t", f"{total:.3f}", target]
    print(f"渲染 {total:.1f}s → {target}（{a.encoder}）", file=sys.stderr)
    try:
        subprocess.run(cmd + venc(a.encoder) + tail, check=True)
    except subprocess.CalledProcessError:
        # 设备节点在、但驱动不支持 h264_vaapi（或编码中途挂掉）：别让整片白等，就地回落
        if a.encoder != "vaapi":
            raise
        print("⚠ vaapi 编码失败，回落到 libx264（CPU）重跑", file=sys.stderr)
        a.encoder = "x264"
        subprocess.run(cmd + venc("x264") + tail, check=True)
    got = dur(target)
    if abs(got - total) > 0.5:
        sys.exit(f"渲染不完整：{got:.2f}s ≠ {total:.2f}s；保留 {target} 供检查，未替换成品")
    # 时长对不代表画面好（双写入的坏片时长分毫不差）。替换前抽几段解码，有 NAL/解码错误就不替换。
    if not a.no_atomic:
        bad = []
        for frac in (0.02, 0.5, 0.9):
            st = max(0.0, min(got - 9.0, got * frac))
            r = sh(["ffmpeg", "-v", "error", "-ss", f"{st:.2f}", "-t", "8",
                    "-i", target, "-f", "null", "-"])
            if r.stderr.strip():
                bad.append(f"{st:.0f}s 处：{(r.stderr.strip().splitlines() or [''])[0][:100]}")
        if bad:
            sys.exit(f"成片解码有误，未替换成品：{'；'.join(bad)}；保留 {target} 供检查")
    if not a.no_atomic:
        if os.path.exists(a.out) and not a.no_backup:
            root, ext = os.path.splitext(a.out)
            shutil.copy2(a.out, f"{root}.备份{ext}")
        os.replace(target, a.out)          # 同盘原子替换，播放器不会读到半个文件
    if os.path.exists(lock):
        os.remove(lock)
    print("完成:", a.out, f"{dur(a.out):.2f}s")


if __name__ == "__main__":
    main()
