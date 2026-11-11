<!-- Gemma 4 Developer Agent Paper Track. 3,000 words max.
     Running count per section in the comments. Target ~2,900. -->

# When the Harness Lies: Operational Budget and Measurement Fidelity Dominate Model and Prompt Choice for Local SWE Agents

*129 published tasks, nine controlled runs, seven scored submissions, 4xL4 GPUs*

**Authors:** Sultan Fawad, Ali Hussain, Balasivan Dhanapal, Yusuf Tagari

<!-- ABSTRACT — target 200 words, currently ~205 -->
## Abstract

Local software-engineering agents are usually improved by changing the model or
the prompt. We report nine controlled runs and five scored submissions on a
fixed 4xL4 / 32,768-token budget showing that two other factors dominate both,
and that the harness shipped with the benchmark misreports them.

First, the harness's subprocess sandbox cannot install per-task dependencies, so
**53 of 129 published tasks (41%) cannot be scored at all** regardless of agent
behaviour. Four pure-Python wheels take the usable fraction from 59% to 92%. We
give an agent-free, GPU-free procedure that detects this in any benchmark whose
local and scoring environments differ.

Second, measurement validity survives neither casually nor cheaply. A
hand-selected 24-task subset reproduced a plausible aggregate while **inverting
the per-repository structure**; **5.4% of tasks pass with no patch applied**; and
our own prompt instructed an action one tool cannot perform, producing a **78.8%
failure rate on that tool** that nine experiments never surfaced, because we read
resolution rates and never tool outcomes.

Third, the local harness **reverses the sign** of step-budget experiments.
Locally, buying steps hurts: a smaller model and disabled reasoning both score
worse, each dying on context overflow. On the scorer, which enables compaction
the local harness does not, buying time helps until it saturates. Conclusions
drawn locally about step budgets are directionally wrong, not merely noisy.

Held-out score rose 0.03 to 0.15 as these were addressed.

## 1. Introduction

A coding agent confined to a single consumer accelerator faces constraints cloud
agents do not: a fixed context window, a wall-clock budget per task, no larger
model to fall back on. The natural assumption is that performance is governed by
model and prompt quality, and most effort goes there.

We set out to do exactly that, sweeping reasoning budgets, model scale and five
prompt revisions. It produced almost nothing: three repetitions of the best
configuration resolved 6, 6 and 6 of 24 development tasks, a range of zero.

What moved the number was infrastructure. This paper reports what we found when
we stopped tuning the agent and started auditing the thing measuring it.

**(i) The local sandbox silently discards 41% of the task set.** The harness
cannot create a virtual environment with `pip`, so per-task test dependencies
are never installed and tests fail at collection. We quantify this across all
129 tasks, identify two root causes, and fix it with four packages. §3.

**(ii) Measurement validity is fragile in ways that produce believable
numbers.** Our subset reported fastapi at 0.077 and rich at 0.455 against true
full-set rates of 0.299 and 0.292 — two sampling errors cancelling into a
plausible aggregate. Seven tasks pass with no patch. And we never inspected
per-tool error rates, which hid a 79% failure rate on one tool. §4, §5.4.

**(iii) The local harness inverts the sign of step-budget effects.** Locally,
more steps reduce accuracy; on the scorer they increase it. The difference is
context compaction, which the scoring wrapper configures and the local CLI does
not. §5.

**(iv) A procedure.** Running the scorer's verification with the agent bypassed
establishes which tasks are measurable at all — no GPU, no model calls. §3.2.

We claim no novel architecture: one declarative LLM agent, six tools, no
fine-tuning — deliberately, to isolate these effects from architectural
confounds.

## 2. Related work

**Repository-level agent benchmarks.** SWE-bench [1] established the task format
we use: a real issue, a repository at a base commit, hidden FAIL_TO_PASS tests.
SWE-agent [2] showed the agent-environment interface is itself a design
variable, Agentless [3] that much apparent sophistication reduces to a fixed
pipeline. We are orthogonal to both: we hold the agent fixed and vary the
measurement apparatus.

**Benchmark quality.** The closest antecedent is SWE-bench Verified [4], where
annotators reviewed 1,699 samples and filtered **68.3%** — 38.3% for
underspecified problem statements, 61.1% for tests that may unfairly reject
valid solutions. Critically for us, it names *unreliable environment setup* as a
third problem area but **reports no figure for it**. Our §3 supplies one: 41%,
under the harness the benchmark ships. Later work questions whether patches
marked resolved are correct [5] and catalogues agent failure modes [6].

