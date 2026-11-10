#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：把 code review 里已复现的缺陷固化成断言。

    python3 tests/test_regressions.py            # 全跑
    python3 tests/test_regressions.py -k dlg     # 只跑名字含 dlg 的
    python3 tests/test_regressions.py --list     # 列出来

约定：**红 = 缺陷还在，绿 = 已修**。测试只通过 CLI 和公开函数观察行为，
不依赖具体实现，所以修法可以随便换。全部离线（TTS/ASR 走 tests/stub）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FX = os.path.join(HERE, "fixture")
TMP = os.path.join(HERE, "tmp")
S = os.path.join(ROOT, "scripts")
STUB_TTS = os.path.join(HERE, "stub", "tts.py")
STUB_ASR = os.path.join(HERE, "stub", "asr.py")

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# ---------------------------------------------------------------- 工具
def sh(cmd, env=None, cwd=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=cwd)


def stub_env(**extra):
    e = dict(COMMENTARY_TTS=STUB_TTS, COMMENTARY_ASR=STUB_ASR,
             FIXTURE_ASR_DIR=os.path.join(FX, "narration"))
    e.update(extra)
    return e


def narrate(out_root, extra_args=(), env=None, names=None, voice="elegantgentle-female"):
    """跑一遍 narration.py（桩 TTS/ASR）。返回 (proc, audio_dir, norm_dir)。"""
    audio, norm = os.path.join(out_root, "audio"), os.path.join(out_root, "norm")
    cmd = [sys.executable, os.path.join(S, "narration.py"),
           "--dir", os.path.join(FX, "narration"), "--audio-dir", audio, "--out", norm,
           "--voice", voice, "--no-calib", "--global-speed", "1.0"] + list(extra_args)
    if names:
        cmd += ["--only", ",".join(names)]
    p = sh(cmd, env=stub_env(**(env or {})))
    return p, audio, norm


def timeline_run(out_dir, cuts=None, plan=None, extra=()):
    plan = plan or os.path.join(FX, "plan.json")
    cmd = [sys.executable, os.path.join(S, "timeline.py"), "--plan", plan,
           "--audio-dir", os.path.join(TMP, "base", "norm"),
           "--narration-dir", os.path.join(FX, "narration"),
           "--source", os.path.join(FX, "src.mp4"), "--out-dir", out_dir,
           "--width", "320", "--height", "180"] + list(extra)
    if cuts:
        cmd += ["--cuts", cuts]
    return sh(cmd)


def ensure_base():
    """所有测试共用的基线产物：norm/*.wav + out/resolved.json。"""
    base = os.path.join(TMP, "base")
    if not os.path.exists(os.path.join(base, "norm", "b06.wav")):
        shutil.rmtree(base, ignore_errors=True)
        p, _, _ = narrate(base)
        if p.returncode != 0:
            return base, f"基线 narration 就失败了：\n{p.stdout[-600:]}{p.stderr[-600:]}"
    return base, None


# ---------------------------------------------------------------- 测试
@test
def test_cuts_file_from_skill5a(ctx):
    """SKILL.md 第 5 阶段 5a 那条命令产出的 cuts.txt，timeline.py 必须能直接用。

    现状：metadata=print 写出的是 'frame:0    pts:76800   pts_time:6'，
    timeline.py 期望每行一个裸浮点 → ValueError 崩溃。
    """
    raw = os.path.join(TMP, "cuts_skill5a.txt")
    p = sh(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(FX, "src.mp4"),
            "-vf", f"select='gt(scene,0.35)',metadata=print:file={raw}", "-an", "-f", "null", "-"])
    if p.returncode != 0 or not os.path.exists(raw):
        return ["无法生成 5a 格式的 cuts 文件"]
    out = os.path.join(TMP, "t1")
    shutil.rmtree(out, ignore_errors=True)
    r = timeline_run(out, cuts=raw)
    if r.returncode != 0:
        tail = [l for l in (r.stderr or r.stdout).strip().splitlines() if l.strip()][-2:]
        return [f"timeline 吃不下 5a 产出的 cuts 文件（rc={r.returncode}）：{' | '.join(tail)}"]
    cuts = json.load(open(os.path.join(out, "resolved.json")))["cuts"]
    got = [round(c) for c in cuts[:3]]
    if got != [8, 16, 24]:
        return [f"切点解析错：期望 [8,16,24]，得到 {cuts[:5]}"]
    return []


@test
def test_punct_stays_in_style(ctx):
    """fix_subs_punct.py 只能在同一样式内回移标点，不许把黄字幕的标点搬进白字幕。

    现状：ASS 里白色 Nar 全排在黄色 Dlg 之前，Dlg 行首的标点会被回移到
    最后一条 Nar 行尾 → 白字幕被污染。
    """
    d = os.path.join(TMP, "t2")
    os.makedirs(d, exist_ok=True)
    ass = os.path.join(d, "t.ass")
    open(ass, "w", encoding="utf-8").write(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:03.00,Nar,,0,0,0,,他抬头看了一眼墙上的钟\n"
        "Dialogue: 0,0:00:03.20,0:00:05.00,Dlg,,0,0,0,,，时针已经越过了午夜十二点\n")
    p = sh([sys.executable, os.path.join(S, "fix_subs_punct.py"), ass])
    txt = {}
    for line in open(ass, encoding="utf-8"):
        if line.startswith("Dialogue:"):
            f = line.split(",", 9)
            txt[f[3].strip()] = f[9].strip()
    bad = []
    if txt.get("Nar", "").endswith("，"):
        bad.append(f"白字幕被污染：{txt['Nar']!r}")
    if "Nar" not in txt or "Dlg" not in txt:
        bad.append(f"字幕行数被改坏：{txt}")
    return bad


