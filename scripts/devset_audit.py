#!/usr/bin/env python3
"""Audit the frozen dev set against triage.csv: coverage, mixture, dead tasks.

Runs anywhere, including Windows PowerShell -- no shell heredocs needed:

    python scripts/devset_audit.py
    python scripts/devset_audit.py --orphan-threshold 3
    python scripts/devset_audit.py --exclude experiments/excluded.txt

Three questions it answers:

  1. Which dev-set tasks look unwinnable? A task whose tests import symbols the
     problem statement never mentions cannot be solved from the statement alone.
     triage.py counts those as orphan symbols; >=3 is the practical cutoff.
  2. Does the dev set match the real repo mixture? Arm comparisons are weighted
     by whatever mixture the dev set actually has, not the one it looks like.
  3. What does the mixture become once dead tasks are removed? This is the
     number that matters, and it is usually much worse than (2).
"""

from __future__ import annotations

import argparse
import collections
import csv
import sys
from pathlib import Path

# Verified 2026-10-29 by `swegemma eval --skip-agent-patch` over all 129 tasks,
# AFTER installing the gemma4-task-deps wheels (starlette 0.52.1, dirty_equals,
# inline_snapshot, pytest-httpbin). 47 tasks were repaired by those wheels and
# the seven previously hardcoded here are all among them.
#
# These still fail at collection with no agent patch applied. The cause is NOT
# cleanly separated between a genuine environment defect and a FAIL_TO_PASS test
# importing the API the task asks you to build -- the two produce the same error
# signature. What is certain is that they cannot be scored locally, which is all
# this list is used for. Re-derive with scripts/baseline_check.py whenever the
# wheels or the Kaggle base image change.
BASELINE_FAILS = {
    "fastapi_14262", "fastapi_15030", "fastapi_15661",
    "fastapi_15745", "fastapi_15785", "rich_3930",
}

# Patch size is a better unwinnability signal than orphan symbols (see below).
# A task needing this many files or added lines is not realistically solvable
# inside a 4-minute, 50-call budget.
MAX_FILES, MAX_LINES = 5, 300


def pct(n: int, total: int) -> str:
    return f"{100 * n / total:5.1f}%" if total else "    --"


def mixture(ids: set[str], repo_of: dict[str, str]) -> collections.Counter:
    return collections.Counter(repo_of.get(i, "?") for i in ids)


