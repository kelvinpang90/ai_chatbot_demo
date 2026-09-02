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
#
# REVIEW_BASE overrides that when the automatic answer is the wrong one: work
# that is not a numbered task has no todo.md entry to date it, and unpushed
# rounds pile up in `origin/master..HEAD` so the range grows a task at a time.
# Reviewing something already reviewed is not free -- it spends the reviewer's
# attention on ground that has been covered.
if [ -n "${REVIEW_BASE:-}" ]; then
  BASE=$(git rev-parse "$REVIEW_BASE" 2>/dev/null) || BASE=""
  [ -n "$BASE" ] || fail "REVIEW_BASE=$REVIEW_BASE is not a commit"
else
  FIRST=$(git rev-list "origin/master..$SHA" 2>/dev/null | tail -1)
  [ -n "$FIRST" ] || FIRST=$SHA
  BASE=$(git rev-parse "$FIRST^" 2>/dev/null) || BASE=""
  [ -n "$BASE" ] || fail "cannot resolve a base commit for $SHA"
fi

if docker version >/dev/null 2>&1; then
  DOCKER_NOTE="Docker 守护进程在线，测试命令可以直接跑。"
else
  DOCKER_NOTE="⚠️ Docker 守护进程当前不可达。你**必须**先自己确认能不能跑测试；如果确实跑不了，不要靠读代码硬凑 findings，直接交 verdict=\"blocked\" 说明原因。"
fi

# Every round parks its worktree at a path named after the commit it reviews, so
# removing "the same path" only ever clears a re-run of this exact round. Rounds
# of other commits pile up untouched, one full checkout each. Clear them all --
# a round that has filed its verdict has no further use for its worktree, and if
# its window is somehow still open, it has already said everything it had to say.
for stale in "$PROJECT_DIR"/.claude/worktrees/review-*; do
  [ -d "$stale" ] && git worktree remove --force "$stale" >/dev/null 2>&1
done
git worktree prune >/dev/null 2>&1
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

# How the reviewer runs. `window` opens a real terminal you can watch and talk
# to; `print` is the headless one-shot, which is what an unattended run wants.
# AI_REVIEW_CHILD keeps the reviewer's own Stop hook from reviewing the review,
# and --add-dir lets it write findings outside the worktree it is judging.
#
# ⚠️ `window` is not unattended yet: it needs one keypress. Claude Code only
# skips the workspace trust dialog in non-interactive mode, and
# hasTrustDialogAccepted is recorded per directory in ~/.claude.json -- so every
# round, whose worktree is a fresh `review-<sha8>` path, opens on "do you trust
# the files in this folder?" and waits. Press Enter and the rest runs on its own.
# Closing that gap means either pinning the worktree to one reusable path or
# having this script write into ~/.claude.json, and the second one is not a
# script's business. Undecided; `print` is unaffected either way.
MODE=${REVIEW_MODE:-window}

# Shorter than wait.sh's own 1200s default on purpose. wait.sh is the developer's
# only blocking call, so a window allowed to outlive it would mean every review
# past that point ends with the developer giving up rather than with a verdict --
# and the round that produced no verdict looks the same as one that found nothing.
WINDOW_TIMEOUT=${REVIEW_WINDOW_TIMEOUT:-1080}

# How long a window gets to prove it opened at all. The launcher touches this
# file as its first act, so a missing one means wt.exe never started cmd.
WINDOW_START_TIMEOUT=${REVIEW_WINDOW_START_TIMEOUT:-60}

# A verdict left over from a previous attempt at this same round would be read as
# this round finishing instantly -- the developer would be handed someone else's
# conclusions about a different commit, and no review would have happened at all.
rm -f "$OUT/findings.json" "$OUT/findings.normalized.json" "$OUT/report.txt" \
      "$OUT/window.started" "$OUT/window.err" "$OUT/breach.txt" "$OUT/breach.diff"

if [ "$MODE" = "print" ]; then
  ( cd "$WT" && AI_REVIEW_CHILD=1 claude -p \
      --permission-mode bypassPermissions \
      --add-dir "$OUT" \
      --output-format json < "$OUT/prompt.md" ) > "$OUT/session.json" 2> "$OUT/session.err"
  CLAUDE_RC=$?