@test
def test_dlg_events_never_overlap_narration(ctx):
    """对白字幕（黄）与原声全音量窗必须互补：解说窗内不许出现对白字幕。

    现状：build_dlg_events 假设解说窗两两不重叠且已排序，重叠时 duck 列表
    失去配对意义、静默产出压在同段解说上的对白事件。
    """
    sys.path.insert(0, S)
    import timeline as T                                          # noqa: N813
    items = [dict(name="b1", a=100.0, b=130.0, start=0.0, dur=30.0,
                  narr=[["b01", 0.5, 7.5], ["b02", 5.0, 4.0], ["b03", 20.0, 6.0]],
                  why="test")]
    cues = [(100.0, 101.0, "第一句台词"), (105.0, 106.0, "被解说盖住的那句"),
            (118.0, 119.0, "第二句台词")]
    try:
        ev = T.build_dlg_events(items, cues)
    except AssertionError as e:                                   # 允许修成显式报错
        return [] if "重叠" in str(e) or "overlap" in str(e).lower() else [f"断言信息看不出原因：{e}"]
    bad = []
    for st, en, txt in ev:
        for _, gs, d in items[0]["narr"]:
            if st < gs + d - 0.01 and en > gs + 0.01:
                bad.append(f"对白「{txt}」{st:.2f}-{en:.2f}s 压在同段解说 "
                           f"{gs:.2f}-{gs + d:.2f}s 上")
    if any(st < 0 or en > 30.0 for st, en, _ in ev):
        bad.append(f"对白事件超出片段范围：{ev}")
    return bad


@test
def test_voice_change_triggers_resynth(ctx):
    """换音色/改指令后必须重新合成，不能复用旧 mp3。

    现状：process() 只看 audio/<name>.mp3 是否存在 → 换了 --voice 也照用旧音频，
    交付的成片还是老音色（技能描述里明确支持"换音色重出片"这个用法）。
    """
    root = os.path.join(TMP, "t4")
    shutil.rmtree(root, ignore_errors=True)
    log = os.path.join(root, "tts.log")
    env = dict(FIXTURE_TTS_LOG=log)
    p1, _, _ = narrate(root, names=["b01", "b02"], env=env)
    if p1.returncode != 0:
        return [f"第一遍就失败：{p1.stdout[-400:]}{p1.stderr[-400:]}"]
    before = open(log).read().count("\n")
    p2, _, _ = narrate(root, names=["b01", "b02"], env=env, voice="magnetic-voiced-male")
    if p2.returncode != 0:
        return [f"第二遍失败：{p2.stdout[-400:]}{p2.stderr[-400:]}"]
    after = open(log).read()
    if "magnetic-voiced-male" not in after:
        return [f"换了音色但 TTS 未被再次调用（调用记录仍 {before} 条，全是旧音色）"]
    return []


@test
def test_failure_is_isolated(ctx):
    """坏段落不能把整条流水线打断，也不能把半成品留在 norm/ 里被 timeline 当有效输入。

    现状：(a) TTS 返回空/静音时 repace() 返回 None，process() 直接 r[...] → TypeError 崩溃；
          (b) 自检不过时 wav 已经写进 norm/，timeline 照用不误。
    """
    bad = []
    # (a) 全静音音频：应报"该段失败"，不是 traceback
    root = os.path.join(TMP, "t5a")
    shutil.rmtree(root, ignore_errors=True)
    p, _, _ = narrate(root, names=["b01"], env=dict(FIXTURE_TTS_SILENT="b01"), extra_args=["--force"])
    blob = p.stdout + p.stderr
    if "Traceback" in blob:
        bad.append("TTS 返回静音音频时崩溃（Traceback）、没有当成一次可报告的段落失败")
    if p.returncode == 0:
        bad.append("静音音频竟然算通过了（退出码 0）")

    # (b) 语速目标不可能达成 → 自检失败 → 半成品 wav 必须不留
    root = os.path.join(TMP, "t5b")
    shutil.rmtree(root, ignore_errors=True)
    p, _, norm = narrate(root, names=["b01"], extra_args=["--force", "--target-cps", "19",
                                                         "--target-artic", "20"])
    left = [f for f in os.listdir(norm) if f.endswith(".wav")] if os.path.isdir(norm) else []
    if left:
        bad.append(f"自检失败的段落在 norm/ 留了半成品 {left}（timeline 会当有效输入用）")
    if "Traceback" in p.stdout + p.stderr:
        bad.append("自检失败路径抛了未捕获异常")
    return bad


@test
def test_canon_numerals(ctx):
    """ASR 回读会被 ITN 归一成阿拉伯数字，比较前必须归一，否则误判「TTS 截断」。

    实测：解说词「一九七九年，BBC 播出了一部…」回读成「1979年，BBC…」——
    旧版 canon 只认「百分之X」，覆盖率报 0.87（<0.90 阈值），于是白重合成一遍；
    而且现在 manifest 会把它标成未验证，timeline 直接拒收。
    """
    sys.path.insert(0, S)
    import narration as N                                            # noqa: N813
    pairs = [("一九七九年", "1979 年"), ("百分之五", "5%"), ("百分之三点五", "3.5%"),
             ("两万三千", "23000"), ("二百一十九", "219"), ("二〇〇一", "2001"),
             ("十五", "15"), ("一百万", "1000000")]
    bad = []
    for a, b in pairs:
        if N.canon(a) != N.canon(b):
            bad.append(f"canon({a!r})={N.canon(a)!r} ≠ canon({b!r})={N.canon(b)!r}")
    return bad


@test
def test_probe_pin_and_cache(ctx):
    """probe.py --pin 要能把整句钉到 ±0.3s；第二次相同查询必须命中缓存（不重复付费）。"""
    keep = os.path.join(TMP, "t8_keep")
    shutil.rmtree(keep, ignore_errors=True)
    src = os.path.join(FX, "src.mp4")
    cmd = [sys.executable, os.path.join(S, "probe.py"), "--source", src,
           "--pin", "16.6", "--expect", "桩听到", "--keep", keep]
    p = sh(cmd, env=stub_env())
    if p.returncode != 0:
        return [f"--pin 失败：{p.stdout} {p.stderr[-300:]}"]
    m = re.search(r"\[([\d.]+),\s*([\d.]+)\]", p.stdout)
    if not m:
        return [f"输出里没有 [起, 止]：{p.stdout[:200]}"]
    st, en = float(m.group(1)), float(m.group(2))
    bad = []
    if abs(st - 16.0) > 0.3 or abs(en - 17.2) > 0.3:
        bad.append(f"定句不准：[{st}, {en}]，素材里的整句是 [16.0, 17.2] "
                   f"（stub 的 burst 边界，见 tests/make_fixture.py）")
    p2 = sh(cmd, env=stub_env())
    if "缓存" not in p2.stdout:
        bad.append("第二次同样查询没命中缓存（会重复花 ASR 费用）")
    return bad


