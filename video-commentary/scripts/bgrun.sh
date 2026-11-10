#!/bin/sh
# 后台启动一个长任务，并记下 pid 与退出码，配合 bgwait.sh 精确等待。
#   sh scripts/bgrun.sh <名字> <命令> [参数...]
# 产物：<名字>.log（输出）、<名字>.pid（等待用）、<名字>.rc（完成后写入的退出码）
# 能用前台 + 足够大的 timeout 跑完的，就不要用后台；只有要同时做别的事时才用它。
set -u
[ $# -ge 2 ] || { echo "用法: bgrun.sh <名字> <命令> [参数...]" >&2; exit 2; }
name="$1"; shift
rm -f "$name.rc"
# 子 shell 本身也要脱离调用方的管道，否则调用方会一直等到任务结束（等于没有后台）
( "$@" > "$name.log" 2>&1; echo $? > "$name.rc" ) </dev/null >/dev/null 2>&1 &
echo $! > "$name.pid"
echo "started $name pid=$(cat "$name.pid") log=$name.log"
