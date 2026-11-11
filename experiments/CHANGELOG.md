## 2026-10-20 — local harness working, first eval

### Kaggle submission
| Sub | Config | Score |
| --- | --- | --- |
| baseline | unmodified `sample_submission`, no changes | _pending_ |

### Local runs
| Run | Config | Result |
| --- | --- | --- |
| run_13 | sample submission, `--max-time-minutes 5 --max-tool-calls 40`, LoRA on | 0/3 resolved, 2 ctx-overflow, 1 clean |

**Env (not scorer-identical — see notebook header):** torch 2.10.0+cu128,
torchvision 0.25.0, vLLM 0.19.1, transformers 5.16.1, google-adk 2.7.1,
`--max-num-seqs 16`, `VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=1`,
`--sandbox subprocess`. GPU KV cache 54,704 tokens with 2 LoRA adapters.

### Findings
1. **Agent committed `repro.py` instead of a fix** (requests_7502). Scratch file
   written to `/workspace` ended up in the patch; no actual fix present.
   → prompt: scratch files go in `/tmp`. README gotcha #3, hit first run.
2. **2 of 3 tasks died on ContextWindowExceededError.**
   → prompt: call `submit_patch` early and repeatedly (it's free).
3. **`requests` tasks can't be verified under `--sandbox subprocess`** —
   `pytest-httpbin` missing, `httpbin` fixture recurses, ~hundreds of errors.
   Local resolve rates for requests are meaningless until Docker sandbox tested.
4. **KV cache 54,704 tokens** with env var + `--max-num-seqs 16`, vs forum's
   best of 48,384. Worth posting to discussion 749191.
5. **`--sandbox docker` is unavailable in Kaggle notebooks** — no daemon, and
   `swebench-sandbox:latest` would need network to build. Subprocess sandbox is
   the only local path; its missing test deps are a permanent constraint.

### Next
- [ ] Prompt v1: `/tmp` scratch + submit-early + no `{hints}` reference
- [ ] Test `--sandbox docker`
- [ ] Null-adapter submission (does LoRA score at all?)

### Run: devset_baseline
**Config:** unmodified `sample_submission`, 24 frozen dev tasks,
`--max-time-minutes 5 --max-tool-calls 40 --sandbox subprocess`, LoRA on
(sample's placeholder adapters), server per notebook cell 3.

**Result: 3/24 = 0.125**

| Repo | Tasks | Resolved |
| --- | --- | --- |
| Textualize/rich | 11 | 3 (0.27) |
| fastapi/fastapi | 13 | **0** |

**Failure modes:**
| Mode | Count |
| --- | --- |
| ContextWindowExceededError | **19** |
| resolved | 3 |
| unresolved, no error | 2 |

### The finding
**79% of tasks die on context overflow**, not on localisation or bad patches.
This is the dominant failure mode by an order of magnitude.

**Caveat — local overstates this.** The scorer configures ADK compaction
(`compaction_interval=15`, `token_threshold=14,336`) in `scripts/inference.py`,
which is the scorer's wrapper, NOT the `swegemma eval` CLI. Our local runs have
compaction off. So the real scorer sees fewer overflows. Still indicative: the
agent generates far more than 32k and only compaction saves it.

**fastapi 0/13 vs rich 3/11** is unexplained and matters — fastapi is 52% of the
public set. Needs trace inspection.

### Actions
- [ ] Prompt v1: submit_patch early + repeatedly (free, doesn't count against
      tool budget); scratch files to /tmp; drop `{hints}` (always empty)
- [ ] `max_output_tokens` 16384 → 4096 (one turn can currently eat half the
      context window; README gotcha #1 warns of truncated tool calls)
- [ ] Read a fastapi trace — why 0/13?
- [ ] Confirm whether compaction is off locally

## 2026-10-21 — baseline scored 0.03

### Kaggle submission
| Sub | Config | Score |
| --- | --- | --- |
| baseline | unmodified `sample_submission` | **0.03** |

### Why it's that low — and the fix
The sample ships `eval_config.yaml` with **1 minute / 10 tool calls / 50 turns**.
The scorer reads that file. Our local runs pass `--max-time-minutes 5
--max-tool-calls 40` as CLI flags, which **override** eval_config.yaml — so
every local number so far was measured at a budget the submission never got.

0.03 on ~50 public-split tasks is 1-2 tasks resolved. Reference points:
starter notebook 0.12, leaderboard plateau 0.22.

**Root cause of the gap between our local 0.125 and Kaggle 0.03 is budget, not
capability.** Our devset_baseline ran 5 min / 40 calls; the submission ran
1 min / 10 calls.

### Actions
- [x] Confirmed submission path works end to end (zip → score)
- [x] Add `submission/eval_config.yaml` — 5 min / 40 calls / 80 turns / 300s
      timeout. This had never existed in our repo; we were shipping the
      sample's crippled defaults by omission.
- [ ] Submit prompt v1 + budget fix together

### Note on the next submission
Prompt v1 and the budget increase ship together, so the result will not
attribute between them. Accepted deliberately: the budget fix is near-certain
to help, submissions are 1/day, and we have ~6 weeks. Do not read the delta
as evidence about the prompt.

### Open
- fastapi 0/13 locally vs rich 3/11 — unexplained, traces lost to session
  restart. Re-examine from the prompt v1 run.
- Local eval has ADK compaction OFF (scorer sets it in scripts/inference.py,
  not the CLI), so our 79% context-overflow rate overstates the scorer's.

## 2026-10-22 — v2 control arm (thinking 4096)

### Run: devset_prompt_v2_think_4096
**Config:** v2 submission (graph tools removed, FIRST RULE submit_patch,
max_output_tokens 4096), 24 frozen dev tasks, `--max-time-minutes 5
--max-tool-calls 40`, `--sandbox subprocess`, no adapters, thinking_budget 4096.

**Result: 6/24 = 0.25**

| | baseline | prompt_v1 | v2_think_4096 |
| --- | --- | --- | --- |
| resolved | 3 | 5 | **6** |
| context overflow | 19 | 1 | 1 |
| session timeout | 0 | 10 | **7** |
| unresolved, judged | 2 | 8 | **10** |
| fastapi | 0/13 | 0/13 | **1/13** |
| rich | 3/11 | 5/11 | 5/11 |
| never called submit_patch | — | 11/24 | **7/24** |

### Trace analysis (537 tool calls across 24 traces)
| tool | calls |
| --- | --- |
| run_command | 193 |
| read_file | 178 |
| edit_file | 111 |
| write_file | 32 |
| submit_patch | 20 |
| get_status | 3 |
| graph tools | 0 (removed in v2; were 0/515 in v1 too) |

**Generation time is ~91% of wall clock** (per-trace range 53–98%, most
92–96%). Tool execution is negligible. Wall-clock budget is effectively a
token-generation budget, so `thinking_budget` is the only real lever on the
7 timeouts.

**Repeat rate 58/537 = 10.8%**, consistent with the published ~9% for
thinking-on. Two tail outliers genuinely loop: `rich_3454` (12/31) and
`rich_3676` (14/31), both unresolved.

> **CORRECTION.** An earlier note put the repeat rate at 38%. That was a bug in
> `scripts/trace.py` — it keyed repeats on `filepath` alone, so paging through
> a file (lines 1-150, 151-300, ...) counted as repeated calls. Fixed to key on
> the full argument dict. The tool-call-reliability angle is NOT a finding; the
> rate is normal.

### Timing — submission budget
mean 251s, median 267s, total 6,018s over 24 tasks.
Projection: `120 x (251 agent + ~62 sandbox) = 10.4 h` against the 12 h cap —
the same margin as the v1 submission that failed. **Next submission goes out at
3-4 min/task.**

`rich_3772` ran 541s on a 300s cap. A single command can block for
`timeout_seconds` (300) and the session budget is only checked between calls,
so worst case per task is `max_time_minutes + timeout_seconds`. Capping
`timeout_seconds: 120` bounds the tail.

### Patch quality (from prompt_v1 `test_exit_code`, same pattern expected here)
| exit code | meaning | count |
| --- | --- | --- |
| 0 | passed | 5 |
| 1 | tests ran and failed | 6 |
| **2** | **pytest could not collect — likely ImportError** | **6** |
| -1 | no patch | 7 |

All six exit-2 cases are fastapi. If these are import failures, the agent is
shipping patches that do not load, which would explain much of fastapi 1/13.
TODO: read one `test_outputs/*.log`.

### What changed in the story
The bottleneck has moved twice: context overflow -> session timeout -> patch
quality. 10 of 24 now complete cleanly and are judged but fail tests.

Tool-call reliability is **not** a problem (10.8%, normal). The remaining
levers are (a) generation speed, i.e. thinking budget, and (b) patch
correctness, especially whatever breaks fastapi imports.

### Caveats
- Three changes shipped together in v2; no attribution between them.
- 24 tasks means one task = 4.2 points and run-to-run noise is ~±2 tasks. The
  3 -> 5 -> 6 trend is suggestive, not significant. The overflow collapse
  (19 -> 1) is the result that is clearly beyond noise.

### Next
- [ ] Collect sweep arms 2048 / 1024 / 0 from teammates
- [ ] Read a fastapi exit-code-2 log; if ImportError, add a post-edit import check to the prompt
- [ ] `timeout_seconds: 120`, `max_time_minutes: 3-4` for the next submission
- [ ] Prompt line for `get_status` (used 3 times in 537 calls; it is free)

## 2026-10-26 — thinking 1024 arm, and three corrections that move the story

### Run: devset_prompt_v2_think_1024
**Config:** identical to `devset_prompt_v2_think_4096` except `thinking_budget:
1024`. 24 frozen dev tasks, `--max-time-minutes 5 --max-tool-calls 40`,
`--sandbox subprocess`, no adapters, `max_output_tokens: 4096`.

**Result: 6/24 = 0.25 as scored — 6/18 = 0.333 on winnable tasks (see finding 1)**

| | baseline | prompt_v1 | v2_think_4096 | **v2_think_1024** |
| --- | --- | --- | --- | --- |
| resolved | 3 | 5 | 6 | **6** |
| context overflow | 19 | 1 | 1 | **2** |
| session timeout | 0 | 10 | 7 | **4** |
| fastapi | 0/13 | 0/13 | 1/13 | **1/13** |
| rich | 3/11 | 5/11 | 5/11 | **5/11** |
| empty patch | — | 7 | — | **4** |
| total wall clock | — | 1.66 h | 1.67 h | **1.57 h** |

| exit code | meaning | count |
| --- | --- | --- |
| 0 | passed | 6 |
| 1 | tests ran and failed | 8 |
| 2 | pytest could not collect | 5 |
| -1 | no patch produced | 4 |
| 124 | verification timed out | 1 |

**Tool mix (503 calls across 24 traces)**

| tool | calls |
| --- | --- |
| run_command | 239 |
| read_file | 158 |
| edit_file | 61 |
| write_file | 25 |
| submit_patch | 19 |
| get_status | **1** |

`run_command` breakdown: grep 102, python3 52, cat 25, echo 16, printf 13,
pytest 10, sed 7, ls 5. **Only 1 of 239 commands bounded its own output**
(`| head` / `| wc`). **Only 14 of 239 invoked pytest** — most patches were
never tested before submission.

---

### Finding 1 — six fastapi tasks are unwinnable under the subprocess sandbox

`eval.log` carries this ~40 times and we had been reading past it:

```
ensurepip unavailable in sandbox, creating venv without pip
```

The subprocess sandbox cannot build a venv with pip, so per-task dependencies
are never installed and tests run against system site-packages. The image
ships **starlette >= 1.0.0rc1 (2026-02-23)**, which removed `on_startup` /
`on_shutdown` from `Starlette` and `Router` ([release notes][sl]). Every
fastapi commit in the dev set predates that and still passes `on_startup`
through `APIRouter.__init__`, so pytest dies at **collection** time:

```
TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'
  fastapi/routing.py:838: in __init__  ->  super().__init__(
```

Last starlette accepting it: **0.52.1 (2026-01-18)**.

Unwinnable, confirmed by checking that none of their diffs touch `routing.py`
or `applications.py`:

`fastapi_13920` · `fastapi_14077` · `fastapi_14356` · `fastapi_14479` ·
`fastapi_5077` · `fastapi_9753`

Also missing from the sandbox: `dirty_equals` (hits `fastapi_14356`),
`inline_snapshot` (hits `fastapi_14978`).

**NOT environment failures, despite a similar signature:**
- `fastapi_14306` — the agent's own `SyntaxError: unmatched ')'` in
  `fastapi/routing.py`, a file its patch edits.
- `fastapi_14978` — implemented `strict_content_type` on `Body()` and
  `param_functions`, never on `APIRouter`. The task asked for the kwarg; the
  agent wired it to the wrong class. A real miss.

**Corrected denominators**

| | as scored | winnable |
| --- | --- | --- |
| overall | 6/24 = 0.250 | **6/18 = 0.333** |
| fastapi | 1/13 = 0.077 | **1/7 = 0.143** |
| rich | 5/11 = 0.455 | 5/11 = 0.455 |

The "fastapi is structurally harder" story was half an artifact: the real gap
is 0.14 vs 0.46, not 0.08 vs 0.46. Arm-to-arm *deltas* remain valid — all arms
hit the same six dead tasks — but the ceiling is 18, not 24, and every number
recorded above 2026-10-26 understates by that factor.

Classifier: `scripts/envcheck.py <results-dir>`, `--mask` for winnable IDs.
It requires the error to raise in a file the agent never patched, and treats
an unexpected-kwarg error naming a symbol the agent's own diff introduces as
an incomplete implementation rather than skew (that rule is what correctly
keeps `fastapi_14978` in the winnable set).

**Consequence for measurement:** the dev set is now 11 rich vs 7 fastapi, two
of which produce empty patches on timeout. We are effectively tuning on rich
while the hidden set is ~52% fastapi. Restoring the fastapi arm is the highest
-value non-submission work outstanding.

[sl]: https://starlette.dev/release-notes/

---

### Finding 2 — the sweep result is one task, and the control arm is confounded

v1 -> 1024 differs by exactly one resolve: `fastapi_15589`. Every other task
kept its verdict. On 18 winnable tasks one task is 5.6 points. **One task on
one seed cannot carry a config decision or a paper claim.**

Worse, the 4096 control arm ran:

```yaml
max_output_tokens: 4096
thinking_budget:   4096
```

Thinking tokens are drawn *from* the output allowance, so that arm had zero
tokens left for the tool call after a full thinking spend. The 1024 arm had
3072. So "4096 ~= 1024" is really "4096-with-no-response-headroom ~=
1024-with-3072-headroom".

What *is* robust is the other column: **timeouts 10 -> 7 -> 4**, six tasks'
worth of movement against one task in resolves. Restate the claim as:

> Reducing the thinking budget from 4096 to 1024 cuts session timeouts by more
> than half with no detectable change in resolve rate.

That is a wall-clock finding, not an accuracy finding. Seeds move from
nice-to-have to **required** — without a second seed on 1024 and 0 there is no
claim, and we are choosing configs off single-task differences.

For remaining arms: hold `max_output_tokens: 4096` fixed across 0 / 1024 /
2048 so each arm sees the same input ceiling. Report 4096 with the headroom
caveat rather than re-running it.

---

### Finding 3 — time is the binding constraint, not tool calls

The four timeouts used 11, 19, 28 and 31 tool calls against a cap of 40.
Nothing came within 3 calls of the limit. Median step 5.3s, p90 29s.
Raising `max_tool_calls` would do nothing; cheaper steps is the whole game.

Of 496 measured tool-execution intervals: **1 over 60s, 0 over 90s.**

> **CORRECTION to 2026-10-22.** That entry attributed `rich_3772`'s 541s to a
> single shell command blocking for `timeout_seconds` (300) inside the agent
> loop, and proposed `timeout_seconds: 120`. Wrong. `rich_3772` has
> `error: null`, `test_exit_code: 124`, 14 tool calls — the agent finished
> inside budget and the overshoot is **Phase 2 verification**, which
> HARNESS_README 7.1 lists as *fixed at 300 sec on the scorer* and not
> settable from `eval_config.yaml`. `timeout_seconds` bounds Phase 1 commands
> only, and nothing comes near it. **Leave `timeout_seconds: 300`.**

> **CORRECTION to 2026-10-22.** Projection was recorded as 10.4 h. Measured
> from `duration_seconds`: v1 mean 248s -> **8.28 h** at 120 tasks, 1024 mean
> 235s -> **7.83 h**. But HARNESS_README 7.1 notes `agent_start_time` begins
> only after container creation, wheel installation and snapshot extraction,
> so **container setup and Phase 2 verification are excluded from the per-task
> budget while still counting against the 12 h wall.** Locally that overhead
> is ~5s (subprocess, no containers), which is why it was invisible. On the
> scorer it is the leading explanation for the v1 submission failure:
> `120 x 5 min = 10 h` agent loop plus container and verification overhead
> lands at or past 12 h, and an overrun errors the entire submission rather
> than scoring what finished.

> **UNVERIFIED.** The 2026-10-22 claim that generation is ~91% of wall clock
> could not be reproduced from the 1024 traces: nearly every step carries
> `tool_calls`, so the interval that follows it contains tool execution *and*
> the next generation, and the two cannot be separated from the ATIF timing
> fields. Treat 91% as unconfirmed, not refuted.

---

### Finding 4 — the harness already truncates, so the context story changes

HARNESS_README 7.1:

| limit | value |
| --- | --- |
| Max command / diff / graph output | 5,000 chars |
| Max lines per `read_file` | 150 lines |
| Max chars per `read_file` | 10,000 chars |

So unbounded grep is **not** the context driver — it is capped at 5,000 chars
regardless. The driver is `read_file`: 158 calls / 24 tasks at up to 10,000
chars each is ~16k tokens per task on its own. That is the 28,673.

It also explains the file paging that the 2026-10-22 entry corrected
`scripts/trace.py` for. The agent reads a file, receives a 150-line prefix,
and reads again at an offset — forced by the cap, not confusion.

Both context overflows sit on the same arithmetic: `28,673 input + 4,096
output = 32,769` against a 32,768 window. Measured completion is mean 301
tokens/step, worst task 9,730 over 13 steps, so 4,096 is ~4x over-provisioned
and could be cut — but **not during the sweep**, since it sets the input
ceiling and would confound the arms.

---

### Finding 5 — `eval_config.yaml` is official, and the notebook cannot run in batch

`eval_config.yaml` is an **optional file at the submission root**, documented
in HARNESS_README 7.1 and shipped by `sample_submission`, loaded via
`load_submission_eval_config()` in `scripts/inference.py`. Precedence is
`env var > eval_config.yaml > default`. Omitting it yields **60 min / 100
calls / 500 turns** per task, which at 120 tasks cannot fit the 12 h wall.
No `HarnessLimits` ceiling rejects an out-of-range request.

`scripts/pack.py` now ships it via a `HARNESS_FILES` allowlist while still
failing any genuinely unreferenced YAML. Also added: exact `model:` value
match against the four allowed names (substring matching accepted a typo'd
`...-ct-v2`), rejection of a zip naming two models, and
`dataset-metadata.json` treated as junk — it has an allowed `.json` extension
and would otherwise ship silently.

**Notebook cell order was fatal for background runs.** The serve cell sat
*below* both eval cells, so `Save & Run All` executed the evals against a
server that did not exist. This is the real cause of the batch run where all
24 tasks returned connection errors with zero LLM calls — the missing hard
gates were real but secondary. Serve now precedes the eval cells, the eval
cell raises on non-zero exit, logs are per-run instead of overwriting
`eval.log`, and `assert not OUT.exists()` prevents a forgotten `RUN` bump from
destroying an arm that cost GPU quota.

Dataset gotcha: `kaggle datasets version -p submission` defaults to
`--dir-mode skip` and silently drops `configs/` and `prompts/`. Use `-r zip`,
and remember Kaggle pins notebook inputs to a version — a new dataset version
does not reach the notebook until the input is bumped.

---

### v3 plan

Three prompt changes, bundled. All three attack a failure mode visible in the
1024 trace data; none touches sampling or budget, so the prompt is the only
live variable. `--max-time-minutes 5 --max-tool-calls 40` stay on the CLI,
where they override `eval_config.yaml`, which keeps v3 comparable to the 1024
arm regardless of what the shipped budget becomes.

1. **Narrow before you read.** State the 5,000-char / 150-line / 10,000-char
   truncation limits explicitly — the agent does not know they exist, and a
   silently truncated result causes the re-reads. `grep -rln` to find the
   file, `grep -n` inside it, then `read_file` on a tight range.
   *Targets:* 2 context overflows, and `read_file` as the dominant consumer.
2. **Give the agent the clock.** `get_status` was called once in 503 calls.
   State the budget numerically, require a check after localisation, and
   mandate an edit once half the budget is gone: a wrong patch scores the same
   as no patch, so an unverified fix beats an unfinished investigation.
   *Targets:* 4 timeouts + 6 tasks that edited but never converged.
3. **Invert the repro-first habit.** 25 `write_file` and 52 `python3` calls
   went on `/tmp` scratch scripts, and all four empty patches came from tasks
   that edited only `/tmp`. Source edit first, verify afterwards if budget
   remains.
   *Targets:* 4 empty patches = 22% of winnable tasks producing nothing.

**Not in v3:** a verify loop. Only 14 of 239 commands ran pytest and 12
winnable tasks shipped a wrong patch, so this is the obvious next lever — but
a reproduce-fix-reverify cycle costs 3-4 steps at 5s+ each and there is no
headroom until 1-3 land. Sequence it after.

**Note on `submit_patch`:** six tasks made source edits and never called it,
including `fastapi_15589`, which resolved anyway. The harness falls back to the
working-tree diff, so the FIRST RULE is largely ceremony and the four empty
patches were not caused by missing `submit_patch` calls. Do not spend prompt
budget reinforcing it.

### Submission

`eval_config.yaml` for the next submission:

```yaml
evaluation:
  max_time_minutes: 4      # 120 x 4 = 8 h agent loop, leaving room for the
                           # container + verification overhead that 7.1 says
                           # is excluded from this budget but not from the wall
  max_tool_calls: 50       # fastapi_14306 used 37 against a cap of 40
  max_turns: 80            # max observed 40; never binds
  timeout_seconds: 300     # Phase 1 only; nothing exceeds 60s. Do not lower.
```

Record the `pack.py` sha256 against every submission. v1 is unreconstructable
for exactly this reason, which is why its failure took a week to narrow.

### Run: devset_v3_31b_think_1024
**Config:** v3 prompt (the three changes below), 31b, `thinking_budget: 1024`,
`max_output_tokens: 4096`, 24 frozen dev tasks, `--sandbox subprocess`, no
adapters.

**`eval_config.yaml` did not apply to this run.** It carried
`max_time_minutes: 4 / max_tool_calls: 50`, but the CLI flags
`--max-time-minutes 5 --max-tool-calls 40` override it — confirmed two ways:
the timeout error reads `Agent exceeded session timeout (5.0 min)`, and
`fastapi_14306` stopped at exactly 40 tool calls. So the prompt's stated
"5 minutes and 40 tool calls" was correct **for this run** and the arm is
comparable to v2. It will be wrong by a minute and ten calls in the scored
run, which v4 fixes.

**Result: 5/24 = 0.208 as scored — 5/17 = 0.294 on winnable tasks**

| | v2_think_1024 | **v3_think_1024** |
| --- | --- | --- |
| resolved (of 17 winnable) | 6 = 0.353 | **5 = 0.294** |
| fastapi | 1/13 | **0/13** |
| rich | 5/11 | 5/11 |
| session timeout | 4 | **3** |
| context overflow | 2 | 2 |
| empty patch | 4 | **5** |
| tasks with zero `edit_file` | 4 | **5** |
| mean duration | 235 s | **214 s** |
| total wall clock | 1.57 h | **1.43 h** |

| exit code | v2 | v3 |
| --- | --- | --- |
| 0 passed | 6 | 5 |
| 1 tests failed | 8 | 7 |
| 2 collection failed | 5 | 6 |
| -1 no patch | 4 | 5 |
| 124 verification timeout | 1 | 1 |

| tool | v2 | v3 |
| --- | --- | --- |
| run_command | 239 | 207 |
| read_file | 158 | 140 |
| **edit_file** | 61 | **93** |
| write_file | 25 | **16** |
| submit_patch | 19 | **24** |
| get_status | 1 | **2** |

`run_command` verbs: grep 102 -> **117**, python3 52 -> **27**,
cat 25 -> **7**, pytest 10 -> 10, echo 16 -> 20, printf 13 -> 10.
Output-bounded commands (`| head` / `| wc`): 1/239 -> **4/207**.
Greps using `-rl` / `-rln`: **22/117**.

---

### Finding 6 — v3 improved the median task and worsened the tail

**What landed.** Change 3 worked broadly. Tasks that ran a scratch script or
pytest three or more times: **15 -> 7**. `write_file` 25 -> 16, `python3`
52 -> 27, `cat` 25 -> 7. The agent acts more: `edit_file` 61 -> 93,
`submit_patch` 19 -> 24. The run is 9% faster with 14% fewer tool calls.

Change 1 partially landed — 22 of 117 greps use `-rl`, but only 4 of 207
commands bound their output and total greps went *up*.

Change 2 did not land at all: `get_status` 1 -> 2.

**What broke.** Five of seventeen winnable tasks (29%) returned an empty
patch, and all five made **zero `edit_file` calls**:
`fastapi_14459` · `fastapi_15589` · `rich_3180` · `rich_3782` · `rich_3942`

The lost resolve is `fastapi_15589` — **the same task that was the single flip
between v1 and v2**. It is a coin-flip task, so 5 vs 6 sits exactly on the
±1-task noise floor established in finding 2. Do not read it as a regression.
The *mechanism* on that task is real and diagnosable, which is the useful part:

`fastapi_15589` in v2 (resolved): eleven steps of investigation, `edit_file` at
steps 17/18/19, then verify.

`fastapi_15589` in v3 (empty patch, 28 tool calls, zero edits):

```
11 write_file    /tmp/repro.py
12 run_command   printf '...' > /tmp/repro.py
13 run_command   python3 /tmp/repro.py
14 run_command   printf '...' > /tmp/repro.py      <- rewrite
15 run_command   python3 /tmp/repro.py
...
26 run_command   printf '...' > /tmp/repro.py      <- sixth attempt
27 run_command   python3 /tmp/repro.py
```

Six iterations trying to make a reproduction reproduce. Cumulative prompt
tokens 208k -> 342k. `rich_3782` is the same shape — 14 calls, zero edits,
four `pytest` invocations, then context overflow; in v2 it produced a 511-byte
patch and scored exit 1.

**Root cause is a design error in change 2, not a model failure.** The escape
hatch was written as:

> If `get_status` shows half your time gone and you have not yet edited a
> source file, stop investigating and make your best edit now.

It is conditional on `get_status`, which the agent called **twice across 24
tasks**. A guard gated on a tool call the model does not make is not a guard.

Secondary effect: patches are growing. `fastapi_14306` went 3,899 -> 6,688
bytes and hit the 40-call cap. The phrasing "a wrong patch scores the same as
no patch, so an unverified fix always beats an unfinished investigation"
encourages shotgunning, while change 3 moved verification *after* editing.
Together they raise edit volume and lower verification per edit.

---

> **CORRECTION to finding 1 (same day).** The unwinnable set is **7 tasks, not
> 6**. `fastapi_14246` surfaced `ModuleNotFoundError: No module named
> 'inline_snapshot'` in the v3 run; in v2 it died on context overflow before
> any test ran, so `envcheck.py` had nothing to classify. Which tasks *reveal*
> the breakage depends on how far the agent gets, but the sandbox is constant —
> so the exclusion list must be the **union across runs**, not per-run output.
>
> Permanent exclusions (7): `fastapi_13920` · `fastapi_14077` ·
> `fastapi_14246` · `fastapi_14356` · `fastapi_14479` · `fastapi_5077` ·
> `fastapi_9753`
>
> Stable denominator is **17**, not 18. Restated:
>
> | | as scored | winnable (17) |
> | --- | --- | --- |
> | v2_think_1024 | 6/24 = 0.250 | **6/17 = 0.353** |
> | v3_think_1024 | 5/24 = 0.208 | **5/17 = 0.294** |
>
> The winnable fastapi arm is **6 tasks**, two of which produce empty patches
> on timeout. Four effectively-live fastapi tasks against eleven rich is not a
> measurement instrument for a hidden set that is ~52% fastapi. Treat the
> starlette wheel fix as blocking, not optional.

---

### v4 plan — make the deadline unconditional

One change, replacing the budget section. The deadline becomes a tool-call
count the model can track from the conversation itself rather than a clock it
has to request, the empty-patch asymmetry is stated outright, and the repro
loop gets a hard cap:

```markdown
## Your budget

You have 4 minutes and 50 tool calls for this task.

By your 15th tool call you must have called edit_file or write_file on a
source file. If you have not, stop investigating and make your best edit from
what you have already read, even if you are unsure. Then continue.

An empty patch scores zero. A wrong patch also scores zero and costs you
nothing. Finishing without editing a source file is the one outcome that is
always worse than guessing.

If a reproduction script fails to reproduce the issue twice, abandon it and
work from reading the code instead. Do not rewrite it a third time.
```

The repro cap alone addresses both lost tasks.

**v4 also aligns the local flags to the shipped budget:**
`--max-time-minutes 4 --max-tool-calls 50`, matching `eval_config.yaml` and
the prompt text. This costs comparability with the v2 and v3 arms, accepted
because v4 changes the prompt anyway, and because shipping a prompt that
misstates the model's budget is worse than losing one comparison.

Changes 1 and 3 from v3 carry forward unaltered. Change 2's conditional
phrasing is retired.

### In flight
- **12b arm** (teammate, running now): v3 prompt byte-identical, 31b -> 12b,
  everything else held including tp4 / 0.90 / 32768 / max-num-seqs 16.
  Read it on **tool calls per task and timeout count**, not resolve count —
  the hypothesis is more steps inside the same wall clock, and resolve count
  cannot resolve ±1 task. If step counts come back similar, tp4 all-reduce over
  PCIe is eating the throughput gain and the follow-up is tp2 or tp1.

### Next (revised)
- [ ] **Second seed on v3/31b/1024.** Three arms now read 6, 6, 5 against a
      ±1-task noise floor. Until a replicate exists, no arm is distinguishable
      from any other and v4 adds a fourth undistinguishable number.
- [ ] v4 prompt, run at 4 min / 50 calls
- [ ] `starlette==0.52.1` + `dirty_equals` + `inline_snapshot` wheel dataset —
      now blocking, since the winnable fastapi arm is down to 6 tasks
- [ ] v1 submission execution time from the Kaggle Submissions tab
- [ ] Confirm the hidden-set task count and the 12 h wall
- [ ] Sweep arm 0 — run on v3/v4 rather than v2; a two-point replication across
      two prompts is a stronger paper result than a longer single-prompt curve
- [ ] Team roles — nine days unresolved


---

### Run: devset_v3_12b_think_1024
**Config:** v3 prompt byte-identical to `devset_v3_31b_think_1024`, model
swapped 31b -> 12b. `thinking_budget: 1024`, `max_output_tokens: 4096`,
tp4 / 0.90 / 32768 / `max-num-seqs 16` all held. 24 frozen dev tasks,
`--max-time-minutes 5 --max-tool-calls 40`, `--sandbox subprocess`.

**Result: 1/24 = 0.042 as scored — 1/17 = 0.059 on winnable tasks**

| | v3 31b | **v3 12b** |
| --- | --- | --- |
| resolved (of 17 winnable) | 5 = 0.294 | **1 = 0.059** |
| fastapi | 0/13 | 0/13 |
| rich | 5/11 | **1/11** |
| tool calls, total | 436 | **658** |
| tool calls per task, mean | 18.2 | **27.4** |
| hit the 40-call cap | 1 | **2** |
| **context overflow** | 2 | **12** |
| session timeout | 3 | 6 |
| empty patch | 5 | **11** |
| prompt tokens per task, mean | 225,385 | **398,823** |
| mean duration | 214 s | 242 s |
| total wall clock | 1.43 h | 1.61 h |

| tool | 31b | 12b |
| --- | --- | --- |
| run_command | 207 | **310** |
| read_file | 140 | **233** |
| edit_file | 93 | **82** |
| write_file | 16 | 34 |
| submit_patch | 24 | **5** |
| get_status | 2 | 0 |

`run_command` verbs: grep 117 -> **219**, python3 27 -> **76**,
pytest 10 -> **2**.

### Finding 7 — cheaper steps move the bottleneck from time to context

**The throughput hypothesis was correct and the conclusion is still no.** The
12b delivers 50% more tool calls per task inside the same wall clock, exactly
as predicted from its ~6-8 GB weight footprint against the 31b's ~16-18 GB. It
spends all of them filling the context window.

**Twelve of twenty-four tasks died on `ContextWindowExceededError`**, against
two for the 31b, and cumulative prompt tokens per task rose 77%. Eleven tasks
produced no patch at all. This is the harder of the two walls: a session
timeout still yields the working-tree diff and gets verified, whereas an
overflow kills the task mid-trajectory and yields nothing.

The tool mix shows the 12b does not convert extra steps into progress. Every
exploratory tool roughly doubles while **editing goes down 12%** and
`submit_patch` falls from 24 calls to 5. `fastapi_9753` produced a 7,980-byte
patch where the 31b produced 694. It is not using the headroom, it is
thrashing in it.

It is also the first arm in which **tool calls bind at all**: two tasks hit
`Agent exceeded tool call budget (40 calls)`, an error never seen in any 31b
arm. Finding 3 ("time is the binding constraint, not tool calls") is therefore
model-specific, not a property of the task set.

**The model question is closed: stay on the 31b.** Cost: one dev run plus one
failed run (below).

**Context is now the top lever**, since three of the four failure modes across
both arms are context-driven -- overflows directly, empty patches as their
consequence, oversized patches as a symptom. Two things follow:
- `max_output_tokens: 4096 -> 2048` buys 2,048 tokens of input ceiling.
  Measured completion is ~301 tokens/step, so it is free. Held back during the
  sweep to avoid confounding arms; the sweep is over.
- **The scorer runs ADK events compaction and we do not.** `scripts/inference.py`
  sets `compaction_interval=15`, `overlap_size=2`, `token_threshold=14,336`,
  `event_retention_size=5` on the `App`; the `swegemma eval` CLI does not. So
  every overflow measured locally is partly an artifact the scorer would not
  see, and the local dev set is systematically harsher on context than the
  thing we are scored by. Do not revisit the 12b on that basis -- 1 vs 5
  resolved is far outside noise -- but discount local overflow counts.

### The failed 12b run before this one

First attempt died after 14.5 min with `RuntimeError: Engine core
initialization failed` and, 120 s earlier, the real cause:

```
WARNING  TransformersMultiModalForCausalLM has no vLLM implementation
```

HARNESS_README 3.1, `MODEL_VLLM_EXTRA_ARGS`: the 12b requires
`--hf-overrides '{"architectures": ["Gemma4ForCausalLM"], "model_type": "gemma4"}'`.
Without it vLLM does not recognise the checkpoint's declared architecture and
falls back to the Transformers backend. The flag is a no-op for 31b / e4b /
e2b, so the serve cell should carry a per-model extras map rather than being
switched by `NAME` alone.

Two notebook guards added as a result: bail out of the readiness loop on
`Engine core initialization failed` or `no vLLM implementation` instead of
polling for the full 600 s, and move the VALIDATE cell *below* the CONFIG cell
-- it currently runs before `agent.yaml` is rewritten, so it validated the 31b
on a 12b run and reported `models: {'gemma-4-31b-it-qat-w4a16-ct'}`.

An earlier attempt failed in 9 s on `MISSING INPUT: gemma4-extra-wheels`.
Private datasets owned by one account are silently dropped when a teammate
copies the notebook. Both `gemma4-extra-wheels` and `gemma4-submission` must be
shared with every team member; the wheels dataset contains no competition data
and would be better public.

---

> **CORRECTION to 2026-10-26.** `scripts/pack.py` was stripping
> `eval_config.yaml` from the zip via `NOT_SHIPPED`, so every submission packed
> from the repo shipped **three files and no budget config**. HARNESS_README
> 2.2 / 7.1 documents the file as part of the submission contract, loaded by
> `load_submission_eval_config()` in `scripts/inference.py`, and omitting it
> falls back to **60 min / 100 tool calls per task** -- 15x the configured
> budget. This is what the submission that ran for 21 hours is doing. Fixed in
> 2f5db58 via a `HARNESS_FILES` allowlist. The whole "unreferenced YAML is the
> v1 failure mode" theory in finding 5 was wrong; `eval_config.yaml` is an
> official optional file and was never a plausible cause of the v1 failure,
> which remains unexplained.

> **The 12 h wall is real and applies to the submission.** The figure is the
> Kaggle notebook batch timeout, visible directly in any batch run's log as
> `pm.execute_notebook(..., timeout=43200)`. The scorer runs Stage 1 inference
> as a notebook (`scripts/inference.py`, producing `submission.parquet`), so
> the same ceiling applies to a scored run. The 21 hours shown against the
> submission is queue time plus roughly 12 h of execution, and the submission
> ended in a notebook timeout -- which is what that ceiling looks like.
>
> An earlier draft of this correction claimed the 12 h figure constrained only
> our dev-set runs and said nothing about the submission. That was wrong. The
> original assumption carried from the forum was right; it is the per-task
> budget, not the wall, that was mis-sized.

### The v2 think-1024 submission timed out — reasons, most to least likely

Submitted zip (`submission_2.zip`), 3 files: `agent.yaml` (10-21),
`configs/sampling.yaml` (10-26, `thinking_budget: 1024`), `prompts/system.md`
(**10-22, the v2 prompt with FIRST RULE** -- v3 has never been submitted).
No `eval_config.yaml`, per the `pack.py` bug above.

**1. No `eval_config.yaml`, so 60 minutes per task.** Not one cause among
several; the arithmetic alone exceeds the wall. In the local v2/1024 run
**6 of 24 tasks (25%) ran to the 300 s cap** -- they were being cut off, not
finishing. Without `eval_config.yaml` the next limit is the 60 min default:

```
capped-out tasks   12 x 60 min             = 12.5 h
everything else    38 x 198 s (optimistic) =  2.1 h
                                             ------
Stage 1 alone                                 14.6 h
```

Twelve tasks consume the whole budget by themselves, before container
creation, wheel staging and snapshot extraction -- none of which count against
the per-task budget and all of which count against the notebook. The tool-call
default compounds it (100 vs our 50; local mean 19.8, max 37 against a 40 cap,
so the cap was close to binding), and `max_turns` defaults to 500 vs our 80
while `max_nudges` only terminates after *three consecutive* nudges with no
tool call.

**2. FIRST RULE was accidentally limiting the damage.** Per 5.3, submitting
early ends the loop, so the v2 prompt shortened tasks. The merged prompt
correctly removes it, which means tasks will now run *longer* per task.
Shipping the new prompt without `eval_config.yaml` would be worse than what
just timed out. The two changes must ship together.

**3. Unbounded grep in the v2 prompt** (`grep -rn ... .` with no `head`) at up
to 5,000 chars per call, with 100 calls available instead of 40.
`ContextWindowExceededError` is non-retryable so it ends the task rather than
burning backoff, which if anything saves wall clock. Second-order.

**4. Container and Phase 2 overhead.** Two containers per task plus a fixed
300 s verification ceiling. Locally ~5 s because subprocess mode skips
containers, which is why no measurement of ours sees it; plausibly 1-2 min per
task on the scorer, so 1-2 h across 50 tasks. Not a cause on its own, but
enough that a budget sized to exactly 12 h fails.

**Unresolved: the scored task count.** All of the above assumes ~50 tasks,
inferred from 0.03 being 1-2 resolved. That is weak evidence. At 120 tasks,
`max_time_minutes: 4` gives 8 h plus overhead and is near the wall again;
3 minutes would cost some of the tail and buy margin. The runtime on the
Submissions tab after the next correctly-budgeted submission is the number
that settles it.

> **CORRECTION to the v3 entry.** "22 of 117 greps use `-rl`" was a bug in my
> own analysis regex. The real count is **0 of 117 in the 31b arm and 0 of 219
> in the 12b arm**. v3 change 1 (narrow before you read) had no measured
> effect in either arm, and the grep-volume difference between models is
> entirely model behaviour. The truncation-limit text was also redundant with
> section 4 of `build_agent_prompt`, and both were removed in 2f5db58.

### Next
- [ ] Rebuild and resubmit with the 4-file zip once the 21 h run resolves;
      record the sha256 against the submission
- [ ] Notebook: `--hf-overrides` extras map, VALIDATE below CONFIG, fail-fast
      on engine-init failure, rename the smoke cell's `RUN` to `SMOKE_RUN`
- [ ] Second seed on v3/31b/1024 -- three arms now read 6, 6, 5 against a
      ±1-task noise floor, so no two are distinguishable
- [ ] `max_output_tokens: 2048`, now that the sweep is finished
- [ ] `starlette==0.52.1` + `dirty_equals` + `inline_snapshot` wheel dataset;
      the winnable fastapi arm is 6 tasks and we are tuning on rich
- [ ] Confirm the scorer's run-time ceiling and the hidden-set task count
- [ ] Share both private datasets with the team, or merge teams on Kaggle
      (deadline Nov 25)
- [ ] Sweep arm 0 on v3/v4 rather than v2
- [ ] Team roles -- ten days unresolved

## 2026-10-29 — first scored submission, and half the task set was never usable

### Kaggle submission
| Sub | Config | Score |
| --- | --- | --- |
| baseline | unmodified `sample_submission` | 0.03 |
| v1 | prompt v1 + 5 min/40 calls | FAILED (Notebook Threw Exception) |
| v2 think 1024 | 3-file zip, no `eval_config.yaml` | FAILED (notebook timeout, ~12 h) |
| **v3 merged** | 4-file zip, `eval_config` 4 min/50, submit-last prompt | **0.10** |

First submission to score end to end. Reference points: starter notebook 0.12,
leaderboard plateau 0.22.

**The scored split is ~100 tasks, not ~50.** Resolution rate is resolved/total,
so the denominator has to make both scores land: 50 fails (1/50 = 0.02,
2/50 = 0.04, neither rounds to 0.03) while 100 works exactly -- 3/100 = 0.03
and 10/100 = 0.10. So 10 tasks resolved. Multiples of 100 also fit but 100 is
the natural public-split size.

That halves the per-task budget headroom. At ~100 tasks, `max_time_minutes: 4`
projects to 6.3 h of agent loop plus 1.7-3.3 h of container and verification
overhead -- 8-9.5 h of a 12 h wall. **5 min is tight and 6 would likely time
out.** Leave the budget at 4. (An earlier estimate in this changelog assumed
~50 tasks and suggested 12 min/task was affordable; that was wrong.)

---

### Run: skipagent_before / skipagent_after (CPU only, no GPU quota)
**Config:** `swegemma eval --skip-agent-patch` over all **129** tasks,
`--sandbox subprocess`. Phase 1 is bypassed, so no agent runs and no LLM is
called: Phase 2 applies `task.test_patch` to the unmodified repo and runs the
target tests. Every task is expected to fail -- what matters is *how*. Tests
that ran and failed mean the environment is sound; a collection or import
error means the repo could not be loaded at all.

**Wheels installed between the two runs** (`gemma4-task-deps` dataset, built in
a CPU notebook with internet so the wheels match the image exactly):
`starlette==0.52.1` (down from **1.6.0**), `dirty_equals==0.11`,
`inline_snapshot==0.36.1`, `pytest-httpbin==2.1.0`, plus their trees.
Installed with `pip install --no-index --find-links`, which resolves offline
and leaves already-satisfied packages alone -- `--force-reinstall` across the
whole set would have replaced `pytest`, `anyio`, `typing_extensions` and
`pluggy` underneath the harness.

**Result: 69/129 -> 116/129 usable by the classifier. 47 repaired, 0 regressed.**

| | before | after |
| --- | --- | --- |
| usable (classifier) | 69 = 53.5% | **116 = 89.9%** |
| version-skew | many | 2 |
| missing-dep | many | 3 |
| import-error | — | 6 |
| collection-error | — | 2 |
| broken by repo | — | fastapi 11, httpx 1, rich 1 |

Zero regressions matters: pinning starlette back below the 1.0 line could have
broken the newest fastapi commits, and `--compare` is what would have shown it.

### Finding 8 — the subprocess sandbox was writing off 41% of the task set

Before the wheels, **53 of 129 tasks could not run at all.** We knew about
seven, from the dev set. The real figure was nearly eight times that, and every
local measurement in this changelog above 2026-10-29 was taken on a task set
where roughly half the tasks could not pass whatever the agent did.

> This paragraph gave the unusable count as 60, and the multiple as nearly
> nine, until 2026-11-09. That came from the classifier's first pass
> (69/129 usable); the corrected counts below are 76/129 usable before the
> wheels and 123/129 after, making the unusable figure 53 -- which is the
> 41% already in this finding's heading. The paper quotes 53.

Two causes, both downstream of `ensurepip unavailable in sandbox, creating venv
without pip`:
- **starlette 1.6.0.** 1.0.0rc1 (2026-02-23) removed `on_startup` /
  `on_shutdown` from `Starlette` and `Router`; every fastapi commit in the set
  predates that and still passes `on_startup` through `APIRouter.__init__`.
- **Missing test-only dependencies**, overwhelmingly `inline_snapshot` and
  `dirty_equals`, which fastapi's test suite imports at module scope.

This is a property of the published harness under `--sandbox subprocess`, not
of our setup, and any entrant without a Docker daemon will have hit it. Worth a
paragraph in the paper and a forum post.

### Finding 9 — two "unwinnable" signals, both with false positives

**`baseline_check.py` cannot distinguish an environment defect from a feature
that does not exist yet.** A FAIL_TO_PASS test imports the API the task asks
you to build, so on an unmodified repo it fails at collection with exactly the
signature of version skew. Seven of the 13 remaining failures are this:

`fastapi_14186` · `fastapi_14306` · `fastapi_14605` · `fastapi_14609` ·
`fastapi_14953` · `fastapi_14978` · `httpx_3672`

`fastapi_14978` is the proof: we already established it is winnable, because
the agent implemented `strict_content_type` on `Body()` and missed
`APIRouter`. `ImportError: cannot import name 'EventSourceResponse'` is the
SSE feature not existing yet.

**Corrected usable count: 123/129 = 95.3% after the wheels, 76/129 = 58.9%
before.**

> **CORRECTION to 2026-10-29 (same day).** The orphan-symbol metric in
> `triage.py` is also weak and was over-trusted in this changelog. It counts
> symbols the tests import that the problem statement never names -- but for
> the tasks it flags hardest those are *ordinary, long-existing* fastapi APIs:
>
> ```
> fastapi_15745  13  BaseRoute;Body;Depends;HTMLResponse;Host;JSONResponse;Match
> fastapi_14459   5  APIRouter;Depends;FastAPI;OAuth2AuthorizationCodeBearer;Security
> ```
>
> It is measuring "the issue text is terse", not "the task is unsolvable".
> `fastapi_15785` carries 7 orphans against 2 files and 66 lines, which is a
> perfectly normal task. **Patch size is the better signal**, and the honest
> permanent exclusion list is 4-5 tasks, not the 13 the baseline check
> reported or the 18 the >=3-orphan threshold suggested:
>
> ```
> rich_3930      26 files, 12,170 lines   hopeless
> fastapi_15745   4 files,    939 lines   very likely hopeless
> fastapi_15030   9 files,    525 lines   large
> fastapi_14262  10 files,    196 lines   large
> fastapi_15661   1 file,     216 lines   needs the repo's scripts/ importable
> ```
>
> The "ceiling 86%" figure derived from the orphan threshold should be read as
> weak evidence, not a bound. Do not exclude on orphan count alone when
> rebuilding the dev set.

### What this changes about the dev set

**All seven tasks the dev set had marked env-broken are repaired** -- 13920,
14077, 14246, 14356, 14479, 5077, 9753 all appear in the repaired list. The
24-task dev set is effectively fully live, and `fastapi_14459` is the only
questionable member, on the metric just discredited above.

So the mixture distortion largely fixes itself. 13 fastapi against 11 rich is
54/46 against a real 52/37 -- close enough to trust, where what we were
actually measuring last week was 31/69.

The `ENV_BROKEN` set in `scripts/devset_audit.py` is now obsolete and must be
replaced with the verified list before that tool is trusted again.

### Next
- [ ] **Re-run the existing 24 tasks, v3 prompt, wheels installed.** One GPU
      run, one variable, directly comparable to v3's 5/16: fastapi goes from 5
      live tasks to 13, and fastapi performance has been unmeasurable all week
      while being 52% of the benchmark.
- [ ] Replace `ENV_BROKEN` in `scripts/devset_audit.py` with the verified list
- [ ] Commit the two skipagent `task_results.jsonl` files so the hour of CPU
      is not lost to a session wipe
- [ ] Second seed, still blocking interpretation of every arm
- [ ] `max_output_tokens: 2048` as its own arm, now the sweep is done
- [ ] Expand the dev set to ~30 with requests coverage (10% of the real set,
      now testable thanks to pytest-httpbin) -- lower priority than it was
- [ ] Notebook: `--hf-overrides` extras map, VALIDATE below CONFIG, fail-fast
      on engine-init failure, `SMOKE_RUN` rename, `GPU` flag in setup
- [ ] Add `scripts/` as a Kaggle dataset so notebooks stop needing pasted cells
- [ ] Team roles -- eleven days unresolved

## 2026-10-30 — first trustworthy denominator, and fastapi is a budget problem

### Run: devset_v3wheels_31b_think_1024
**Config:** v3 prompt (merged: submit-last, no FIRST RULE), 31b,
`thinking_budget: 1024`, `max_output_tokens: 4096`, 24 frozen dev tasks,
`--sandbox subprocess`. **`gemma4-task-deps` wheels installed**, so all 24
tasks are live for the first time. Budget `4 min / 50 calls`, derived in the
notebook from `submission/eval_config.yaml` rather than hardcoded, so the run
matches what the zip ships.

**Result: 6/24 = 0.250** — and unlike every number above this line, the
denominator is real.

| | v3 @5min (16 live) | **v3wheels @4min (24 live)** |
| --- | --- | --- |
| resolved | 5/16 = 0.313 | **6/24 = 0.250** |
| fastapi | 0/5 live | **1/13** |
| rich | 5/11 | 5/11 |
| session timeout | 3 | **10** |
| context overflow | 2 | 1 |
| empty patch | 5 | 6 |
| **exit 2 (collection failed)** | 6 | **2** |
| mean duration | 214 s | 221 s (of a 240 s cap) |
| total wall clock | 1.43 h | 1.48 h |

| exit code | count |
| --- | --- |
| 0 passed | 6 |
| 1 tests ran and failed | 9 |
| 2 collection failed | 2 |
| -1 no patch | 6 |
| 124 verification timeout | 1 |

**The wheels worked.** Collection failures fell 6 -> 2 and all eight tasks the
sandbox had been writing off now run:

| task | exit | resolved |
| --- | --- | --- |
| fastapi_14077 | 0 | **yes** |
| fastapi_13920 | 1 | no (timeout) |
| fastapi_14356 | 1 | no |
| fastapi_14479 | 1 | no |
| fastapi_9753 | 1 | no (timeout) |
| fastapi_14246 | -1 | no (timeout, no patch) |
| fastapi_14459 | -1 | no (timeout, no patch) |
| fastapi_5077 | -1 | no (timeout, no patch) |

Net score effect of the environment fix: **+1 task.** The seven others run
properly now and still fail, which is the point -- they were never going to
tell us anything while they could not run at all.

### Finding 10 — `max_time_minutes: 4` is validated, not a compromise

On the 16 tasks that were live in **both** runs, so prompt and task set are
held constant and only the budget moves:

```
v3  @ 5 min:   5 resolved,  2 timeouts
v3w @ 4 min:   5 resolved,  5 timeouts
```

Identical resolves. Three more tasks were cut off and none of them were going
to succeed. So the minute surrendered to fit the ~100-task scored split costs
nothing measurable, and the 2026-10-29 decision to leave the budget alone
holds. Revisit only if the scored task count turns out to be well under 100.

### Finding 11 — fastapi fails on budget, not on diagnosis

This is the answer to the question that has been open since 2026-10-22, and it
is not the one the environment story implied.

| | fastapi | rich |
| --- | --- | --- |
| tasks | 13 | 11 |
| resolved | **1** | **5** |
| session timeouts | **8/13 = 62%** | **2/11 = 18%** |
| mean tool calls | 21.8 | 18.3 |
| mean patch size | **1,384 B** | 930 B |
| empty patches | 4 | 2 |
| mean duration | 217 s | 226 s |

fastapi tasks time out **three and a half times as often**. Mean duration is
the same only because both repos press against the cap. What differs is that
fastapi burns more tool calls getting nowhere and produces patches 50% larger;
`fastapi_14306` emitted 4,950 B.

The one fastapi task that resolved, `fastapi_14077`, finished in **82 seconds
with 15 tool calls** -- the fastest task in the run. When fastapi works it
works quickly; when it does not, the agent grinds to the wall. That is a
triage failure, not a reasoning failure.

**So the verify loop queued on 2026-10-28 is now the wrong next move.** Adding
3-4 steps of reproduce-fix-reverify to a repo that already exhausts its budget
on 62% of tasks would make the worse half worse. Shelved, not cancelled.

### v4 plan — attack the grind

1. **Pull the edit deadline from call 15 to call 10.** fastapi averages 21.8
   calls and still returns nothing on four tasks, so "make your best edit now"
   is currently firing too late to leave room for refinement.
2. **Give `## Scope` teeth.** It says one file and under ten lines; nothing
   enforces it, and fastapi patches average 1,384 B. Add an explicit
   instruction to stop and re-diagnose once the diff passes roughly 40 lines.
3. **`max_output_tokens: 4096 -> 2048`**, now more attractive than it looked:
   `rich_3942` still overflowed, measured completion is ~301 tokens/step, and
   the 2,048 freed goes to input headroom. The sweep is finished so there is
   nothing left to confound.

Run 1 and 2 together as v4 (both aimed at the same failure mode), and 3 as its
own arm against this run.

### Next
- [ ] v4: deadline at 10 calls + scope ceiling, 24 tasks, 4 min / 50 calls
- [ ] `max_output_tokens: 2048` as a separate arm
- [ ] **Second seed on this run.** Four arms now read 6, 6, 5, 6 against a
      ±1-task noise floor. Still blocking, and now blocking on a dev set that
      is finally worth replicating.
- [ ] Commit the skipagent `task_results.jsonl` files before the session wipe
- [ ] Expand to ~30 tasks with requests coverage (10% of the real set, now
      testable via pytest-httpbin)
- [ ] Strip `task_prompt` from committed traces, or hold the repo private past
      2 December. README line 83 says it goes public; the traces carry
      competition problem statements verbatim.
- [ ] Team roles -- twelve days unresolved

## 2026-11-02 — seeds and thinking 0: reasoning on/off matters, the budget does not

### Runs: devset_v3wheels_s2 / s3 (seeds), devset_v3wheels_think_0
**Config:** identical to `devset_v3wheels_31b_think_1024` in every respect, 24
dev tasks, 4 min / 50 calls derived from `eval_config.yaml`, wheels installed.
No seed is set: `temperature: 0.2` plus vLLM's non-deterministic batching make a
plain re-run an independent sample, which is also the configuration we ship.
The think-0 arm sets `thinking_budget: 0` (which per HARNESS_README 2.4 sets
`enable_thinking: false`) and `include_thoughts: false`.

**Result: 6 / 6 / 6 at thinking 1024. Resolve-count range across seeds: zero.**

| | s1 | s2 | s3 | think 0 |
| --- | --- | --- | --- | --- |
| resolved | 6 | 6 | 6 | **4** |
| fastapi | 1/13 | 1/13 | 1/13 | 1/13 |
| rich | 5/11 | 5/11 | 5/11 | **3/11** |
| session timeout | 10 | 14 | 7 | **1** |
| context overflow | 1 | 1 | 3 | **7** |
| empty patch | 6 | 9 | 4 | 7 |
| mean duration | 221 s | 210 s | 254 s | **119 s** |
| mean tool calls | 20.2 | 22.3 | 22.8 | **28.2** |
| total wall clock | 1.48 h | 1.40 h | 1.69 h | **0.79 h** |

Task-level, the six are not the same six:

```
rich_2725  rich_3454  rich_3718  rich_3894  rich_4077     resolve in ALL three
fastapi_14077   s1 Y   s2 Y   s3 .
fastapi_15589   s1 .   s2 .   s3 Y
```

A five-task deterministic core plus two unstable fastapi tasks, of which
**exactly one resolved in each run**. If those two are near-independent coin
flips, seeing exactly one three times running has p ~ 0.125, so the defensible
statement is **range 0 observed, task-level instability implying a true spread
of about 5-7** -- not "variance is zero".

**The process is far noisier than the outcome.** Timeouts 10/14/7, empty
patches 6/9/4, wall clock 1.40-1.69 h. The agent behaves materially differently
run to run and lands on the same score. Process metrics therefore need seeds
even where the headline does not.

> **CORRECTION to 2026-10-26/29.** The "±1-2 task noise floor" asserted
> repeatedly above was pessimistic. Observed resolve-count range over three
> runs is 0. That makes the earlier prompt arms (5/6/6/5) somewhat more
> interpretable than those entries claim -- though they remain confounded by
> the broken sandbox, and two of the three tasks that distinguish them are the
> unstable fastapi pair.

### Finding 12 — reasoning on/off matters; the budget above ~1024 does not

Thinking 0 lands **two tasks below** the 6/6/6 band, with the failure profile
inverted: timeouts collapse 7-14 -> **1**, overflows rise 1-3 -> **7**, mean
duration nearly halves, and tool calls go **up** to 28.2.

Combined with 1024 ≈ 4096 (identical completion-token distributions, 2026-10-30):

```
thinking 0  <  thinking 1024  ≈  thinking 4096
```

It is not "more reasoning is better" and not "reasoning has no effect". The
budget is not binding above some small threshold -- the model emits ~300
completion tokens per call at 1024 and at 4096 -- but switching reasoning off
entirely costs two tasks.

**The mechanism replicates across two independent manipulations.** Shrinking
the model (12b, 2026-10-27) and disabling reasoning both make steps cheaper,
both produce more tool calls per task, both shift failure from wall-clock to
context exhaustion, and both reduce resolve rate:

| | 31b / think 1024 | 12b / think 1024 | 31b / think 0 |
| --- | --- | --- | --- |
| mean tool calls | 20-23 | 27.4 | 28.2 |
| timeouts | 7-14 | 6 | 1 |
| overflows | 1-3 | 12 | 7 |
| resolved (of 24) | 6 | 1 | 4 |

Two different ways of buying steps, the same trade, the same outcome. That is a
mechanism rather than a coincidence, and it is the strongest result we have.

---

## 2026-11-06 — the full 129-task benchmark, and the dev set had it backwards

### Run: full129_31b_think_1024 (sharded 3 ways)
**Config:** the shipped config unchanged -- 31b, `thinking_budget: 1024`,
`max_output_tokens: 4096`, merged v3 prompt, 4 min / 50 calls from
`eval_config.yaml`. All 129 published tasks, no `--task-ids`, partitioned with
`--shard-index k --num-shards 3` (`task_idx % 3`). Three operators, one shard
each: 2.61 / 2.64 / 2.66 h, **7.90 h total**, 43 tasks per shard, 129 unique
instance ids pooled with no gaps or overlap.

**Result: 37/129 = 0.287**

| repo | resolved | rate | what the 24-task dev set reported |
| --- | --- | --- | --- |
| fastapi/fastapi | 20/67 | **0.299** | 1/13 = 0.077 |
| Textualize/rich | 14/48 | **0.292** | 5/11 = 0.455 |
| psf/requests | 3/13 | **0.231** | never measured |
| encode/httpx | 0/1 | 0.000 | never measured |

| failure mode | count | share |
| --- | --- | --- |
| session timeout | 62 | 48% |
| at or over the 240 s cap | 76 | **59%** |
| empty patch | 44 | 34% |
| context overflow | 8 | 6% |
| exit 0 (resolved) | 37 | 29% |
| exit 1 (tests failed) | 41 | 32% |
| exit 2 (collection failed) | 7 | 5% |

mean duration 221 s of a 240 s cap; mean 23.7 tool calls, max 47 of 50.

### Finding 13 — the dev set inverted the per-repo structure

**fastapi 0.299 and rich 0.292 are the same rate.** Finding 11 -- fastapi
times out 3.5x more often and fails on budget rather than diagnosis -- does not
survive the full set. It was an artifact of thirteen unrepresentatively hard
fastapi tasks.

The runs are consistent; the sample was not. Measured *within this run*:

```
the 24 dev tasks       7/24  = 0.292      (dev-set runs gave 6/24 = 0.250)
  of which fastapi     2/13  = 0.154
the other 105 tasks   30/105 = 0.286
  of which fastapi    18/54  = 0.333
```

`make_devset.py` selected fastapi tasks that resolve at **half** the rate of
the other 54, and rich tasks that over-perform by about as much. The two
sampling errors cancelled, so the aggregate (0.250 vs 0.287) looked plausible
while the per-repo structure was backwards.

> **CORRECTION to 2026-10-30.** Finding 11 is withdrawn. "fastapi fails on
> budget, not diagnosis" was measured on 13 tasks and is contradicted by 67.
> The per-repo timeout spread that supported it (62% / 77% / 31% across seeds)
> was already unstable; the full set shows the resolve rates are equal.

This supersedes, and strengthens, the measurement thesis. It is not only that
the sandbox corrupts the denominator (finding 8) -- it is that **after fixing
that, a hand-built 24-task subset still got the per-repo structure exactly
wrong while producing a believable aggregate.**

### Finding 14 — a 2.9x generalisation gap to held-out tasks

```
published task set (129, training split)   0.287
held-out scored submission (~100 tasks)    0.100
```

> **CORRECTION to 2026-10-29.** The "dev set overstates by ~2.5x" claim is
> withdrawn; the diagnosis was wrong. It rested on one local point against one
> scored point and attributed the gap to dev-set easiness. The full published
> set gives 0.287, so easiness is not the cause. The gap is between the
> published training tasks and the held-out scored split -- a generalisation
> gap of roughly 2.9x, not a sampling artifact.

Caveat: n=1 on the scored side, and the two sets differ in sandbox (subprocess
vs Docker) as well as in task identity, so the 2.9x is an observation rather
than a decomposition.

### Finding 15 — the budget binds hard, and there is headroom after all

**59% of tasks hit the 240-second cap** and 48% terminate on session timeout.
Mean duration is 221 s against a 240 s ceiling. This is not a model that
finishes early.

7.90 h for 129 tasks means a ~100-task scored run costs about **6.1 h of agent
loop**, against a 12 h notebook ceiling (`pm.execute_notebook(timeout=43200)`).
With container and verification overhead that leaves real slack.

> **CORRECTION to 2026-10-29/30.** `max_time_minutes: 4` was recorded as
> "validated, not a compromise", on the basis that 5 min and 4 min both
> resolved 5 of the 16 then-live dev tasks. That test was run on a 24-task
> subset we now know mis-samples the benchmark, and at full scale the cap binds
> on 59% of tasks. Raising the per-task budget is back on the table and is the
> best-supported lever available.

### Next
- [ ] **Raise `max_time_minutes` and re-run the full set sharded.** 6 min x 129
      = 12.9 h sharded three ways is 4.3 h each; a ~100-task scored run would
      be ~9.2 h of agent loop against a 12 h ceiling. Tight but the single
      best-supported change we have.
- [ ] Commit all run results to `experiments/` -- v3_31b, v3wheels, s2, s3,
      think0, the three shards, and both skipagent directories
- [ ] Rebuild or retire the 24-task dev set. Finding 13 means it cannot be
      trusted for per-repo claims; sample proportionally from the verified
      123 usable tasks, or run full shards for anything that matters
- [ ] Paper: findings 8, 9, 12, 13, 14, 15 are supported. Finding 11 is
      withdrawn. 3,000 words, deadline 12 November 11:59 PM UTC
- [ ] Related work section -- still zero progress, still required
- [ ] Strip `task_prompt` from committed traces before the repo goes public
      (§2.4.b prohibits redistributing Competition Data)
- [ ] Merge the Kaggle team (§3.6.a: dataset sharing outside a merged team is
      a disqualification risk, and three people now share these datasets)

### Finding 16 — seven published tasks pass with no agent patch at all

Re-reading the `--skip-agent-patch` runs for a different purpose turned up
something the 2026-11-06 entry above does not account for. With **no patch
applied**, these tasks' target tests pass:

```
after the wheels (7):  fastapi_14077  fastapi_14851  requests_7309
                       requests_7315  requests_7328  requests_7427  requests_7433
before the wheels (4): fastapi_14873  requests_7309  requests_7315  requests_7427
```

Their FAIL_TO_PASS tests do not fail at `base_commit`, so the resolution
criterion in HARNESS_README 8.2 is already satisfied. **5.4% of the published
task set is free credit for any submission.**

Note it is not monotonic: `fastapi_14873` passes *before* the wheels and fails
after. Installing `inline_snapshot` and friends causes more tests to collect,
and some of the newly collected ones fail. So "free pass" is itself a property
of the environment, not of the task.

**Effect on the full-run headline:**

| | |
| --- | --- |
| reported | 37/129 = 0.2868 |
| of which pass for free | 4 |
| **attributable to the agent** | **33/122 = 0.2705** |
| free tasks the run did not capture | 3 |

The three it lost are `fastapi_14851`, `requests_7328`, `requests_7427` --
each with `agent_patch_size: 0` and `test_exit_code: -1`. The mechanism is in
8.2: **verification only runs when the patch is non-empty.** An empty patch is
not verified, so a task that would have passed untouched is recorded as
unresolved. The agent did not break them; it failed to submit anything and the
harness never checked.

That makes the prompt line "a wrong patch also scores zero and costs you
nothing" wrong in a measurable way. Any non-empty patch that does not break
the target tests banks these tasks, and at a 34% empty-patch rate the run gave
away three guaranteed wins. Worth a prompt change and worth stating in the
paper.

> **CORRECTION to 2026-11-06.** The 0.287 headline is not wrong, but it is not
> all agent work. Report 37/129 = 0.287 as the raw resolution rate and
> 33/122 = 0.271 as the agent-attributable rate, and say which is which. The
> 0.100 scored submission presumably contains free passes too, in unknown
> proportion, so finding 14's 2.9x gap is between two rates that are both
> slightly inflated.

---

### Committed run artefacts (2026-11-06)

`experiments/` now holds every run the changelog references:

```
full129_31b_think_1024_sh0of3 / sh1of3 / sh2of3    the full benchmark, 43 tasks each
skipagent_before / skipagent_after                 summary + task_results only
```

Shards carry `summary.json`, `task_results.jsonl`, `patches/` and `traces/`,
matching the existing convention; `logs/` and `test_outputs/` are dropped for
size. The skipagent directories keep only the two JSON artefacts -- their 258
Phase 2 logs regenerate in about an hour on CPU.

**`task_prompt` steps are stripped from all 129 committed shard traces**
(585 KB of problem statements) and replaced with a length marker. Competition
Rules §2.4.b prohibits redistributing Competition Data, the README states this
repo goes public, and §2.5 requires winners to open-source their submission.
Nothing analytical is lost: the statements are in the competition's own
`tasks.jsonl`, and the traces retain every metric, tool call and timing.

**The older committed traces under `devset_*` still contain problem statements
and must be stripped the same way before the repo is made public.**

## 2026-11-08 — 0.15 on the leaderboard, and eval_config is honoured

### Kaggle submissions
| # | Config | Score |
| --- | --- | --- |
| 1 | unmodified `sample_submission` (ships 1 min / 10 calls) | 0.03 |
| 2 | prompt v1 + 5 min / 40 calls | FAILED (Notebook Threw Exception) |
| 3 | v2 think 1024, 3-file zip, no `eval_config.yaml` | FAILED (notebook timeout) |
| 4 | v3 merged: submit-last prompt, 4 min / 50, timeout 300 | 0.10 |
| 5 | **prompt v4**, 4 min / 50, timeout 300 | **0.12** |
| 6 | **prompt v4, 5 min / 50, timeout 60** | **0.15** |

Starter notebook is 0.12; the leaderboard plateau is 0.22.

**Submission 5 isolates the prompt cleanly: +2 tasks on ~100** for the six v4
changes (edit by call 8, never finish empty, no repro before editing, create
what the issue names, import check, 30-line ceiling). Submission 6 bundles two
budget changes so its +3 is not attributable between them -- but both push the
same lever, usable seconds per task, so the direction is unambiguous.

### Finding 17 — `eval_config.yaml` IS read by the scorer

Open since 2026-10-27. Raising `max_time_minutes` from 4 to 5 moved the score,
so `scripts/inference.py` is not overriding the file with
`SWE_MAX_TIME_MINUTES`. Every budget decision from here is real, and the
precedence chain `env var > eval_config > default` resolves in our favour.

**It also bounds the overhead we could never measure.** Submission 6 completed,
so ~6.9h of agent loop (100 tasks x 5 min, upper bound from the 7.90h/129
full-set run) plus container creation plus Phase 2 verification fits inside the
12h notebook ceiling. That puts the scorer's per-task overhead under roughly
3 minutes -- the figure every budget projection in this changelog has been
guessing at.

**`timeout_seconds: 300` was inert all along.** `run_command`'s timeout is
`min(command_timeout_seconds, max(5, remaining_time_seconds))`, and remaining
time never exceeds the session cap, so at any `max_time_minutes <= 5` a 300s
value can never bind. Lowering it to 60 is the only way the parameter does
anything: it stops one unqualified `pytest` from consuming the rest of a
session, which the v4 prompt makes likely by telling the agent to run the
repository's own tests.

### Finding 18 — the local harness inverts the sign of the step-budget effect

Locally, buying more steps made things **worse**:

| | steps bought | resolved |
| --- | --- | --- |
| 12b vs 31b | +35% tool calls | 1/24 vs 6/24 |
| think 0 vs 1024 | +39% tool calls | 4/24 vs 6/24 |

On the scorer, buying more time made things **better** (+3 tasks).

The explanation is context compaction. `scripts/inference.py` configures ADK
events compaction on the scored run -- `compaction_interval=15`,
`overlap_size=2`, `token_threshold=14,336`, `event_retention_size=5` -- and the
`swegemma eval` CLI configures none. Locally, extra steps accumulate context
until the 32,768-token window overflows; both arms above died that way (12
overflows for the 12b, 7 for think 0, against 1-3 for the baseline). On the
scorer they do not.

**So the published local harness does not merely add noise to step-budget
experiments; it reverses their sign.** That is the sharpest form of the
measurement thesis so far and it belongs in the paper.

> **CORRECTION to 2026-11-06.** "More time buys more exploration, which is
> precisely what the 12b and thinking-0 arms showed doesn't convert" is wrong
> as a general claim. It held under the v3 prompt in a harness without
> compaction. Under v4 on the scorer, more time is worth +3 tasks.

> **CORRECTION to 2026-10-27.** "Stay on the 31b; the model question is closed"
> rested entirely on the 12b's context overflows, which compaction mitigates.
> The question is reopened and the 12b deserves a scored submission.

### Next
- [ ] **Submission 7: `max_time_minutes: 6`.** ~7.8h of agent loop for 100
      tasks against a ceiling that accommodated 6.9h. 7 min is ~8.8h and should
      wait for evidence.
- [ ] **Submission 8: the 12b at the best budget.** Its local verdict is
      invalid for the reason in finding 18, and it buys ~30% more steps.
- [ ] Ensure 0.15 is selected as one of the two Final Submissions
- [ ] Validate v4 on the full 129 sharded -- the number to watch is the 34%
      empty-patch rate falling. No submission cost, and it gives the paper a
      before/after on an identical task set
- [ ] Paper: 12 November, 11:59 PM UTC. Related work still at zero
- [ ] Strip `task_prompt` from the `devset_*` traces before the repo goes public

## 2026-11-09 — Submission 7: the time budget saturates at 5 minutes

Submission 7 was submission 6 with one field changed: `max_time_minutes`
5 -> 6. Everything else identical (prompt v4, 31b, `max_tool_calls: 50`,
`timeout_seconds: 60`, sampling unchanged).

**Public score: 0.15. Unchanged.**

### Finding 19: the per-task time budget has a knee at 5 minutes, and we are past it

Three points on the scored set, same prompt, same model, one variable:

| `max_time_minutes` | Public score | Tasks (of ~100) | Delta |
|---|---|---|---|
| 4 | 0.12 | 12 | — |
| 5 | **0.15** | 15 | **+3** |
| 6 | 0.15 | 15 | **0** |

The marginal return on wall-clock per task is +3 tasks for the fourth-to-fifth
minute and zero for the fifth-to-sixth. The budget is saturated. **Do not spend
a submission on 7 minutes.**

Revert to 5. It scores identically to 6, costs ~15% less wall clock, and leaves
more headroom under the 12h notebook ceiling for full-set local runs. The
committed `eval_config.yaml` already says 5; no change needed in the repo.

### Why it saturates, and what that implies

This is not the local overflow story. The scorer runs ADK compaction
(`compaction_interval=15`, `token_threshold=14,336`), so the agent is not dying
of context when given more room — it simply does not convert the extra room.

The full-129 run explains why. Of 129 tasks, 44 (34%) produced an **empty
patch**, and of those 44:

- 21 wrote only `/tmp/repro.py` and never touched source
- 13 never edited anything at all
- 9 attempted source edits that did not survive
- 1 edited only `tox.ini` (stripped as protected)

Patch-producing tasks resolve at **43.5%**; empty-patch tasks resolve at
**0.0%**. Among resolved tasks the first edit lands at median call 6, with 86%
by call 10.

So past 5 minutes the binding constraint is no longer time — it is **whether the
agent commits to an edit at all**. Extra minutes handed to an agent that is
writing reproduction scripts buy more reproduction scripts. The v4 prompt's
"no repro before editing" instruction is evidently not landing on the 21 tasks
that still only wrote one.

This yields a falsifiable prediction: interventions that raise the
patch-producing rate should move the score, and further increases to
`max_time_minutes` should not.

### Consequence for the time-budget curve as a whole

Combined with finding 18, the full shape is now three regimes, not two:

- **Local harness, no compaction:** buying steps *decreases* accuracy (the 12b
  at 1/24, thinking-0 at 4/24, both via context overflow).
- **Scored harness, with compaction, below 5 min:** buying time *increases*
  accuracy (+3 tasks, 4 -> 5).
- **Scored harness, with compaction, above 5 min:** buying time is *neutral*.

The local harness therefore does not merely add noise to step-budget
experiments. It reports a monotone-decreasing curve where the true curve is
monotone-increasing-then-flat, and it hides the location of the knee.

### Next lever is not time

Two candidates remain, in order of expected value:

1. **The 12b at 5 minutes.** Decode is ~2.5x faster, so the same wall clock
   buys ~2.5x the tool calls, which attacks "reach call 6 sooner" directly.
   Finding 18 already invalidated the local verdict against the 12b (its
   failure there was overflow, which the scorer mitigates). **Caveat: this test
   is confounded unless `max_tool_calls` is raised.** Max observed is 47 of 50
   with time binding first; a 2.5x faster model at the same 5 minutes will hit
   the 50-call cap, and the result would measure the cap, not the model. Raise
   `max_tool_calls` to 100 and `max_turns` to 110 so that *time remains the
   binding constraint* — this preserves the experimental condition across the
   model swap rather than changing a second variable. Per-task wall clock is
   still capped at 5 min, so total runtime should fall, not rise.
   Note the `--hf-overrides` arg the 12b needs is a **local vLLM fix only**; the
   submission zip needs nothing but `model: gemma-4-12b-it-qat-w4a16-ct`. If
   submission 8 fails to start, that architecture-recognition issue on the
   scorer's serving stack is the likely cause and is not fixable from the zip.

2. **Prompt v5 against the 34% empty-patch rate**, specifically the 21
   repro-only tasks. Historical ceiling for a prompt revision is +2 tasks.

> **CORRECTION (same day).** The finding-19 table above labels all three rows
> "one variable." That is wrong for the 4 -> 5 row. Submission 6 changed *two*
> fields relative to submission 5: `max_time_minutes` 4 -> 5 **and**
> `timeout_seconds` 300 -> 60. The +3 tasks are therefore attributable to the
> pair, not to the extra minute alone, and the plausible mechanism for the
> timeout half is large: at `timeout_seconds: 300` with a 240s session,
> `run_command` resolves to `min(300, remaining)` = remaining, so a single
> unqualified `pytest` can consume the entire remaining budget. Capping it at
> 60s returns control to the agent.
>
> What survives cleanly: **submission 7 vs 6 is a true single-variable test**
> (5 -> 6 min, timeout 60 in both) and it returned zero. So "the time budget is
> saturated at 5 minutes" holds. What does **not** survive: any claim about
> where the knee sits, or that the fourth-to-fifth minute specifically bought
> +3. The paper must state the 4 -> 5 delta as a combined effect.
>
> This is resolvable with one submission (4 min, `timeout_seconds: 60`) but that
> run can only match or lose ground, so it is optional and deferred.

### Prompt v5 candidate: the scratch-file licence

v4 contains a direct internal contradiction. `## Committing to an edit` says
"Do not write a reproduction script before you have edited the source."
`## Scratch files` then says "If you do write a scratch script, put it in /tmp,
never inside /workspace."

21 of the 44 empty-patch tasks wrote only `/tmp/repro.py` — the exact path the
second section supplies. An advisory prohibition and an operational permission
that names a destination are not equally weighted by the model; the one with the
concrete path wins. v4 is licensing the failure mode it elsewhere forbids.

v5 removes the licence rather than restating the prohibition:

1. Delete the scratch-script permission. Retain the protected-files warning in
   that section, which is load-bearing (one task spent its entire patch on
   `tox.ini` and had it stripped).
2. Make the constraint structural, not advisory: every `write_file` and
   `edit_file` call must target a path under `/workspace`. This makes
   `/tmp/repro.py` not an option rather than a discouraged option.
3. Keep the 8th-call edit deadline. Resolved tasks edit at median call 6 with
   86% by call 10, so 8 is well placed; the failure is tasks ignoring it
   entirely, which an earlier deadline would not fix.

Predicted effect: ~34 of 100 scored tasks currently produce nothing. Converting
10 of them to patch-producers at the measured 43.5% rate is +4 tasks. The
historical ceiling for a prompt revision is +2, so +2 to +4 is the realistic
band.


## 2026-11-10 — Submission 8: prompt v5 regressed, and why

Submission 8 was submission 6 with the prompt swapped v4 -> v5. Nothing else
changed: 31b, 5 min, 50 calls, `timeout_seconds: 60`, sampling identical.

**Public score: 0.12, down from 0.15. Three tasks lost.**

Prompt reverted to v4 on `main` (`3d4a7b8`). v4 remains the best known prompt.

### Finding 20: a universal rule over a tool's arguments hit the success path

v5's single added sentence was:

> Every edit_file and write_file call must target a path under /workspace. Do
> not create files anywhere else.

The baseline traces show what that rule actually acts on. Across all 450
`write_file`/`edit_file` calls in the full-129 run:

| `filepath` form | Calls | Share | What they are |
|---|---|---|---|
| **relative** (`fastapi/routing.py`) | **333** | **74.0%** | the real source edits |
| `/tmp/...` | 104 | 23.1% | scratch and repro scripts |
| `/workspace/...` absolute | 12 | 2.7% | rare |
| missing | 1 | 0.2% | — |

Every resolved task comes from the 74%. The rule declares that form
non-compliant and mandates the one used in 2.7% of calls. It was written to
suppress a 23% failure mode and it landed on the 74% success path.

**It also redirects scratch files into the patch rather than preventing them.**
The v4 line it replaced sent them to `/tmp` *because* "anything left in
/workspace becomes part of your patch." Under v5 a `write_file` that would have
produced `/tmp/repro.py` produces `/workspace/repro.py` — inside the repo,
inside the diff. A stray top-level script is collected by pytest and can error
the whole verification even when the source edit is correct. This is the only
mechanism identified here that yields a *decrease* rather than a flat result.

**And it misses the dominant route.** Scratch files reach `/tmp` two ways:

```
write_file to /tmp            96 / 129 tasks
run_command shell redirect    89 / 129 tasks   (cat <<EOF > /tmp/repro.py)
either route                  97 / 129 tasks
```

v5's rule names only `write_file` and `edit_file`. The `run_command` route is
untouched, so v5 pushed the one contained route into the repository while the
uncontained one carried on.

> **CORRECTION to finding 20 (2026-11-10).** Two things in this entry are
> superseded by a measurement we had not taken when it was written: per-tool
> error rates.
>
> **1. `write_file` cannot write outside `/workspace` at all.** Of 132
> `write_file` calls in the full-129 run, **104 failed (78.8%)**, almost all
> with `Path traversal detected: '/tmp/repro.py' escapes workspace root`. So
> the 104 write/edit calls this entry counted as "targeting /tmp" were not
> scratch files being safely contained — they were **hard tool failures**. v4's
> `/tmp` instruction did not contain anything; it directed the agent at a path
> the tool rejects, and the sandbox is what kept the repo clean. The v5
> mechanism still holds and is in fact sharper: v5 pointed the same impulse at
> the one writable location, where the write *succeeds* and the file enters the
> patch. The prompt was wrong either way; only v5's wrongness reached the diff.
>
> **2. "first edit at median call 6, 86% by call 10" is wrong.** That counted
> failed `/tmp` write attempts as edits, and those happen early, biasing the
> figure early. Counting only the first *successful* source edit, among
> resolved tasks: **median call 11, 43% by call 10, 16% by call 8.** This
> reverses this entry's conclusion that the call-8 deadline was well placed.
> It is not placed well -- it is **ignored**, by 84% of the tasks that go on to
> resolve.
>
> Full per-tool error rates, which we had never once inspected across nine
> experiments and seven scored submissions:
>
> ```
> read_file     1,074 calls      4 errors   0.4%
> edit_file       318 calls     27 errors   8.5%
> write_file      132 calls    104 errors  78.8%
> ```
>
> `edit_file`'s 27 are 14 `old_string not found`, 10 ambiguous "occurs N
> times", 1 no-op -- real but minor, and not the tier-defining problem some
> third-party advice suggests.

### What was misread

v4's two sections were called contradictory in the 2026-11-09 entry above — one
forbidding reproduction scripts, the other saying where to put them. That was
wrong. The ban was **policy**; the `/tmp` line was **containment**, and the
"becomes part of your patch" clause was the reason it bound. 74% of tasks wrote
a scratch file regardless of the ban, so the policy never held and the
containment was doing all of the work. v5 deleted the working mechanism to
strengthen the one that did not work, and removed the
abandon-after-two-failures loop breaker in the same edit.

### Consequence for the paper

This is not only a prompt-engineering lesson. We had measured the **failure**
mode in detail (34% empty patches, 21 repro-only, first edit at median call 6)
and never measured the **success** mechanism — that three quarters of productive
writes use relative paths. Intervening on a well-measured failure while blind
to the success path is the same error as §4's, in a new place: the instrument
captured what went wrong and not what went right.

### Next

Do not spend another submission on the prompt. That axis has returned +2 at
best and now -3. v4 at 0.15 stands. The 12b at 5 min with `max_tool_calls: 100`
and `max_turns: 110` is the remaining untested axis, and it also closes the
limitation stated in §6 of the paper.


## 2026-11-10 — Submission 9: the 12b, and a prediction that failed

Submission 9: `model: gemma-4-12b-it-qat-w4a16-ct`, `max_tool_calls: 100`,
`max_turns: 110`, everything else as submission 6 (5 min, `timeout_seconds: 60`,
prompt v4). The call cap was raised so that *time* stayed the binding constraint
across the model swap rather than the cap becoming it.

**Public score: 0.08. Down 7 tasks from 0.15.**

### Finding 21: the local verdict on model scale was right; our mechanism was wrong

Finding 18 argued the 12b's local collapse (1/24) was an artifact of the local
harness lacking compaction: the logs showed context exhaustion, the scorer
enables compaction, so the 12b should recover when scored. It did not. It
roughly halved.

So overflow was a **symptom of a weaker model, not the cause of its failure**.
Finding 18's reversal is withdrawn as applied to model scale.

This matters more than one submission. It bounds the central claim of the
paper. The local harness *demonstrably* misreports step budgets — the
4/5/6-minute curve is measured directly on the scorer and still stands — yet it
reported model scale correctly. **Unfaithfulness is selective.** "The local
harness is unfaithful" is not a licence to discard local results wholesale, and
treating it as one is what produced this wasted submission.

Note also that the 12b had *more* steps, not fewer: 2.5x decode speed and a
call cap raised to 100. It still halved. More steps is not the lever.

### Consequences

**The model axis is closed.** Do not try e4b or e2b; the gradient from 31b
(0.15) to 12b (0.08) is unambiguous. This retires the "if the 12b gains, go
smaller" branch.

**31b at 5 min / 50 calls / `timeout_seconds: 60` has now survived two
deliberate attempts to beat it** (v5 at 0.12, the 12b at 0.08). It should be
locked in as one of the two Final Submissions now rather than at the deadline.

**It tempers the LoRA case.** Capability evidently binds, not only policy. A
LoRA on the 31b adds policy without subtracting capability, so the case is not
refuted — but it is weaker than finding 20's behavioural framing implied, and
expectations should drop accordingly.

**It promotes the BM25 localiser.** Third-party measurement on this task set
puts BM25-over-source with tests filtered at 0.64 hit@5 for locating the edited
file, against grep's 0.41 — and we do localisation with `run_command` grep,
1,612 calls, 56% of all tool calls. That lever reduces the work a task requires
instead of changing the model, so it is capability-neutral, which is now the
property worth having. Verify the figure on our own 129 tasks before building a
submission on it.

### Submission history

| # | Config | Score |
|---|---|---|
| 1 | unmodified sample | 0.03 |
| 2 | prompt v1, 5 min / 40 | FAILED |
| 3 | v2 think 1024, 3-file zip | FAILED (12h) |
| 4 | v3, 4 min / 50, timeout 300 | 0.10 |
| 5 | v4, 4 min / 50, timeout 300 | 0.12 |
| 6 | **v4, 5 min / 50, timeout 60** | **0.15** |
| 7 | v4, 6 min / 50, timeout 60 | 0.15 |
| 8 | v5, 5 min / 50, timeout 60 | 0.12 |
| 9 | 12b, 5 min / 100 / turns 110 | 0.08 |

