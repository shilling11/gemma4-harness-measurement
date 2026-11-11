#!/usr/bin/env python3
"""Triage tasks.jsonl before writing any prompt.
 
    python scripts/triage.py harness/tasks.jsonl
 
Answers five questions that change what the system prompt should say:
  1. How many gold patches CREATE files vs modify existing ones?
  2. How much signal is in the problem statement, after PR boilerplate?
  3. How many tasks have no hints at all?
  4. How large is a typical gold patch?
  5. How many tasks look UNSOLVABLE — tests importing symbols the problem
     statement never mentions?
 
(5) is the important one: it bounds the resolve rate achievable by any agent.
No GPU needed. Writes a per-task CSV for follow-up.
"""
 
from __future__ import annotations
 
import argparse
import json
import re
import sys
from pathlib import Path
 
# --- patch parsing ---------------------------------------------------------
 
NEW_FILE_RE = re.compile(r"^@@ -0,0 ", re.M)
FILE_HDR_RE = re.compile(r"^\+\+\+ b/(.+)$", re.M)
ADDED_RE = re.compile(r"^\+(?!\+\+)", re.M)
REMOVED_RE = re.compile(r"^-(?!--)", re.M)
 
# Imports ADDED by the test patch. Handles parenthesised multi-line imports.
TEST_IMPORT_RE = re.compile(
    r"^\+\s*from\s+(?P<mod>[\w.]+)\s+import\s+(?P<names>\(?[^\n]*)",
    re.M,
)
 
# Test-infrastructure imports carry no task signal.
STDLIB_NOISE = {
    "pytest", "unittest", "mock", "MagicMock", "patch", "Path", "pathlib",
    "os", "sys", "re", "json", "datetime", "date", "time", "typing",
    "Any", "Optional", "List", "Dict", "Tuple", "Union", "Callable",
    "dataclass", "field", "annotations", "contextlib", "tempfile",
    "CliRunner", "TestClient", "Client", "pytestmark", "fixture",
    "warnings", "logging", "copy", "io", "math", "random", "subprocess",
}
 
# Boilerplate that carries no task signal. PR templates dominate this dataset.
BOILERPLATE = [
    r"<!--.*?-->",                      # html comments
    r"##\s*Checklist.*",                # trailing checklist
    r"- \[[ xX]\].*",                   # checkbox lines
    r"##\s*AI Disclaimer.*?(?=\n##|\Z)",
    r"<details>.*?</details>",
    r"##\s*Pull Request\s*",
    r"Discussion:\s*",
]
 
 
def strip_boilerplate(text: str) -> str:
    out = text or ""
    for pat in BOILERPLATE:
        out = re.sub(pat, "", out, flags=re.S | re.I)
    return re.sub(r"\n{2,}", "\n", out).strip()
 
 
def patch_files(patch: str) -> list[str]:
    return FILE_HDR_RE.findall(patch or "")
 
 
def imported_symbols(test_patch: str, touched_files: list[str]) -> set[str]:
    """Symbols the hidden tests import FROM THE CODE UNDER TEST.
 
    Only counts imports whose module maps onto a file the gold patch touches,
    so `import pytest` and `from pathlib import Path` are ignored. These are
    the names an agent has to invent exactly right to pass verification.
    """
    # scripts/prepare_release.py -> scripts.prepare_release
    modules = {f[:-3].replace("/", ".") for f in touched_files if f.endswith(".py")}
    tails = {m.split(".")[-1] for m in modules}
 
    lines = (test_patch or "").splitlines()
    names: set[str] = set()
    for i, line in enumerate(lines):
        m = re.match(r"^\+\s*from\s+([\w.]+)\s+import\s+(.*)$", line)
        if not m:
            continue
        mod, rest = m.group(1), m.group(2)
        mod_clean = mod.lstrip(".")
        first_party = (
            mod_clean in modules
            or mod_clean.split(".")[-1] in tails
            or any(mod_clean.startswith(m2.split(".")[0]) for m2 in modules)
        )
        if not first_party:
            continue
        # gather continuation lines for parenthesised imports
        chunk = rest
        if "(" in rest and ")" not in rest:
            for nxt in lines[i + 1:]:
                chunk += " " + nxt.lstrip("+").strip()
                if ")" in nxt:
                    break
        chunk = chunk.replace("(", " ").replace(")", " ").replace("\\", " ")
        for part in chunk.split(","):
            sym = part.strip().split(" as ")[0].strip()
            if sym.isidentifier() and sym not in STDLIB_NOISE:
                names.add(sym)
    return names
 
 
