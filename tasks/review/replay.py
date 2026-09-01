"""Print what the reviewer actually did, one step at a time.

The reviewer runs detached in a worktree that gets deleted, so all that lands in
the repo is its verdict. That makes the most expensive part of this process the
least inspectable part: you can read what it concluded, but not how it got
there, and a review you cannot audit is a review you have to take on faith.

Claude Code keeps the full transcript under ~/.claude/projects/<cwd-slug>/, which
outlives the worktree. This turns one of those into something readable.

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


def transcript_for(session_id: str) -> Path:
    matches = list((Path.home() / ".claude" / "projects").glob(f"*/{session_id}.jsonl"))
    if not matches:
        raise SystemExit(
            f"no transcript for session {session_id}.\n"
            "Claude Code prunes these over time; the verdict in findings.json stays."
        )
    return matches[0]


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
    session = json.loads((root / "session.json").read_text(encoding="utf-8"))

    out(f"===== task {task} / round {round_} =====")
    out(
        f"{session['num_turns']} turns, "
        f"{session['duration_ms'] / 60000:.1f} min, "
        f"${session['total_cost_usd']:.2f}"
    )
    out(f"transcript: {transcript_for(session['session_id'])}")
    out()

    step = 0
    for line in io.open(transcript_for(session["session_id"]), encoding="utf-8"):
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


if __name__ == "__main__":
    main()
