"""Write a findings.json standing in for a review that never happened.

wait.sh only knows how to read findings.json, so a crashed or blocked run has to
speak the same language as a successful one -- otherwise the dev session sits at
a blank prompt guessing whether silence means "clean" or "broken".
"""
import io
import json
import os
import sys

out_path, task, rnd, sha, reason = sys.argv[1:6]
os.makedirs(os.path.dirname(out_path), exist_ok=True)
payload = {
    "task": task,
    "round": int(rnd),
    "commit": sha,
    "base": "",
    "verdict": "error",
    "error": reason,
    "findings": [],
}
with io.open(out_path, "w", encoding="utf-8", newline="\n") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2)
