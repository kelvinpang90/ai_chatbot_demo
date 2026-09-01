#!/usr/bin/env bash
# Run the backend suite in the pinned container.
#
# Both sides of the review use this one script so "red" and "green" mean the same
# thing on both sides. Reproduction tests live outside the backend tree and are
# mounted in at /app/repro, which is what keeps the reviewed worktree pristine:
# the reviewer never has to drop a file into backend/tests to prove a bug.
#
# Usage: pytest_docker.sh <backend_dir> [repro_dir] [extra pytest args...]
#        repro_dir may be "" to run the suite alone.
set -uo pipefail

# Git Bash rewrites anything that looks like a Unix path in an argument, so the
# container-side `-w /app` arrived as `D:/Git/app` and docker refused to start.
# No effect anywhere else -- other shells do not read this.
export MSYS_NO_PATHCONV=1

BACKEND=${1:?usage: pytest_docker.sh <backend_dir> [repro_dir] [pytest args...]}
REPRO=${2:-}
shift 2 2>/dev/null || shift 1

# Docker Desktop wants Windows paths; everything else passes straight through.
winpath() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi
}

if ! docker version >/dev/null 2>&1; then
  echo "[pytest_docker] Docker daemon is not reachable -- start Docker Desktop." >&2
  exit 125
fi

[ -d "$BACKEND" ] || { echo "[pytest_docker] no such backend dir: $BACKEND" >&2; exit 2; }

args=(run --rm -v "$(winpath "$(cd "$BACKEND" && pwd)"):/app")
if [ -n "$REPRO" ] && [ -d "$REPRO" ]; then
  args+=(-v "$(winpath "$(cd "$REPRO" && pwd)"):/app/repro")
  TARGETS="/app/repro"
else
  TARGETS=""
fi
args+=(-w /app -e PYTHONPATH=/app -e PYTHONIOENCODING=utf-8 python:3.13-slim)

# python -m pytest, never bare pytest: bare pytest leaves cwd off sys.path and
# every test module dies with ModuleNotFoundError: No module named 'app'.
args+=(sh -c "pip install -q -r requirements-dev.txt && python -m pytest -q -p no:cacheprovider $TARGETS $*")

docker "${args[@]}"
