"""Harness for reproducing bugs in the review orchestration itself.

The code under review this round is shell and orchestration, not backend Python,
so these reproductions drive the real `tasks/review/run_review.sh` against a
throwaway git repo instead of importing `app.*`.

⚠️ They therefore need `bash` and `git` ON THE HOST. `tasks/review/pytest_docker.sh`
mounts only `backend/` into python:3.13-slim, which has neither git nor the
`tasks/review/` tree, so these cannot run through the shared entry point. Run
them from the repo root with plain pytest:

    python -m pytest tasks/review/task-review-infra/round-1/repro -q

Nothing here touches the reviewed worktree: every run gets its own temp repo
built from a copy of `tasks/review/`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

COPY_GLOBS = ("*.sh", "*.py", "reviewer_prompt.md", "accepted-risks.md")


def review_src() -> Path:
    """The tasks/review/ directory of the checkout this repro file lives in.

    Walking up rather than hard-coding means the developer re-running this after
    a fix exercises their fixed scripts, not a snapshot of the broken ones.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "tasks" / "review" / "run_review.sh").exists():
            return parent / "tasks" / "review"
    raise RuntimeError("cannot locate tasks/review/ above %s" % __file__)


BASH = shutil.which("bash")


class Harness:
    """A disposable repo with the real review scripts installed in it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.review = root / "tasks" / "review"
        self.stub_dir = root / "stub-bin"
        self.review.mkdir(parents=True)
        self.stub_dir.mkdir()

        src = review_src()
        for pattern in COPY_GLOBS:
            for path in src.glob(pattern):
                shutil.copy2(path, self.review / path.name)

        self._git("init", "-q", ".")
        self._git("config", "user.email", "harness@example.invalid")
        self._git("config", "user.name", "harness")
        (root / "reviewed.txt").write_text("original\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")
        self.base = self._git("rev-parse", "HEAD").strip()
        (root / "reviewed.txt").write_text("changed by the developer\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "work under review")
        self.sha = self._git("rev-parse", "HEAD").strip()

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=False
        ).stdout

    def out_dir(self, task: str, round_: int) -> Path:
        return self.review / ("task-%s" % task) / ("round-%d" % round_)

    def worktree(self, sha: str) -> Path:
        return self.root / ".claude" / "worktrees" / ("review-%s" % sha[:8])

    def stub_wt(self, body: str) -> None:
        """Install a fake Windows Terminal so no real window ever opens.

        Git Bash execs a `#!`-script regardless of its .exe name, so this
        shadows the real wt.exe as long as stub-bin comes first on PATH.
        """
        path = self.stub_dir / "wt.exe"
        path.write_bytes(("#!/bin/sh\n" + body).encode("utf-8"))
        os.chmod(path, 0o755)

    def run_review(self, round_: int = 1, task: str = "T", sha: str | None = None,
                   window_timeout: int = 20, timeout: int = 300):
        env = dict(os.environ)
        # The reviewer's own session exports these; they must not leak into a
        # harness that is specifically testing mode selection.
        for key in ("REVIEW_MODE", "AI_REVIEW_CHILD", "REVIEW_WINDOW_TIMEOUT"):
            env.pop(key, None)
        env["REVIEW_BASE"] = self.base
        env["REVIEW_WINDOW_TIMEOUT"] = str(window_timeout)
        env["PATH"] = str(self.stub_dir) + os.pathsep + env["PATH"]

        script = str(self.review / "run_review.sh").replace("\\", "/")
        started = time.time()
        proc = subprocess.run(
            [BASH, script, sha or self.sha, str(round_), task],
            cwd=str(self.root), env=env, capture_output=True, text=True,
            timeout=timeout,
        )
        proc.elapsed = time.time() - started  # type: ignore[attr-defined]
        return proc

    def state(self) -> dict:
        path = self.review / "state.env"
        if not path.exists():
            return {}
        pairs = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                pairs[key.strip()] = value.strip()
        return pairs


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    if not BASH:
        pytest.fail(
            "these reproductions drive tasks/review/run_review.sh and need bash on "
            "the host; pytest_docker.sh cannot run them (it mounts only backend/)"
        )
    return Harness(tmp_path / "repo")
