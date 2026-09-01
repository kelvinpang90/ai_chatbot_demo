"""Turn a reviewer's findings into a queue the developer is actually bound by.

The point of the whole two-session setup is that "is this finding real?" stops
being a matter of opinion. A finding earns a place in the fix queue by carrying
evidence a machine can re-run:

  repro      a test file, mounted in and run against the UNMODIFIED commit, that
             fails now and passes after the fix. This is the default and it is
             what P1 normally has to look like.
  command    the approved exception, for security and configuration problems
             that no test can express -- "the repository is public" is true or
             false, but pytest cannot tell you which. Needs the command and its
             output, verbatim.
  read-only  read the code and reasoned about it. Never enters the queue; round
             one of this process put the false-positive rate of that category at
             the top of the list of things not to trust.

Usage: validate_findings.py <round_dir>
"""
import io
import json
import os
import sys

EXCEPTION_CATEGORIES = {"security", "config"}
VALID_SEVERITY = ("P1", "P2", "P3")


def load(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def check(finding, repro_dir):
    """Return (queued, severity, notes) for one finding."""
    notes = []
    severity = finding.get("severity", "P3")
    if severity not in VALID_SEVERITY:
        notes.append("severity 非法 (%r)，按 P3 处理" % severity)
        severity = "P3"

    evidence = finding.get("evidence") or {}
    kind = evidence.get("kind", "read-only")
    category = (finding.get("category") or "").lower()

    if kind == "repro":
        rel = evidence.get("test") or ""
        target = os.path.join(repro_dir, os.path.basename(rel.split("::")[0]))
        if not rel:
            notes.append("evidence.kind=repro 但没写 test 路径 → 降级")
            return False, "P3", notes
        if not os.path.exists(target):
            notes.append("repro 文件不存在: %s → 降级" % rel)
            return False, "P3", notes
        if not evidence.get("observed_failure"):
            notes.append("没贴 repro 跑红时的输出 → 降级")
            return False, "P3", notes
        return True, severity, notes

    if kind == "command":
        if category not in EXCEPTION_CATEGORIES:
            notes.append(
                "command 证据只对 security/config 类开放，category=%r → 降级" % category
            )
            return False, "P3", notes
        if not (evidence.get("command") and evidence.get("output")):
            notes.append("command 证据缺 command 或 output → 降级")
            return False, "P3", notes
        return True, severity, notes

    notes.append("只读代码推测，不进修复队列（可以作为线索）")
    return False, "P3", notes


def main():
    round_dir = sys.argv[1]
    findings_path = os.path.join(round_dir, "findings.json")
    data = load(findings_path)
    repro_dir = os.path.join(round_dir, "repro")

    # Task and round come from the directory the orchestrator created, not from
    # what the reviewer typed into its own report. Nothing the reviewer says
    # about which round it is should be able to mislabel the evidence.
    round_name = os.path.basename(os.path.normpath(round_dir))
    task_name = os.path.basename(os.path.dirname(os.path.normpath(round_dir)))
    data["task"] = task_name.replace("task-", "")
    data["round"] = round_name.replace("round-", "")

    lines = []
    verdict = data.get("verdict", "findings")
    lines.append("任务 %s / 第 %s 轮 / commit %s" % (
        data["task"], data["round"], (data.get("commit") or "")[:8]))
    lines.append("verdict: %s" % verdict)
    if data.get("error"):
        lines.append("error: %s" % data["error"])

    breach = os.path.join(round_dir, "breach.txt")
    if os.path.exists(breach):
        lines.append("")
        lines.append("🚨 审查方改动了被审 worktree（见 breach.diff）。")
        lines.append("   它跑出来的每一条 repro 都是在它自己改过的代码上跑的，")
        lines.append("   这一轮的结论一律按未经证实处理。")

    queued = 0
    for finding in data.get("findings", []):
        ok, severity, notes = check(finding, repro_dir)
        finding["queue"] = bool(ok) and not os.path.exists(breach)
        finding["effective_severity"] = severity
        finding["validator_notes"] = notes
        queued += 1 if finding["queue"] else 0

    total = len(data.get("findings", []))
    lines.append("")
    lines.append("报了 %d 条，进修复队列 %d 条，降级 %d 条。" % (total, queued, total - queued))
    lines.append("")
    for finding in data.get("findings", []):
        flag = "MUST FIX" if finding["queue"] else "降级"
        lines.append("[%s] %s %s  %s:%s" % (
            flag,
            finding.get("id", "?"),
            finding["effective_severity"],
            finding.get("file", "?"),
            finding.get("line", "?"),
        ))
        lines.append("    %s" % finding.get("summary", ""))
        ev = finding.get("evidence") or {}
        lines.append("    证据: %s %s" % (ev.get("kind", "?"), ev.get("test") or ev.get("command") or ""))
        for note in finding["validator_notes"]:
            lines.append("    ! %s" % note)

    data["queued_count"] = queued
    with io.open(os.path.join(round_dir, "findings.normalized.json"), "w",
                 encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)

    # Write the report here rather than letting the shell redirect stdout: a
    # redirected stdout on Windows encodes as cp1252, and every Chinese
    # character in this report raises UnicodeEncodeError.
    with io.open(os.path.join(round_dir, "report.txt"), "w",
                 encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    sys.stdout.write("validated: %d findings, %d queued\n" % (total, queued))


if __name__ == "__main__":
    main()