@test
def test_probe_transcribe_tail_repair(ctx):
    """长块 ASR 吞尾必须被 --transcribe 的短窗补测修掉。

    真实事故（S3E05《如坐针毡》）：分块 ASR 把全剧最后一句 "Yes, Minister!"
    吞成 "Yes."（末句终点少 1.5s）→ 彩蛋 pe 短 1.5s → 成片把最后一个词切掉
    半截。补测用 ≤20s 短窗（同一位置长块不出内容、短窗出）。
    """
    keep = os.path.join(TMP, "t10_keep")
    shutil.rmtree(keep, ignore_errors=True)
    src = os.path.join(FX, "src.mp4")                  # 32s；--chunk-sec 10 → 4 块
    smap = os.path.join(TMP, "t10_sents.json")
    # chunk_002 覆盖 [20,30]：只转写到 27.0（尾部空缺 3s，模拟吞尾）
    # tailfix_25 覆盖 [25,30]：短窗补测拿到 27.0 之后被吞掉的尾句
    json.dump({"chunk_002": [[0.0, 3.0, "第二块第一句"], [4.0, 7.0, "第二块最后一句"]],
               "tailfix_25": [[2.0, 5.0, "被吞掉的尾句"]]},
              open(smap, "w", encoding="utf-8"), ensure_ascii=False)
    tsv = os.path.join(TMP, "t10.tsv")
    p = sh([sys.executable, os.path.join(S, "probe.py"), "--source", src,
            "--transcribe", "--chunk-sec", "10", "--tail-gap", "2.0",
            "-o", tsv, "--keep", keep], env=stub_env(FIXTURE_ASR_SENTS=smap))
    bad = []
    if p.returncode != 0:
        return [f"--transcribe 失败：{p.stderr[-300:]}"]
    if "尾部空缺" not in p.stderr + p.stdout:
        bad.append("没有报告块尾部空缺（吞尾没被发现）")
    if not os.path.exists(tsv):
        return bad + ["没生成 TSV"]
    txt = open(tsv, encoding="utf-8").read()
    if "被吞掉的尾句" not in txt:
        bad.append(f"补测到的尾句没并回台词表：\n{txt}")
    # 关掉补测后这句必须消失（证明测试抓的是真行为，不是桩自说自话）
    keep2 = os.path.join(TMP, "t10_keep_off")
    shutil.rmtree(keep2, ignore_errors=True)
    tsv2 = os.path.join(TMP, "t10_off.tsv")
    sh([sys.executable, os.path.join(S, "probe.py"), "--source", src,
        "--transcribe", "--chunk-sec", "10", "--tail-gap", "2.0", "--no-tail-fix",
        "-o", tsv2, "--keep", keep2], env=stub_env(FIXTURE_ASR_SENTS=smap))
    if "被吞掉的尾句" in open(tsv2, encoding="utf-8").read():
        bad.append("--no-tail-fix 模式下尾句仍然出现（补测开关没生效）")
    return bad


@test
def test_cut_audit_last_segment_asr(ctx):
    """全片最后一段的 ✗ 不许一律驳回：cut_audit 自动窗外 ASR 实裁。

    真实事故（S3E05）：末段 SRT 末行横跨切点，cut_audit 报了 ✗，但被「本季
    SRT 偏早 → 16/28 全假」的结论连带驳回；「下一句起点 − 切点」判据对全剧
    最后一句没有下一句、vacuously 通过。窗外 ASR 是唯一客观判据。
    """
    d = os.path.join(TMP, "t11")
    os.makedirs(d, exist_ok=True)
    src = os.path.join(FX, "src.mp4")                  # 每 2s 一句 1.2s 假台词
    plan = os.path.join(d, "plan.json")
    json.dump({"items": [
        {"name": "彩蛋一", "punch": [14.0, 15.2]},
        {"name": "末段", "punch": [24.0, 26.6]}]},     # b=26.6 落在 26.0-27.2 台词里
        open(plan, "w", encoding="utf-8"), ensure_ascii=False)
    srt = os.path.join(d, "dlg.srt")
    open(srt, "w", encoding="utf-8").write(
        "1\n00:00:14,000 --> 00:00:15,400\n第一句\n\n"
        "2\n00:00:26,500 --> 00:00:28,500\n被啃的最后一句\n\n")
    # ② 用的 SRT：行止只越过切点 0.2s（≤0.3s，SRT 正常时偏）
    srt_soft = os.path.join(d, "dlg_soft.srt")
    open(srt_soft, "w", encoding="utf-8").write(
        "1\n00:00:14,000 --> 00:00:15,400\n第一句\n\n"
        "2\n00:00:26,400 --> 00:00:26,800\n刚好收尾的一句\n\n")
    bad = []
    # ① 窗外 ASR 显示切点后还有话 → 必须判 ✗ 且退出码 1
    keep1 = os.path.join(TMP, "t11_keep_bad")
    shutil.rmtree(keep1, ignore_errors=True)
    smap1 = os.path.join(d, "sents_bad.json")
    json.dump({"*": [[3.5, 5.5, "切点后还有半句"]]},
              open(smap1, "w", encoding="utf-8"), ensure_ascii=False)
    log1 = os.path.join(d, "asr_calls_bad.log")
    p = sh([sys.executable, os.path.join(S, "cut_audit.py"), "--plan", plan,
            "--source", src, "--srt", srt, "--keep", keep1],
           env=stub_env(FIXTURE_ASR_SENTS=smap1, FIXTURE_ASR_LOG=log1))
    out = p.stdout + p.stderr
    if "窗外 ASR 实裁" not in out:
        bad.append(f"末段没做窗外 ASR 实裁：\n{out[-400:]}")
    if "没说完" not in out:
        bad.append(f"窗外 ASR 抓到切点后还有话，却没报「没说完」：\n{out[-400:]}")
    if p.returncode != 1:
        bad.append(f"末段没说完应退出码 1，实际 {p.returncode}")
    # 多样本：ASR 对「句尾混音乐」的窗有方差（S3E05 实测单发假阴性），必须采样多个窗
    n_calls = len(open(log1, encoding="utf-8").read().strip().splitlines()) \
        if os.path.exists(log1) else 0
    if n_calls < 3:
        bad.append(f"末段实裁只调了 {n_calls} 次 ASR（应多样本取最大，防单发假阴性）")
    # ② SRT 行止只越过切点 0.2s（正常时偏）+ ASR 采样干净 → ✗ 被推翻，退出码 0
    keep2 = os.path.join(TMP, "t11_keep_ok")
    shutil.rmtree(keep2, ignore_errors=True)
    smap2 = os.path.join(d, "sents_ok.json")
    json.dump({"*": [[0.5, 1.5, "切点前说完的句子"]]},
              open(smap2, "w", encoding="utf-8"), ensure_ascii=False)
    p2 = sh([sys.executable, os.path.join(S, "cut_audit.py"), "--plan", plan,
             "--source", src, "--srt", srt_soft, "--keep", keep2],
            env=stub_env(FIXTURE_ASR_SENTS=smap2))
    out2 = p2.stdout + p2.stderr
    if "句子完整" not in out2:
        bad.append(f"SRT 时偏 + ASR 干净时没推翻 ✗：\n{out2[-400:]}")
    if p2.returncode != 0:
        bad.append(f"✗ 被推翻后应退出码 0，实际 {p2.returncode}")
    # ③ SRT 行止越过切点 1.9s 但 ASR 采样全干净（引擎方差）→ 保守按啃句，退出码 1
    keep3 = os.path.join(TMP, "t11_keep_var")
    shutil.rmtree(keep3, ignore_errors=True)
    p3 = sh([sys.executable, os.path.join(S, "cut_audit.py"), "--plan", plan,
             "--source", src, "--srt", srt, "--keep", keep3],
            env=stub_env(FIXTURE_ASR_SENTS=smap2))
    out3 = p3.stdout + p3.stderr
    if "保守按啃句" not in out3:
        bad.append(f"ASR 采样漏检 + SRT 跨切点时应保守按啃句：\n{out3[-400:]}")
    if p3.returncode != 1:
        bad.append(f"保守按啃句应退出码 1，实际 {p3.returncode}")
    return bad