**Reasoning budget.** Zhou et al. [7] show returns on reasoning tokens diminish
at higher budgets and that extended chains can make models discard answers they
had reached. We observe that regime directly — 1,024 and 4,096 tokens are
indistinguishable at ~301 completion tokens per call — and add its lower
boundary: disabling reasoning costs accuracy even where the budget above it is
slack.

**Context management.** CliffCompaction [8] reports that without compaction a
long-horizon coding agent exhausts context early, capping the benefit of a larger
step budget, while with compaction performance keeps rising as steps increase.
Our §5 observes the same mechanism from the opposite direction and draws a
methodological consequence: when a local harness omits compaction and its scorer
enables it, step-budget experiments run locally produce conclusions with the
wrong sign — a hazard general to any benchmark with divergent local and scoring
environments.

## 3. The local sandbox discards 41% of the task set

### 3.1 Mechanism and magnitude

The harness offers two sandboxes, `docker` and `subprocess`. Any entrant without
a Docker daemon — which includes every hosted notebook we know of, and so
everyone using the competition's free compute — is restricted to `subprocess`.
There it reports `ensurepip unavailable in sandbox, creating venv without pip`
and never installs per-task test dependencies.

Two causes dominate. First, a transitive major-version break: the resolved
environment carries starlette 1.6.0, whose 1.0.0rc1 removed `on_startup` and
`on_shutdown` from `Starlette` and `Router`, while every fastapi commit in the
set predates that removal and still passes `on_startup` through
`APIRouter.__init__`. Second, missing test-only dependencies, overwhelmingly
`inline_snapshot` and `dirty_equals`, which fastapi's suite imports at module
scope. Either way collection fails before any test runs.

**53 of 129 tasks (41%) could not pass regardless of the patch applied.**
Pinning starlette to 0.52.1 and adding `dirty_equals`, `inline_snapshot` and
`pytest-httpbin` — four pure-Python wheels, no compilation — cuts collection
failures from 53 tasks to 11, raising the usable fraction from **58.9% to
91.5%** and repairing 42 tasks while regressing none.

What makes this expensive is its invisibility. A dependency failure manifests as
a collection error, which the harness scores exactly as a wrong patch:
unresolved. Nobody reading a resolution rate can tell them apart, and we did
not — every measurement in our first three weeks came from a set where half the
tasks were unwinnable by construction. We had found seven by hand; the true
figure was nearly eight times that.

### 3.2 An agent-free procedure for detecting it

The diagnostic is the harness's own `--skip-agent-patch`, which bypasses the
agent phase and verifies against the unmodified repository: no GPU, no model
calls, minutes rather than hours. Run it before and after any environment change
and treat the difference as ground truth.

This cannot be recovered from a normal run, where a collection failure and a
patch that broke an import produce the same observable; only with the agent
removed is the former unambiguously environmental. An unexpected-keyword error
naming a symbol the agent's own diff introduces, for instance, is an incomplete
implementation rather than skew — a distinction no classifier reading final logs
can make. This should generalise to any benchmark shipping a local harness
alongside a separately-hosted scorer; the only precondition is that the two can
diverge.

## 4. Measurement validity: reproducible and wrong

With the environment fixed, we assumed our frozen 24-task development subset was
sound. It was not, and its failure mode survived every check we thought to apply.

**The subset inverted the structure it was meant to represent.** On it, fastapi
resolved at 0.077 and rich at 0.455 — a 5.9x gap we had already written up as a
finding with a mechanism attached. On the full 129 tasks the two repositories
resolve at **0.299 and 0.292**: the same rate. The gap did not shrink; it never
existed. Thirteen unrepresentatively hard fastapi tasks produced it.

The subset's *aggregate* was not obviously wrong — 6/24 = 0.250 against 0.287
for the full set — which is why the error persisted: two sampling errors in
opposite directions cancelling into a believable headline while the structure
beneath was reversed.

**Reproducibility did not help.** Three repetitions of the same configuration
resolved 6, 6 and 6. We read that stability as evidence the measurement was
trustworthy; it was evidence only that it was *precise*. A biased instrument
with low variance reports the same wrong answer every time, and repeating it
cannot detect the bias.

