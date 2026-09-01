#!/usr/bin/env bash
# Stop hook: when the dev session finishes a turn sitting on a commit that asked
# for review, start the cold reviewer in the background and pull the session back
# with exit code 2 so it waits for the findings instead of moving on.
#
# Two rules this file lives by:
#   1. Be fast. It runs after every single turn.
#   2. Never block on doubt. Any confusion exits 0 and lets the session stop; a
#      broken review hook must not be able to wedge the dev loop.
set -uo pipefail

PROJECT_DIR=${1:-${CLAUDE_PROJECT_DIR:-$PWD}}
cd "$PROJECT_DIR" 2>/dev/null || exit 0

STATE=tasks/review/state.env
ROUND_LIMIT=2

# Gate 0: never recurse. The reviewer runs claude inside a worktree of this
# same repo, so it inherits these hooks; without this it would review itself
# forever. run_review.sh exports the flag.
[ -n "${AI_REVIEW_CHILD:-}" ] && exit 0

git rev-parse --git-dir >/dev/null 2>&1 || exit 0
HEAD_SHA=$(git rev-parse HEAD 2>/dev/null) || exit 0
MSG=$(git log -1 --format=%B 2>/dev/null) || exit 0

# Gate 1: the commit has to ask for it. Opting in per commit is deliberate --
# tasks/REVIEW.md says this flow doubles the cost of a task, so it is for the
# ones that write real data or hold state, not for every commit.
printf '%s' "$MSG" | grep -qiE '^Review:[[:space:]]*required' || exit 0

TASK=$(printf '%s' "$MSG" | tr 'A-Z' 'a-z' \
  | sed -nE 's/^review:[[:space:]]*required[[:space:]]*\(task[[:space:]]*([^)]+)\).*/\1/p' \
  | head -1 | tr -d ' ')
TASK=${TASK:-adhoc}

prev_task=""; prev_round=0; prev_sha=""; prev_status=""
# shellcheck disable=SC1090
[ -f "$STATE" ] && . "$STATE"

# Gate 2: this exact commit was already handled. Say nothing -- the session is
# either inside wait.sh or already working through the findings.
[ "$prev_sha" = "$HEAD_SHA" ] && exit 0

# Gate 3: a task that already burned its rounds stays escalated until a human
# clears it (delete tasks/review/state.env) or a new task number shows up.
[ "$prev_task" = "$TASK" ] && [ "$prev_status" = "escalated" ] && exit 0

if [ "$prev_task" = "$TASK" ]; then round=$((prev_round + 1)); else round=1; fi

write_state() {
  cat > "$STATE" <<STATE_EOF
prev_task=$TASK
prev_round=$round
prev_sha=$HEAD_SHA
prev_status=$1
prev_out=tasks/review/task-$TASK/round-$round
STATE_EOF
}

if [ "$round" -gt "$ROUND_LIMIT" ]; then
  write_state escalated
  cat >&2 <<MSG_EOF
🔍 任务 $TASK 已经跑满 $ROUND_LIMIT 轮审查，第 $round 轮不再自动开。

这不是"通过"，是超时。停止自我修复，把下面这些摆给用户，然后等指示：
  - 哪些 finding 已经修掉（附 repro 从红转绿的证据）
  - 哪些还在争，双方的理由各是什么
  - 你自己认为该 push 还是不该 push

历史轮次在 tasks/review/task-$TASK/ 下。用户拍板后删掉 tasks/review/state.env 可以重开。
MSG_EOF
  exit 2
fi

LOG="tasks/review/logs/task-$TASK-round-$round.log"
mkdir -p tasks/review/logs
nohup bash tasks/review/run_review.sh "$HEAD_SHA" "$round" "$TASK" >"$LOG" 2>&1 &
disown 2>/dev/null || true

write_state running

cat >&2 <<MSG_EOF
🔍 任务 $TASK 第 $round 轮冷审已在后台启动（日志 $LOG）。**先不要 push。**

按顺序做这三步：
  1. 运行 \`bash tasks/review/wait.sh\`（会阻塞到审查方交卷，最多 20 分钟）
  2. 逐条处理 findings：
     - queue=true 的必须修到它那条 repro 由红转绿，然后全套测试仍全过
     - 驳回的把理由写回 tasks/todo.md 对应任务下，理由要能被第三方检验
     - 已在 tasks/review/accepted-risks.md 里的，回一句 "owner accepted"，不要重开辩论
  3. 修完照常 commit（同样带 \`Review: required (task $TASK)\` 这行 trailer），会自动触发下一轮

审查方跑在一个抛弃式 worktree 里，改不到你的工作区；findings 和 repro 已经捞回主仓。
MSG_EOF
exit 2
