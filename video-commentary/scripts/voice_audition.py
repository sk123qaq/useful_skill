#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""音色试听样音：用同一段 ~20 秒解说词、同一语境指令，只换音色生成一批样音，供用户挑选。

用法:
  python3 voice_audition.py --text-file sample.txt --out ./voice_samples
  python3 voice_audition.py --text "《是，大臣》…" --voices elegantgentle-female,zixinnansheng
  python3 voice_audition.py --list                       # 只看内置候选音色

输出: NN_中文名_voiceid.mp3 + 00_试听合集.mp3 + 试听清单.txt（含时长/语速/基频，便于客观比较）
"""
import argparse, array, os, re, subprocess, sys, time, wave
from concurrent.futures import ThreadPoolExecutor

TTS = os.environ.get("COMMENTARY_TTS",
                     os.path.expanduser("~/.agents/skills/stepaudio-tts/scripts/tts.py"))
INS = "影视解说旁白，温婉清晰，语速中等"

# 国际版明列的 7 个音色 + 常见国内音色（不可用的会被标出来，不影响其余）
CANDIDATES = [
    ("elegantgentle-female", "气质温婉", "女｜当前默认"), ("livelybreezy-female", "活力轻快", "女"),
    ("lively-girl", "灵动少女", "女"), ("zixinnansheng", "自信男声", "男"),
    ("magnetic-voiced-male", "磁性男声", "男｜低沉"), ("soft-spoken-gentleman", "轻声绅士", "男"),
    ("vibrant-youth", "朝气青年", "男"), ("ruyananshi", "儒雅男士", "男｜叙述感强"),
    ("boyinnansheng", "播音男声", "男｜播音腔"), ("cixingnansheng", "磁性男声(国内)", "男"),
    ("lengyanyujie", "冷艳御姐", "女｜播音感"), ("ganliannvsheng", "干练女声", "女"),
    ("wenjingxuejie", "文静学姐", "女"), ("youyanvsheng", "优雅女声", "女"),
]


def dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def units(text):
    """音节近似：汉字 + 字母 + 数字"""
    return len(re.sub(r"[^\u4e00-\u9fff]", "", text)) + len(re.findall(r"[A-Za-z0-9]", text))


def mean_f0(path):
    """粗估基频中位数（Hz）：低沉 <120、正常 120-170、明亮 >190"""
    w = f"{path}.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-ac", "1", "-ar", "16000", w], check=True)
    with wave.open(w) as f:
        data = array.array("h", f.readframes(f.getnframes()))
    os.remove(w)
    sr, win, hop, f0s = 16000, 640, 320, []
    for s in range(0, len(data) - win, hop):
        seg = data[s:s + win]
        if sum(x * x for x in seg) / win < 3e5:
            continue
        best, bl = 0, 0
        for lag in range(28, 300):
            c = sum(seg[i] * seg[i - lag] for i in range(lag, win, 2))
            if c > best:
                best, bl = c, lag
        if bl:
            f0s.append(sr / bl)
    f0s.sort()
    return f0s[len(f0s) // 2] if f0s else 0


def synth(tts, voice, text, ins, out, speed=1.0, tries=3):
    for i in range(tries):
        r = subprocess.run([sys.executable, tts, text, "--voice", voice, "--instruction", ins,
                            "--speed", str(speed), "--out", out], capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 5000:
            return True, ""
        time.sleep(2 + i * 3)
    return False, (r.stderr.strip()[:110] if r else "?")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    ap.add_argument("--text-file")
    ap.add_argument("--voices", help="逗号分隔的音色 id；不给就用内置候选")
    ap.add_argument("--instruction", default=INS)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--out", default="./voice_samples")
    ap.add_argument("-j", "--jobs", type=int, default=3)
    ap.add_argument("--tts", default=TTS)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        for v, n, note in CANDIDATES:
            print(f"{v:24s} {n:12s} {note}")
        return

    text = a.text or (open(a.text_file).read().strip() if a.text_file else None)
    if not text:
        ap.error("需要 --text 或 --text-file")
    n_units = units(text)

    want = [v.strip() for v in a.voices.split(",")] if a.voices else [c[0] for c in CANDIDATES]
    name_of = {v: (n, note) for v, n, note in CANDIDATES}
    os.makedirs(a.out, exist_ok=True)

    def job(i_v):
        i, v = i_v
        out = f"{a.out}/{i:02d}_{name_of.get(v, ('', ''))[0] or v}_{v}.mp3"
        ok, err = synth(a.tts, v, text, a.instruction, out, a.speed)
        if not ok:
            return (i, v, name_of.get(v, ("", ""))[0], None, None, None, err)
        d = dur(out)
        return (i, v, name_of.get(v, ("", ""))[0], d, n_units / d, mean_f0(out), "")

    rows = []
    with ThreadPoolExecutor(a.jobs) as ex:
        for r in ex.map(job, list(enumerate(want, 1))):
            rows.append(r)
            i, v, nm, d, cps, f0, err = r
            print(f"{i:02d} {nm or v:14s} " + (f"{v:22s} {d:6.2f}s {cps:.2f}单位/秒 F0≈{f0:.0f}Hz"
                                               if d else f"★不可用：{err}"), flush=True)

    lines = ["音色试听样音（同一段解说词，同一语境指令）", f"样本文本（{n_units} 单位）：{text}",
             f"语境指令：{a.instruction}（speed={a.speed}）", ""]
    for i, v, nm, d, cps, f0, err in rows:
        lines.append(f"{i:02d} {nm or v:12s} {v:24s} " +
                     (f"{d:6.2f}s {cps:.2f}单位/秒 {f0:.0f}Hz" if d else f"★不可用 {err}"))
    ok_files = [f"{a.out}/{i:02d}_{nm or v}_{v}.mp3" for i, v, nm, d, cps, f0, err in rows if d]
    lines += ["", "播放顺序 = 序号顺序（00_试听合集.mp3 为连续试听）"]
    open(f"{a.out}/试听清单.txt", "w").write("\n".join(lines) + "\n")

    if ok_files:
        ins, labels = [], []
        for i, f in enumerate(ok_files):
            ins += ["-i", f]
            labels.append(f"[{i}:a]")
        flt = "".join(labels) + f"concat=n={len(ok_files)}:v=0:a=1[a]"
        subprocess.run(["ffmpeg", "-v", "error", "-y"] + ins + ["-filter_complex", flt, "-map", "[a]",
                       "-c:a", "libmp3lame", "-b:a", "128k", f"{a.out}/00_试听合集.mp3"], check=True)
        print("合集:", f"{a.out}/00_试听合集.mp3", f"{dur(a.out + '/00_试听合集.mp3'):.1f}s")
    print("清单:", f"{a.out}/试听清单.txt")


if __name__ == "__main__":
    main()
