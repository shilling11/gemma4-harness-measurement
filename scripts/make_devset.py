#!/usr/bin/env python3
"""Pick a fixed dev set for prompt iteration.
 
    python scripts/make_devset.py experiments/triage.csv --n 24
 
Selection rules, in order:
  1. fastapi + rich only. requests and httpx cannot be verified under the
     subprocess sandbox (missing pytest-httpbin -> recursive fixture error),
     and Docker is unavailable in Kaggle notebooks.
  2. Drop the 6 likely-unwinnable tasks (new file + 3+ symbols the issue
     never names). They burn a full time budget and can never resolve.
  3. Drop monsters: >5 files or >300 lines added. One task cannot be worth
     8% of a 25-task run's wall clock.
  4. Stratify across patch size so the set spans trivial to hard, and
     across repo in proportion to the public mix.
 
Writes experiments/devset.txt (one instance_id per line) and prints the
swegemma --task-ids argument.
 
FREEZE THIS. Changing the dev set mid-competition makes every earlier
measurement incomparable.
"""
 
from __future__ import annotations
 
import argparse
import csv
import random
from pathlib import Path
 
KEEP_REPOS = {"fastapi/fastapi", "Textualize/rich"}
MAX_FILES = 5
MAX_LINES = 300
 
 
def load(path: Path) -> list[dict]:
    rows = list(csv.DictReader(path.open()))
    for r in rows:
        for k in ("files_changed", "lines_added", "lines_removed",
                  "stmt_chars_clean", "orphan_symbols"):
            r[k] = int(r[k])
        for k in ("creates_file", "only_creates"):
            r[k] = r[k] == "True"
    return rows
 
 
def eligible(rows: list[dict]) -> tuple[list[dict], dict[str, int]]:
    dropped = {"repo": 0, "unwinnable": 0, "monster": 0}
    out = []
    for r in rows:
        if r["repo"] not in KEEP_REPOS:
            dropped["repo"] += 1
        elif r["creates_file"] and r["orphan_symbols"] >= 3:
            dropped["unwinnable"] += 1
        elif r["files_changed"] > MAX_FILES or r["lines_added"] > MAX_LINES:
            dropped["monster"] += 1
        else:
            out.append(r)
    return out, dropped
 
 
def bucket(r: dict) -> str:
    """Difficulty proxy: how much code the fix touches."""
    n = r["lines_added"] + r["lines_removed"]
    if n <= 5:
        return "tiny"
    if n <= 20:
        return "small"
    if n <= 60:
        return "medium"
    return "large"
 
 
def pick(rows: list[dict], n: int, seed: int) -> list[dict]:
    """Proportional by repo, then spread evenly across size buckets."""
    rng = random.Random(seed)
    chosen: list[dict] = []
 
    for repo in sorted(KEEP_REPOS):
        pool = [r for r in rows if r["repo"] == repo]
        quota = round(n * len(pool) / len(rows))
        by_bucket: dict[str, list[dict]] = {}
        for r in pool:
            by_bucket.setdefault(bucket(r), []).append(r)
        for v in by_bucket.values():
            rng.shuffle(v)
 
        # round-robin across buckets so the set spans the difficulty range
        order = sorted(by_bucket, key=lambda b: -len(by_bucket[b]))
        i = 0
        while len([c for c in chosen if c["repo"] == repo]) < quota:
            b = order[i % len(order)]
            if by_bucket[b]:
                chosen.append(by_bucket[b].pop())
            elif not any(by_bucket.values()):
                break
            i += 1
    return chosen
 
 
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("triage", type=Path, nargs="?",
                    default=Path("experiments/triage.csv"))
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=Path("experiments/devset.txt"))
    args = ap.parse_args()
 
    rows = load(args.triage)
    pool, dropped = eligible(rows)
    chosen = pick(pool, args.n, args.seed)
    chosen.sort(key=lambda r: (r["repo"], r["instance_id"]))
 
    print(f"{len(rows)} tasks -> {len(pool)} eligible -> {len(chosen)} selected\n")
    print(f"  dropped: {dropped['repo']} wrong repo (requests/httpx, "
          f"unverifiable locally)")
    print(f"           {dropped['unwinnable']} likely unwinnable")
    print(f"           {dropped['monster']} too large (>{MAX_FILES} files "
          f"or >{MAX_LINES} lines)\n")
 
    counts: dict[tuple[str, str], int] = {}
    for r in chosen:
        counts[(r["repo"], bucket(r))] = counts.get((r["repo"], bucket(r)), 0) + 1
    print("  composition:")
    for (repo, b), c in sorted(counts.items()):
        print(f"    {repo:18} {b:7} {c}")
 
    print(f"\n  median lines changed: "
          f"{sorted(r['lines_added'] + r['lines_removed'] for r in chosen)[len(chosen)//2]}")
    print(f"  median stmt chars:    "
          f"{sorted(r['stmt_chars_clean'] for r in chosen)[len(chosen)//2]}")
 
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(r["instance_id"] for r in chosen) + "\n")
    print(f"\nwrote {args.out}")
    print(f"\n--task-ids {' '.join(r['instance_id'] for r in chosen)}")
    return 0
 
 
if __name__ == "__main__":
    raise SystemExit(main())
 
