#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""封面：一帧底图 → 4:3（1920x1440）+ 3:4（1080x1440）两种规格，各出 PNG+JPG。

用法:
  # ① 默认流程：用户指定底图位置（成片时间轴上的一个点）
  python3 scripts/cover.py --film 成片.mp4 --at 8:09 --out-dir . \
        --above "是，大臣 · 第二季第二集" --title 无功受禄 --below "中文解说 · DOING THE HONOURS"
  # ② 要没有烧录字幕的干净帧：再给 --source + --plan，脚本把成片时间映射回源片时间
  python3 scripts/cover.py --film 成片.mp4 --at 8:09 --source 原片.mp4 --plan out/resolved.json ...
  # ③ 已经有图片
  python3 scripts/cover.py --image frame.png ...
  # ④ 让用户挑位置：出候选帧拼图（每格烧上时间码）
  python3 scripts/cover.py --film 成片.mp4 --sheet 6 --out-dir .

版式（左下角四行：金色小字／白色宋体大字／金短线／小字），字号按画面宽的固定比例，
与既有封面同档（4:3 = 8.33% 画宽、3:4 = 11.11% 画宽）。想要别的样子就改这里的默认值，
不要每个项目重写一遍脚本。

依赖：Pillow（python3-pillow）+ ffmpeg。流水线其余脚本无第三方依赖。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import sys

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:                                                # pragma: no cover
    sys.exit("cover.py 需要 Pillow（Fedora: sudo dnf install python3-pillow）")

WHITE = (252, 250, 246)
GOLD = (198, 162, 92)
SOFT = (232, 227, 214)

# 版式常数（相对画布的比例）——量自项目既有封面的 4:3/3:4 成品
LAY = dict(
    size43=0.0833, size34=0.1111,      # 大字字号 / 画宽
    left=0.0815,                       # 文字左 ink / 画宽
    top43=0.6528, top34=0.7153,        # 大字 ink 顶 / 画高
    eye=0.28, eye_track=0.055,         # 上方小字：字号、字距（×大字）
    tail=0.255, tail_track=0.035,      # 下方小字
    gap_eye=0.42, gap_rule=0.40, gap_tail=0.30,   # 大字→上/下留白（×大字）
    rule=0.028,                        # 金线粗细（×大字）
    shade=0.52, shade_from=0.38,       # 底部渐暗：强度、从画高百分之几开始
)
FONT_CANDIDATES = [
    "/usr/share/fonts/google-noto-serif-cjk-vf-fonts/NotoSerifCJK-VF.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Black.ttc",
    "/usr/share/fonts/noto-cjk/NotoSerifCJK-Black.ttc",
]


# ---------------------------------------------------------------- 小工具
def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode:
        sys.exit(f"✗ {' '.join(str(c) for c in cmd[:6])}…\n{p.stderr.strip()[:500]}")
    return p.stdout


def parse_time(s):
    """8:09 / 00:08:09.5 / 489.5 → 秒"""
    s = str(s).strip()
    if ":" not in s:
        return float(s)
    parts = [float(x) for x in s.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, sec = parts
    return h * 3600 + m * 60 + sec


def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "csv=p=0", path])
    return float(out.strip() or 0)


def grab(video, t, out):
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", video,
         "-frames:v", "1", out])
    return out


def find_font(explicit=None):
    """返回 (path, index, weight_name)。优先静态 Black，其次可变字体的 Black 实例。"""
    cands = [explicit] if explicit else FONT_CANDIDATES
    for p in cands:
        if p and os.path.exists(p):
            idx = ttc_index_sc(p)
            return p, idx, "Black"
    fc = shutil.which("fc-match")
    if fc:
        p = run([fc, "-f", "%{file}", "Noto Serif CJK SC:weight=210"]).strip()
        if p and os.path.exists(p):
            return p, ttc_index_sc(p), "Black"
    sys.exit("找不到中文宋体字重文件，用 --font 指定（如 NotoSerifCJK-VF.ttc）")


def ttc_index_sc(path, limit=8):
    """在 .ttc 里找 SC 面；找不到就退回 0"""
    for i in range(limit):
        try:
            if ImageFont.truetype(path, 20, index=i).getname()[0].endswith("SC"):
                return i
        except Exception:
            break
    return 0


def load_font(path, index, weight, size):
    f = ImageFont.truetype(path, size, index=index)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass                                    # 静态字重没有 variation，忽略
    return f


