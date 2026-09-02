"""replay.py returns the lexicographically last session file, not the newest.

`transcript_for` does `sorted(glob(...))[-1]`, and Claude Code names session
files with random UUIDs, so the ordering it sorts by carries no information
about which session is the review you asked to replay.

One session file per project directory is the lucky case, not the guaranteed
one: this diff makes the reviewer interactive on purpose ("而且可以打断它"), the
generated launch.cmd is advertised as something you can re-run by hand, and each
`claude` invocation in that cwd files a new transcript. When there is more than
one, replay.py silently prints a plausible-looking timeline from whichever UUID
happens to sort last -- and a replay tool that shows you the wrong session
without saying so is worse than one that refuses.
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

from conftest import review_src

COMMIT = "abcdef1234567890abcdef1234567890abcdef12"


@pytest.fixture
def replay():
    path = review_src() / "replay.py"
    spec = importlib.util.spec_from_file_location("replay_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _session(directory: Path, name: str, text: str, mtime: float) -> Path:
    path = directory / name
    path.write_text(
        json.dumps({"type": "assistant",
                    "message": {"content": [{"type": "text", "text": text}]}}) + "\n",
        encoding="utf-8",
    )
    os.utime(path, (mtime, mtime))
    return path


def test_transcript_for_returns_the_session_that_actually_ran_this_review(
    replay, tmp_path, monkeypatch
):
    home = tmp_path / "home"
    project = home / ".claude" / "projects" / (
        "E--projects-demo--claude-worktrees-review-%s" % COMMIT[:8]
    )
    project.mkdir(parents=True)

    # An abandoned first attempt, and the run that produced the findings.
    _session(project, "ffffffff-0000-0000-0000-000000000000.jsonl",
             "first attempt, interrupted", mtime=1_000_000)
    newest = _session(project, "00000000-1111-2222-3333-444444444444.jsonl",
                      "the session that filed the findings", mtime=2_000_000)

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    chosen = replay.transcript_for(COMMIT)
    assert chosen == newest, (
        "replay.py chose the abandoned session %s (mtime older by ~11 days) over "
        "the one that filed the findings, %s. It sorted two random UUIDs and took "
        "the last one, so which review you get to audit is decided by filename "
        "luck." % (chosen.name, newest.name)
    )
