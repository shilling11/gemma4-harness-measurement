# When the Harness Lies — evidence and code

Supporting material for the paper *When the Harness Lies: Operational Budget and
Measurement Fidelity Dominate Model and Prompt Choice for Local SWE Agents*
(Sultan Fawad, Ali Hussain, Balasivan Dhanapal, Yusuf Tagari), submitted to the
paper track of Google's Gemma 4 Developer Agent Competition.

The paper is in [`paper/DRAFT.md`](paper/DRAFT.md).

## Check the paper instead of trusting it

```
python scripts/verify_paper_numbers.py
```

This re-derives every figure the paper reports from the data in this
repository, prints the claimed value beside the computed one, and exits
non-zero if any pair disagrees. At the time of submission it reports
**24/24 figures reproduced**.

Four figures cannot be derived here and are listed separately as EXTERNAL: the
held-out public scores (0.03 / 0.10 / 0.12 / 0.15) and the `max_time_minutes`
4/5/6 curve in §5.3. Those are produced only by the competition's own scorer,
which we cannot run.

## What is here

```
experiments/
  CHANGELOG.md        the full research record, every configuration to its score
  full129_*_sh{0,1,2}of3/   the 129-task run, in three shards
  devset_*/           the 24-task development arms: prompt versions, reasoning
                      budgets, model scale, and three repeated seeds
  skipagent_before/   verification run with the agent bypassed, before the
  skipagent_after/    dependency fix and after -- the basis for §3
  */task_results.jsonl   per-task outcome, patch size, duration, tool calls
  */traces/           per-step tool calls, observations and metrics
  */patches/          the diffs the agent produced
scripts/
  verify_paper_numbers.py  re-derives the paper's figures (start here)
  baseline_check.py        classifies an agent-free run into usable vs broken
  bm25_locate.py           BM25 file localisation over a repository
  bm25_eval.py             hit@5 for localisation against gold-patch file lists
  strip_traces.py          the redaction described below
  pack.py                  builds and validates the submission archive
  devset_audit.py, triage.py, make_devset.py, get_data.py
submission/           the exact agent configuration behind the reported scores
paper/DRAFT.md
```

## What has been removed, and why

Competition data may not be redistributed to anyone who has not accepted the
competition's rules. Each trace carried the task's problem statement verbatim,
and the agent's own reasoning quoted and paraphrased it across thousands of
further steps.

So `scripts/strip_traces.py` removed the message text of every `user` and
`agent` step — 6,834,896 characters across 345 traces — replacing each with a
redaction marker. What remains is `system` messages (our own prompt), and all
`tool_calls`, `observations`, `metrics` and timings.

This costs the paper nothing, and that is checkable rather than asserted: no
task text appears in `tool_calls` or `observations` anywhere in the 345 traces,
and those are where every derived figure comes from. Re-deriving the figures
from the redacted traces returns identical values, which is what
`verify_paper_numbers.py` demonstrates.

The repository history contains only the redacted form. Nothing here has ever
held the unredacted traces.

## Reproducing the environment finding

§3 reports that 53 of 129 tasks (41%) could not be scored under the harness's
`subprocess` sandbox, because it cannot install per-task test dependencies. The
evidence is the two agent-free runs:

```
python scripts/baseline_check.py experiments/skipagent_before
python scripts/baseline_check.py experiments/skipagent_after
```

A task is unscorable when its tests fail to collect, which the harness reports
as exit code 2. That count falls from 53 to 11 once starlette is pinned to
0.52.1 and `dirty_equals`, `inline_snapshot` and `pytest-httpbin` are
installed — 42 tasks repaired, none regressed.

## Licence and scope

The code here is ours and is offered for inspection and reuse. The task set,
repository snapshots and problem statements belong to the competition and are
not included in any form.
