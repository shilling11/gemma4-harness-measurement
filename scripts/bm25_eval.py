#!/usr/bin/env python3
"""Measure hit@5 for localising the files a gold patch edits.

Reproduces three rows of the published comparison on OUR task set, before any
submission depends on the figure:

    grep       identifier counts per source file      published 0.41
    bm25_all   BM25, tests included                   published 0.48
    bm25_src   BM25, tests excluded                   published 0.64

If our numbers land near those, the lever is real and worth shipping. If they
do not, we have spent an afternoon instead of a submission.

Run this where the competition data lives -- it needs tasks.jsonl and the
repository snapshots. It is CPU-only and needs no GPU.

    python scripts/bm25_eval.py \
        --tasks harness/tasks.jsonl \
        --snapshots harness/snapshots \
        --layout "{instance_id}"

--layout is a template for each task's checkout directory under --snapshots.
If the real layout differs, pass the right template; --probe prints what it
found so you can work it out without a full run.

Known interpretation choice: the published grep baseline is described only as
"issue identifiers counted per source file". We implement it over every .py
file, without the test filter, since applying the filter to grep as well would
confound the comparison we care about. If their 0.41 was measured with tests
excluded, our grep row will not reproduce theirs -- but bm25_src vs bm25_all
remains a clean internal comparison either way, and that is the factor worth
the submission.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bm25_locate import collect, rank, tokenize  # noqa: E402

PATCH_KEYS = ("patch", "gold_patch", "solution_patch", "test_patch_excluded",
              "golden_patch", "diff")
STMT_KEYS = ("problem_statement", "issue", "task_prompt", "problem", "text",
             "issue_body", "description")
EDITED = re.compile(r"^\+\+\+ b/(.+)$", re.M)


def pick(d: dict, keys) -> tuple[str | None, str | None]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return k, v
    return None, None


def gold_files(patch: str) -> set[str]:
    out = set()
    for m in EDITED.finditer(patch):
        path = m.group(1).strip()
        if path and path != "/dev/null":
            out.add(path)
    return out


def grep_rank(root: str, query: str, top: int):
    """The grep baseline: count issue identifiers per source file."""
    terms = set(tokenize(query))
    if not terms:
        return []
    scored = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            c = Counter(t for t in tokenize(text) if t in terms)
            if c:
                scored.append((sum(c.values()), os.path.relpath(full, root)))
    scored.sort(key=lambda r: (-r[0], r[1]))
    return [p for _, p in scored[:top]]


def boot(flags, n=2000, seed=0):
    if not flags:
        return (0.0, 0.0)
    rng = random.Random(seed)
    k = len(flags)
    means = sorted(sum(rng.choices(flags, k=k)) / k for _ in range(n))
    return (means[int(0.025 * n)], means[int(0.975 * n)])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--snapshots", required=True)
    ap.add_argument("--layout", default="{instance_id}")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--probe", action="store_true",
                    help="print detected fields and resolved paths, then exit")
    a = ap.parse_args()

    tasks = [json.loads(l) for l in open(a.tasks, encoding="utf-8") if l.strip()]
    if a.limit:
        tasks = tasks[: a.limit]
    if not tasks:
        print("no tasks loaded", file=sys.stderr)
        return 2

    pk, _ = pick(tasks[0], PATCH_KEYS)
    sk, _ = pick(tasks[0], STMT_KEYS)
    if a.probe or not pk or not sk:
        print("keys present:", sorted(tasks[0].keys()))
        print("patch field detected:    ", pk)
        print("statement field detected:", sk)
        for t in tasks[:3]:
            iid = t.get("instance_id") or t.get("id") or "?"
            d = os.path.join(a.snapshots, a.layout.format(**t))
            print(f"  {iid}: {d}  exists={os.path.isdir(d)}")
        if not pk or not sk:
            print("\nCould not detect required fields. Pass the right data or "
                  "add the key names to PATCH_KEYS / STMT_KEYS.", file=sys.stderr)
            return 2
        return 0

    res = {m: [] for m in ("grep", "bm25_all", "bm25_src")}
    skipped = 0
    for t in tasks:
        iid = t.get("instance_id") or t.get("id") or "?"
        patch = t.get(pk) or ""
        stmt = t.get(sk) or ""
        gold = gold_files(patch)
        root = os.path.join(a.snapshots, a.layout.format(**t))
        if not gold or not stmt or not os.path.isdir(root):
            skipped += 1
            continue
        terms = tokenize(stmt)

        def hit(paths):
            return 1.0 if any(p in gold for p in paths) else 0.0

        res["grep"].append(hit(grep_rank(root, stmt, a.top)))
        for name, inc in (("bm25_all", True), ("bm25_src", False)):
            docs = collect(root, include_tests=inc, include_nonsource=inc)
            res[name].append(hit([p for _, p, _ in rank(docs, terms, a.top)]))
        print(f"  {iid}: grep={res['grep'][-1]:.0f} "
              f"all={res['bm25_all'][-1]:.0f} src={res['bm25_src'][-1]:.0f}",
              file=sys.stderr)

    n = len(res["grep"])
    print(f"\nscored {n} tasks ({skipped} skipped)\n")
    print(f"{'method':10s} {'hit@5':>7s}  {'95% CI':>16s}   published")
    for m, pub in (("grep", 0.41), ("bm25_all", 0.48), ("bm25_src", 0.64)):
        v = sum(res[m]) / n if n else 0.0
        lo, hi = boot(res[m])
        print(f"{m:10s} {v:7.3f}  [{lo:.3f}, {hi:.3f}]   {pub:.2f}")
    if n:
        d = sum(res["bm25_src"]) / n - sum(res["grep"]) / n
        print(f"\nbm25_src - grep = {d:+.3f}. Ship only if this is clearly positive;"
              f"\nour own rule is to require gains above 3 tasks before accepting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
