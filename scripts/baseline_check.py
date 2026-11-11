#!/usr/bin/env python3
"""Classify a `swegemma eval --skip-agent-patch` run: which tasks can run at all.

With --skip-agent-patch the agent never runs, so Phase 2 applies task.test_patch
to the UNMODIFIED repo and runs the target tests. Every task is expected to fail
-- those are the FAIL_TO_PASS tests. What distinguishes a usable task from a
broken one is HOW it fails:

    tests ran and failed        -> environment is fine, the task is winnable
    collection / import error   -> the repo could not even be imported

The second kind is an environment defect, not a task. Under --sandbox subprocess
the harness cannot create a venv with pip, so per-task dependencies are never
installed and the tests die against whatever is in system site-packages.

No GPU is needed for any of this: no agent, no LLM calls.

Usage:
    python scripts/baseline_check.py results/skipagent_before
    python scripts/baseline_check.py results/skipagent_after \
        --compare results/skipagent_before
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

# Failures that happen while pytest is still importing the test module, i.e.
# before any assertion in the task's own tests could run.
COLLECTION = (
    (re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'"), "missing-dep"),
    (re.compile(r"ImportError: cannot import name '([\w]+)'"), "import-error"),
    (re.compile(r"TypeError: \w+\.__init__\(\) got an unexpected keyword argument '(\w+)'"),
     "version-skew"),
    (re.compile(r"error during collection"), "collection-error"),
    (re.compile(r"Interrupted: \d+ error"), "collection-error"),
)


def classify(log: Path) -> tuple[str, str]:
    """Return (verdict, detail) for one task's Phase 2 log."""
    if not log.is_file():
        return "no-log", "no test_outputs log written"
    text = log.read_text(errors="replace")
    for pattern, kind in COLLECTION:
        m = pattern.search(text)
        if m:
            detail = m.group(0).strip()
            return kind, detail[:72]
    return "ok", "tests ran"


def load(run: Path) -> dict[str, tuple[str, str, int | None]]:
    results = run / "task_results.jsonl"
    if not results.is_file():
        print(f"no task_results.jsonl under {run}", file=sys.stderr)
        raise SystemExit(1)
    out = {}
    for line in results.open():
        r = json.loads(line)
        tid = r["instance_id"]
        verdict, detail = classify(run / "test_outputs" / f"{tid}.log")
        out[tid] = (verdict, detail, r.get("test_exit_code"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", type=Path)
    ap.add_argument("--compare", type=Path,
                    help="an earlier run to diff against (e.g. before the wheels)")
    ap.add_argument("--quiet", action="store_true", help="omit the per-task table")
    args = ap.parse_args()

    # This classifier is only sound on a --skip-agent-patch run. On a normal
    # run the agent's own broken patch also produces collection errors, so
    # environment damage and agent damage become indistinguishable.
    patches = sorted((args.run / "patches").glob("*.patch"))
    applied = [f for f in patches if f.stat().st_size > 0]
    if applied:
        print(f"WARNING  {len(applied)} non-empty patch(es) in {args.run}/patches.\n"
              f"         This looks like a normal eval run, not --skip-agent-patch.\n"
              f"         A collection error here may be the AGENT's patch, not the\n"
              f"         environment. Do not paste this ENV_BROKEN set anywhere.\n")

    now = load(args.run)
    # "no-log" means Phase 2 never ran for that task (usually the run was cut
    # short). That is unknown, not broken, and must not reach ENV_BROKEN.
    broken = {t for t, (v, _, _) in now.items() if v not in ("ok", "no-log")}
    unknown = {t for t, (v, _, _) in now.items() if v == "no-log"}

    if not args.quiet:
        print(f"{'task':20}{'verdict':18}{'exit':6}detail")
        for tid in sorted(now):
            v, d, code = now[tid]
            print(f"{tid:20}{v:18}{str(code):6}{d if v != 'ok' else ''}")

    kinds = collections.Counter(v for v, _, _ in now.values())
    print(f"\n{len(now)} task(s): " +
          ", ".join(f"{k} {n}" for k, n in kinds.most_common()))
    usable = len(now) - len(broken) - len(unknown)
    print(f"usable: {usable}/{len(now)} = {usable / len(now):.1%}")
    if unknown:
        print(f"UNKNOWN: {len(unknown)} task(s) have no Phase 2 log — the run "
              f"did not reach them. Re-run before trusting this list.")

    if args.compare:
        before = load(args.compare)
        was_broken = {t for t, (v, _, _) in before.items()
                      if v not in ("ok", "no-log")}
        fixed = sorted(was_broken - broken)
        regressed = sorted(broken - was_broken)
        print(f"\n{'='*70}\nvs {args.compare}\n{'='*70}")
        print(f"  repaired : {len(fixed)}")
        for t in fixed:
            print(f"      {t:20}{before[t][1]}")
        if regressed:
            print(f"  REGRESSED: {len(regressed)}")
            for t in regressed:
                print(f"      {t:20}{now[t][1]}")
        print(f"\n  usable {len(before) - len(was_broken)} -> {len(now) - len(broken)}")

    print(f"\n{'='*70}\npaste into scripts/devset_audit.py\n{'='*70}")
    print("ENV_BROKEN = {")
    for i in range(0, len(sorted(broken)), 4):
        chunk = sorted(broken)[i:i + 4]
        print("    " + ", ".join(f'"{t}"' for t in chunk) + ",")
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