def table(title: str, counts: collections.Counter, total: int,
          reference: collections.Counter | None = None,
          ref_total: int = 0) -> None:
    print(f"\n{title}  (n={total})")
    repos = sorted(set(counts) | set(reference or {}),
                   key=lambda r: -(reference or counts)[r])
    for repo in repos:
        line = f"  {repo:22}{counts[repo]:4}  {pct(counts[repo], total)}"
        if reference is not None:
            drift = (100 * counts[repo] / total if total else 0) - (
                100 * reference[repo] / ref_total if ref_total else 0)
            flag = "  <-- off by {:+.0f} pts".format(drift) if abs(drift) >= 8 else ""
            line += f"   target {pct(reference[repo], ref_total)}{flag}"
        print(line)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--triage", default=Path("experiments/triage.csv"), type=Path)
    ap.add_argument("--devset", default=Path("experiments/devset.txt"), type=Path)
    ap.add_argument("--exclude", type=Path,
                    help="file of extra task ids to treat as dead, one per line")
    ap.add_argument("--orphan-threshold", type=int, default=3,
                    help="report tasks at or above this orphan count")
    ap.add_argument("--strict-orphans", action="store_true",
                    help="also treat orphan-flagged tasks as dead (NOT advised: "
                         "the metric mostly measures how terse the issue text is)")
    args = ap.parse_args()

    for p in (args.triage, args.devset):
        if not p.is_file():
            print(f"not found: {p}", file=sys.stderr)
            return 1

    rows = list(csv.DictReader(args.triage.open(encoding="utf-8")))
    if not rows:
        print(f"no rows in {args.triage}", file=sys.stderr)
        return 1

    rows_by_id = {r["instance_id"]: r for r in rows}
    repo_of = {r["instance_id"]: r["repo"] for r in rows}
    orphans = {r["instance_id"]: int(r["orphan_symbols"] or 0) for r in rows}
    names = {r["instance_id"]: r.get("orphan_names", "") for r in rows}

    dev = {line.strip() for line in args.devset.read_text().splitlines() if line.strip()}
    extra = set()
    if args.exclude and args.exclude.is_file():
        extra = {l.strip() for l in args.exclude.read_text().splitlines() if l.strip()}

    missing = dev - set(repo_of)
    if missing:
        print(f"WARNING  {len(missing)} dev id(s) absent from triage.csv: "
              f"{', '.join(sorted(missing))}")

    # 1. unwinnable by orphan count
    flagged = sorted(
        (i for i in dev if orphans.get(i, 0) >= args.orphan_threshold),
        key=lambda i: -orphans[i],
    )
    print(f"\n{'='*70}\nORPHAN-SYMBOL SIGNAL (weak -- read the caveat)"
          f"\n{'='*70}")
    if flagged:
        for i in flagged:
            print(f"  {i:18}{orphans[i]:3}  {names[i][:58]}")
        print(f"\n  {len(flagged)} task(s) at >={args.orphan_threshold} orphans. "
              f"Treat as weak evidence only:\n"
              f"  for the tasks this metric flags hardest the 'orphan' symbols are\n"
              f"  ordinary long-existing APIs (APIRouter, Depends, FastAPI), so it\n"
              f"  measures how terse the issue text is, not whether the task can be\n"
              f"  solved. Not counted as dead unless --strict-orphans.")
    else:
        print("  none")

    # size-based exclusion, computed rather than hardcoded
    oversized = {
        i for i in dev
        if i in rows_by_id
        and (int(rows_by_id[i]["files_changed"] or 0) > MAX_FILES
             or int(rows_by_id[i]["lines_added"] or 0) > MAX_LINES)
    }
    if oversized:
        print(f"\n{'='*70}\nOVERSIZED (> {MAX_FILES} files or > {MAX_LINES} added lines)"
              f"\n{'='*70}")
        for i in sorted(oversized):
            r = rows_by_id[i]
            print(f"  {i:18}{r['files_changed']:>3} files  {r['lines_added']:>6} lines")

    dead = oversized | (BASELINE_FAILS & dev) | (extra & dev)
    if args.strict_orphans:
        dead |= set(flagged)
    live = dev - dead

    # 2 and 3. mixture
    full = mixture(set(repo_of), repo_of)
    table("REAL MIXTURE (all triaged tasks)", full, len(repo_of))
    table("DEV SET as listed", mixture(dev, repo_of), len(dev), full, len(repo_of))
    table("DEV SET excluding dead tasks  <-- what you are actually measuring",
          mixture(live, repo_of), len(live), full, len(repo_of))

    print(f"\n{'='*70}\nDEAD TASKS ({len(dead)} of {len(dev)})\n{'='*70}")
    for i in sorted(dead):
        why = []
        if args.strict_orphans and orphans.get(i, 0) >= args.orphan_threshold:
            why.append(f"{orphans[i]} orphans")
        if i in oversized:
            r = rows_by_id[i]
            why.append(f"oversized ({r['files_changed']}f/{r['lines_added']}L)")
        if i in BASELINE_FAILS:
            why.append("fails at baseline")
        if i in extra:
            why.append("excluded")
        print(f"  {i:18}{', '.join(why)}")

    if dead:
        print(f"\nscore any arm out of {len(live)}, not {len(dev)}")
    else:
        print(f"\nall {len(dev)} dev tasks are live -- score arms out of {len(dev)}")

    uncovered = sorted(set(full) - set(mixture(live, repo_of)))
    if uncovered:
        share = sum(full[r] for r in uncovered)
        print(f"\nNO COVERAGE AT ALL: {', '.join(uncovered)}"
              f"  ({pct(share, len(repo_of))} of the real set)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