# ---------------------------------------------------------------- 版式
def text_line(text, font_path, index, weight, size, tracking=0, color=WHITE, alpha=255):
    """逐字排版（CJK 要字距只能逐字画），返回裁到 ink 的 RGBA"""
    f = load_font(font_path, index, weight, size)
    pad = int(size * 1.2)
    w = int(size * (len(text) + 2) + tracking * len(text)) + 2 * pad
    tmp = Image.new("RGBA", (w, int(size * 2.2) + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    x = float(pad)
    for ch in text:
        d.text((x, pad), ch, font=f, fill=color + (alpha,))
        x += d.textlength(ch, font=f) + tracking
    return tmp.crop(tmp.getbbox())


def crop43(w, h):
    """4:3 取景：宽度优先（宽片切上下）"""
    need = min(w, h * 4 / 3)
    return need, need * 3 / 4


def crop34(w, h, zoom=1.0):
    """3:4 取景：高度优先（宽片切左右），zoom<1 表示取更小一块（等于放大）"""
    if w / h > 0.75:
        bw, bh = h * 0.75, h
    else:
        bw, bh = w, w / 0.75
    return bw * zoom, bh * zoom


def anchor(span, box, key):
    """key ∈ left/center/right 或 0~1 的数"""
    if isinstance(key, (int, float)):
        f = float(key)
    else:
        f = {"left": 0.0, "center": 0.5, "right": 1.0}.get(key, 0.5)
    return int(round((span - box) * f))


def make(src_png, out_base, W, H, box, anchor_x, anchor_y,
         lines, font_path, f_index, f_weight, lay, sizes, shade, jpg=True, scrim=0.0):
    im = Image.open(src_png).convert("RGB")
    bg = im.crop((anchor_x, anchor_y, anchor_x + int(box[0]), anchor_y + int(box[1])))
    bg = bg.resize((W, H), Image.LANCZOS)
    if shade:
        col = Image.new("L", (1, H))
        for y in range(H):
            t = max(0.0, (y / H - lay["shade_from"]) / (1 - lay["shade_from"]))
            col.putpixel((0, y), int(255 * t * t))
        mask = col.resize((W, H)).point(lambda v: int(v * shade))
        bg = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), bg, mask)

    size = int(round(sizes["title"] * W))
    above, title, below = lines
    empty = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    l_above = text_line(above, font_path, f_index, f_weight, round(size * lay["eye"]),
                        tracking=round(size * lay["eye_track"]), color=GOLD) if above else empty
    l_title = text_line(title, font_path, f_index, f_weight, size,
                        tracking=round(size * 0.02))
    l_below = text_line(below, font_path, f_index, f_weight, round(size * lay["tail"]),
                        tracking=round(size * lay["tail_track"]), color=SOFT) if below else empty

    left = int(round(lay["left"] * W))
    y_title = int(round(sizes["top"] * H))
    rule_h = max(3, int(round(size * lay["rule"])))
    y_rule = y_title + l_title.height + int(round(size * lay["gap_rule"]))
    y_below = y_rule + rule_h + int(round(size * lay["gap_tail"]))
    y_above = y_title - int(round(size * lay["gap_eye"])) - l_above.height

    # 文字块后面那条羽化暗带：`--shade` 的 t² 曲线在画面中段几乎为 0（2886×2160 上 y=0.59H
    # 只有 ~11%），浅色/亮底图（白墙、桌面、剧照）在中段放不住金色小字和白字。scrim 从文字块
    # 上沿上方 ~0.9 字高开始线性起，一直到画底，直接压在文字后面。默认 0 = 不动既有封面。
    if scrim > 0:
        feather = max(size * 1.5, H * 0.24)      # 羽化要足够长：短了会在均一的墙面/桌面上留一条可见的横边
        start = max(0.0, y_above - feather)
        col = Image.new("L", (1, H))
        for y in range(H):
            col.putpixel((0, y), int(255 * scrim * min(1.0, max(0.0, (y - start) / feather))))
        bg = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), bg, col.resize((W, H)))

    cv = bg.convert("RGBA")

    for lay_img, x, y in ((l_above, left, y_above), (l_title, left, y_title), (l_below, left, y_below)):
        if lay_img.width <= 1:
            continue
        sh = Image.new("RGBA", cv.size, (0, 0, 0, 0))
        sh.paste((0, 0, 0, 150), (x + int(size * 0.015), y + int(size * 0.02)), lay_img)
        sh = sh.filter(ImageFilter.GaussianBlur(max(1.0, size / 60)))
        cv = Image.alpha_composite(cv, sh)
        cv.alpha_composite(lay_img, (x, y))
    d = ImageDraw.Draw(cv)
    d.rectangle([left, y_rule, left + l_title.width, y_rule + rule_h], fill=GOLD)

    out = cv.convert("RGB")
    png = out_base + ".png"
    out.save(png)
    if jpg:
        out.save(out_base + ".jpg", quality=93, optimize=True)
    return dict(path=png, size=(W, H), font=size, block_bottom=y_below + l_below.height,
                title_px=(l_title.width, l_title.height), left=left, title_top=y_title)