def analyse(row: dict) -> dict:
    patch = row.get("patch") or ""
    test_patch = row.get("test_patch") or ""
    stmt = row.get("problem_statement") or ""
    stripped = strip_boilerplate(stmt)
 
    files = patch_files(patch)
    new_hunks = len(NEW_FILE_RE.findall(patch))
 
    syms = imported_symbols(test_patch, files)
    # A symbol is "orphan" if the problem statement never names it.
    orphans = sorted(s for s in syms if s not in stmt)
 
    return {
        "instance_id": row.get("instance_id"),
        "repo": row.get("repo"),
        "creates_file": new_hunks > 0,
        "only_creates": new_hunks > 0 and new_hunks == len(files),
        "files_changed": len(files),
        "lines_added": len(ADDED_RE.findall(patch)),
        "lines_removed": len(REMOVED_RE.findall(patch)),
        "stmt_chars_raw": len(stmt),
        "stmt_chars_clean": len(stripped),
        "has_hints": bool((row.get("hints_text") or "").strip()),
        "test_symbols": len(syms),
        "orphan_symbols": len(orphans),
        "orphan_names": ";".join(orphans[:8]),
    }
 
 
def pct(n: int, total: int) -> str:
    return f"{n:>4} / {total}  ({n / total * 100:5.1f}%)" if total else "n/a"
 
 
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tasks", type=Path, nargs="?", default=Path("harness/tasks.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("experiments/triage.csv"))
    args = ap.parse_args()
 
    if not args.tasks.is_file():
        print(f"not found: {args.tasks}", file=sys.stderr)
        return 1
 
    rows = [analyse(json.loads(l)) for l in args.tasks.open() if l.strip()]
    n = len(rows)
    print(f"{n} tasks from {args.tasks}\n")
 
    # 1. repo mix
    repos: dict[str, int] = {}
    for r in rows:
        repos[r["repo"]] = repos.get(r["repo"], 0) + 1
    print("REPO MIX")
    for repo, c in sorted(repos.items(), key=lambda kv: -kv[1]):
        print(f"  {repo:28} {pct(c, n)}")
 
    # 2. new files
    creates = sum(r["creates_file"] for r in rows)
    only = sum(r["only_creates"] for r in rows)
    print("\nPATCH SHAPE")
    print(f"  creates at least one file   {pct(creates, n)}")
    print(f"  ONLY creates files          {pct(only, n)}")
    print(f"  pure modification           {pct(n - creates, n)}")
 
    # 3. patch size
    fc = sorted(r["files_changed"] for r in rows)
    la = sorted(r["lines_added"] for r in rows)
    def med(xs): return xs[len(xs) // 2] if xs else 0
    print(f"\n  files changed   median {med(fc):>4}   max {max(fc, default=0)}")
    print(f"  lines added     median {med(la):>4}   max {max(la, default=0)}")
 
    # 4. problem statement signal
    sc = sorted(r["stmt_chars_clean"] for r in rows)
    thin = sum(1 for r in rows if r["stmt_chars_clean"] < 200)
    nohint = sum(1 for r in rows if not r["has_hints"])
    print("\nPROBLEM STATEMENT")
    print(f"  chars after boilerplate  median {med(sc):>5}   min {min(sc, default=0)}")
    print(f"  under 200 chars          {pct(thin, n)}")
    print(f"  no hints_text            {pct(nohint, n)}")
 
    # 5. the one that matters
    orph = sum(1 for r in rows if r["orphan_symbols"] > 0)
    orph3 = sum(1 for r in rows if r["orphan_symbols"] >= 3)
    print("\nUNSOLVABLE SIGNAL  (tests import names the issue never mentions)")
    print(f"  >=1 orphan symbol        {pct(orph, n)}")
    print(f"  >=3 orphan symbols       {pct(orph3, n)}   <- likely unwinnable")
    print(f"\n  ceiling if >=3 orphans are lost: {(n - orph3) / n * 100:.1f}%")
 
    worst = sorted(rows, key=lambda r: -r["orphan_symbols"])[:10]
    print("\n  worst offenders:")
    for r in worst:
        if r["orphan_symbols"]:
            print(f"    {r['instance_id']:22} {r['orphan_symbols']:>3}  {r['orphan_names'][:60]}")
 
    # csv
    args.out.parent.mkdir(parents=True, exist_ok=True)
    import csv
    with args.out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nper-task detail -> {args.out}")
    return 0
 
 
if __name__ == "__main__":
    raise SystemExit(main())
 
