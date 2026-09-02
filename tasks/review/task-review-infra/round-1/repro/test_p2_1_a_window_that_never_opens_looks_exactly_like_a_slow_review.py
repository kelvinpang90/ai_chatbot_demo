"""Window mode never learns whether the window opened.

`MSYS_NO_PATHCONV=1 wt.exe "$LAUNCH" >/dev/null 2>&1 &` throws away both the
output and the exit status of the only thing that starts the reviewer, and
CLAUDE_RC is then hard-coded to 0. A machine with no Windows Terminal, a wt.exe
that refuses to start, a broken launch.cmd -- all of them look identical to a
review that is still thinking, for the full REVIEW_WINDOW_TIMEOUT.

Two consequences, one test each.
"""

import json
import re

from conftest import review_src


def test_a_failed_launch_burns_the_timeout_then_blames_a_file_that_was_never_written(harness):
    out = harness.out_dir("T", 1)
    harness.stub_wt("exit 1\n")  # Windows Terminal missing or refusing to start

    proc = harness.run_review(round_=1, task="T", window_timeout=15)

    findings = json.loads(out.joinpath("findings.json").read_text(encoding="utf-8"))
    error = findings.get("error", "")
    assert error, "harness precondition: the run should have failed\n%s" % proc.stderr

    assert not ("session.err" in error and not out.joinpath("session.err").exists()), (
        "after waiting %.0fs for a window that never opened, the round's only "
        "diagnostic is %r -- and window mode never writes session.err, so the one "
        "file it names does not exist. The launcher's exit status (1 here) was "
        "discarded, so nothing distinguishes 'wt.exe failed instantly' from "
        "'the reviewer is still working'." % (proc.elapsed, error)
    )


def _default(path, name):
    text = path.read_text(encoding="utf-8")
    match = re.search(r"\$\{%s:-(\d+)\}" % name, text)
    assert match, "no default found for %s in %s" % (name, path)
    return int(match.group(1))


def test_the_window_timeout_default_outlives_the_developers_blocking_wait():
    src = review_src()
    window = _default(src / "run_review.sh", "REVIEW_WINDOW_TIMEOUT")
    wait = _default(src / "wait.sh", "REVIEW_WAIT_TIMEOUT")

    assert window <= wait, (
        "run_review.sh waits up to %ds for the window but wait.sh -- the "
        "developer's one blocking call, and the only thing watching -- gives up "
        "at %ds. Every window-mode run that exceeds %ds ends with the developer "
        "told 'this is a timeout, do not read it as a pass' while the round is "
        "still live and will later overwrite state.env behind them."
        % (window, wait, wait)
    )
