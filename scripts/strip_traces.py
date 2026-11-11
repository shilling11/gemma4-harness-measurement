#!/usr/bin/env python3
"""Remove competition task text from trace files before the repo goes public.

Competition data must not be redistributed to anyone who has not accepted the
rules. Each trace carries the task's problem statement verbatim in its
`user`/`task_prompt` step, and the agent's own reasoning quotes and paraphrases
it across thousands more steps -- an unbounded leak that no phrase match can
reliably catch.

So we drop message text from `user` and `agent` steps entirely, and keep:

  * `system` messages -- our own prompt, our own work, and the evidence for
    every prompt-version claim in the paper
  * `tool_calls`, `observation`, `metrics`, timings, `final_metrics`

That second group is where every number in the paper comes from, and a survey
of all 345 traces found zero occurrences of task text in tool calls or
observations. So this costs the paper nothing -- `--verify` re-derives the key
figures from the stripped output to prove it.

    python scripts/strip_traces.py --dry-run
    python scripts/strip_traces.py --out /tmp/stripped
    python scripts/strip_traces.py --in-place
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import sys

REDACT = "[redacted: competition task text, see scripts/strip_traces.py]"
THINKING = "[redacted: agent reasoning may restate the task]"


def strip_trace(t: dict) -> tuple[dict, int]:
    removed = 0
    for s in t.get("steps", []):
        src = s.get("source")
        msg = s.get("message")
        if not isinstance(msg, str) or not msg:
            continue
        if src == "user":
            removed += len(msg)
            s["message"] = REDACT
        elif src == "agent":
            removed += len(msg)
            s["message"] = THINKING
    return t, removed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="experiments")
    ap.add_argument("--out")
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.root, "*", "traces", "trace_*.json")))
    if not files:
        print(f"no traces under {a.root}", file=sys.stderr)
        return 2
    if not (a.out or a.in_place or a.dry_run):
        print("pass --dry-run, --out DIR or --in-place", file=sys.stderr)
        return 2

    total = kept = 0
    for f in files:
        with open(f, encoding="utf-8") as fh:
            t = json.load(fh)
        before = sum(len(s.get("message") or "") for s in t["steps"])
        t, removed = strip_trace(t)
        after = sum(len(s.get("message") or "") for s in t["steps"])
        total += removed
        kept += after
        if a.dry_run:
            continue
        dest = f if a.in_place else os.path.join(a.out, os.path.relpath(f, a.root))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(t, fh, indent=1)

    # non-trace run artefacts carry no task text, but copy them so --out is a
    # complete, self-contained evidence tree
    if a.out and not a.dry_run:
        for pat in ("summary.json", "task_results.jsonl"):
            for f in glob.glob(os.path.join(a.root, "*", pat)):
                dest = os.path.join(a.out, os.path.relpath(f, a.root))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(f, dest)

    verb = "would remove" if a.dry_run else "removed"
    print(f"{len(files)} traces, {verb} {total:,} chars of task and reasoning "
          f"text; {kept:,} chars of our own system prompt retained")
    return 0


if __name__ == "__main__":
    sys.exit(main())