**Some tasks are free credit.** With no patch applied, seven published tasks'
target tests pass: their FAIL_TO_PASS tests do not fail at `base_commit`, so the
resolution criterion is already met. That is **5.4% of the published set**
available to any submission, including an empty one. Wang et al. [5] find weak
patch validation inflates reported SWE-bench rates by 6.2 percentage points;
our 5.4% is a distinct and additive source. The effect is also not monotonic in
environment quality — one task passes *before* our wheel fix and fails after,
because installing the missing dependencies lets more tests collect and one
newly-collected test fails. Repairing an environment can destroy free credit.

**Heuristics for "unwinnable" were worse than nothing.** One cannot separate an
environment defect from a feature that does not exist yet, since a FAIL_TO_PASS
test importing the API you are asked to build fails at collection either way.
The other counts symbols the tests import that the statement never names — but
on the tasks it flagged hardest those were ordinary APIs (`APIRouter`,
`Depends`, `FastAPI`). It measured issue terseness, not solvability.

## 5. The local harness reverses the sign of step-budget experiments

### 5.1 Configuration barely moves the result

We report a null first, because it motivates everything after. Three
repetitions of the best configuration resolved 6, 6 and 6 of 24 development
tasks: a range of zero. Raising the reasoning budget from 1,024 to 4,096 tokens
changed nothing measurable — mean completion is ~301 tokens per call, so 1,024
was never binding. Disabling reasoning *did* cost accuracy (4/24 against 6/24),
so reasoning is not inert; the budget above it is slack.

Prompt revisions are harder to measure than they look: our local sequence spans
the environment repair of §3, so counts either side of it are not comparable —
the objection this paper raises elsewhere applies to our own sweep. The one
comparison that is clean, on the held-out scorer at a matched budget, is worth
**+2 tasks**.

### 5.2 Locally, buying steps hurts

Two interventions that buy more steps both made things worse locally. The 12B
model, at ~2.5x decode speed and +35% tool calls, resolved **1 of 24**;
disabling reasoning, worth +39% tool calls, resolved 4 of 24. Both logs show the
same cause: the agent exhausts its 32,768-token context and ends mid-task.

The natural conclusion — that more steps destroy this agent — does not survive
§5.3, and we held it for two weeks.

### 5.3 On the scorer, buying time helps, then stops

The scorer wraps the same agent in ADK event compaction
(`compaction_interval=15`, `overlap_size=2`, `token_threshold=14,336`,
`event_retention_size=5`). The local CLI configures none of it, so the agent
that overflows locally does not overflow when scored.

| `max_time_minutes` | Score | Tasks (of ~100) | Marginal |
|---|---|---|---|
| 4 | 0.12 | 12 | — |
| 5 | **0.15** | 15 | **+3** |
| 6 | 0.15 | 15 | **0** |

The 4 → 5 step also cut `timeout_seconds` from 300 to 60, so its +3 belongs to
the pair. The 5 → 6 step changed one field and returned exactly zero.

The true curve on the faithful environment is increasing then flat; the local
harness reports it as *decreasing*. Not extra variance — the wrong sign, and it
hides where the knee sits.

### 5.4 Why it flattens, and the signal we never read

Saturation is not a context limit; compaction removed that. Past five minutes
the constraint is whether the agent ever lands a source edit. Of 129 tasks, 44
(34%) produced an **empty patch**; patch-producing tasks resolve at **43.5%**,
empty-patch tasks at **0%**. Among resolved tasks the first *successful* source
edit lands at median call 11, only 16% by call 8 — though our prompt demanded
one by then.

Decomposing those 44 found something we had not been measuring:

```
26   attempted edits, every attempt failed
12   never called an edit or write tool
 5   edited successfully, patch still empty
 1   scratch work only
```

Twenty-six tried to edit and were refused. The per-tool error rates say why:

| Tool | Calls | Errors | Rate |
|---|---|---|---|
| `read_file` | 1,074 | 4 | 0.4% |
| `edit_file` | 318 | 27 | 8.5% |
| **`write_file`** | **132** | **104** | **78.8%** |

Nearly every `write_file` failure is one error: `Path traversal detected:
'/tmp/repro.py' escapes workspace root`. The tool is sandboxed to the
repository, and **our own prompt told the agent to put scratch files in
`/tmp`** — an action it cannot perform — producing a 79% failure rate on one of
six tools. Nine experiments and five scored submissions missed it, because we
read resolution rates and never tool outcomes. Twelve further tasks never
called an edit tool at all — an instance of the "cognitive deadlock" Liu et al.
[6] identify as the dominant agentic failure mode, and not diagnosable from
resolution rates either.

