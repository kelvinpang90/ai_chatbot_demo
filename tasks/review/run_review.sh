#!/usr/bin/env bash
# Run one round of cold review, detached, and leave the verdict on disk.
#
# The isolation here is structural, not disciplinary. The reviewer gets its own
# throwaway worktree parked on the reviewed commit, so anything it edits is a
# copy that gets deleted; its findings go to an output directory outside that
# worktree. That gives us a signal discipline alone cannot: if the worktree comes
# back dirty, the reviewer touched the code under test, and every reproduction it
# claims to have run was run against code it had modified.
#
# Usage: run_review.sh <sha> <round> <task>
set -uo pipefail

SHA=${1:?sha}; ROUND=${2:?round}; TASK=${3:?task}
PROJECT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
cd "$PROJECT_DIR" || exit 1

OUT="$PROJECT_DIR/tasks/review/task-$TASK/round-$ROUND"
WT="$PROJECT_DIR/.claude/worktrees/review-${SHA:0:8}"
STATE="$PROJECT_DIR/tasks/review/state.env"

mkdir -p "$OUT/repro"

finish() {  # finish <status>
  cat > "$STATE" <<STATE_EOF
prev_task=$TASK
prev_round=$ROUND
prev_sha=$SHA
prev_status=$1
prev_out=tasks/review/task-$TASK/round-$ROUND
STATE_EOF
  exit 0
}

fail() {  # fail <reason>
  python "$PROJECT_DIR/tasks/review/emit_error.py" "$OUT/findings.json" \
    "$TASK" "$ROUND" "$SHA" "$1"
  echo "[run_review] FAILED: $1" >&2
  finish error
}

# The spec the developer worked from is the todo.md as it stood before the work,
# not the one they rewrote afterwards to explain themselves. Same base rule as
# tasks/REVIEW.md: first commit of the range, its parent.
FIRST=$(git rev-list "origin/master..$SHA" 2>/dev/null | tail -1)
[ -n "$FIRST" ] || FIRST=$SHA
BASE=$(git rev-parse "$FIRST^" 2>/dev/null) || BASE=""
[ -n "$BASE" ] || fail "cannot resolve a base commit for $SHA"

if docker version >/dev/null 2>&1; then
  DOCKER_NOTE="Docker 守护进程在线，测试命令可以直接跑。"
else
  DOCKER_NOTE="⚠️ Docker 守护进程当前不可达。你**必须**先自己确认能不能跑测试；如果确实跑不了，不要靠读代码硬凑 findings，直接交 verdict=\"blocked\" 说明原因。"
fi

git worktree remove --force "$WT" >/dev/null 2>&1
git worktree add --detach "$WT" "$SHA" >/dev/null 2>&1 || fail "git worktree add failed for $SHA"

# The whitelist travels with the round: the reviewer reads the current one,
# not whatever version happened to be committed at the reviewed sha.
cp "$PROJECT_DIR/tasks/review/accepted-risks.md" "$OUT/accepted-risks.md" 2>/dev/null

python - "$PROJECT_DIR/tasks/review/reviewer_prompt.md" "$OUT/prompt.md" <<PY
import io, sys
src, dst = sys.argv[1], sys.argv[2]
values = {
    "{{TASK}}": """$TASK""",
    "{{ROUND}}": """$ROUND""",
    "{{SHA}}": """$SHA""",
    "{{BASE}}": """$BASE""",
    "{{OUT}}": """$OUT""",
    "{{WT}}": """$WT""",
    "{{PROJECT_DIR}}": """$PROJECT_DIR""",
    "{{DOCKER_NOTE}}": """$DOCKER_NOTE""",
}
text = io.open(src, encoding="utf-8").read()
for k, v in values.items():
    text = text.replace(k, v)
io.open(dst, "w", encoding="utf-8", newline="\n").write(text)
PY
[ -s "$OUT/prompt.md" ] || fail "prompt rendering produced nothing"

# AI_REVIEW_CHILD keeps the reviewer's own Stop hook from starting a review of
# the review. --add-dir lets it write findings outside the worktree it is judging.
( cd "$WT" && AI_REVIEW_CHILD=1 claude -p \
    --permission-mode bypassPermissions \
    --add-dir "$OUT" \
    --output-format json < "$OUT/prompt.md" ) > "$OUT/session.json" 2> "$OUT/session.err"
CLAUDE_RC=$?

DIRTY=$(git -C "$WT" status --porcelain 2>/dev/null)
if [ -n "$DIRTY" ]; then
  printf '%s\n' "$DIRTY" > "$OUT/breach.txt"
  git -C "$WT" diff > "$OUT/breach.diff" 2>/dev/null
fi
git worktree remove --force "$WT" >/dev/null 2>&1

[ -s "$OUT/findings.json" ] || fail "reviewer exited rc=$CLAUDE_RC without writing findings.json (see session.err)"

PYTHONIOENCODING=utf-8 python "$PROJECT_DIR/tasks/review/validate_findings.py" "$OUT" \
  > "$OUT/validator.log" 2>&1
finish done
