#!/usr/bin/env python3
"""Rank repository source files against an issue description, using BM25.

Why this exists: the agent currently localises with `run_command` grep -- 1,612
calls in the full-129 run, 56% of all tool calls. Published measurement on this
task set puts BM25 over source, with test code filtered out, at 0.64 hit@5 for
ranking the file a fix actually edits, against 0.41 for grep. This reproduces
that method so the figure can be checked on our own tasks before any submission
depends on it.

Constraints this respects, because the scorer enforces them:
  * standard library only -- the environment is offline, nothing installs
  * bounded runtime -- it runs under `timeout_seconds`, which is 60 or less
  * compact output -- harness stdout is truncated at 5,000 characters

Usage:
    python bm25_locate.py --root /workspace --query-file issue.txt
    python bm25_locate.py --root /workspace --query "APIRouter on_startup ignored"
    python bm25_locate.py --root /workspace --query "..." --json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter

K1, B = 1.2, 0.75

# Three distinct filters, kept separate so each can be ablated. The test filter
# alone is the difference between 0.48 and 0.64 hit@5 in the published numbers,
# so conflating it with the others would make that factor unmeasurable.
ALWAYS_SKIP = {
    ".git", ".github", "__pycache__", ".tox", ".venv", "venv", "node_modules",
    "build", "dist", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".eggs",
    "site-packages",
}
TEST_DIRS = {"test", "tests", "testing", "_test", "_tests"}
NONSOURCE_DIRS = {"docs", "doc", "examples", "example", "benchmarks", "bench",
                  "scripts", "tools"}
SKIP_FILE = re.compile(r"(^test_|_test\.py$|^conftest\.py$)")
NONSOURCE_FILE = re.compile(r"^(setup|noxfile|tasks)\.py$")
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")
MAX_TOKENS_PER_FILE = 4000   # bounds runtime on very large modules
MAX_FILE_BYTES = 400_000

# Terms so common in issue prose that they add noise rather than signal.
STOP = {
    "the","and","for","that","this","with","from","not","are","but","you","your",
    "has","have","was","were","will","would","should","could","can","its","it",
    "when","then","there","here","also","into","out","use","used","using","via",
    "def","self","class","import","return","none","true","false","if","else",
    "issue","bug","error","expected","actual","example","code","line","file",
    "python","version","following","above","below","like","does","doesn","instead",
}


def tokenize(text: str) -> list[str]:
    """Identifiers plus their snake_case and camelCase parts, lowercased.

    `APIRouter` yields `apirouter`, `api`, `router`, so an issue written in
    prose can match an identifier written in code.
    """
    out: list[str] = []
    for ident in IDENT.findall(text):
        low = ident.lower()
        if low not in STOP and len(low) > 2:
            out.append(low)
        if "_" in ident:
            out.extend(p for p in low.split("_") if len(p) > 2 and p not in STOP)
        else:
            parts = CAMEL.findall(ident)
            if len(parts) > 1:
                out.extend(p.lower() for p in parts
                           if len(p) > 2 and p.lower() not in STOP)
    return out


def collect(root: str, include_tests: bool, include_nonsource: bool):
    docs: list[tuple[str, list[str]]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        keep = []
        for d in dirnames:
            dl = d.lower()
            if d.startswith(".") or dl in ALWAYS_SKIP:
                continue
            if dl in TEST_DIRS and not include_tests:
                continue
            if dl in NONSOURCE_DIRS and not include_nonsource:
                continue
            keep.append(d)
        dirnames[:] = keep
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            if SKIP_FILE.search(fn) and not include_tests:
                continue
            if NONSOURCE_FILE.search(fn) and not include_nonsource:
                continue
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    continue
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            toks = tokenize(text)[:MAX_TOKENS_PER_FILE]
            if toks:
                docs.append((os.path.relpath(full, root), toks))
    return docs


def rank(docs, query_terms, top):
    n = len(docs)
    if not n:
        return []
    tfs = [Counter(t) for _, t in docs]
    lens = [len(t) for _, t in docs]
    avgdl = sum(lens) / n

    df = Counter()
    qset = set(query_terms)
    for tf in tfs:
        for q in qset & tf.keys():
            df[q] += 1

    qtf = Counter(query_terms)
    scored = []
    for i, (path, _) in enumerate(docs):
        s = 0.0
        hits = []
        for q, qn in qtf.items():
            f = tfs[i].get(q, 0)
            if not f:
                continue
            idf = math.log(1 + (n - df[q] + 0.5) / (df[q] + 0.5))
            s += idf * qn * (f * (K1 + 1)) / (f + K1 * (1 - B + B * lens[i] / avgdl))
            hits.append(q)
        if s > 0:
            hits.sort(key=lambda h: -tfs[i][h])
            scored.append((s, path, hits[:6]))
    scored.sort(key=lambda r: (-r[0], r[1]))
    return scored[:top]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/workspace")
    ap.add_argument("--query")
    ap.add_argument("--query-file")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--include-tests", action="store_true")
    ap.add_argument("--include-nonsource", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.query_file:
        with open(a.query_file, "r", encoding="utf-8", errors="replace") as fh:
            qtext = fh.read()
    elif a.query:
        qtext = a.query
    else:
        qtext = sys.stdin.read()

    terms = tokenize(qtext)
    if not terms:
        print("no usable query terms", file=sys.stderr)
        return 2

    docs = collect(a.root, a.include_tests, a.include_nonsource)
    results = rank(docs, terms, a.top)

    if a.json:
        print(json.dumps({
            "root": a.root, "files_indexed": len(docs),
            "results": [{"path": p, "score": round(s, 3), "matched": h}
                        for s, p, h in results],
        }, indent=1))
        return 0

    if not results:
        print(f"no matches across {len(docs)} source files")
        return 0
    excl = "tests excluded" if not a.include_tests else "tests included"
    print(f"{len(docs)} source files indexed, {excl}. Top {len(results)}:")
    for i, (s, p, hits) in enumerate(results, 1):
        print(f"{i:2d}. {p}  [{s:.1f}]  {' '.join(hits)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
