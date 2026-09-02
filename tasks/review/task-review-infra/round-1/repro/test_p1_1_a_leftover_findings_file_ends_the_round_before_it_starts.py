"""Window mode treats "findings.json exists" as "the review is finished".

Nothing clears the file first, and the output directory is a pure function of
task and round -- `tasks/review/task-$TASK/round-$ROUND`. So any round whose
directory already holds a findings.json is declared finished within seconds,
against a reviewer that has not read a single line.

This is reachable through the project's own documented recovery path. REVIEW.md
says a stuck task is reopened by deleting `tasks/review/state.env`; hook_stop.sh
then restarts the count at round 1, and `tasks/review/task-9/round-1/findings.json`
is committed in the repository. Re-running run_review.sh by hand -- also
documented in REVIEW.md -- lands on the same file.
"""

import json


STALE = {
    "task": "T",
    "round": 1,
    "commit": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    "base": "",
    "verdict": "clean",
    "suite_result": "left behind by an earlier run of this same round",
    "findings": [],
}


def test_a_round_whose_output_dir_is_not_empty_is_never_actually_reviewed(harness):
    out = harness.out_dir("T", 1)
    out.mkdir(parents=True)
    out.joinpath("findings.json").write_text(json.dumps(STALE), encoding="utf-8")

    launched = harness.root / "wt-was-called.txt"
    harness.stub_wt('echo called >> "%s"\n' % str(launched).replace("\\", "/"))

    proc = harness.run_review(round_=1, task="T", window_timeout=20)

    state = harness.state()
    assert state.get("prev_status") == "done", (
        "harness precondition: the round should report a status\n"
        "stdout=%s\nstderr=%s" % (proc.stdout, proc.stderr)
    )

    normalized = json.loads(
        out.joinpath("findings.normalized.json").read_text(encoding="utf-8")
    )
    assert normalized["commit"] != STALE["commit"], (
        "run_review.sh reported round 1 as done after %.1fs and handed the "
        "developer a verdict copied out of a findings.json that was already on "
        "disk before this round started (commit %s, verdict %r). No review of "
        "%s ever happened."
        % (proc.elapsed, normalized["commit"][:8], normalized.get("verdict"),
           harness.sha[:8])
    )
