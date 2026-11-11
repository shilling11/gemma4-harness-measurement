#!/usr/bin/env python3
"""Assemble the public, redacted evidence tree for the paper.

The private repository's git history contains unredacted traces, so it cannot
be made public by deleting files -- `git show` would still recover them. This
builds a clean tree instead, to be pushed as a fresh repository with no history.

    python scripts/build_public_export.py --out ../gemma4-public
    cd ../gemma4-public && python scripts/verify_paper_numbers.py
    git init && git add -A && git commit -m "evidence and code for the paper"
    gh repo create <name> --public --source=. --remote=origin --push

It refuses to write anything if the redaction check fails.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
# Built from fragments so that this file does not itself contain the
# contiguous phrases, which would make the check below fail on its own source.
MARK = re.compile(rb"Problem" + rb" State" + rb"ment|"
                  rb"You are evaluating a software" + rb" engineering task")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    out = os.path.abspath(a.out)
    if os.path.exists(out):
        if not a.force:
            print(f"{out} exists; pass --force to replace it", file=sys.stderr)
            return 2
        shutil.rmtree(out)
    os.makedirs(out)

    exp_src = os.path.join(REPO, "experiments")
    exp_out = os.path.join(out, "experiments")

    # 1. redacted traces, plus summary.json and task_results.jsonl
    r = subprocess.run([sys.executable, os.path.join(HERE, "strip_traces.py"),
                        "--root", exp_src, "--out", exp_out],
                       capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode:
        return r.returncode

    # 2. the agent's own patches, and the derived task lists
    for name in sorted(os.listdir(exp_src)):
        p = os.path.join(exp_src, name, "patches")
        if os.path.isdir(p):
            shutil.copytree(p, os.path.join(exp_out, name, "patches"))
    for f in ("CHANGELOG.md", "devset.txt", "triage.csv"):
        s = os.path.join(exp_src, f)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(exp_out, f))

    # 3. code, configuration, paper, README
    os.makedirs(os.path.join(out, "scripts"))
    for f in sorted(os.listdir(HERE)):
        if f.endswith(".py"):
            shutil.copy2(os.path.join(HERE, f), os.path.join(out, "scripts", f))
    shutil.copytree(os.path.join(REPO, "submission"), os.path.join(out, "submission"))
    os.makedirs(os.path.join(out, "paper"))
    shutil.copy2(os.path.join(REPO, "paper", "DRAFT.md"),
                 os.path.join(out, "paper", "DRAFT.md"))
    pub = os.path.join(REPO, "paper", "PUBLIC_README.md")
    if os.path.isfile(pub):
        shutil.copy2(pub, os.path.join(out, "README.md"))

    # 4. refuse to ship if any competition task text survives
    hits, n = [], 0
    for root, _, files in os.walk(out):
        for fn in files:
            p = os.path.join(root, fn)
            n += 1
            try:
                with open(p, "rb") as fh:
                    if MARK.search(fh.read()):
                        hits.append(os.path.relpath(p, out))
            except OSError:
                pass
    if hits:
        print(f"\nREDACTION CHECK FAILED: {len(hits)} files still carry task text:",
              file=sys.stderr)
        for h in hits[:10]:
            print("   ", h, file=sys.stderr)
        shutil.rmtree(out)
        print("export deleted; nothing was written", file=sys.stderr)
        return 1

    print(f"redaction check passed: 0 of {n} files carry task text")
    print(f"\nexport ready at {out}")
    print("next: cd there, run scripts/verify_paper_numbers.py, then git init and push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