@test
def test_validate_catches_plan_errors(ctx):
    """validate.py 必须在渲染前抓到：片段装不下解说、彩蛋窗太短、段名打错、原声窗越界。"""
    d = os.path.join(TMP, "t7")
    os.makedirs(d, exist_ok=True)
    bad_plan = os.path.join(d, "plan.json")
    json.dump({"items": [
        {"name": "太短的固定段", "fixed": [0.0, 2.0], "units": ["b02"]},        # 6.8s 解说塞 2s
        {"name": "彩蛋太短", "punch": [16.0, 16.2], "units": ["b05"]},
        {"name": "段名打错", "punch": [24.0, 25.2], "units": ["没有这段"]},
        {"name": "原声窗越界", "a": 26.0, "b": 30.0,
         "blocks": [["narr", "b05"], ["orig", 20.0, 21.2]]},                 # 窗外
    ]}, open(bad_plan, "w", encoding="utf-8"), ensure_ascii=False)
    p = sh([sys.executable, os.path.join(S, "validate.py"), "--plan", bad_plan,
            "--narration-dir", os.path.join(FX, "narration"),
            "--audio-dir", os.path.join(TMP, "base", "norm"),
            "--source", os.path.join(FX, "src.mp4")])
    out = p.stdout + p.stderr
    bad = []
    if p.returncode == 0:
        bad.append("坏 plan 竟然校验通过了（退出码 0）")
    for kw in ("装不下", "0.6s", "找不到解说词", "不在片段"):
        if kw not in out:
            bad.append(f"没报出「{kw}」这类问题；实际输出：\n{out[-500:]}")
            break
    return bad


@test
def test_docs_flags_exist(ctx):
    """SKILL.md 里写的每条命令、每个参数都必须在对应脚本的 --help 里真实存在。

    文档与脚本漂移是真实故障源：SKILL.md 曾写 `probe.py --chunks`（根本没这个参数）、
    第 5 阶段的 5a 命令（产出的 cuts.txt 格式不是 timeline 要的）、`validate.py --doc-title`。
    这个测试拿源文件当接口，拿 --help 当真相。
    """
    skill = os.path.join(ROOT, "SKILL.md")
    text = open(skill, encoding="utf-8").read()
    helps = {}
    bad = []
    for m in re.finditer(r"python3\s+scripts/([\w.]+)((?:[^\n]*\\\n)*[^\n]*)", text):
        script, rest = m.group(1), m.group(2).replace("\\\n", " ")
        path = os.path.join(S, script)
        if not os.path.exists(path):
            bad.append(f"SKILL.md 提到了不存在的脚本 {script}")
            continue
        if script not in helps:
            p = sh([sys.executable, path, "--help"])
            helps[script] = p.stdout + p.stderr
        known = set(re.findall(r"(--[\w-]+)", helps[script]))
        for flag in set(re.findall(r"(--[\w-]+)", rest)):
            if flag not in known:
                bad.append(f"{script} 没有参数 {flag}（SKILL.md 里用了），实际支持："
                           f"{', '.join(sorted(known))[:200]}")
    return sorted(set(bad))


@test
def test_norm_manifest(ctx):
    """norm/ 要有一份 manifest：哪几段过了校验、时长多少、内容指纹。

    现状：没有任何校验凭据，timeline 只看 wav 在不在——半成品与合格品无法区分。
    """
    root = os.path.join(TMP, "t6")
    shutil.rmtree(root, ignore_errors=True)
    p, _, norm = narrate(root, names=["b01", "b02"])
    if p.returncode != 0:
        return [f"narration 失败：{p.stdout[-400:]}"]
    mf = os.path.join(norm, "manifest.json")
    if not os.path.exists(mf):
        return [f"缺 {os.path.relpath(mf, ROOT)}"]
    try:
        d = json.load(open(mf, encoding="utf-8"))
    except Exception as e:
        return [f"manifest.json 不是合法 JSON：{e}"]
    segs = d["segments"] if isinstance(d, dict) and "segments" in d else d
    bad = []
    for nm in ("b01", "b02"):
        row = segs.get(nm) if isinstance(segs, dict) else None
        if not row:
            bad.append(f"manifest 里没有 {nm}")
            continue
        if not row.get("verified"):
            bad.append(f"{nm} 未标记 verified")
        if abs(float(row.get("dur", 0)) - 0) < 1e-9:
            bad.append(f"{nm} 缺 dur")
    return bad


