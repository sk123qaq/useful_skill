#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字幕样式预览：在一张假画面上把几种成品样式并排渲染出来，用来定"长什么样"。

用法:
  python3 scripts/style_preview.py --width 1426 --height 1080 --out /tmp/style
  python3 scripts/style_preview.py --frame 原片.jpg --width 1426 --height 1080 --out /tmp/style

不给 --frame 时自己画一张底图：明暗渐变 + 底部两条假"原片烧录字幕" + 右上角假水印，
这样一眼能看出"解说字幕该让开哪、水印挡没挡住"。
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import timeline as T                                                      # noqa: E402

VARIANTS = [
    # 第一个 = 本项目默认（timeline.py 的默认值就是这一套：描边 3.0 / 阴影 1.0 / \fad 140ms / 4.5% 画面高）
    ("1_项目默认B", dict(bold=0, outline=3.0, shadow=1.0, scale=0.045, mv=0.10, fade=140)),
    ("2_旧版描边细", dict(bold=0, outline=2.4, shadow=1.2, scale=0.045, mv=0.10, fade=0)),
    ("3_抖音大字", dict(bold=1, outline=3.3, shadow=1.6, scale=0.052, mv=0.14, fade=140)),
    ("4_S1E1E3同款", dict(bold=1, outline=3.3, shadow=1.6, scale=0.057, mv=0.13, fade=140)),
]
TEXTS = ["先把这一集的处境说清楚：他手里这份文件，谁签谁负责。",
         "You can't be serious. 你不是认真的吧。（黄=原片对白）"]


def fake_frame(w, h, out):
    """画一张示意图：明暗背景 + 底部假烧录字幕 + 右上角假水印。"""
    box = (f"drawbox=x=0:y=0:w=iw:h=ih:color=0x1b2733:t=fill,"
           f"drawbox=x=0:y=0:w=iw:h={int(h * 0.55)}:color=0x2d3b4a:t=fill,"
           f"drawtext=text='FAKE FRAME':x=(w-text_w)/2:y={int(h * 0.28)}:fontsize={int(h * 0.07)}:"
           f"fontcolor=white@0.30,"
           f"drawbox=x=0:y={int(h * 0.915)}:w=iw:h={int(h * 0.06)}:color=black@0.55:t=fill,"
           f"drawtext=text='原片烧录字幕（假）':x=(w-text_w)/2:y={int(h * 0.925)}:"
           f"fontsize={int(h * 0.04)}:fontcolor=0x9fd0ff,"
           f"drawbox=x={int(w * 0.72)}:y={int(h * 0.02)}:w={int(w * 0.26)}:h={int(h * 0.05)}:"
           f"color=black@0.35:t=fill,"
           f"drawtext=text='右上角水印':x={int(w * 0.73)}:y={int(h * 0.03)}:"
           f"fontsize={int(h * 0.03)}:fontcolor=white@0.6")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c=0x1b2733:s={w}x{h}", "-vf", box, "-frames:v", "1", out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("造底图失败：" + r.stderr[-300:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", help="用真实截帧当底图（不给就自画一张示意图）")
    ap.add_argument("--width", type=int, default=1426)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--font", default="Noto Sans CJK SC")
    ap.add_argument("--out", default="/tmp/style_preview")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    base = os.path.join(a.out, "base.png")
    if a.frame:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.frame,
                        "-vf", f"scale={a.width}:{a.height}", "-frames:v", "1", base], check=True)
    else:
        fake_frame(a.width, a.height, base)

    pngs = []
    for name, v in VARIANTS:
        size = max(14, round(a.height * v["scale"]))
        mv = max(8, round(a.height * v["mv"]))
        ass = os.path.join(a.out, f"{name}.ass")
        with open(ass, "w", encoding="utf-8") as f:
            f.write(T.ass_head(a.width, a.height, a.font, size, mv, v["bold"],
                               v["outline"], v["shadow"], dlg=True))
            tag = f"{{\\fad({v['fade']},{v['fade']})}}" if v["fade"] else ""
            f.write("Dialogue: 0,0:00:00.00,0:00:10.00,Nar,,0,0,0,," + tag + TEXTS[0] + "\n")
            f.write("Dialogue: 0,0:00:00.00,0:00:10.00,Dlg,,0,0,0,," + tag + TEXTS[1] + "\n")
        png = os.path.join(a.out, f"{name}.png")
        # 注意：-ss 必须在滤镜之后（且输入要 -loop 1）——放 -i 前会让 subtitles 滤镜的\n        # 时间戳归零，\fad 淡入的那一刻抽出来就是全透明（画面上什么都没有）。
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "25",
                        "-i", base, "-vf", f"subtitles={ass}", "-ss", "1.0",
                        "-frames:v", "1", png], check=True)
        pngs.append(png)
        print(f"{name}: 字号 {size}px（画面高 {v['scale']:.1%}）、MarginV {mv}px、"
              f"描边 {v['outline']}、阴影 {v['shadow']}"
              f"{'、淡入淡出 %dms' % v['fade'] if v['fade'] else ''}")
    sheet = os.path.join(a.out, "样式对比.jpg")
    ins = sum([["-i", p] for p in pngs], [])
    sw = max(360, a.width // 2)
    sh_ = round(sw * a.height / a.width / 2) * 2
    flt = "".join(f"[{i}:v]scale={sw}:{sh_}[v{i}];" for i in range(len(pngs))) + \
          "".join(f"[v{i}]" for i in range(len(pngs))) + \
          f"xstack=inputs={len(pngs)}:layout=" + \
          "|".join(f"{(i % 2) * sw}_{(i // 2) * sh_}" for i in range(len(pngs))) + "[o]"
    subprocess.run(["ffmpeg", "-v", "error", "-y"] + ins + ["-filter_complex", flt,
                   "-map", "[o]", "-q:v", "3", sheet], check=True)
    print("对比图:", sheet)


if __name__ == "__main__":
    main()