# ---------------------------------------------------------------- 候选帧拼图
def make_sheet(film, n, out, t0=None, t1=None, cols=None, width=430, label=True):
    dur = duration(film)
    t0 = 0.02 * dur if t0 is None else t0
    t1 = 0.98 * dur if t1 is None else t1
    ts = [t0 + (t1 - t0) * i / max(1, n - 1) for i in range(n)]
    cols = cols or min(3, n)
    rows = (n + cols - 1) // cols
    tiles = []
    with tempfile.TemporaryDirectory(prefix="cover_sheet_") as tmpd:
        for i, t in enumerate(ts):
            p = os.path.join(tmpd, f"s{i:02d}.png")
            grab(film, t, p)
            im = Image.open(p).convert("RGB")
            im = im.resize((width, int(round(width * im.height / im.width))), Image.LANCZOS)
            tiles.append((t, im))
    th = max(i.height for _, i in tiles)
    sheet = Image.new("RGB", (cols * width, rows * th), (16, 16, 16))
    for k, (t, im) in enumerate(tiles):
        sheet.paste(im, ((k % cols) * width, (k // cols) * th))
    if label:
        d = ImageDraw.Draw(sheet)
        f = None
        try:
            fp, fi, fw = find_font()
            f = load_font(fp, fi, fw, 28)
        except SystemExit:
            pass
        for k, (t, im) in enumerate(tiles):
            x, y = (k % cols) * width, (k // cols) * th
            tag = f"{int(t // 60)}:{t % 60:04.1f}"
            if f:
                d.text((x + 10, y + 8), tag, font=f, fill=(255, 235, 160))
            else:
                d.text((x + 10, y + 8), tag, fill=(255, 235, 160))
            x, y = (k % cols) * width, (k // cols) * th
            tag = f"{int(t // 60)}:{t % 60:04.1f}"
            if f:
                d.text((x + 10, y + 8), tag, font=f, fill=(255, 235, 160))
            else:
                d.text((x + 10, y + 8), tag, fill=(255, 235, 160))
    sheet.save(out, quality=92)
    print(f"→ {out}（{n} 格，{int(t0//60)}:{t0%60:04.1f}–{int(t1//60)}:{t1%60:04.1f}，"
          f"每格左上角是时间码）")
    return out


# ---------------------------------------------------------------- 成片时间 → 源片时间
def map_to_source(film_t, plan_path):
    cfg = json.load(open(plan_path, encoding="utf-8"))
    for it in cfg["items"]:
        if it["start"] <= film_t < it["start"] + it["dur"]:
            return it["a"] + (film_t - it["start"]), it["name"]
    last = cfg["items"][-1]
    return last["a"] + (film_t - last["start"]), last["name"]


FONT_CACHE = (FONT_CANDIDATES[0], 0, "Black")


def main():
    ap = argparse.ArgumentParser(description="做 4:3 / 3:4 封面（一帧底图 → 两种规格）")
    src = ap.add_argument_group("底图（三选一）")
    src.add_argument("--film", help="成片（默认底图来源；配 --at 用）")
    src.add_argument("--at", help="成片时间轴上的位置：8:09 / 489.5 / 00:08:09")
    src.add_argument("--image", help="直接用一张现成图片当底图")
    src.add_argument("--source", help="原片；给了它 + --plan，就取源片那一帧（没有烧录字幕）")
    src.add_argument("--plan", help="out/resolved.json（把成片时间映射回源片时间）")
    ap.add_argument("--out-dir", default=".", help="输出目录（默认当前目录）")
    ap.add_argument("--prefix", default="封面", help="输出文件名前缀，如 是,大臣S2E02_无功受禄_封面")
    ap.add_argument("--above", default="", help="大字上方的小字（金色）：系列·集数")
    ap.add_argument("--title", required=False, help="大字（必给）：本集名")
    ap.add_argument("--below", default="中文解说", help="大字下方的小字：中文解说 · 英文集名")
    ap.add_argument("--font", help="中文宋体字重文件（默认自动找 Noto Serif CJK SC Black）")
    ap.add_argument("--size", type=float, help="4:3 大字字号（像素）；默认画宽 8.33%%")
    ap.add_argument("--size34", type=float, help="3:4 大字字号（像素）；默认画宽 11.11%%")
    ap.add_argument("--crop43", default="center", help="4:3 取景锚点 left/center/right 或 0~1")
    ap.add_argument("--crop34", default="center", help="3:4 取景锚点 left/center/right 或 0~1")
    ap.add_argument("--zoom34", type=float, default=1.0,
                    help="3:4 取景再缩多少（<1 = 取更小一块、放大更多；切掉切脸的前景用）")
    ap.add_argument("--shade", type=float, default=LAY["shade"], help="底部渐暗强度 0~1")
    ap.add_argument("--scrim", type=float, default=0.0,
                    help="文字块后面那条羽化暗带强度 0~1（浅色/亮底图用：白墙、桌面、剧照；默认 0）")
    ap.add_argument("--no-jpg", action="store_true", help="只出 PNG")
    ap.add_argument("--sheet", type=int, metavar="N", help="只出候选帧拼图（N 格），不做封面")
    ap.add_argument("--sheet-cols", type=int, help="拼图每行几格（默认 3）")
    ap.add_argument("--keep-plate", action="store_true",
                    help="把抽出来的底图也留在输出目录（默认用临时文件，不留）")
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    base = os.path.join(a.out_dir, a.prefix)

    if a.sheet:
        make_sheet(a.film or a.image, a.sheet, base + "_候选帧.jpg", cols=a.sheet_cols)
        return
    if not a.title:
        sys.exit("✗ 缺 --title（大字，本集名）")

    # 1) 定底图
    tmpd = None
    if a.image:
        src_png, note = a.image, "图片"
    elif a.film and a.at:
        t = parse_time(a.at)
        if a.keep_plate:
            plate = base + "_底图.png"
        else:
            tmpd = tempfile.TemporaryDirectory(prefix="cover_plate_")
            plate = os.path.join(tmpd.name, "plate.png")
        if a.source and a.plan:
            st, seg = map_to_source(t, a.plan)
            src_png = grab(a.source, st, plate)
            note = f"成片 {a.at} → 源片 {st:.2f}s（{seg}，无烧录字幕）"
        else:
            src_png = grab(a.film, t, plate)
            note = f"成片 {a.at}（若这帧有烧录字幕，加 --source + --plan 换干净帧）"
    else:
        sys.exit("✗ 要 --image，或 --film + --at（先跑 --sheet 让用户挑位置）")
    print(f"底图：{note}")

    fpath, fidx, fweight = find_font(a.font)
    w, h = Image.open(src_png).size
    print(f"底图 {w}x{h}｜字体 {os.path.basename(fpath)} index={fidx} {fweight}")

    # 2) 4:3
    b = crop43(w, h)
    r43 = make(src_png, base + "_4x3", 1920, 1440, b,
               anchor(w, b[0], a.crop43) if b[0] < w else 0,
               anchor(h, b[1], a.crop43) if b[1] < h else 0,
               (a.above, a.title, a.below), fpath, fidx, fweight, LAY,
               dict(title=(a.size / 1920) if a.size else LAY["size43"], top=LAY["top43"]),
               a.shade, jpg=not a.no_jpg, scrim=a.scrim)
    # 3) 3:4
    b = crop34(w, h, a.zoom34)
    r34 = make(src_png, base + "_3x4", 1080, 1440, b,
               anchor(w, b[0], a.crop34),
               anchor(h, b[1], 0.5) if b[1] < h else 0,
               (a.above, a.title, a.below), fpath, fidx, fweight, LAY,
               dict(title=(a.size34 / 1080) if a.size34 else LAY["size34"], top=LAY["top34"]),
               a.shade, jpg=not a.no_jpg, scrim=a.scrim)
    for r in (r43, r34):
        print(f"→ {r['path']}  {r['size'][0]}x{r['size'][1]}｜大字 {r['font']}px "
              f"({r['title_px'][0]}x{r['title_px'][1]}) @({r['left']},{r['title_top']})｜"
              f"文字块底 {r['block_bottom']}")


if __name__ == "__main__":
    main()
