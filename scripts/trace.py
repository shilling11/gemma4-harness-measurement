#!/usr/bin/env python3
"""Summarise an ATIF trace: what the agent did, and where the time went.

    python scripts/trace.py results/<run>/traces/                  # all, one line each
    python scripts/trace.py results/<run>/traces/trace_x.json      # one in full

ATIF v1.7 shape (verified against the harness output):
  step.source            agent | system | user
  step.extra.event_type  thinking | system_instruction | task_prompt | final
  step.message           the reasoning text
  step.tool_calls[]      {tool_call_id, function_name, arguments, extra.elapsed_s}
  step.observation       the tool result

Time between a step's own elapsed_s and the previous tool's elapsed_s is
time the model spent generating (thinking + the call itself). That is the
number that matters when the budget is wall-clock.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ARG_KEYS = ("command", "filepath", "old_string", "node", "query", "nodes", "content")


def arg_summary(args: dict) -> str:
    if not isinstance(args, dict):
        return str(args)[:70]
    for k in ARG_KEYS:
        if k in args:
            return f"{k}={str(args[k])[:64]!r}"
    return str(args)[:64] if args else ""


def walk(t: dict):
    """Yield (elapsed_s, kind, name, desc) in order."""
    for s in t.get("steps", []):
        ev = (s.get("extra") or {}).get("event_type", "")
        msg = str(s.get("message") or "").replace("\n", " ")
        calls = s.get("tool_calls") or []

        if ev in ("system_instruction", "task_prompt"):
            yield (s.get("extra", {}).get("elapsed_s"), ev, "",
                   f"{len(msg)} chars", {})
            continue

        if ev == "thinking" and not calls:
            yield (s.get("extra", {}).get("elapsed_s"), "think", "", msg[:88], {})

        for c in calls:
            el = (c.get("extra") or {}).get("elapsed_s")
            name = c.get("function_name", "?")
            a = c.get("arguments") or {}
            yield (el, "tool", name, arg_summary(a), a)

        if ev == "final":
            yield (s.get("extra", {}).get("elapsed_s"), "final", "", msg[:88], {})


def summarise(p: Path, verbose: bool = True) -> dict:
    t = json.loads(p.read_text())
    tools: Counter[str] = Counter()
    seen: Counter[str] = Counter()
    repeats = 0
    gen_time = 0.0
    last = 0.0
    submitted = 0

    if verbose:
        print(f"\n=== {p.name}")

    for el, kind, name, desc, raw in walk(t):
        gap = (el - last) if (el and last) else 0.0
        if el:
            last = el
        if kind == "tool":
            tools[name] += 1
            key = f"{name}|{json.dumps(raw, sort_keys=True)}"
            seen[key] += 1
            if seen[key] > 1:
                repeats += 1
            if name == "submit_patch":
                submitted += 1
            gen_time += gap
        if verbose and kind not in ("system_instruction",):
            stamp = f"{el:7.1f}s" if el else "        "
            delta = f"+{gap:5.1f}" if gap > 0.5 else "      "
            label = name or kind
            print(f"  {stamp} {delta}  {label:20} {desc[:78]}")

    calls = sum(tools.values())
    out = {"trace": p.name, "calls": calls, "repeats": repeats,
           "submits": submitted, "elapsed": round(last, 1),
           "gen_s": round(gen_time, 1), "tools": dict(tools)}

    if verbose:
        pct = 100 * gen_time / last if last else 0
        print(f"\n  {last:.0f}s elapsed | {calls} calls | {repeats} repeated "
              f"| {submitted} submit_patch")
        print(f"  {gen_time:.0f}s ({pct:.0f}%) spent generating between calls")
        for n, c in tools.most_common():
            print(f"    {n:24} {c}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", type=Path)
    args = ap.parse_args()

    if args.path.is_dir():
        rows = [summarise(p, False) for p in sorted(args.path.glob("trace_*.json"))]
        print(f"{'trace':32} {'calls':>6} {'rpt':>4} {'sub':>4} "
              f"{'secs':>6} {'gen_s':>6} {'gen%':>5}")
        for r in rows:
            pct = 100 * r["gen_s"] / r["elapsed"] if r["elapsed"] else 0
            print(f"{r['trace'][:32]:32} {r['calls']:>6} {r['repeats']:>4} "
                  f"{r['submits']:>4} {r['elapsed']:>6.0f} {r['gen_s']:>6.0f} "
                  f"{pct:>4.0f}%")
        agg: Counter[str] = Counter()
        for r in rows:
            agg.update(r["tools"])
        print(f"\n{sum(r['calls'] for r in rows)} calls across {len(rows)} traces:")
        for n, c in agg.most_common():
            print(f"  {n:24} {c}")
        never = [r["trace"] for r in rows if not r["submits"]]
        if never:
            print(f"\nNEVER called submit_patch ({len(never)}):")
            for n in never:
                print(f"  {n}")
        return 0

    if not args.path.is_file():
        print(f"not found: {args.path}", file=sys.stderr)
        return 1
    summarise(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())