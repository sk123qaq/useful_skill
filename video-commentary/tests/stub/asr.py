#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性 ASR 桩（离线，不联网）。接口与真 ASR 一致：

    asr.py <音频> [--language L] [--no-itn] [--chunks ...]

取值优先级：
  1. $FIXTURE_ASR_MAP 指向的 JSON：{文件名（不含扩展名）: 文本}
  2. $FIXTURE_ASR_DIR/<名字>.txt
  3. $FIXTURE_ASR_TEXT（兜底文本，默认空）

环境变量：
  FIXTURE_ASR_LOG=path        每次调用追加 "音频路径\t返回长度"
  FIXTURE_ASR_TRUNCATE=n03    名单里的段落只返回前 40%（模拟回读截断 → 覆盖率低）
  FIXTURE_ASR_SENTS=path      JSON {音频名(不含扩展名): [[起, 止, 文本], ...]}（秒，相对
                              音频起点）；传了 --json 就按它写句级时间戳，支持 "*" 兜底。
                              用来模拟「长块吞尾、短窗补到」这类分块转写行为。
"""
import json
import os
import sys


def main():
    argv = sys.argv[1:]
    if not argv:
        print("asr.py <音频>", file=sys.stderr)
        return 2
    audio = argv[0]
    json_out = None
    if "--json" in argv:                     # probe.py --transcribe / cut_audit 末段实裁
        i = argv.index("--json")
        json_out = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
    name = os.path.basename(audio)
    for ext in (".mp3", ".wav", ".m4a", ".flac"):
        if name.endswith(ext):
            name = name[: -len(ext)]
    text = ""
    mp = os.environ.get("FIXTURE_ASR_MAP")
    if mp and os.path.exists(mp):
        try:
            text = json.load(open(mp, encoding="utf-8")).get(name, text)
        except Exception:
            pass
    if not text:
        d = os.environ.get("FIXTURE_ASR_DIR")
        p = os.path.join(d, name + ".txt") if d else None
        if p and os.path.exists(p):
            text = open(p, encoding="utf-8").read().strip()
    if not text:
        text = os.environ.get("FIXTURE_ASR_TEXT", "")
    if name in {x.strip() for x in os.environ.get("FIXTURE_ASR_TRUNCATE", "").split(",") if x.strip()}:
        text = text[: max(1, int(len(text) * 0.40))]
    log = os.environ.get("FIXTURE_ASR_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{audio}\t{len(text)}\n")
    if json_out:
        smap = {}
        mp = os.environ.get("FIXTURE_ASR_SENTS")
        if mp and os.path.exists(mp):
            smap = json.load(open(mp, encoding="utf-8"))
        spans = smap.get(name) or smap.get("*") or []
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump({"text": text,
                       "sents": [{"start": float(a), "end": float(b), "text": t}
                                 for a, b, t in spans]},
                      f, ensure_ascii=False)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
