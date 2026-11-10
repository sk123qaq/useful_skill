#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成离线测试素材 tests/fixture/：假原片 + 解说词 + plan.json + 桩环境。

    python3 tests/make_fixture.py [--force]

产出：
  tests/fixture/src.mp4        32s / 320x180 / 25fps，4 个镜头（8/16/24s 处硬切），
                               音轨是"每 2 秒一句 1.2s 台词"的假对白（0.8s 停顿）
  tests/fixture/narration/*.txt 6 段解说词
  tests/fixture/plan.json      四种条目都覆盖：fixed / punch / punch / blocks
  tests/fixture/env.sh         桩环境变量（TTS/ASR 走 tests/stub，不联网）
设计要点：所有素材都由脚本确定性生成，不依赖任何外部文件或网络。
"""
import argparse
import array
import json
import os
import subprocess
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(HERE, "fixture")
SR = 48000

SHOTS = ["testsrc2=size=320x180:rate=25", "smptebars=size=320x180:rate=25",
         "rgbtestsrc=size=320x180:rate=25", "testsrc=size=320x180:rate=25"]
SHOT_LEN = 8.0                     # 每镜 8s → 切点 8 / 16 / 24
BURST, GAP = 1.2, 0.8              # 假"台词"节奏：每 2s 一句 1.2s

NARRATION = {
    "b01": "开场先交代背景，这一集讲的是一个谁都不肯让步的老问题。",
    "b02": "他本以为这份文件只是走个过场，没想到对方早就准备好了另一套说法。",
    "b03": "会议室里的沉默持续了整整十秒，谁先开口谁就输了这场较量。",
    "b04": "真正的转折发生在那句看似客气的反问之后，局面彻底翻了过来。",
    "b05": "来听原话，这是全片最精彩的一段对话。",
    "b06": "他赢了争论，却输掉了更重要的东西。",
}

PLAN = {"items": [
    {"name": "片头", "fixed": [0.0, 7.0], "units": ["b01"]},
    {"name": "冲突", "punch": [16.0, 17.2], "units": ["b02"]},
    {"name": "反转", "punch": [26.0, 27.2], "units": ["b03"]},
    {"name": "收尾", "a": 20.0, "b": 32.0, "units": [],
     "blocks": [["narr", "b05"], ["orig", 24.1, 25.1], ["narr", "b06"]]},
]}


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.exit(f"命令失败: {' '.join(cmd)}\n{r.stderr[-800:]}")
    return r


def make_audio(path):
    """每 2 秒一句 1.2s 的假台词（音高轮换），其余为数字静音。"""
    total = SHOT_LEN * len(SHOTS)
    n = int(total * SR)
    buf = array.array("h", [0]) * n
    import math
    speech = []
    for k in range(int(total // 2)):
        a, b = int(k * 2 * SR), int((k * 2 + BURST) * SR)
        freq = 180 + 15 * (k % 6)
        for i in range(a, min(b, n)):
            buf[i] = int(8000 * math.sin(2 * math.pi * freq * (i - a) / SR))
        speech.append((k * 2, k * 2 + BURST))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(buf.tobytes())
    return speech


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="连视频也重建（默认只重建文本/计划/字幕）")
    a = ap.parse_args()
    os.makedirs(f"{FX}/narration", exist_ok=True)

    if os.path.exists(f"{FX}/src.mp4") and not a.force:
        speech = None
    else:
        wa = f"{FX}/_speech.wav"
        speech = make_audio(wa)
        ins, flt = [], []
        for i, s in enumerate(SHOTS):
            ins += ["-f", "lavfi", "-t", str(SHOT_LEN), "-i", s]
            flt.append(f"[{i}:v]setsar=1,format=yuv420p[s{i}]")
        flt.append("".join(f"[s{i}]" for i in range(len(SHOTS))) + f"concat=n={len(SHOTS)}:v=1:a=0[v]")
        sh(["ffmpeg", "-v", "error", "-y"] + ins + ["-i", wa,
            "-filter_complex", ";".join(flt), "-map", "[v]", "-map", f"{len(SHOTS)}:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
            "-c:a", "aac", "-b:a", "96k", "-shortest", f"{FX}/src.mp4"])
        os.remove(wa)

    for k, v in NARRATION.items():
        open(f"{FX}/narration/{k}.txt", "w", encoding="utf-8").write(v + "\n")

    # 假外挂双语 SRT（每句都落在 burst 区间里）+ 一份台词表 TSV（两种输入都练到）
    def srt_t(t):
        return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d},{int(round(t % 1 * 1000)):03d}"
    dlg = [(2.0, 3.2, "I don't like the look of this.", "我不喜欢这件事的迹象。"),
           (16.0, 17.2, "You can't be serious.", "你不是认真的吧。"),
           (24.0, 25.2, "I am perfectly serious.", "我是非常认真的。"),
           (28.0, 29.2, "It's a matter of principle.", "这是原则问题。")]
    with open(f"{FX}/dlg.srt", "w", encoding="utf-8") as f:
        for i, (st, en, s, c) in enumerate(dlg, 1):
            f.write(f"{i}\n{srt_t(st)} --> {srt_t(en)}\n{s}\n{c}\n\n")
    with open(f"{FX}/dlg.tsv", "w", encoding="utf-8") as f:
        f.write("idx\tstart\tend\ttext\n")
        for i, (st, en, s, c) in enumerate(dlg, 1):
            f.write(f"{i}\t{st:.2f}\t{en:.2f}\t{c}\n")

    json.dump(PLAN, open(f"{FX}/plan.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # 桩环境：测试一律走 stub，不联网、不读用户 .env
    open(f"{FX}/env.sh", "w", encoding="utf-8").write(
        "#!/bin/sh\n"
        "# source 之后 narration.py / probe.py 走离线桩\n"
        f"export COMMENTARY_TTS={HERE}/stub/tts.py\n"
        f"export COMMENTARY_ASR={HERE}/stub/asr.py\n"
        f"export FIXTURE_ASR_DIR={FX}/narration\n"
        f"export FIXTURE_TTS_LOG={FX}/tts_calls.log\n"
        f"export FIXTURE_ASR_LOG={FX}/asr_calls.log\n"
        # 分块/探测类调用没有对应文本文件，给个兜底台词
        "export FIXTURE_ASR_TEXT=\"桩听到的一句台词\"\n")

    # 自检：切点必须能被骨架里的检测命令找到
    raw = f"{FX}/_cuts.raw"
    sh(["ffmpeg", "-v", "error", "-y", "-i", f"{FX}/src.mp4",
        "-vf", f"select='gt(scene,0.35)',metadata=print:file={raw}", "-an", "-f", "null", "-"])
    import re
    cuts = sorted({round(float(m.group(1)), 2) for m in re.finditer(r"pts_time:([\d.]+)", open(raw).read())})
    os.remove(raw)
    d = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
            f"{FX}/src.mp4"]).stdout.strip()
    print(f"{FX}/src.mp4  时长 {float(d):.2f}s  检测到切点 {cuts}")
    if speech:
        print(f"假台词 {len(speech)} 句，第一句 {speech[0]}，最后一句 {speech[-1]}")
    print(f"解说词 {len(NARRATION)} 段、plan.json {len(PLAN['items'])} 个片段（四种条目）")
    if [round(c) for c in cuts[:3]] != [8, 16, 24]:
        sys.exit(f"素材异常：期望切点 8/16/24，实测 {cuts}")
    print("素材自检通过")


if __name__ == "__main__":
    main()
