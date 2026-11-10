#!/bin/sh
# 全链冒烟：假素材 → 配音（离线桩）→ 时间轴 → 标点归位 → 渲染 → 成片自检 → 封面。
# 它验证的是"这条流水线今天还跑得通"，不是画质；跑完的成片在 tests/tmp/smoke/。
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
python3 tests/make_fixture.py
. tests/fixture/env.sh
rm -rf tests/tmp/smoke
mkdir -p tests/tmp/smoke

step() { printf '\n=== %s ===\n' "$1"; }

step "1/7 配音（桩 TTS/ASR）"
python3 scripts/narration.py --dir tests/fixture/narration \
    --audio-dir tests/tmp/smoke/audio --out tests/tmp/smoke/norm \
    --no-calib --global-speed 1.0 --level-mode speech

step "2/7 plan 校验（validate.py，可缺省）"
if [ -f scripts/validate.py ]; then
    python3 scripts/validate.py --plan tests/fixture/plan.json \
        --audio-dir tests/tmp/smoke/norm --narration-dir tests/fixture/narration \
        --source tests/fixture/src.mp4
else
    echo "（还没写 validate.py，跳过）"
fi

step "3/7 时间轴 + 音轨 + 双语字幕"
python3 scripts/timeline.py --plan tests/fixture/plan.json \
    --audio-dir tests/tmp/smoke/norm --narration-dir tests/fixture/narration \
    --source tests/fixture/src.mp4 --out-dir tests/tmp/smoke/out --track \
    --dlg-srt tests/fixture/dlg.srt

step "4/7 标点归位"
python3 scripts/fix_subs_punct.py tests/tmp/smoke/out/narration.ass

step "5/7 渲染"
python3 scripts/render.py --source tests/fixture/src.mp4 \
    --plan tests/tmp/smoke/out/resolved.json --narration tests/tmp/smoke/out/narration.wav \
    --ass tests/tmp/smoke/out/narration.ass --out tests/tmp/smoke/成片.mp4 \
    --top-bar 0 --intro-card "测试卡|Smoke Test::2.0" \
    --sub-band 0.7 --sub-band-fade 40 --sub-band-steps 8

step "6/7 成片自检"
if [ -f scripts/verify.py ]; then
    python3 scripts/verify.py --film tests/tmp/smoke/成片.mp4 --plan tests/tmp/smoke/out/resolved.json \
        --ass tests/tmp/smoke/out/narration.ass --source tests/fixture/src.mp4 \
        --dlg-srt tests/fixture/dlg.srt --out-dir tests/tmp/smoke/out
else
    ffmpeg -v error -i tests/tmp/smoke/成片.mp4 -f null - && echo "解码 OK"
fi

step "7/7 封面（4:3 + 3:4）"
python3 scripts/cover.py --film tests/tmp/smoke/成片.mp4 --at 0:02 \
    --out-dir tests/tmp/smoke --prefix 封面 \
    --above "是，大臣 · 冒烟" --title 测试集 --below "中文解说 · SMOKE TEST"

echo
echo "冒烟通过 → $ROOT/tests/tmp/smoke/成片.mp4"
