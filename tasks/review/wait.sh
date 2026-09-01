#!/usr/bin/env bash
# Block until the background reviewer has filed its verdict, then print it.
#
# The Stop hook starts the review and immediately hands control back, so this is
# the developer's one blocking call. It exists so the dev session waits on a real
# file appearing rather than guessing how long a review takes.
set -uo pipefail

PROJECT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
cd "$PROJECT_DIR" || exit 1
STATE=tasks/review/state.env
TIMEOUT=${REVIEW_WAIT_TIMEOUT:-1200}
INTERVAL=10

if [ ! -f "$STATE" ]; then
  echo "没有正在进行的审查（tasks/review/state.env 不存在）。"
  echo "审查由 commit message 里的 'Review: required (task N)' 触发。"
  exit 1
fi

waited=0
while :; do
  prev_status=""; prev_out=""; prev_task=""; prev_round=""
  # shellcheck disable=SC1090
  . "$STATE"

  case "$prev_status" in
    done|error)
      echo "===== 任务 $prev_task 第 $prev_round 轮审查结果 ====="
      if [ -f "$prev_out/report.txt" ]; then
        cat "$prev_out/report.txt"
      elif [ -f "$prev_out/findings.json" ]; then
        cat "$prev_out/findings.json"
      else
        echo "审查进程结束了但什么都没留下，看 tasks/review/logs/。"
      fi
      echo
      echo "完整材料: $prev_out/"
      echo "  findings.normalized.json  逐条带 queue 标记的最终清单"
      echo "  repro/                    复现测试，用下面这条跑（先红，修完必须转绿）："
      echo "  bash tasks/review/pytest_docker.sh backend $prev_out/repro"
      echo "  修完再跑一次全套：bash tasks/review/pytest_docker.sh backend"
      [ "$prev_status" = "error" ] && exit 2
      exit 0
      ;;
    escalated)
      echo "这个任务已经跑满轮次上限，需要用户拍板，见 $prev_out/。"
      exit 2
      ;;
  esac

  if [ "$waited" -ge "$TIMEOUT" ]; then
    echo "等了 ${TIMEOUT}s 审查方还没交卷。它可能已经死了——"
    echo "看 tasks/review/logs/task-$prev_task-round-$prev_round.log 和 $prev_out/session.err。"
    echo "别当成'审查通过'，这是超时。"
    exit 3
  fi
  sleep "$INTERVAL"
  waited=$((waited + INTERVAL))
done
