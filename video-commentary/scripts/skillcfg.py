# -*- coding: utf-8 -*-
"""skill 级参数（profile.json）的读取。

profile.json 只放「换音色、换素材才会变」的参数：配音音色与指令、语速（已标定）、
电平、节奏上限，以及解说遮蔽窗的间距。脚本的默认值从这里来，命令行显式参数优先。
换音色或换一批解说词时，用 narration.py --recalibrate 重新标定，再把新值写回 profile.json。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROFILE = os.path.join(ROOT, "profile.json")
NARRATION_KEYS = ("voice", "instruction", "target_cps", "target_artic", "max_run",
                  "level_mode", "target_db")
GAP_FALLBACK = 0.45      # 与 timeline.narration_windows 的两侧余量之和（0.10 + 0.35）一致


def load(path=None):
    """读 profile；path=None 用默认文件，path='none' 或文件不存在时返回空 dict。"""
    path = DEFAULT_PROFILE if path is None else path
    if not path or str(path).lower() == "none" or not os.path.exists(path):
        return {}
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"profile 读不了：{path}（{e}）")


def narration_defaults(prof):
    """narration.py 用得到的那几个键，原样作为 argparse 默认值。"""
    return {k: prof[k] for k in NARRATION_KEYS if k in prof}


def gap_default(path=None):
    """timeline.py / validate.py 的 --gap 默认值。"""
    return float(load(path).get("gap", GAP_FALLBACK))