# ---------------------------------------------------------------- 字幕标记 / 水印行 / 响度普查
@test
def test_dlg_srt_strips_override_tags(ctx):
    """外挂 SRT 正文里的样式标记必须剥掉，否则 libass 会按标记里的字号渲染。

    现状（实测）：read_dlg_srt 原样返回 `{\\fs18}看过了?`，libass 就真按 18px 画——
    样式里定 58px 也不管用：黄色对白字幕包围盒 136×11px，应为 439×38px，被静默压小 4 倍。
    """
    sys.path.insert(0, S)
    import timeline as T                                          # noqa: N813
    p = os.path.join(TMP, "dlg_tags.srt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:02,000\n{\\fs13}Have you read this?\n"
                "{\\fs18}看过了?\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\n"
                "<font color=#ffff00>仅供交流  严禁商用</font>\n\n"
                "3\n00:00:05,000 --> 00:00:06,000\n{\\fs18}你看过了 他也看过了\n")
    cues = T.read_dlg_srt(p, set())
    bad = [f"字幕文本仍带标记：{cn!r}" for _, _, cn in cues if any(c in cn for c in "{}<>")]
    if not any("看过了" in cn for _, _, cn in cues):
        bad.append(f"把正文弄丢了：{cues}")
    return bad


@test
def test_dlg_srt_drops_fansub_watermark(ctx):
    """字幕组信息/水印行不是对白：既不该出现在成片里，也不该算进"原声窗对白覆盖"。

    现状：这类行含中文，会被"取中文行"的逻辑当成对白；verify.py 又写死跳过集为空，
    于是片头那段纯音乐的原声窗被判成"覆盖 0%"。
    """
    sys.path.insert(0, S)
    import timeline as T                                          # noqa: N813
    p = os.path.join(TMP, "dlg_junk.srt")
    with open(p, "w", encoding="utf-8") as f:
        f.write("1\n00:00:01,000 --> 00:00:02,000\n-=某字幕组=-\n"
                "翻译: 甲 时间轴: 乙 校对: 丙\n\n"
                "2\n00:00:03,000 --> 00:00:04,000\n为什么要压制消息?\n")
    cues = T.read_dlg_srt(p, set())
    bad = [f"水印行被当成对白：{cn!r}" for _, _, cn in cues if T.is_non_dialogue(cn)]
    if not any("压制消息" in cn for _, _, cn in cues):
        bad.append("把正常台词误杀了（压制消息 不含冒号，不该被过滤）")
    return bad


@test
def test_verify_accepts_dlg_skip(ctx):
    """verify.py 必须能像 timeline.py 一样跳过指定 idx，否则标题行会污染覆盖检查。"""
    p = sh([sys.executable, os.path.join(S, "verify.py"), "--help"])
    if "--dlg-skip" not in (p.stdout + p.stderr):
        return ["verify.py --help 里没有 --dlg-skip"]
    return []


@test
def test_level_check_is_census_not_sample(ctx):
    """响度平衡必须全片普查（每个片段一窗），不能只抽时长最长的几段。

    现状：pick_windows(samples=4) 只取最长的 4 段；原片逐场电平差 7dB（−18.0~−25.5），
    这 4 段恰好都偏轻，把残差 +0.06dB 的成片误报成 +2.4dB，照它调会把真实平衡推向另一侧。
    """
    sys.path.insert(0, S)
    import verify as V                                            # noqa: N813
    items = [dict(name=f"m{i}", start=i * 10.0, dur=10.0, a=100.0 + i * 10.0,
                  orig=[[1.0, 7.0]], narr_mask=[[0.0, 4.0]]) for i in range(6)]
    c = V.census_windows(items, "orig")
    s = V.pick_windows(items, "orig", samples=4)
    bad = []
    if len(c) != 6:
        bad.append(f"census_windows 只取到 {len(c)} 窗（6 个片段应各取一窗）")
    if len(s) != 4:
        bad.append(f"pick_windows(samples=4) 返回 {len(s)} 窗，抽样行为变了")
    return bad


@test
def test_cover_two_ratios(ctx):
    """cover.py 要一帧底图出两种规格（4:3 + 3:4），且标题真的画上去了、位置没漂。

    现状：没有封面工具，每集现写一遍排版脚本 → 字号/位置跨集漂移；文档声明“一帧两规格、
    字号跟 LAY 走”就必须有东西盯着它。
    """
    try:
        from PIL import Image
    except ImportError:
        return []                       # 没装 Pillow 就跳过（封面本来就需要它）
    out = os.path.join(TMP, "cover")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    r = sh([sys.executable, os.path.join(S, "cover.py"),
            "--film", os.path.join(FX, "src.mp4"), "--at", "4.0",
            "--out-dir", out, "--prefix", "封面",
            "--above", "是，大臣 · 冒烟", "--title", "测试集", "--below", "中文解说"])
    if r.returncode != 0:
        return [f"cover.py 跑失败（rc={r.returncode}）：{(r.stderr or r.stdout)[-300:]}"]
    sys.path.insert(0, S)
    import cover as C                                            # noqa: N813
    bad = []
    for tag, want in (("4x3", (1920, 1440)), ("3x4", (1080, 1440))):
        p = os.path.join(out, f"封面_{tag}.png")
        if not os.path.exists(p):
            bad.append(f"{tag}: 没产出 {os.path.basename(p)}")
            continue
        im = Image.open(p).convert("RGB")
        if im.size != want:
            bad.append(f"{tag}: 尺寸 {im.size} ≠ {want}")
            continue
        W, H = im.size
        px = im.load()
        # 标题字色是精确的 #FCFAF6：底图（测试图案）里不会有这大片同色
        cols, low = {}, 0
        for y in range(int(H * 0.55), H):
            for x in range(0, int(W * 0.75)):
                if px[x, y] == C.WHITE:
                    cols[x] = cols.get(x, 0) + 1
                    low = max(low, y)
        if len(cols) < 60:
            bad.append(f"{tag}: 标题那几列没找到白字（只有 {len(cols)} 列）——字没画上去？")
            continue
        x0 = min(cols)
        if abs(x0 - C.LAY["left"] * W) > 24:
            bad.append(f"{tag}: 标题左边界 {x0} ≠ 版式 {C.LAY['left'] * W:.0f}（位置漂了）")
        if low > H - 24:
            bad.append(f"{tag}: 文字块贴到画底（最低白字 y={low}/{H}），下边距不够")
        if os.path.getsize(p) < 20000:
            bad.append(f"{tag}: 文件只有 {os.path.getsize(p)}B，像张空图")
    return bad


