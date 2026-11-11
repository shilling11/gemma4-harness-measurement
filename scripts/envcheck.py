#!/usr/bin/env python3
"""Flag dev-set tasks whose tests fail for environment reasons, not agent reasons.

The subprocess sandbox cannot create a venv with pip (ensurepip is stripped from
the Kaggle image), so per-task dependencies are never installed and tests run
against whatever is in system site-packages. When that resolves to a library
version the task's commit predates, the test file dies at COLLECTION time with a
TypeError/ImportError in a file the agent never touched. Those tasks are
unwinnable under subprocess sandboxing and must be masked out of the dev set,
or every arm of a sweep is scored against a lower ceiling than it looks.

A task is flagged when BOTH hold:
  1. its test log shows a collection-time failure (import/TypeError on kwargs,
     ModuleNotFoundError, SyntaxError) outside the agent's own patch, and
  2. the agent patch does not touch the file the error is raised in.

Condition 2 is what separates "broken environment" from "agent broke the repo".

Usage:
    python envcheck.py results/devset_prompt_v2_think_1024
    python envcheck.py results/<run> --mask    # print just the winnable IDs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Errors that fire while pytest is still importing test modules. These mean the
# repo could not be loaded at all, so the target test never ran.
COLLECTION_ERRORS = (
    re.compile(r"TypeError: \w+\.__init__\(\) got an unexpected keyword argument '([\w]+)'"),
    re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'"),
    re.compile(r"ImportError: cannot import name '([\w]+)'"),
    re.compile(r"SyntaxError: (.+)"),
)

# Any repo source file named in a traceback frame. Frames come in two shapes:
#   fastapi/routing.py:838: in __init__
#   E   File "/tmp/swegemma_sandbox_<id>/workspace/fastapi/routing.py", line 337
# The second must be normalised to repo-relative or a file the agent broke
# inside the sandbox looks like a different file from the one it patched.
FRAME = re.compile(r"((?:[\w.\-]+/)*[\w.\-]+\.py)[\":]")
SANDBOX = re.compile(r"^.*?/workspace/")


def patched_files(patch: Path) -> set[str]:
    """Files the agent's diff touches, normalised to repo-relative paths."""
    if not patch.is_file():
        return set()
    files: set[str] = set()
    for line in patch.read_text(errors="replace").splitlines():
        if line.startswith(("+++ b/", "--- a/")):
            files.add(line[6:].strip())
    return files


def diagnose(log: Path, touched: set[str], patch_text: str) -> tuple[str, str] | None:
    """Return (kind, detail) when the log shows an environment failure."""
    if not log.is_file():
        return None
    text = log.read_text(errors="replace")

    for pat in COLLECTION_ERRORS:
        m = pat.search(text)
        if not m:
            continue

        # Every repo file named in the traceback frames just above the error,
        # plus the error line itself (a SyntaxError names its own file there).
        window = text[: m.end()].splitlines()[-16:]
        culprits = set()
        for line in window:
            for raw in FRAME.findall(line):
                culprits.add(SANDBOX.sub("", raw).lstrip("/"))
        repo_culprits = {c for c in culprits if not c.startswith("tests/")}

        # The agent broke it if the raising file is one the agent edited.
        if repo_culprits & touched:
            return None

        # An unexpected-kwarg error on a name the agent's own diff introduces
        # is an incomplete implementation, not version skew: the task asked for
        # that kwarg and the agent wired it into the wrong place.
        name = m.group(1)
        if "unexpected keyword argument" in m.group(0) and name in patch_text:
            return None

        kind = "missing-dep" if "ModuleNotFound" in m.group(0) else "version-skew"
        where = ", ".join(sorted(repo_culprits)) or "unknown"
        return kind, f"{m.group(0).strip()}  (raised in {where})"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", type=Path, help="a results directory")
    ap.add_argument("--mask", action="store_true", help="print winnable IDs only")
    args = ap.parse_args()

    results = args.run / "task_results.jsonl"
    if not results.is_file():
        print(f"no task_results.jsonl under {args.run}", file=sys.stderr)
        return 1

    rows = [json.loads(line) for line in results.open()]
    broken, winnable, resolved_ok = [], [], 0

    for r in sorted(rows, key=lambda r: r["instance_id"]):
        tid = r["instance_id"]
        patch = args.run / "patches" / f"{tid}.patch"
        touched = patched_files(patch)
        patch_text = patch.read_text(errors="replace") if patch.is_file() else ""
        verdict = diagnose(args.run / "test_outputs" / f"{tid}.log", touched, patch_text)

        if verdict and not r["resolved"]:
            broken.append((tid, *verdict))
        else:
            winnable.append(tid)
            resolved_ok += bool(r["resolved"])

    if args.mask:
        print(" ".join(winnable))
        return 0

    print(f"{len(broken)} task(s) unwinnable under the subprocess sandbox:\n")
    for tid, kind, detail in broken:
        print(f"  {tid:16} {kind:13} {detail}")

    n = len(winnable)
    print(f"\nscored  {resolved_ok}/{len(rows)} = {resolved_ok / len(rows):.3f}  (as reported)")
    print(f"true    {resolved_ok}/{n} = {resolved_ok / n:.3f}  (winnable only)")
    print(f"\nmask:   python {Path(__file__).name} {args.run} --mask")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