### 5.5 External validation

The held-out score rose **0.03 → 0.10 → 0.12 → 0.15** with a single declarative
agent, six tools, no fine-tuning and no architectural change. The gains came
from §3's environment repair and §5.3's budget correction, not from the model or
the prompt.

<!-- §6 — target 250 words -->
## 6. Limitations

Our evidence is one competition, one model family, one agent architecture: 129
published tasks from four repositories plus a held-out split of roughly 100 of
unknown composition.

The scored evidence is thinner. Submissions are limited to one per day, so
every scored configuration is **n=1** with no error bars, and the score is
reported to two decimals — about one task. A one-task difference is not
distinguishable from none, which is why we treat the 5 → 6 result as a null.

Two claims are weaker than they look. The 4 → 5 comparison is confounded
between time budget and command timeout, so we report its +3 as a combined
effect. And §5.2's reversal is **inferred from mechanism rather than measured**:
we saw the 12B model fail locally through context overflow and know the scorer
enables the compaction that prevents it, but the claim here is that the local
verdict is *unsound*, not that the opposite is established.

We also under-used the harness: our agent declares six tools where roughly
eleven exist, including code-graph and embedding retrieval over a pre-computed
index. We declared three of those briefly and removed them as unused — the
agent never called them, and we never instructed it to, so "unused" is a fact
about our prompt rather than about the tools. Our localisation claims therefore
describe our configuration, not the best available one.

Finally, the published tasks are a training split. The 2.9x gap between our
full-set rate (0.287) and a matched scored submission (0.100) means local
measurements do not transfer in level. We rely on them transferring in
*ordering*, which §5 shows is not guaranteed.

## 7. Conclusion

For a budget-constrained local coding agent, the dominant levers were not the
model or the prompt. They were whether 41% of the tasks could run, whether the
development subset represented the population it came from, whether the local
harness managed context the way the scorer does, and whether the tools were
succeeding at all. Each was invisible in the resolution-rate signal, and three
produced confidently-held conclusions that were wrong rather than imprecise.
Anyone evaluating agents against a hosted scorer should verify environment
parity, with the agent bypassed, before trusting any configuration comparison.

## Artifact availability

Everything behind the figures above is published at **<REPO URL>**: the 129-task
run in three shards, the 24-task development arms including the three repeated
seeds, both agent-free verification runs, the per-task outcomes, the per-step
traces, the agent's own patches, the full research record as a changelog, and
the exact agent configuration that produced the reported scores.

The repository includes `scripts/verify_paper_numbers.py`, which re-derives
every figure in this paper from that data, prints each claimed value beside the
computed one, and exits non-zero on any disagreement. At submission it reports
24 of 24 figures reproduced. The four quantities it cannot check are the
held-out public scores and the budget curve of §5.3, which only the
competition's scorer produces.

Competition problem statements have been redacted from the published traces,
since competition data may not be redistributed. No task text appears in the
tool calls or observations that the figures are derived from, so the redaction
leaves every reported number reproducible — which is what running the
verification script on the published data demonstrates.

## References

[1] Jimenez et al. *SWE-bench: Can Language Models Resolve Real-World GitHub
Issues?* ICLR 2024. arXiv:2310.06770.

[2] Yang et al. *SWE-agent: Agent-Computer Interfaces Enable Automated Software
Engineering.* NeurIPS 2024. arXiv:2405.15793.

[3] Xia et al. *Agentless: Demystifying LLM-based Software Engineering Agents.*
arXiv:2407.01489.

[4] Chowdhury et al. *Introducing SWE-bench Verified.* OpenAI, August 2024.

[5] Wang, Pradel and Liu. *Are "Solved Issues" in SWE-bench Really Solved
Correctly?* ICSE 2026. arXiv:2503.15223.

[6] Liu et al. *An Empirical Study on Failures in Automated Issue Solving.*
arXiv:2509.13941.

[7] Zhou et al. *When More Thinking Hurts: Overthinking in LLM Test-Time
Compute Scaling.* arXiv:2604.10739.

[8] Nguyen et al. *CliffCompaction: Cost-Efficient Compaction for Long-Horizon
Coding Agents.* arXiv:2609.26779.