LINT = os.path.join(S, "lint_narration.py")


@test
def test_canon_big_numbers(ctx):
    """ASR 回读会把「十万」写成「10万」：两边都要归一到同一个数，否则覆盖率误判。

    实测：第六集 ad1「十万英国工人」回读成「10万英国工人」，canon 旧版得到 100000 与 10万 两个串，
    覆盖率 0.87 < 0.90，白重合成一遍。
    """
    sys.path.insert(0, S)
    import narration as N                                            # noqa: N813
    pairs = [("十万英国工人", "10万英国工人"), ("两百万", "200万"), ("二亿", "2亿"),
             ("3.5万", "35000"), ("一亿二千万", "1.2亿"), ("一百万", "1000000")]
    return [f"canon({a!r})={N.canon(a)!r} ≠ canon({b!r})={N.canon(b)!r}"
            for a, b in pairs if N.canon(a) != N.canon(b)]


@test
def test_lint_levels_and_exit_codes(ctx):
    """lint_narration.py：空段 → ERROR 退出 1；子句过长/过短 → WARN，默认退出 0、--strict 退出 1；干净段无提示。"""
    root = os.path.join(TMP, "lint_case")
    shutil.rmtree(root, ignore_errors=True)
    cases = {
        "err": {"empty": ""},
        "warn": {"long": "这一整段话没有任何逗号也没有任何句号从头一直说到底所以配音的时候很可能会连成一口气超过四秒钟的连续发声",
                 "short": "这里只有十几个字。"},
        "clean": {"ok": "这是一段干净的解说，有逗号也有句号，读起来不会连成一口气，字数也足够，所以不应该出现任何提示。"},
    }
    for case, files in cases.items():
        d = os.path.join(root, case)
        os.makedirs(d)
        for nm, txt in files.items():
            open(os.path.join(d, nm + ".txt"), "w", encoding="utf-8").write(txt)
    bad = []
    for case, want_rc, want_words in [("err", 1, ["空段"]), ("warn", 0, ["子句", "过短"]),
                                      ("clean", 0, [])]:
        p = sh([sys.executable, LINT, "--dir", os.path.join(root, case)])
        if p.returncode != want_rc:
            bad.append(f"{case}: 退出码 {p.returncode}，应为 {want_rc}\n{p.stdout[-300:]}")
        for w in want_words:
            if w not in p.stdout:
                bad.append(f"{case}: 报告里缺 {w!r}")
    p = sh([sys.executable, LINT, "--dir", os.path.join(root, "clean")])
    if "WARN 0" not in p.stdout or "INFO 0" not in p.stdout:
        bad.append(f"clean: 干净段却有提示\n{p.stdout[-300:]}")
    p = sh([sys.executable, LINT, "--dir", os.path.join(root, "warn"), "--strict"])
    if p.returncode != 1:
        bad.append(f"warn --strict 应退出 1，实际 {p.returncode}")
    return bad


@test
def test_pilot_calibrates_on_real_units(ctx):
    """配音前 pilot 标定：真实解说在 speed 1.0 下合成 5 段，算出全局 speed 写入缓存，全量统一用它。

    现状（第六集）：探针句偏了一点，全量跑完才修正，于是「全量 → 修正 → 再全量」白跑一轮。
    """
    root = os.path.join(TMP, "pilot_case")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root)
    log = os.path.join(root, "tts.log")
    p = sh([sys.executable, os.path.join(S, "narration.py"), "--dir", os.path.join(FX, "narration"),
            "--audio-dir", os.path.join(root, "audio"), "--out", os.path.join(root, "norm"),
            "--profile", "none"], env=stub_env(FIXTURE_TTS_LOG=log))
    if p.returncode != 0:
        return [f"narration 失败：{p.stdout[-300:]}{p.stderr[-300:]}"]
    cache = json.load(open(os.path.join(root, "audio", ".pacing.json"), encoding="utf-8"))
    bad = []
    if len(cache.get("pilot", {}).get("artic", [])) < 3:
        bad.append(f"缓存里没有 pilot 记录：{sorted(cache)}")
    s = cache.get("speed", 0)
    if not 0.85 <= s <= 1.15:
        bad.append(f"pilot 得到的 speed={s}，桩理论上接近 1.0")
    calls = [ln.split("\t") for ln in open(log, encoding="utf-8").read().splitlines()]
    pilot = [c for c in calls if c[0].startswith(".pilot_")]
    full = [c for c in calls if not c[0].startswith(".pilot_")]
    # 样本是 >=24 单位的解说段，个数取决于素材（fixture 里是 4 段），少于 3 段才说明取样坏了
    if len(pilot) < 3 or any(c[2] != "speed=1.0" for c in pilot):
        bad.append(f"pilot 应 >=3 次且 speed=1.0，实际 {len(pilot)} 次：{pilot[:2]}")
    if not full or any(c[2] != f"speed={s}" for c in full):
        bad.append(f"全量没有统一用 pilot 的 speed {s}：{sorted({c[2] for c in full})}")
    return bad