else
  # A .cmd file rather than a wt.exe command line: quoting a nested command
  # through Git Bash, wt and cmd is three levels of escaping and one silent
  # failure mode. This is also something you can re-run by hand.
  winpath() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }
  LAUNCH="$OUT/launch.cmd"
  {
    echo "@echo off"
    echo "title review: task $TASK round $ROUND"
    echo "set AI_REVIEW_CHILD=1"
    # First act, so its absence is proof the window never got as far as cmd.
    echo "echo started > \"$(winpath "$OUT")\\window.started\""
    echo "cd /d \"$(winpath "$WT")\""
    echo "echo ==== cold review: task $TASK, round $ROUND, commit ${SHA:0:8} ===="
    echo "echo Brief: $(winpath "$OUT")\\prompt.md"
    echo "echo."
    echo "echo If it asks whether you trust the files in this folder, press Enter."
    echo "echo It is a throwaway worktree of your own repo and every round makes a"
    echo "echo new one, so the answer is never remembered. Nothing else needs you."
    echo "echo."
    echo "claude --permission-mode bypassPermissions --add-dir \"$(winpath "$OUT")\" \"Read the file $(winpath "$OUT")\\prompt.md and do exactly what it says.\""
    echo "echo."
    echo "echo ==== window done. Findings: $(winpath "$OUT")\\findings.json ===="
    echo "pause"
  } > "$LAUNCH"

  MSYS_NO_PATHCONV=1 wt.exe "$(winpath "$LAUNCH")" > "$OUT/window.err" 2>&1 &
  WT_PID=$!

  # Waiting for a verdict from a window that never opened burns the whole timeout
  # and then reports it as if the reviewer had been thinking the entire time.
  # Fail on the one thing that distinguishes them: did anything start?
  waited=0
  while [ ! -s "$OUT/window.started" ] && [ "$waited" -lt "$WINDOW_START_TIMEOUT" ]; do
    sleep 2
    waited=$((waited + 2))
  done
  if [ ! -s "$OUT/window.started" ]; then
    wait "$WT_PID" 2>/dev/null; LAUNCH_RC=$?
    fail "review window never opened (wt.exe exited $LAUNCH_RC); see $OUT/window.err and try $LAUNCH by hand"
  fi

  # The window does not exit when the review does -- you may still be reading it
  # or asking follow-ups -- so the finish line is the verdict file appearing,
  # held steady for one interval so a half-written file is not read as done.
  CLAUDE_RC=0
  waited=0; stable=0
  while [ "$waited" -lt "$WINDOW_TIMEOUT" ]; do
    if [ -s "$OUT/findings.json" ]; then
      stable=$((stable + 1))
      [ "$stable" -ge 2 ] && break
    else
      stable=0
    fi
    sleep 5
    waited=$((waited + 5))
  done
  [ -s "$OUT/findings.json" ] || fail "window opened but filed no verdict within ${WINDOW_TIMEOUT}s -- the window is still on screen, look at it"
fi

DIRTY=$(git -C "$WT" status --porcelain 2>/dev/null)
if [ -n "$DIRTY" ]; then
  printf '%s\n' "$DIRTY" > "$OUT/breach.txt"
  git -C "$WT" diff > "$OUT/breach.diff" 2>/dev/null
fi

# What that check is worth depends on the mode, and the difference matters enough
# to record rather than leave the reader to infer. Headless, the reviewer process
# is already dead, so a clean worktree covers the whole session. In a window the
# session is still alive and the worktree stays, so it only covers the moment the
# verdict was filed -- which is still the moment that matters, since every claim
# in findings.json was produced before it.
{
  echo "mode: $MODE"
  echo "checked_at: $(date -Iseconds 2>/dev/null || date)"
  if [ "$MODE" = "print" ]; then
    echo "coverage: whole session (the reviewer process had already exited)"
  else
    echo "coverage: up to the filing of findings.json (the window is still open;"
    echo "          anything done in it after that is outside this check)"
  fi
  echo "dirty: ${DIRTY:-none}"
} > "$OUT/integrity.txt"

# Only the headless run removes the worktree. In window mode you are probably
# still standing in it; the next round's `git worktree remove --force` at the
# top of this script clears it anyway.
[ "$MODE" = "print" ] && git worktree remove --force "$WT" >/dev/null 2>&1

[ -s "$OUT/findings.json" ] || fail "reviewer exited rc=$CLAUDE_RC without writing findings.json (see session.err)"

PYTHONIOENCODING=utf-8 python "$PROJECT_DIR/tasks/review/validate_findings.py" "$OUT" \
  > "$OUT/validator.log" 2>&1
finish done
