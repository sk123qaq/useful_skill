#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qwen3.0 ASR 适配层 —— 把 qwen-asr skill 的 CLI 包成 video-commentary 的 ASR 接口。

约定接口（probe.py / narration.py 依赖）：

    asr_qwen.py <音频> [--language L] [--json out.json]

- stdout 只输出转写纯文本（引擎原始输出里的任务头/失败行会被剥掉）
- --language 只接受不报错：qwen 自动识别语种，本 skill 默认不开 language_hints
- --json 额外落一份规范化结果：
      {"text": "...", "sents": [{"start": 秒, "end": 秒, "text": "..."}], "raw": {...}}
  sents 时间相对音频文件起点；qwen filetrans 固定返回句级 + 词级时间戳（词级是
  分词块不是逐字 cue），没有时间戳的引擎给空 sents，调用方按块级时间退化。

引擎：~/.hermes/skills/media/qwen-asr/scripts/asr.py
      （环境变量 COMMENTARY_ASR_ENGINE 换引擎脚本，COMMENTARY_ASR_MODEL 换模型名）
API Key：$DASHSCOPE_API_KEY 或 ~/.config/qwen-asr/api_key（qwen-asr skill 的约定）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

ENGINE = os.environ.get("COMMENTARY_ASR_ENGINE",
                        os.path.expanduser("~/.hermes/skills/media/qwen-asr/scripts/asr.py"))
TRANSIENT = re.compile(r"HTTP 5\d\d|网络错误|429|下载结果 JSON 失败|提交失败|timed out|timeout",
                       re.I)


def run_engine(engine, audio, jout, model, language):
    """跑一次引擎，返回 (returncode, stdout, stderr)。language 目前仅接受不报错。"""
    cmd = [sys.executable, engine, audio, "--json", jout]
    if model:
        cmd += ["--model", model]
    return subprocess.run(cmd, capture_output=True, text=True)


def parse_payload(path):
    """把 qwen-asr 的 --json 产物规范成 (text, sents)。sents 时间为文件内相对秒。"""
    data = json.load(open(path, encoding="utf-8"))
    text, sents = [], []
    for rec in data.get("records") or []:
        if rec.get("subtask_status") != "SUCCEEDED":
            continue
        if rec.get("text"):
            text.append(rec["text"])
        for tr in (rec.get("transcription") or {}).get("transcripts") or []:
            for s in tr.get("sentences") or []:
                t = (s.get("text") or "").strip()
                if not t:
                    continue
                sents.append({"start": round(s.get("begin_time", 0) / 1000.0, 3),
                              "end": round(s.get("end_time", 0) / 1000.0, 3),
                              "text": t})
    sents.sort(key=lambda s: (s["start"], s["end"]))
    return "\n".join(x for x in text if x).strip(), sents


def main():
    ap = argparse.ArgumentParser(description="Qwen3.0 ASR 适配层（video-commentary 的 ASR 接口）")
    ap.add_argument("audio", help="音频/视频文件（本地路径）")
    ap.add_argument("--language", help="语言提示（qwen 自动识别，仅接受不报错）")
    ap.add_argument("--json", dest="json_path",
                    help="把规范化结果 {text, sents, raw} 保存为 JSON（含句级时间戳）")
    ap.add_argument("--model", default=os.environ.get("COMMENTARY_ASR_MODEL", ""),
                    help="模型名（默认用 qwen-asr 的默认：qwen-audio-3.0-asr-flash-filetrans）")
    a = ap.parse_args()

    if not os.path.exists(ENGINE):
        print("找不到 ASR 引擎：%s（用 COMMENTARY_ASR_ENGINE 指定）" % ENGINE, file=sys.stderr)
        return 1

    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        for attempt in (1, 2):
            r = run_engine(ENGINE, a.audio, tmp, a.model, a.language)
            text, sents = ("", [])
            try:
                if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                    text, sents = parse_payload(tmp)
            except Exception as exc:  # noqa: BLE001
                print("解析引擎结果失败：%s" % exc, file=sys.stderr)
            if text:
                if a.json_path:
                    raw = {}
                    try:
                        raw = json.load(open(tmp, encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        pass
                    with open(a.json_path, "w", encoding="utf-8") as f:
                        json.dump({"text": text, "sents": sents, "raw": raw},
                                  f, ensure_ascii=False, indent=2)
                print(text)
                return 0
            err = (r.stderr or "").strip()
            if attempt == 1 and TRANSIENT.search(err):
                time.sleep(3)
                continue
            print("ASR 失败（%s）：%s" % (ENGINE, err[-300:] or "引擎无输出"), file=sys.stderr)
            return 1
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return 1


if __name__ == "__main__":
    sys.exit(main())