@test
def test_profile_supplies_defaults(ctx):
    """profile.json 给默认值：同音色同指令时直接用 profile 的 speed，不标定、不写缓存；音色不同则忽略它。"""
    root = os.path.join(TMP, "profile_case")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root)
    prof = os.path.join(root, "p.json")
    json.dump({"voice": "elegantgentle-female", "instruction": "影视解说旁白，温婉清晰，语速中等",
               "target_artic": 5.35, "speed": 0.91, "level_mode": "speech", "target_db": -19.6},
              open(prof, "w", encoding="utf-8"), ensure_ascii=False)
    audio, norm = os.path.join(root, "audio"), os.path.join(root, "norm")
    log = os.path.join(root, "tts.log")
    p = sh([sys.executable, os.path.join(S, "narration.py"), "--dir", os.path.join(FX, "narration"),
            "--audio-dir", audio, "--out", norm, "--profile", prof], env=stub_env(FIXTURE_TTS_LOG=log))
    bad = []
    if p.returncode != 0:
        return [f"narration 失败：{p.stdout[-300:]}{p.stderr[-300:]}"]
    if "profile" not in p.stdout:
        bad.append("没有走 profile 的 speed（输出里找不到 profile 字样）")
    if os.path.exists(os.path.join(audio, ".pacing.json")):
        bad.append("profile 命中时不该写 .pacing.json 缓存")
    speeds = {ln.split("\t")[2] for ln in open(log, encoding="utf-8").read().splitlines()}
    if speeds != {"speed=0.91"}:
        bad.append(f"speed 应全部为 0.91，实际 {sorted(speeds)}")
    # 音色不一致：profile 的 speed 不适用，--no-calib 直接用 --speed
    p = sh([sys.executable, os.path.join(S, "narration.py"), "--dir", os.path.join(FX, "narration"),
            "--audio-dir", os.path.join(root, "a2"), "--out", os.path.join(root, "n2"),
            "--profile", prof, "--voice", "other-voice", "--no-calib"], env=stub_env())
    if "未标定" not in p.stdout:
        bad.append("音色与 profile 不一致时，profile 的 speed 不该被采用")
    return bad


@test
def test_recalibrate_overrides_profile(ctx):
    """--recalibrate 忽略 profile 与缓存，重新标定（换素材时用）。"""
    root = os.path.join(TMP, "recal_case")
    shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root)
    prof = os.path.join(root, "p.json")
    json.dump({"voice": "elegantgentle-female", "instruction": "影视解说旁白，温婉清晰，语速中等",
               "target_artic": 5.35, "speed": 0.91}, open(prof, "w", encoding="utf-8"), ensure_ascii=False)
    log = os.path.join(root, "tts.log")
    p = sh([sys.executable, os.path.join(S, "narration.py"), "--dir", os.path.join(FX, "narration"),
            "--audio-dir", os.path.join(root, "audio"), "--out", os.path.join(root, "norm"),
            "--profile", prof, "--recalibrate"], env=stub_env(FIXTURE_TTS_LOG=log))
    if p.returncode != 0:
        return [f"narration 失败：{p.stdout[-300:]}{p.stderr[-300:]}"]
    speeds = {ln.split("\t")[2] for ln in open(log, encoding="utf-8").read().splitlines()}
    bad = []
    if "speed=0.91" in speeds:
        bad.append("--recalibrate 仍然使用了 profile 的 0.91")
    if not os.path.exists(os.path.join(root, "audio", ".pacing.json")):
        bad.append("--recalibrate 应重新标定并写缓存")
    return bad


@test
def test_gap_default_comes_from_profile(ctx):
    """timeline / validate 的 --gap 默认值来自 profile.json，且等于解说遮蔽窗两侧余量之和（0.10 + 0.35）。"""
    sys.path.insert(0, S)
    import skillcfg                                                  # noqa: N813
    bad = []
    if abs(skillcfg.gap_default() - 0.45) > 1e-9:
        bad.append(f"profile 的 gap={skillcfg.gap_default()}，应为 0.45")
    for script in ("timeline.py", "validate.py"):
        h = sh([sys.executable, os.path.join(S, script), "--help"]).stdout
        if "profile.json" not in h:
            bad.append(f"{script} 的 --gap 帮助里没说明默认来自 profile.json")
    return bad


@test
def test_sub_band_seals_to_frame_bottom(ctx):
    """承载带必须封到画面底边，且只在解说窗内出现。

    真实事故（S1E1 用户第一轮反馈）：解说时画面最底下还露着原片一道。根因是黑条写死高度
    （`--info-bar "::起::止::1812::294"`，2886x2160 上只铺到 y2106，离底边差 54px）。
    现在 `--sub-band` 用 `h=ih-N` 封到底，时间窗从 plan 的 narr_mask 自动推导。
    本测试两级都查：① 窗口推导的数学；② 真渲染出来的像素（解说窗内最后一行必须黑，
    原声窗内必须还是画面）。
    """
    sys.path.insert(0, S)
    import render as R                                            # noqa: N813
    bad = []
    # ① 窗口推导： narr_mask（段内相对）→ 成片绝对时间；两侧各放宽 pad；过近的窗合并；不越总长
    items = [dict(name="a", start=0.0, narr_mask=[[0.0, 5.0]]),
             dict(name="b", start=10.0, narr_mask=[[0.0, 2.0], [2.05, 4.0]]),   # 隔 0.05 → 合并
             dict(name="c", start=30.0, narr_mask=[[0.0, 4.9]])]
    wins = R.sub_band_windows(items, pad=0.10, merge=0.30, total=34.9)
    if wins != [[0.0, 5.1], [9.9, 14.1], [29.9, 34.9]]:
        bad.append(f"窗口推导错：{wins}")
    # ② 滤镜链：本体必须用 h=ih-N（封到底），渐变各级区域必须互不重叠
    flt, _, _ = R.sub_band_filters("vcat", 0, top=126, fade=40, steps=8, opacity=1.0,
                                   accent="0xD8B26A", accent_h=4, en="between(t,0,5)")
    if not any("h=ih-166" in f for f in flt):
        bad.append(f"本体没用 h=ih-N 封到底：{flt[-2:]}")
    steps_y = []
    for f in flt:
        m = re.search(r"y=(\d+):w=iw:h=(\d+)", f)
        if m and "ih-" not in f and "color=black@" in f:
            steps_y.append((int(m.group(1)), int(m.group(1)) + int(m.group(2))))
    for (a0, a1), (b0, _) in zip(steps_y, steps_y[1:]):
        if b0 < a1:
            bad.append(f"渐变区域重叠 {a0}-{a1} 与 {b0} 起：alpha 会复合出梯步")
            break
    # ③ 像素：真渲染一帧，解说窗内最后一行黑、原声窗内还是画面
    d = os.path.join(TMP, "t_subband")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    out = os.path.join(d, "out")
    r = timeline_run(out, extra=["--track"])
    if r.returncode != 0:
        return [f"timeline 跑不出 resolved.json：{(r.stderr or r.stdout)[-200:]}"]
    plan = json.load(open(os.path.join(out, "resolved.json")))
    film = os.path.join(d, "band.mp4")
    r = sh([sys.executable, os.path.join(S, "render.py"),
            "--source", os.path.join(FX, "src.mp4"), "--plan", os.path.join(out, "resolved.json"),
            "--narration", os.path.join(out, "narration.wav"), "--ass", os.path.join(out, "narration.ass"),
            "--out", film, "--sub-band", "0.7", "--sub-band-fade", "40", "--sub-band-steps", "8"])
    if r.returncode != 0:
        return bad + [f"render.py --sub-band 失败：{(r.stderr or r.stdout)[-300:]}"]
    H = 180
    for kind in ("narr_mask", "orig"):
        for it in plan["items"]:
            for s, e in it.get(kind, []):
                if e - s < 1.0:
                    continue
                t = it["start"] + (s + e) / 2
                png = os.path.join(d, f"{kind}_{t:.1f}.png")
                sh(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", film,
                    "-frames:v", "1", png])
                if not os.path.exists(png):
                    bad.append(f"{kind} {t:.1f}s 抽不出帧")
                    continue
                try:
                    from PIL import Image                                # noqa: N813
                    px = Image.open(png).convert("L").load()
                    W = Image.open(png).width
                    last = max(px[x, H - 1] for x in range(0, W, 3))
                except ImportError:
                    return bad + ["没有 Pillow，跳过像素断言（装 python3-pillow 才有这一级）"]
                if kind == "narr_mask" and last > 2:
                    bad.append(f"解说窗 {t:.1f}s 底边 y{H - 1} 亮度 {last}：承载带没封到底")
                if kind == "orig" and last <= 2:
                    bad.append(f"原声窗 {t:.1f}s 底边也是黑的：带子在该撤的时候没撤")
                os.remove(png)
    return bad


