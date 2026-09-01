"""Print what the reviewer actually did, one step at a time.

The reviewer runs detached in a worktree that gets deleted, so all that lands in
the repo is its verdict. That makes the most expensive part of this process the
least inspectable part: you can read what it concluded, but not how it got
there, and a review you cannot audit is a review you have to take on faith.

Claude Code keeps the full transcript under ~/.claude/projects/<cwd-slug>/, and
that outlives the worktree. The slug ends in the reviewed commit, which is also
recorded in findings.json -- the one file here that is committed. Everything
this script needs therefore survives both the worktree being removed and the
run-time files being gitignored, which the first version did not: it read the
session id out of session.json, and session.json dies with the worktree.

Usage:
    python tasks/review/replay.py 9 1           # task 9, round 1
    python tasks/review/replay.py 9 1 --full    # do not trim long output
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

# Enough to see which file or command it was, not enough to bury the timeline.
PREVIEW = 400

TOOL_FIELDS = ("command", "file_path", "pattern", "path", "description")


def out(text: str = "") -> None:
    """stdout that survives a Windows console's default code page."""
    sys.stdout.buffer.write((text + "\n").encode("utf-8", "replace"))


def transcript_for(commit: str) -> Path:
    """The reviewer's transcript, found by the commit it was reviewing.

    run_review.sh parks the worktree at `.claude/worktrees/review-<sha8>`, and
    Claude Code names its project directory after that path.
    """
    matches = sorted(
        (Path.home() / ".claude" / "projects").glob(f"*review-{commit[:8]}/*.jsonl")
    )
    if not matches:
        raise SystemExit(
            f"no transcript for the review of {commit[:8]}.\n"
            "Claude Code prunes these over time; findings.json and repro/ stay in git."
        )
    return matches[-1]


def blocks(entry: dict) -> list:
    content = (entry.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


def summarise(tool: dict, full: bool) -> str:
    name = tool.get("name", "?")
    args = tool.get("input") or {}
    for field in TOOL_FIELDS:
        if field in args:
            value = str(args[field])
            return f"{name}: {value if full else value[:PREVIEW]}"
    return name


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    full = "--full" in sys.argv
    if len(args) != 2:
        raise SystemExit(__doc__)
    task, round_ = args

    root = Path(__file__).resolve().parent / f"task-{task}" / f"round-{round_}"
    findings = json.loads((root / "findings.json").read_text(encoding="utf-8"))
    path = transcript_for(findings["commit"])

    out(f"===== task {task} / round {round_} =====")
    out(f"reviewed {findings['commit'][:8]}, verdict: {findings.get('verdict')}")
    out(f"transcript: {path}")
    out()

    step = 0
    for line in io.open(path, encoding="utf-8"):
        entry = json.loads(line)
        if entry.get("type") != "assistant":
            continue
        for block in blocks(entry):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and block.get("text", "").strip():
                text = block["text"].strip()
                out(f"  {text if full else text[:PREVIEW]}")
                out()
            elif block.get("type") == "tool_use":
                step += 1
                out(f"[{step:>3}] {summarise(block, full)}")

    out()
    out(f"{step} tool calls. Findings and reproductions: {root}")


if __name__ == "__main__":
    main()
