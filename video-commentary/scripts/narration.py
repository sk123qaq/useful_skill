#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解说配音流水线：逐段 TTS → ASR 回读校验 → 吐字率/停顿归一 → 电平归一。

用法:
    python3 narration.py --dir narration --out norm \
            --voice elegantgentle-female --instruction "影视解说旁白，温婉清晰，语速中等" \
            --target-cps 4.4 --target-artic 5.35 --target-db -15.5
    python3 narration.py --only n04 --force          # 只重做某段
    python3 narration.py --extra-tts-args "--subtitles"

输出: <out>/<name>.wav（已按目标吐字率、停顿预算与电平归一）+ 一张核对表

为什么是 v2（修「语速忽快忽慢」）
--------------------------------
实测一集 34 段：旧版把「整段语速 = 单位数/整段时长」全部归一到 4.40，看起来完美，
但**净吐字率**（剔除停顿后的 单位数/发声时长）散布在 4.7–6.2，极差 40%。
听众感知的"语速"是后者——"说得快但停顿多"和"说得慢但不换气"在旧指标下得分相同。
顺着这条线还有两个次因：
  * 逐段 `--speed` 乱跳（旧版有 12/34 段用了 0.99–1.31 的不同值）。speed 不止改速率，
    连重音、语调、停顿位置一起改，是音色质感不一致的来源。
  * 停顿密度不归一（0–4.1s / 段），配合不固定的电平测量口径，进一步放大差异。

v2 的三条对策：
  1) 归一化对象改为**净吐字率** `--target-artic`（默认 5.35 单位/发声秒）。
  2) `--speed` 全局唯一：先用 3 个固定探针句测出「该音色+该指令」的自发语速，
     迭代推出唯一全局 speed 并缓存到 <audio_dir>/.pacing.json，残差全部交给
     atempo（WSOLA 时域拉伸，只改时钟、不改语气形状）。
  3) 停顿预算显式归一：内部停顿总量 = U/--target-cps - U/--target-artic - 头 - 尾，
     单个停顿按比例缩放到 [--pause-min, --pause-max] 且涨幅 ≤1.8×、缩幅 ≥0.55×，
     吸收不下的余额进尾静音。**总时长仍是 U/--target-cps，时间轴/字幕不用重排。**

实现要点
--------
  * 词级时间戳拿不到：StepFun 国际版端点忽略 `--subtitles`（timestamp/return_url
    均不返回 subtitles 字段，SSE 模式只有 speech.audio.delta），已实测确认。
    所以静音边界用 ffmpeg silencedetect 在本地估，停顿重建全部离线完成。
  * atempo 只做一次、且作用在整段上，保证每个音节的时间关系不被二次扭曲；
    之后只做「按检测到的静音区间改长度」的拼接，语音样本本身不再被改动，
    因此不会引入切片爆音。拼接用 stdlib wave 直接写，无临时文件轰炸。
  * 电平按**净发声段**的平均绝对值测量（旧版测整段，停顿多的段会被多补增益，
    导致说话时响度不一致）。探针 -42dB / 0.15s：只认短语级停顿，
    0.15s 以下的气口不当停顿处理，避免把词中间隙拉长。

缓存与凭据（v3）
----------------
  * `<audio_dir>/.meta.json`：每段的**内容指纹** = sha1(文本 + 音色 + 指令 + speed)。
    指纹变了就重新合成——旧版只看 mp3 在不在，导致"换了 --voice 却照用旧音色"，
    而技能明确支持"换音色重出片"这个用法。
  * `<out>/manifest.json`：本轮产出、**验过**的段（dur / 吐字率 / 覆盖率 / sha1 / 指纹）。
    timeline.py 只认 manifest 里的段，半成品和没验过的段进不了剪辑。
