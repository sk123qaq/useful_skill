#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性 TTS 桩（离线，不联网）。接口与真 TTS 一致：

    tts.py <文本> --voice V --instruction I --speed S --out FILE

行为（为了让 narration.py 的静音/语速/电平统计有东西可测）：
  * 净发声时长 = units(text)/5.35/speed 秒（5.35 是 narration.py 默认 --target-artic），
    切成等长 burst（≤0.72s），burst 之间插 0.30s 数字静音；
  * 前后各留 0.05s / 0.10s 静音；
  * 输出 16bit 单声道 wav（扩展名随调用方，ffmpeg 按内容嗅探，不看扩展名）。

环境变量（测试注入用）：
  FIXTURE_TTS_LOG=path        每次调用追加 "name\tvoice\tspeed"
  FIXTURE_TTS_FAIL=n01,n02    名单里的段落前两次调用返回非零（第 3 次成功，模拟限流）
  FIXTURE_TTS_TRUNCATE=n03    名单里的段落只输出 40% 的音频（模拟服务端截断）
  FIXTURE_TTS_SILENT=n04      名单里的段落输出纯静音（模拟服务端返回空音频）
"""
import math
import os
import sys
import wave

SPEECH_RATE = 5.35          # 与 narration.py 默认 --target-artic 对齐
BURST_MAX = 0.72            # 单个连续发声上限（秒）
GAP = 0.30                  # burst 间静音（> narration.py 的 silence-min 0.15）
LEAD, TAIL = 0.05, 0.10
SR = 48000
AMP = 8000                  # ≈ −12 dBFS，远高于 −42dB 静音阈值


def env_list(name):
    return {x.strip() for x in os.environ.get(name, "").split(",") if x.strip()}


def units(text):
    # 与 narration.py units() 同口径：汉字 + ASCII 字母数字（别用 str.isalnum()——
    # 它对汉字也返回 True，会把汉字数成两倍单位，桩就跑偏了）
    import re
    return len(re.sub(r"[^\u4e00-\u9fff]", "", text)) + len(re.findall(r"[A-Za-z0-9]", text))


def opt(argv, name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


def main():
    argv = sys.argv[1:]
    if not argv:
        print("tts.py <文本> --voice V --out FILE", file=sys.stderr)
        return 2
    text, voice = argv[0], opt(argv, "--voice", "")
    speed = float(opt(argv, "--speed", "1.0"))
    out = opt(argv, "--out")
    if not out:
        print("缺少 --out", file=sys.stderr)
        return 2
    name = os.path.basename(out).rsplit(".", 1)[0]

    log = os.environ.get("FIXTURE_TTS_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{name}\tvoice={voice}\tspeed={speed}\n")

    if name in env_list("FIXTURE_TTS_FAIL"):
        cnt = os.path.join(os.path.dirname(out), f".failcount_{name}")
        n = int(open(cnt).read()) if os.path.exists(cnt) else 0
        open(cnt, "w").write(str(n + 1))
        if n < 2:
            print("stub: simulated 429", file=sys.stderr)
            return 1

    if name in env_list("FIXTURE_TTS_SILENT"):
        speech, nburst = 0.0, 1
    elif name in env_list("FIXTURE_TTS_TRUNCATE"):
        speech = 0.40 * units(text) / SPEECH_RATE / speed
        nburst = max(1, math.ceil(speech / BURST_MAX))
    else:
        speech = units(text) / SPEECH_RATE / speed
        nburst = max(1, math.ceil(speech / BURST_MAX))
    burst = speech / nburst

    def tone(freq, sec):
        return [int(AMP * math.sin(2 * math.pi * freq * k / SR)) for k in range(int(sec * SR))]

    samples = [0] * int(LEAD * SR)
    for i in range(nburst):
        samples += tone(180 + 12 * (i % 5), burst)
        if i < nburst - 1:
            samples += [0] * int(GAP * SR)
    samples += [0] * int(TAIL * SR)

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(array_bytes(samples))
    return 0


def array_bytes(ints):
    import array
    a = array.array("h", ints)
    if sys.byteorder == "big":
        a.byteswap()
    return a.tobytes()


if __name__ == "__main__":
    sys.exit(main())