@test
def test_bgwait_exit_codes(ctx):
    """bgrun/bgwait：退出码原样回传；超时返回 124 而不是卡住；只看自己的 pid，不用 pgrep -f。"""
    d = os.path.join(TMP, "bg_case")
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    bgrun, bgwait = os.path.join(S, "bgrun.sh"), os.path.join(S, "bgwait.sh")
    bad = []
    sh(["sh", bgrun, "ok", "sh", "-c", "echo hi; sleep 1"], cwd=d)
    p = sh(["sh", bgwait, "ok", "30", "1"], cwd=d)
    if p.returncode != 0 or "hi" not in p.stdout:
        bad.append(f"成功任务应返回 0 并回显日志，实际 rc={p.returncode}")
    sh(["sh", bgrun, "bad", "sh", "-c", "echo boom; exit 3"], cwd=d)
    p = sh(["sh", bgwait, "bad", "30", "1"], cwd=d)
    if p.returncode != 3:
        bad.append(f"失败任务应回传退出码 3，实际 {p.returncode}")
    sh(["sh", bgrun, "slow", "sleep", "8"], cwd=d)
    p = sh(["sh", bgwait, "slow", "1", "1"], cwd=d)
    if p.returncode != 124:
        bad.append(f"超时应返回 124，实际 {p.returncode}")
    sh(["sh", bgwait, "slow", "60", "1"], cwd=d)           # 等它收尾，免得留下后台进程
    return bad




@test
def test_touching_narration_windows_are_not_overlap(ctx):
    """段间距正好 0.45（= 遮蔽窗两侧余量 0.1+0.35）时，相邻两个解说窗只在一个点上相接，
    那是正常排布，不该报「解说遮蔽窗重叠」；真正压掉一段的仍然要报。

    现状：告警按「合并后条数变少」判断，边界相接也会变少，于是第六集 p23 被误报成
    「plan.json 里该段的解说排布不正常」——而它的彩蛋原声窗其实完好。
    """
    sys.path.insert(0, S)
    import timeline as T                                          # noqa: N813
    import contextlib, io

    def warn(narr, name):
        it = dict(name=name, a=100.0, b=130.0, start=0.0, dur=30.0, narr=narr, why="test")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            T.build_dlg_events([it], [])
        return err.getvalue()
    # 窗 [0,10.35] 与 [10.35,20.8]：只在 10.35 这一个点上相接
    touch = warn([["b01", 0.0, 10.0], ["b02", 10.45, 10.0]], "相接")
    # 亚毫秒尾差：manifest 时长按 6 位小数存，累积出 0.15ms 的"重叠"（第六集实测 0.15–0.56ms）
    jitter = warn([["b01", 0.0, 10.0], ["b02", 10.449854, 10.0]], "尾差")
    # 窗 [0,10.35] 与 [10.2,20.35]：真压掉 0.15 秒
    real = warn([["b01", 0.0, 10.0], ["b02", 10.3, 10.0]], "重叠")
    bad = []
    if "重叠" in touch:
        bad.append(f"边界相接被误报成重叠：{touch.strip()[:120]}")
    if "重叠" in jitter:
        bad.append(f"亚毫秒尾差被误报成重叠：{jitter.strip()[:120]}")
    if "重叠" not in real:
        bad.append("真正的重叠没有告警")
    return bad

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", help="只跑名字含该子串的测试")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for t in TESTS:
            print(f"{t.__name__:38s} {(t.__doc__ or '').strip().splitlines()[0]}")
        return 0
    os.makedirs(TMP, exist_ok=True)
    if not os.path.exists(os.path.join(FX, "src.mp4")):
        r = sh([sys.executable, os.path.join(HERE, "make_fixture.py")])
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            return 1
    base, err = ensure_base()
    if err:
        print("✗ 基线准备失败：", err)
        return 1

    todo = [t for t in TESTS if not a.k or a.k in t.__name__]
    fails = 0
    print(f"跑 {len(todo)} 个回归测试（红 = 缺陷还在）\n" + "-" * 72)
    for t in todo:
        try:
            problems = t(base) or []
        except Exception as e:
            import traceback
            problems = [f"测试自身异常：{e}\n{traceback.format_exc()[-400:]}"]
        if problems:
            fails += 1
            print(f"✗ {t.__name__}")
            for x in problems:
                print(f"    {x}")
        else:
            print(f"✓ {t.__name__}")
    print("-" * 72)
    print(f"{len(todo) - fails}/{len(todo)} 通过")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