"""

import argparse
import array
import hashlib
import json
import math
import os
import re
import subprocess
import statistics
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor

import skillcfg
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

TTS = os.environ.get("COMMENTARY_TTS",
                     os.path.expanduser("~/.agents/skills/stepaudio-tts/scripts/tts.py"))
ASR = os.environ.get("COMMENTARY_ASR",
                     os.path.join(os.path.dirname(os.path.abspath(__file__)), "asr_qwen.py"))

# 语速探针：固定文本、与解说内容无关，用来标定「这个音色 + 这条指令」的自发语速。
# 取 3 句平均以降噪；长度取解说词的常见区间（35–45 字）。
PROBES = [
    "夜色降临，城市的灯火次第亮起，街道上的车流渐渐稀了，一天的喧嚣终于慢慢退去。",
    "他放下手里的笔，抬头看向窗外，沉默了许久，才缓缓开口说出那个藏了很久的决定。",
    "数据不会说谎，但它也不会主动开口，所有被忽略的细节，最后都变成了代价。",
]

CN_DIGIT = {"零": "0", "〇": "0", "一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
            "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
CN_UNIT = {"十": 10, "百": 100, "千": 1000}
CN_NUM = "零〇一二三四五六七八九十百千万亿两"
CN_DIGITS_ONLY = "零〇一二三四五六七八九两"
# 数字串 = 两个以上的中文数字（一九七九/十五/两万三千），或单个数字字（五→5）；
# 孤立的 十/百/千/万 不单独换算，避免把「百货」这类词拆得莫名其妙。
NUM_RUN = re.compile(f"[{CN_NUM}]{{2,}}|[{CN_DIGITS_ONLY}]")


def cn_run_to_num(s):
    """中文数字串 → 阿拉伯数字串（两种写法都认）。

      * 逐位念的年份/编号：一九七九 → 1979、二〇〇一 → 2001
      * 带单位的数量：两万三千 → 23000、十五 → 15、二百一十九 → 219

    为什么要它：ASR 的 ITN 会把「一九七九年」回读成「1979年」，不做这个归一，
    覆盖率就永远差那么几格（实测 0.87 < 0.90 阈值）——而覆盖率低会被判成
    "TTS 被服务端截断"，白重合成一遍还进不了 manifest。pipeline-notes 里
    "用 asr.py --no-itn 手工回读" 那条土办法，实测国际版端点也不生效
    （--no-itn 仍然回 1979年），所以只能在比较前归一。
    """
    s = s.strip()
    if not s or s.isdigit():
        return s
    if any(c in CN_UNIT or c in "万亿" for c in s):
        # 亿/万 各自断节（一亿二千万 = 1.2 亿），节内再累加 十/百/千
        result = section = cur = 0
        for ch in s:
            if ch in CN_DIGIT:
                cur = int(CN_DIGIT[ch])
            elif ch in CN_UNIT:
                section += (cur or 1) * CN_UNIT[ch]
                cur = 0
            elif ch in "万亿":
                result += (section + cur) * (10000 if ch == "万" else 100000000)
                section = cur = 0
        return str(result + section + cur)
    return "".join(CN_DIGIT.get(c, "") for c in s)


def _big_arabic(m):
    """阿拉伯数字 + 万/亿（10万、3.5亿）→ 整数串，与中文写法（十万、三点五亿）对齐。

    为什么要它：ASR 回读常把「十万」写成「10万」，旧版 canon 只认中文，两边归一后
    一个是 100000、一个是「10万」，覆盖率白白掉下去（第六集 ad1 因此 0.87）。
    """
    v = float(m.group(1)) * (10000 if m.group(2) == "万" else 100000000)
    return str(int(round(v))) if abs(v - round(v)) < 1e-6 else str(v)


def canon(s):
    """比较用规范化：中文数字转阿拉伯数字，只留汉字/字母/数字/%（ASR 会把"百分之五"写成 5%）"""
    def pct(m):
        # 百分之五 == 5%；百分之三点五 == 3.5%
        head, _, tail = m.group(1).partition("点")
        num = cn_run_to_num(head) + ("." + cn_run_to_num(tail) if tail else "")
        return num + "%"

    s = re.sub(r"百分之\s*([" + CN_NUM + r"\d]+(?:点[" + CN_NUM + r"\d]+)?)", pct, s)
    s = re.sub(r"(\d+(?:\.\d+)?)([万亿])", _big_arabic, s)
    s = NUM_RUN.sub(lambda m: cn_run_to_num(m.group(0)), s)
    return re.sub(r"[^0-9A-Za-z%.\u4e00-\u9fff]", "", s).lower()   # ASR 大小写不稳，比较一律小写


def units(text):
    """音节近似：汉字 + 字母 + 数字。字母必须算——CMG 会被逐字母念出来"""
    return len(re.sub(r"[^\u4e00-\u9fff]", "", text)) + len(re.findall(r"[A-Za-z0-9]", text))


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def dur(p):
    if not os.path.exists(p):
        return 0.0
    r = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p])
    return float(r.stdout.strip() or 0)


def selfcheck(path, U, cp):
    """成品回读自检。返回错误信息字符串，全部通过返回 None。

    刻意走与 repace 不同的路径：repace 用自己拼出来的段表，这里重新 silencedetect
    量成品文件，所以能抓住"拼错了但内部自洽"的那类 bug。
    """
    total, spans = silence_map(path, -50.0, 0.06)   # 比生产参数更严，避免自我循环论证
    if total <= 0.05:
        return "成品为空"
    lead = spans[0][1] if spans and spans[0][0] <= 1e-3 else 0.0
    tail = total - spans[-1][0] if spans and spans[-1][1] >= total - 1e-3 else 0.0
    inner = [b - a for a, b in spans if a > 1e-3 and b < total - 1e-3]
    speech = total - lead - tail - sum(inner)
    if speech <= 0.05:
        return f"成品净发声只有 {speech:.2f}s"
    art = U / speech
    D = U / cp.target_cps
    pos, runs = 0.0, []
    for a, b in spans:
        if a > 1e-3 and b < total - 1e-3:
            runs.append(a - pos)
            pos = b
    runs.append(total - pos)
    run = max(runs) if runs else total
    bad = []
    if abs(art - cp.target_artic) > 0.30:
        bad.append(f"净吐字率 {art:.2f} ≠ 目标 {cp.target_artic}")
    if abs(total - D) > 0.06:
        bad.append(f"总时长 {total:.3f}s ≠ 目标 {D:.3f}s（差 {total-D:+.3f}s）")
    if run > cp.max_run + 0.40:
        bad.append(f"最长连续发声 {run:.2f}s 远超 --max-run {cp.max_run}")
    return "；".join(bad) if bad else None


# ---------------------------------------------------------------- WAV 读写
def read_wav(p):
    import wave
    with wave.open(p, "rb") as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        if ch != 1 or sw != 2:
            raise RuntimeError(f"{p}: 需要 16bit 单声道 wav（实际 {ch}ch/{sw*8}bit）")
        a = array.array("h")
        a.frombytes(w.readframes(n))
    if sys.byteorder == "big":
        a.byteswap()
    return a, sr


def write_wav(p, a, sr):
    import wave
    if sys.byteorder == "big":
        a.byteswap()
    with wave.open(p, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(a.tobytes())
    if sys.byteorder == "big":
        a.byteswap()


def speech_rms_db(a):
    """净发声段 RMS（dBFS）。

    口径说明：ffmpeg volumedetect 的 mean_volume 其实是 RMS 而不是平均绝对值
    （0.5 幅度正弦实测 -27.10 dB = 20*log10(0.0625/√2)），所以这里用 RMS 才能和
    --target-db 的语义对上。
    """
    if not a:
        return -99.0
    s = 0
    for x in a:
        s += x * x
    return 20.0 * math.log10(math.sqrt(s / len(a)) / 32768.0) if s else -99.0


# ---------------------------------------------------------------- 静音分析
def silence_map(p, db, dmin):
    """→ (总时长, [(start,end), ...] 全部静音区间按时序)

    只认 >= dmin 的静音，因此 0.15s 以下的气口/爆破音闭合不当停顿处理。
    """
    r = sh(["ffmpeg", "-hide_banner", "-i", p, "-af",
            f"silencedetect=noise={db}dB:d={dmin}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", r.stderr)]
    total = dur(p)
    spans = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else total
        if e - s > 1e-4:
            spans.append((s, e))
    return total, spans


def envelope_db(a, sr, win=0.02):
    """20ms 帧 RMS 电平（dBFS）序列，用于找段内自然谷点。"""
    n = max(1, int(sr * win))
    out = []
    for i in range(0, len(a) - n + 1, n):
        s = 0
        for v in a[i:i + n]:
            s += v * v
        out.append(20.0 * math.log10(math.sqrt(s / n) / 32768.0) if s else -99.0)
    return out


def quietest_offset(a, sr, margin=0.35, win=0.02, min_dip=8.0):
    """在 a 中找最安静的采样偏移（避开两端 margin 秒）；谷点不够深则返回 None。

    连续发声段往往不是真的没有边界，只是气口太浅、没过静音阈值。
    直接在最深谷点下刀，比按字数硬切安全得多。
    """
    n = max(1, int(sr * win))
    if len(a) < n * 2 + int(sr * 2 * margin):
        return None
    e = envelope_db(a, sr, win)
    lo, hi = int(margin / win), len(e) - int(margin / win)
    if hi - lo < 2:
        return None
    mid = sorted(e[lo:hi])[(hi - lo) // 2]
    k = min(range(lo, hi), key=lambda i: e[i])
    if mid - e[k] < min_dip:
        return None
    return k * n


def split_long_runs(segs, cp, sr):
    """把超过 cp.max_run 的连续发声段在最安静处劈开、插入 cp.split_pause 秒停顿。

    返回 (segs, 追加的停顿秒数)。为什么要这个：吐字率归一只管"说"有多快，
    管不了 TTS 把话连成多长一口气。实测一集里最长连续发声 1.5–6.9s 不等，
    连续发声越长，听感越像"赶着说完"——即使每秒字数完全一致。
    """
    if cp.max_run <= 0:
        return segs, 0.0
    out, added = [], 0.0
    for kind, data, tag in segs:
        if kind != "S":
            out.append((kind, data, tag))
            continue
        guard = 0
        while len(data) / sr > cp.max_run and guard < 8:
            guard += 1
            k = quietest_offset(data, sr, cp.split_margin, 0.02, cp.split_dip)
            if not k or k >= len(data):
                break
            out.append(("S", data[:k], ""))
            out.append(("P", cp.split_pause, "ins"))
            added += cp.split_pause
            data = data[k:]
        out.append(("S", data, ""))
    return out, added


def fit_durations(durs, target, lo, hi, grow, shrink, iters=60):
    """按比例把 durs 总和拉到 target；每个值同时受 [lo,hi] 与 [shrink*d, grow*d] 约束。
    装不下的部分由调用方处理（返回实际可达的最接近值）。"""
    if not durs:
        return []
    los = [max(lo, d * shrink) for d in durs]
    his = [max(l, min(hi, d * grow)) for d, l in zip(durs, los)]
    durs = [min(h, max(l, d)) for d, l, h in zip(durs, los, his)]
    for _ in range(iters):
        s = sum(durs)
        if abs(s - target) < 0.004:
            break
        if s < target:
            free = [i for i in range(len(durs)) if durs[i] < his[i] - 1e-6]
            if not free:
                break
            room = sum(his[i] - durs[i] for i in free)
            need = min(target - s, room)
            for i in free:
                durs[i] += need * (his[i] - durs[i]) / room
        else:
            free = [i for i in range(len(durs)) if durs[i] > los[i] + 1e-6]
            if not free:
                break
            room = sum(durs[i] - los[i] for i in free)
            cut = min(s - target, room)
            for i in free:
                durs[i] -= cut * (durs[i] - los[i]) / room
    return durs


# ---------------------------------------------------------------- 核心：重排
def repace(src, out, U, cp):
    """把 src 重排成目标吐字率 + 目标停顿预算，写 out。返回统计 dict。"""
    total, spans = silence_map(src, cp.silence_db, cp.silence_min)
    if total <= 0.05:
        raise RuntimeError(f"音频文件是空的（{os.path.basename(src)}）——TTS 可能没返回内容")
    speech0 = total - sum(b - a for a, b in spans)
    if speech0 <= 0.05:
        raise RuntimeError("整段都是静音——TTS 可能返回了空音频（重试或把这段按句号拆开）")
    artic0 = U / speech0

    atempo = min(cp.atempo_max, max(cp.atempo_min, cp.target_artic / artic0))

    # 1) 整段 atempo —— 只此一次，语气形状（重音/起伏）不被二次扭曲
    tmp = out + ".scaled.wav"
    r = sh(["ffmpeg", "-v", "error", "-y", "-i", src, "-af", f"atempo={atempo:.5f}",
            "-ar", str(cp.sr), "-ac", "1", "-c:a", "pcm_s16le", tmp])
    if r.returncode != 0 or not os.path.exists(tmp):
        raise RuntimeError("atempo 失败: " + r.stderr.strip()[:200])
    total1, spans1 = silence_map(tmp, cp.silence_db, cp.silence_min)
    samp, sr = read_wav(tmp)

    # 2) 停顿预算（内部停顿；头/尾另算）
    D = U / cp.target_cps
    # speech_total 由后面拼装后的 S 段实际样本数得出

    # 3) 先切长跑，再排停顿预算——插入的停顿也要占预算，否则总时长会超
    segs, pos = [], 0
    for i, (a, b) in enumerate(spans1):
        if i == 0 and a <= 1e-3:
            tag, dur_ = "lead", cp.lead          # 起始静音归一成固定值
        elif i == len(spans1) - 1 and b >= total1 - 1e-3:
            tag, dur_ = "tail", b - a            # 结束静音长度最后再定
        else:
            tag, dur_ = "det", b - a
        i0 = max(pos, min(int(round(a * sr)), len(samp)))
        i1 = max(i0, min(int(round(b * sr)), len(samp)))
        if i0 > pos:
            segs.append(("S", samp[pos:i0], ""))
        segs.append(("P", dur_, tag))
        pos = i1
    if pos < len(samp):
        segs.append(("S", samp[pos:], ""))

    segs, extra = split_long_runs(segs, cp, sr)
    speech_a = array.array("h")
    for kind, data, _ in segs:
        if kind == "S":
            speech_a.extend(data)
    speech_s = len(speech_a) / sr

    det_idx = [i for i, (k, _, t) in enumerate(segs) if k == "P" and t == "det"]
    budget = D - cp.lead - cp.tail_min - speech_s - extra
    fitted = fit_durations([segs[i][1] for i in det_idx], budget,
                           cp.pause_min, cp.pause_max, cp.pause_grow, cp.pause_shrink)
    if sum(fitted) > budget + 0.004:
        # 停顿地板（pause_min / shrink）把预算托住了 → 总时长会超。
        # 宁可让停顿比目标略短，也不能让时长漂：时长一漂，timeline 的镜头吸附和
        # 字幕边界全都会跟着偏。所以放开下限再拟合一次。
        fitted = fit_durations(fitted, budget, 0.05, cp.pause_max, 1.0, 0.25)
    for i, d in zip(det_idx, fitted):
        segs[i] = ("P", d, "det")

    # 4) 拼装：语音样本原样搬运，静音段按目标长度改 → 无切片爆音。
    #    末尾静音整段丢弃（长度由下面 tail 重新决定）。
    out_a = array.array("h")
    for kind, data, tag in segs:
        if kind == "S":
            out_a.extend(data)
        elif tag != "tail":
            out_a.extend(array.array("h", bytes(2 * int(round(data * sr)))))
    used = sum(d for k, d, t in segs if k == "P" and t != "tail")

    # 尾部静音吃掉预算余额，保证总时长 == U/target_cps。
    # 注意 used 已含 lead，不能再减一次 cp.lead。
    tail = D - speech_s - used
    if tail < 0:
        # 预算装不下（多半是 pause_min/shrink 把停顿托住了）：先压缩插入的停顿，
        # 它们最可牺牲；仍不够才认下这点超时。
        deficit = -tail
        for i, (k, _, t) in enumerate(segs):
            if deficit <= 0.002 or k != "P" or t != "ins":
                continue
            room = segs[i][1] - 0.15
            if room <= 0:
                continue
            cut = min(room, deficit)
            segs[i] = ("P", segs[i][1] - cut, "ins")
            deficit -= cut
        used = sum(d for k, d, t in segs if k == "P" and t != "tail")
        tail = max(0.0, D - speech_s - used)
    out_a.extend(array.array("h", bytes(2 * int(round(tail * sr)))))
    write_wav(out, out_a, sr)

    # 4) 电平。两种模式，默认 auto —— 与旧版逐字节等价，不改变你已有成片的响度：
    #    auto   : volume + alimiter(level=1)。alimiter 默认开自动电平，会把每段
    #             峰值顶到 0dBFS，--target-db 只是它之前的一次相对增益（旧版就是这样，
    #             所以 -15.5 从来没真正生效过，成片实际是峰值归一，RMS≈-10.4dB）。
    #    speech : alimiter level=disabled，--target-db 真正生效，按净发声 RMS 归一，
    #             说话时的响度一致（峰值归一会被个别响音带偏）。峰值留 0.9dB 余量，
    #             对 AAC 编码更安全。
    lvl = speech_rms_db(speech_a)
    gain = 0.0 if cp.no_gain else max(0.0, min(16.0, cp.target_db - lvl))
    final = out + ".g.wav"
    lim = "alimiter=limit=0.90" if cp.level_mode == "auto" else "alimiter=limit=0.90:level=disabled"
    sh(["ffmpeg", "-v", "error", "-y", "-i", out, "-af",
        f"volume={gain:.2f}dB,{lim},aresample={cp.sr}", "-ac", "1", final])
    os.replace(final, out)
    for junk in (tmp,):
        if os.path.exists(junk):
            os.remove(junk)

    # 5) 自检：用独立测量回读成品，任一项不在容差内就报错。
    #    本次开发教训：sil_db 命名错、fit_durations 定义被吞、lead 被减两次、inner_idx
    #    残留——4 个 bug 全是静默的，全靠事后手工 ffmpeg 量才发现。与其靠人记得量，
    #    不如在这里直接断言。
    chk = selfcheck(out, U, cp)
    if chk:
        raise RuntimeError(chk)

    total_f = dur(out)
    return dict(artic0=artic0, atempo=atempo, speech0=speech0, speech1=speech_s,
                run=max((len(d) / sr for k, d, _ in segs if k == "S"), default=0.0),
                nsplit=sum(1 for k, _, t in segs if k == "P" and t == "ins"),
                pause0=sum(b - a for a, b in spans1 if a > 1e-3 and b < total1 - 1e-3),
                pause1=used, npause=len(det_idx), lead=cp.lead, tail=tail,
                total=total_f, cps=U / total_f if total_f else 0.0,
                artic=U / (len(speech_a) / sr) if speech_a else 0.0,
                gain=gain, rms=lvl)


# ---------------------------------------------------------------- 全局语速标定
def calib_from_dir(d, a):
    """用目录里已有的 mp3 实测中位吐字率反推全局 speed（零 API 成本，样本量远大于探针）。

    返回 (median_artic, speed) 或 None。注意：若那些 mp3 是用不同 --speed 合成的，
    各种速度大致对冲后中位数仍然可用，但不如 .speeds.json 记录的精确。
    """
    if not os.path.isdir(d):
        return None
    arts = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".mp3") or f.startswith("."):
            continue
        tp = os.path.join(a.dir, f[:-4] + ".txt")
        if not os.path.exists(tp):
            continue
        u = units(open(tp, encoding="utf-8").read().strip())
        tot, spans = silence_map(os.path.join(d, f), a.silence_db, a.silence_min)
        sp = tot - sum(b - x for x, b in spans)
        if sp > 0.05:
            arts.append(u / sp)
    if len(arts) < 5:
        return None
    med = statistics.median(arts)
    return med, max(0.75, min(1.35, a.speed * (a.target_artic / med)))


def pick_pilot_units(d, k, min_units=24):
    """配音前标定用的代表段：按字数从短到长取 k 个分位点，优先选 >= min_units 的段。

    太短的段停顿占比大，测出的吐字率不可信，而它们也正是拉伸风险最大的那批，所以不用来标定。
    """
    rows = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".txt"):
            t = open(os.path.join(d, f), encoding="utf-8").read().strip()
            if t:
                rows.append((units(t), f[:-4], t))
    pool = sorted(r for r in rows if r[0] >= min_units) or sorted(rows)
    if len(pool) <= k:
        return pool
    return [pool[round(i * (len(pool) - 1) / (k - 1))] for i in range(k)]


def pilot_global_speed(a, cache_path, key):
    """配音前标定：k 段真实解说在 speed0 下各合成一次，取净吐字率中位数，一步算出全局 speed。

    为什么不用固定探针句：探针句的停顿与真实解说不同，第六集实测偏差约 0.1 单位/秒，
    结果是「全量 → 发现偏差 → 再全量」白跑一轮。这里用的就是正式要配的文本。
    只做 k 次 TTS、不做 ASR 回读；样本是 .pilot_*.mp3，不进 manifest。
    """
    picks = pick_pilot_units(a.dir, a.pilot)
    if len(picks) < 3:
        return None
    s0 = a.speed

    def one(item):
        n, nm, t = item
        p = os.path.join(a.audio_dir, f".pilot_{nm}.mp3")
        ok, _ = synth(a.tts, a.voice, t, a.instruction, p, s0, a.extra)
        if not ok:
            return nm, None
        tot, spans = silence_map(p, a.silence_db, a.silence_min)
        sp = tot - sum(b - x for x, b in spans)
        return nm, (n / sp if sp > 0.05 else None)

    with ThreadPoolExecutor(max(1, min(a.jobs, len(picks)))) as ex:
        res = list(ex.map(one, picks))
    arts = [x for _, x in res if x]
    if len(arts) < 3:
        return None
    med = statistics.median(arts)
    s1 = round(max(0.75, min(1.35, s0 * (a.target_artic / med))), 3)
    try:
        json.dump(dict(key, speed=s1, pilot=dict(units=[nm for nm, _ in res], speed0=s0,
                                                  artic=[round(x, 3) for x in arts],
                                                  median=round(med, 3))),
                  open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass
    return s1, f"pilot：{len(arts)} 段真实解说在 speed {s0} 下的中位净吐字率 {med:.2f}"


def probe_global_speed(a):
    """全局 --speed 的来源（优先级）：profile（同音色同指令）> 缓存 > 已有 mp3 反推 > pilot > 3 句探针。

    结果缓存到 <audio_dir>/.pacing.json；profile 命中时不写缓存（所以不会触发下面的修正）。
    """
    cache_path = os.path.join(a.audio_dir, ".pacing.json")
    a.cache_path = cache_path
    key = dict(voice=a.voice, instruction=a.instruction, target_artic=a.target_artic)
    prof = getattr(a, "profile", None) or {}
    if (not a.recalibrate and prof.get("speed")
            and all(prof.get(k) == v for k, v in key.items())):
        return float(prof["speed"]), f"profile（{os.path.basename(a.profile_path)}）"
    if os.path.exists(cache_path) and not a.recalibrate:
        try:
            c = json.load(open(cache_path, encoding="utf-8"))
            if all(c.get(k) == v for k, v in key.items()) and c.get("speed"):
                return float(c["speed"]), "缓存"
        except Exception:
            pass
    if a.calib_from:
        r = calib_from_dir(a.calib_from, a)
        if r:
            med, sp = r
            try:
                json.dump(dict(key, speed=round(sp, 3), calib_from=a.calib_from,
                               calib_artic=round(med, 3)),
                          open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            except Exception:
                pass
            return round(sp, 3), f"由 {a.calib_from} 的 {med:.2f} 单位/秒中位数反推"
        print(f"⚠ --calib-from {a.calib_from} 可用样本不足 5 个，改走探针", file=sys.stderr)
    if a.no_calib:
        return a.speed, "未标定(--no-calib)"
    if a.pilot >= 3:
        r = pilot_global_speed(a, cache_path, key)
        if r:
            return r
        print("⚠ pilot 样本不足，回退 3 句探针", file=sys.stderr)

    best = a.speed
    hist = []
    for rnd in range(2):
        arts = []
        for i, txt in enumerate(PROBES):
            p = os.path.join(a.audio_dir, f".probe_{i}.mp3")
            if a.force or not os.path.exists(p) or rnd > 0:
                ok, err = synth(a.tts, a.voice, txt, a.instruction, p, best, a.extra)
                if not ok:
                    print(f"  探针合成失败: {err}", file=sys.stderr)
                    return a.speed, "标定失败，回退 --speed"
            tot, spans = silence_map(p, a.silence_db, a.silence_min)
            sp = tot - sum(b - a for a, b in spans)
            if sp > 0.05:
                arts.append(units(txt) / sp)
        if not arts:
            return a.speed, "标定失败，回退 --speed"
        mean_art = sum(arts) / len(arts)
        hist.append(mean_art)
        nxt = max(0.75, min(1.35, best * (a.target_artic / mean_art)))
        if abs(nxt / best - 1) < 0.03:
            best = round(nxt, 3)
            break
        best = round(nxt, 3)
    try:
        json.dump(dict(key, speed=best, probe_artic=[round(x, 3) for x in hist]),
                  open(cache_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass
    return best, "探针标定"


# ---------------------------------------------------------------- 原样保留
def synth(tts, voice, text, ins, out, speed, extra=(), tries=3):
    for i in range(tries):
        cmd = [sys.executable, tts, text, "--voice", voice, "--instruction", ins,
               "--speed", str(speed), "--out", out] + list(extra)
        r = sh(cmd)
        if r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 5000:
            return True, ""
        time.sleep(2 + i * 3)
    return False, (r.stderr.strip()[:110] if r else "?")


def coverage(src_text, audio, asr, lang):
    r = sh([sys.executable, asr, audio] + (["--language", lang] if lang else []))
    got = canon(r.stdout)
    cs, ca = Counter(canon(src_text)), Counter(got)
    inter = sum(min(cs[c], ca[c]) for c in cs)
    return inter / max(1, len(canon(src_text))), r.stdout.strip()


# ---------------------------------------------------------------- 指纹与产物凭据
def sha1_file(p, n=1 << 20):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        while True:
            b = f.read(n)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def fingerprint(text, voice, ins, speed):
    """内容指纹：文本/音色/指令/speed 任一变化，旧音频就得作废重合成。"""
    return hashlib.sha1(f"{text}\x00{voice}\x00{ins}\x00{speed}".encode("utf-8")).hexdigest()[:16]


def discard(path):
    """删掉不可信的产物，别让半成品留在 norm/ 里被 timeline 当有效输入。"""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def process(name, a, report):
    src_txt = open(f"{a.dir}/{name}.txt", encoding="utf-8").read().strip()
    n = units(src_txt)
    fp = fingerprint(src_txt, a.voice, a.instruction, a.gspeed)
    raw = f"{a.audio_dir}/{name}.mp3"
    out = f"{a.out}/{name}.wav"

    meta = a.meta.get(name) or {}
    reuse = (not a.force) and os.path.exists(raw) and meta.get("fp") == fp
    fresh = not reuse
    if fresh:
        ok, err = synth(a.tts, a.voice, src_txt, a.instruction, raw, a.gspeed, a.extra)
        if not ok:
            discard(out)
            report.append(dict(name=name, n=n, err=f"TTS失败 {err}"))
            return False
        a.meta[name] = dict(fp=fp, voice=a.voice, instruction=a.instruction,
                            speed=a.gspeed, text=src_txt[:40])

    cov = txt = None
    if not a.no_verify:
        for _ in range(3):
            cov, txt = coverage(src_txt, raw, a.asr, a.language)
            if cov >= 0.90:
                break
            fresh = True
            ok, err = synth(a.tts, a.voice, src_txt, a.instruction, raw, a.gspeed, a.extra)
            if ok:
                a.meta[name] = dict(fp=fp, voice=a.voice, instruction=a.instruction,
                                    speed=a.gspeed, text=src_txt[:40])
            if not ok:
                break
    cp = a
    if a.cps_map.get(name):
        c = a.cps_map[name]
        if c >= a.target_artic:
            print(f"⚠ {name}: --cps-map 给的 {c} 不小于 --target-artic {a.target_artic}，"
                  f"没有停顿预算，这一段按全局目标跑", file=sys.stderr)
        else:
            import copy as _copy
            cp = _copy.copy(a)
            cp.target_cps = c
    try:
        r = repace(raw, out, n, cp)
    except Exception as e:
        discard(out)
        report.append(dict(name=name, n=n, err=f"重排失败 {e}"))
        return False
    if not r:
        discard(out)
        report.append(dict(name=name, n=n, err="重排没有产出（源音频不可用）"))
        return False

    r["name"], r["n"], r["cov"], r["fresh"] = name, n, cov, fresh
    r["verified"] = cov is None or cov >= 0.90
    r["cps_target"] = round(cp.target_cps, 2) if cp is not a else None
    r["sha1"] = sha1_file(out)
    report.append(r)
    a.manifest[name] = dict(verified=r["verified"], dur=round(r["total"], 3),
                            artic=round(r["artic"], 3), cps=round(r["cps"], 3),
                            cov=(None if cov is None else round(cov, 3)),
                            sha1=r["sha1"], fp=fp, voice=a.voice,
                            cps_target=r.get("cps_target"),
                            instruction=a.instruction, speed=a.gspeed)
    return r["verified"]


def cp_level_speech(a):
    return getattr(a, "level_mode", "auto") == "speech"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="./narration", help="解说词目录：每段一个 <name>.txt")
    ap.add_argument("--audio-dir", default="./audio", help="原始 TTS 输出目录")
    ap.add_argument("--out", default="./norm", help="归一后的 wav 目录（timeline.py 用它）")
    ap.add_argument("--voice", default="elegantgentle-female")
    ap.add_argument("--instruction", default="影视解说旁白，温婉清晰，语速中等")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="TTS 语速参数基准值（pilot 标定的起点）；标定结果是全局唯一值，见 profile.json")
    ap.add_argument("--global-speed", type=float, help="手动指定全局语速，跳过探针标定")
    ap.add_argument("--no-calib", action="store_true", help="不做探针标定，直接用 --speed")
    ap.add_argument("--calib-from", metavar="DIR",
                    help="改用 DIR 下已有 mp3 的实测中位吐字率反推全局 speed（零 API 成本，"
                         "比 3 句探针稳得多；样本需 >=5 个）")
    ap.add_argument("--target-cps", type=float, default=4.4,
                    help="目标整段节奏（单位/秒，含停顿）——决定总时长，时间轴按它排")
    ap.add_argument("--target-artic", type=float, default=5.35,
                    help="目标净吐字率（单位/发声秒，不含停顿）——决定听感语速")
    ap.add_argument("--pause-min", type=float, default=0.10, help="单个短语停顿下限（秒）")
    ap.add_argument("--pause-max", type=float, default=0.85, help="单个短语停顿上限（秒）")
    ap.add_argument("--pause-grow", type=float, default=2.2, help="单个停顿最多拉长几倍")
    ap.add_argument("--pause-shrink", type=float, default=0.50, help="单个停顿最多压到几折")
    ap.add_argument("--lead", type=float, default=0.12, help="每段起始静音（秒）")
    ap.add_argument("--tail-min", type=float, default=0.10, help="每段结束静音下限（秒）")
    ap.add_argument("--max-run", type=float, default=4.0,
                    help="最长连续发声（秒）。超过就在段内最安静的谷点插一个停顿，"
                         "避免 TTS 把话连成一口气听起来发赶；设 0 关闭。"
                         "默认 4.0：实测原片这种解说的天然一口气多在 2.2–3.3s（关掉插入量出来的），"
                         "阈值 2.8 会在正常句子上反复开火，而它挑的是\"最安静的谷点\"、不是语法边界，"
                         "偶发切在音节缝（如\"在萧条的｜边缘选区\"）。4.0 只在真长跑（案例里有 6.87s 的）上开火")
    ap.add_argument("--split-pause", type=float, default=0.26, help="插入停顿的时长（秒）")
    ap.add_argument("--split-dip", type=float, default=8.0,
                    help="谷点至少比段内中位低这么多 dB 才肯下刀（太浅说明不是真边界）")
    ap.add_argument("--split-margin", type=float, default=0.35, help="插入点距段首/段尾至少这么远（秒）")
    ap.add_argument("--silence-db", type=float, default=-42.0, help="静音判定阈值 dB")
    ap.add_argument("--silence-min", type=float, default=0.15,
                    help="静音最短时长（秒）；0.15 以下的气口不当停顿处理")
    ap.add_argument("--atempo-min", type=float, default=0.80)
    ap.add_argument("--atempo-max", type=float, default=1.25)
    ap.add_argument("--atempo-warn", type=float, default=0.12,
                    help="atempo 偏离 1 超过此值就在报表里提示拆句")
    ap.add_argument("--no-gain", action="store_true", help="跳过电平归一")
    ap.add_argument("--target-db", type=float, default=-15.5,
                    help="目标净发声电平（dB，RMS 口径）。--level-mode speech 时才真正生效")
    ap.add_argument("--level-mode", choices=["auto", "speech"], default="auto",
                    help="auto=复刻旧版（alimiter 自动电平顶到 0dBFS 峰值，响度与旧成片一致）；"
                         "speech=按净发声 RMS 归一，说话时响度更一致，峰值留 0.9dB 余量")
    ap.add_argument("--language", help="ASR 语言提示")
    ap.add_argument("--cps-map", metavar="JSON",
                    help="按段覆盖 --target-cps：{\"段名\": 4.6, ...}。高潮段快一点、收尾慢一点，"
                         "时长跟着解说词走（timeline 按实际 wav 排镜头）")
    ap.add_argument("--only", help="只处理某一段（逗号分隔）")
    ap.add_argument("-j", "--jobs", type=int, default=1,
                    help="并发处理的段数（TTS/ASR 都是网络调用，服务端限流约 8；建议 3-4）")
    ap.add_argument("--force", action="store_true", help="强制重新合成")
    ap.add_argument("--no-verify", action="store_true", help="跳过 ASR 回读校验（省时间，风险自负）")
    ap.add_argument("--sr", type=int, default=48000, help="输出采样率")
    ap.add_argument("--extra-tts-args", default="", help="透传给 TTS 脚本的额外参数，如 --subtitles")
    ap.add_argument("--tts", default=TTS)
    ap.add_argument("--asr", default=ASR)
    ap.add_argument("--profile", default=skillcfg.DEFAULT_PROFILE,
                    help="参数 profile（默认 skill 根目录的 profile.json；none=不用）。"
                         "profile 只给默认值，命令行显式参数优先")
    ap.add_argument("--pilot", type=int, default=5, metavar="N",
                    help="配音前用 N 段真实解说标定语速（默认 5；设 0 = 旧的 3 句探针）")
    ap.add_argument("--recalibrate", action="store_true",
                    help="忽略 profile 与缓存，重新标定语速（换音色、换素材时用）")
    # profile 要先于 parse_args 读出来，才能当作各参数的默认值
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--profile", default=skillcfg.DEFAULT_PROFILE)
    pk, _ = pre.parse_known_args()
    prof = skillcfg.load(pk.profile)
    ap.set_defaults(**skillcfg.narration_defaults(prof))
    a = ap.parse_args()
    a.profile, a.profile_path = prof, pk.profile
    a.extra = a.extra_tts_args.split() if a.extra_tts_args else []

    if a.target_artic <= a.target_cps:
        print(f"错误: --target-artic({a.target_artic}) 必须大于 --target-cps({a.target_cps})，"
              f"否则没有停顿预算可用", file=sys.stderr)
        sys.exit(2)
    try:
        a.cps_map = {str(k): float(v) for k, v in json.load(open(a.cps_map, encoding="utf-8")).items()} \
            if a.cps_map else {}
    except Exception as e:
        sys.exit(f"--cps-map 读不了：{e}")
    if a.cps_map:
        print(f"→ 逐段语速：{a.cps_map}（未列出的段用 --target-cps {a.target_cps}）")

    os.makedirs(a.audio_dir, exist_ok=True)
    os.makedirs(a.out, exist_ok=True)
    meta_path = os.path.join(a.audio_dir, ".meta.json")
    try:
        a.meta = json.load(open(meta_path, encoding="utf-8"))
    except Exception:
        a.meta = {}
    mf_path = os.path.join(a.out, "manifest.json")
    try:
        prev = json.load(open(mf_path, encoding="utf-8"))
        a.prev_manifest = prev.get("segments", {}) if isinstance(prev, dict) else {}
    except Exception:
        a.prev_manifest = {}
    a.manifest = {}

    a.gspeed, how = (a.global_speed, "手动指定") if a.global_speed else probe_global_speed(a)
    print(f"→ 全局 --speed = {a.gspeed}（{how}）", flush=True)

    names = ([x.strip() for x in a.only.split(",")] if a.only
             else sorted(f[:-4] for f in os.listdir(a.dir) if f.endswith(".txt")))
    names = [nm for nm in names if f"{nm}.txt" in os.listdir(a.dir)]
    jobs = max(1, min(6, a.jobs))
    if a.jobs > 6:
        print(f"⚠ --jobs {a.jobs} 超出服务端承受（约 8），已压到 {jobs}", file=sys.stderr)

    def work(nm):
        """单段的全部活（TTS + 回读校验 + 重排）。并发时每段互不依赖，只共享只增的 meta/manifest 字典。"""
        rep = []
        ok = process(nm, a, rep)
        return ok, rep

    report, bad = [], 0
    if jobs > 1 and len(names) > 1:
        print(f"→ {jobs} 路并发处理 {len(names)} 段", flush=True)
    with ThreadPoolExecutor(jobs) as ex:
        results = list(ex.map(work, names))
    for ok, rep in results:
        report.extend(rep)
        bad += 0 if ok else 1
        if not rep:
            print(f"{'?':10s} ★ 没有产出", flush=True)
            continue
        r = rep[-1]
        if r.get("err"):
            print(f"{r['name']:10s} {r['n']:4d}单位  ★ {r['err']}", flush=True)
            continue
        note = (f"cov={r['cov']:.2f}" if r["cov"] is not None else "未校验")
        if r["cov"] is not None and r["cov"] < 0.90:
            note += " ★覆盖率低，建议按句号拆成两段"
        if abs(r["atempo"] - 1) > a.atempo_warn:
            note += f" ★atempo{r['atempo']:.2f}偏离大，建议拆句"
        if r["run"] > a.max_run + 0.05:
            note += f" ★连续发声{r['run']:.2f}s未切开（没有足够深的谷点）"
        if r.get("nsplit"):
            note += f" 插入停顿{r['nsplit']}处"
        if r["gain"] > 0.5:
            note += f" gain=+{r['gain']:.1f}dB"
        if a.level_mode == "speech" and r.get("rms") is not None:
            note += f" RMS{r['rms']:.1f}dB"
        if r.get("cps_target"):
            note += f" 目标{r['cps_target']}/秒★"
        if not r["fresh"]:
            note += " ↺复用（指纹未变）"
        elif r["cov"] is not None:
            note += " ↻新合成"
        print(f"{r['name']:10s} {r['n']:4d}单位 吐字率{r['artic0']:.2f}→{r['artic']:.2f} "
              f"atempo{r['atempo']:.3f} 停顿{r['npause']}个 {r['pause0']:.2f}→{r['pause1']:.2f}s "
              f"连续发声≤{r['run']:.2f}s 尾{r['tail']:.2f}s 共{r['total']:6.2f}s({r['cps']:.2f}/秒)  {note}",
              flush=True)

    good = [r for r in report if not r.get("err")]
    if good:
        ar = [r["artic"] for r in good]
        tt = [r["total"] for r in good]
        cs = [r["cps"] for r in good]
        rr = [r["run"] for r in good]
        ns = [r.get("nsplit", 0) for r in good]
        print(f"→ 净吐字率 {min(ar):.2f}–{max(ar):.2f}（目标 {a.target_artic}，"
              f"极差 {max(ar)-min(ar):.2f}，CV "
              f"{statistics.pstdev(ar)/statistics.mean(ar)*100:.1f}%）")
        print(f"→ 连续发声 ≤{max(rr):.2f}s（阈值 {a.max_run}s；未切开 "
              f"{sum(1 for x in rr if x > a.max_run + 0.05)} 段，共插入停顿 {sum(ns)} 处）")
        print(f"→ 整段节奏 {min(cs):.2f}–{max(cs):.2f} 单位/秒"
              f"（{'--cps-map 逐段覆盖' if a.cps_map else f'目标 {a.target_cps}'}）"
              f"；总时长 {sum(tt):.1f}s")

    # 用本轮「新合成」段落的实测吐字率中位数反哺全局 speed，下次跑/新段落更贴近 1.0，
    # 少依赖 atempo。只统计 fresh 段——复用旧 mp3 的段语速参数不可考。
    fresh = [r for r in good if r.get("fresh")]
    if (fresh and len(fresh) >= 5 and not a.global_speed and not a.no_calib
            and os.path.exists(getattr(a, "cache_path", ""))):
        med = statistics.median([r["artic0"] for r in fresh])
        if med > 0:
            refined = round(max(0.75, min(1.35, a.gspeed * (a.target_artic / med))), 3)
            if abs(refined / a.gspeed - 1) > 0.02:
                try:
                    c = json.load(open(a.cache_path, encoding="utf-8"))
                    c["speed"], c["refined_from"] = refined, len(fresh)
                    json.dump(c, open(a.cache_path, "w", encoding="utf-8"),
                              ensure_ascii=False, indent=1)
                    print(f"→ 据本轮 {len(fresh)} 段实测（中位 {med:.2f}），全局 speed 缓存"
                          f"修正为 {refined}，下次生效")
                except Exception:
                    pass
    # 落盘：内容指纹缓存 + 产物凭据（timeline.py 只认 manifest 里 verified 的段）
    try:
        json.dump(a.meta, open(meta_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"⚠ 写 {meta_path} 失败：{e}", file=sys.stderr)
    segs = {k: v for k, v in a.prev_manifest.items() if os.path.exists(f"{a.out}/{k}.wav")}
    segs.update(a.manifest)
    orphan = [f[:-4] for f in sorted(os.listdir(a.out))
              if f.endswith(".wav") and f[:-4] not in segs]
    try:
        json.dump(dict(generated=time.strftime("%Y-%m-%d %H:%M:%S"), voice=a.voice,
                       instruction=a.instruction, speed=a.gspeed, target_cps=a.target_cps,
                       target_artic=a.target_artic, level_mode=a.level_mode,
                       segments=segs),
                  open(mf_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"⚠ 写 {mf_path} 失败：{e}", file=sys.stderr)
    nv = sum(1 for v in segs.values() if v.get("verified"))
    print(f"→ {mf_path}：{len(segs)} 段（verified {nv}）")
    voices = sorted({v.get("voice", "?") for v in segs.values()})
    if len(voices) > 1:
        print(f"⚠ manifest 里混了 {len(voices)} 种音色 {voices}——说明有段落没重录，"
              f"整片会听起来不一致（用 --force 重跑那几段）", file=sys.stderr)
    if orphan:
        print(f"⚠ {a.out}/ 里有 {len(orphan)} 个没进 manifest 的 wav（未校验/旧版本）："
              f"{orphan[:6]}{'…' if len(orphan) > 6 else ''}；timeline.py 不会用它们",
              file=sys.stderr)
    print(f"→ {len(report) - bad}/{len(report)} 段通过校验")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
