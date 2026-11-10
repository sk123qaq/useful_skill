#!/bin/sh
# 精确等待 bgrun.sh 启动的任务。只看自己的 pid 和 .rc 文件，不用 pgrep -f 模糊匹配
# （pgrep -f 会匹配到发起等待的 shell 自己，循环永远不退出——第六集白等过 12 分钟）。
#   sh scripts/bgwait.sh <名字> [超时秒=1800] [轮询秒=10]
# 退出码：任务自己的退出码；超时 124；没有 pid 文件 2。
set -u
[ $# -ge 1 ] || { echo "用法: bgwait.sh <名字> [超时秒] [轮询秒]" >&2; exit 2; }
name="$1"; limit="${2:-1800}"; step="${3:-10}"
[ -f "$name.pid" ] || { echo "没有 $name.pid（先用 bgrun.sh 启动）" >&2; exit 2; }
pid=$(cat "$name.pid")
running() {   # 进程还在且不是僵尸
  st=$(ps -o stat= -p "$pid" 2>/dev/null | tr -d ' ')
  [ -n "$st" ] && [ "${st#Z}" = "$st" ]
}
start=$(date +%s)
while [ ! -f "$name.rc" ] && running; do
  if [ $(( $(date +%s) - start )) -ge "$limit" ]; then
    echo "超时 ${limit}s：$name 仍在运行（pid $pid）。尾部日志："
    tail -n 10 "$name.log" 2>/dev/null | tr '\r' '\n' | tail -n 10
    exit 124
  fi
  sleep "$step"
done
rc=$(cat "$name.rc" 2>/dev/null || echo 1)
case "$rc" in *[!0-9]*|'') rc=1 ;; esac
echo "done $name rc=$rc 用时 $(( $(date +%s) - start ))s"
tail -n 12 "$name.log" 2>/dev/null | tr '\r' '\n' | tail -n 12
exit "$rc"
