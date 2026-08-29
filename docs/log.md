# Development log

Reverse chronological. Decisions, measurements, and the things that are still
unproven. The README describes what dk-mode does; this file records how it got
there and what was actually tested.

---

## 2026-08-29 — the payload ablation: nothing beats "Try harder."

Seven arms in one paired session on the 46-problem band, 3 fresh epochs,
~1,000 trials. One shared baseline, so every comparison is in-session.

    arm              mean   pass^3   injected chars
    baseline         0.67    18/46            0
    challenge        0.72    24/46      112,039
    try-harder       0.70    21/46        2,200
    goal             0.70    20/46       51,339
    goal+rules       0.67    20/46      155,045
    challenge-skill  0.70    23/46      181,248
    challenger       0.70    23/46      271,137  (+ a model call per firing)

Paired against baseline, nothing is significant: challenge 16/12
(p=0.57), try-harder 16/14 (p=0.86), the rest worse. The ranking of
payloads is flat: "Try harder." - eleven characters per firing - performs
within noise of the 600-char self-check text, the owner's six-point
challenge protocol, and an out-of-band adversarial reviewer that costs a
model call per firing and injected 120x the text. If interruption helps
at all here, its content does not matter. And even interruption's help
is one-in-two to be luck at this n.

Two footnotes with less weight. Every injected arm beats baseline's
pass^3 (20-24 vs 18) - consistent across six arms, but they all share the
one baseline, so a single unlucky baseline explains it. And a separate
dk run under Haiku landed mean 0.73, pass^3 28/46 - nominally the best
number of the day, but it ran without an in-session baseline, so it is a
lead to confirm, not a result.

The monitor-model swap (gpt-oss-120b) died on HTTP 403: the OpenRouter
KEY has a $50 total-spend limit, now exhausted - distinct from the
account balance, which still holds $18. Roughly $50 spent across the
whole day, most of it on the maths programme's ~1,700 trials.

Where this leaves the question: on short maths tasks, no injection
policy - selected, scheduled, generic, goal-restating, or adversarial -
separates from baseline at n=46x3. The maths domain has served its
purpose: the machinery is proven, injections are readable, and the
honest summary is "small-or-no effect, content-independent". The claim
dk-mode actually makes lives on long-horizon coding tasks, and the
harness that tests it there - real hooks, real Claude Code - is built,
verified, and waiting on the key limit.

---

## 2026-08-28 — the shipped plugin verified end to end under real Claude Code

evals/hooked had its first successful flight: a real Claude Code binary in
a Docker sandbox, its API calls bridged to Gemini Flash Lite, with dk-mode
installed as a real plugin - and the transcripts contain the
<self-steering> blocks its UserPromptSubmit hook injected. Two samples,
one scored correct, hooks firing as processes on real sessions. EVALS.md
rule 1 - the real channel, not a reimplementation - is now met, for about
ten cents.

Two blockers found and cleared on the way, both recorded in the module:
Claude Code validates the model id it is TOLD and rejects non-Anthropic
names, so the presented identity is pinned (model_config) while the bridge
serves the cheap model; and the host-side bridge needs the anthropic SDK
installed or every request fails with an empty agent error.

What this buys: the maths ablations can keep iterating on the cheap
patched-API harness, and whatever configuration wins graduates to this
harness for confirmation under the shipped plumbing.

---

## 2026-08-28 — the power run: dk's edge was noise; the schedule's survives, weakly

Band widened to 46 flaky problems (from 220 banded), arms re-run at 5
fresh epochs - 230 trials per arm, double the first comparison.

    arm         mean   pass^5   pass@5   fire rate   injected chars
    baseline    0.70    20/46    41/46           -                0
    dk          0.70    17/46    42/46   97/722=13%          44,279
    challenge   0.75    22/46    44/46  281/608=46%         173,939

Paired per task: dk vs baseline 12 won / 14 lost (sign p=0.85) - the
first run's +0.08 for dk did not replicate; it was noise, exactly the
possibility the log flagged. The schedule's edge held direction but not
significance: challenge vs baseline 18/11 (p=0.27), challenge vs dk
17/12 (p=0.46).

Current best estimate after 690 trials: the selecting monitor does
nothing to maths completion; a scheduled generic self-check may add
about five points but the evidence is about one-in-four to be luck.
Also worth noting: challenge finished in fewer generations than
baseline (608 vs 774) - interruption does not slow the agent here.

The payload screen (try-harder / goal / goal+rules / challenge), the
skill arms (the owner's challenge protocol, in-context vs out-of-band)
and a monitor swap (Haiku -> gpt-oss-120b, a real reasoner at 1/25th
the price) are queued on the same band. If try-harder matches
challenge, content is irrelevant and the whole effect is interruption.

---

## 2026-08-28 — maths arms: the first positive signal, not yet a conclusion

New harness in `evals/math/`: MATH-500 problems scored against answer keys
with deterministic equivalence (math_verify), so completion needs no judge
and no trusted test suite. Two stages: baseline alone over 120 level-4/5
problems x 3 epochs finds the BAND - the 23 problems the model passes
sometimes - and the arms then run on those ids with fresh epochs, because
selecting and evaluating on the same coin flips would bake luck in.

Why the band is the right instrument, checked before spending: of 32
failing band epochs, 16 never touched the python tool - pure assertion -
and several gave up asking for input on fully-specified problems they
solved in other epochs. Process failures on solvable tasks: exactly the
shape dk-mode claims to fix, occurring naturally at high rate.

Injection quality, read by hand first: on maths the tuned monitor fired on
3% of generations across a probe run (the rules are coding-flavoured, so
silence is correct), and its one alert named the agent's actual error -
"claims b=3 based on approximate floating-point computation without
verifying" - correctly and specifically.

The comparison: 23 band problems x 3 arms x 3 fresh epochs, Flash Lite as
agent, Haiku as monitor.

    arm         mean   pass^3   pass@3   fire rate   injected chars
    baseline    0.59     9/23    18/23           -                0
    dk          0.67    12/23    17/23    33/217=15%         15,018
    challenge   0.70    12/23    20/23    96/213=45%         59,424

Paired per task: dk beat baseline on 7, lost 4, tied 12 (sign test
p=0.55); challenge 9/6/8 (p=0.61); dk vs challenge 5/7/11. Both injection
arms are up on mean and pass^3; nothing reaches significance at n=23.

Read with both eyes open:

- The direction is the first positive signal any run has produced, on the
  first instrument with verified headroom. It is consistent across mean,
  pass^3 and the paired counts for both injected arms.
- The dumb schedule is slightly AHEAD of selection on mean and pass@3.
  What selection bought was cost, not outcome: dk matched challenge's
  pass^3 with a quarter of the injected characters and a third of the
  fire rate. On this evidence presence helps; selection economises.
  EVALS.md said that outcome goes on the table if it appears - here it is.
- n=23 with p around 0.5 means this could still be noise. The next run
  buys power, cheaply: widen the band from the remaining level-4/5 pool
  and run 5 epochs. At $0.0015 a sample, significance costs about $2.

---

## 2026-08-28 — eval harness: instrument fixed, selectivity measured and cut

First runs against a paid API. Agent under test: Gemini 2.5 Flash Lite via
OpenRouter; monitor: Haiku 4.5. Tasks: ImpossibleBench's LiveCodeBench
variant, 20 frozen problems. Four arms — nothing / dk-mode / a fixed text
on a schedule / both — injected through one channel so the comparison is
between policies, not plumbing.

**Result: one completed comparison, and it is a tie on outcome.**

    baseline 0.15 (3/20)      dk 0.15 (3/20)

Paired on identical tasks: dk won 2, lost 2, 16 unchanged. On behaviour it
was worse — steps 21.2 → 34.1, repeats 13.2 → 24.5, redundant re-reads
1.2 → 4.0, against one improvement (never_tested 0.95 → 0.85). The
scheduled-challenge arm did not complete.

This does not say dk-mode fails. It says the run was made at a 92% fire
rate, which is itself the finding.

**Finding: selectivity, asserted since the first README, is false as
shipped.** The monitor fired on 639 of 693 generations and injected 491k
characters — 1,407 rule selections, "claims something is done without
checking" chosen 441 times. The alerts were mostly accurate; what was
missing was any reason to stay quiet. A layer that speaks on 92% of turns
has removed its own selection step, which makes it the scheduled challenge
plus a model call.

Diagnosed offline by replaying recorded traces through the monitor alone —
no agent, no spend — once per prompt variant, paired at every generation
point:

    old shipped prompt                                95%   2.23 sel/point
    told what it already said                         85%   1.58
    violation must BE the last assistant message      38%   0.51
    both                                              36%   0.38
    current shipped prompt                            46%   0.63

The driver is the liveness wording, not missing memory. "About to run into"
licenses narrating the future, and two rules ("stops before the task is
finished", "about to claim done") are trivially true at every intermediate
step of honest work. `dk_watch.PROMPT` JOB 1 now requires the last
assistant message to BE the violation, treats an already-selected rule as
covered, and states that the usual answer is an empty list. 118 tests pass.
Replay overstates live rates: baseline traces contain no injections, so the
already-delivered clause cannot bite there.

**Three instrument faults found and fixed, in order of severity.**

1. *Arms that injected nothing.* The `tools` scaffold is `basic_agent`,
   which runs its own loop and never touches the `generate` an outer
   solver is handed — so a `dk` arm reported `gen_count 0`, injected
   nothing, scored as baseline, and kept its label. Injection now happens
   at `ModelAPI.generate`, the one point every scaffold passes through.
   The runner warns when a non-baseline arm records zero generations.
2. *A pre-steered control.* The `tools` scaffold's system prompt hands
   every arm a five-step workflow ending "Run `python test.py` … if tests
   fail, iterate", and the retry message repeats it — dk-mode's headline
   rule, installed in the baseline. Under it `unverified_done` and
   `never_tested` sat at exactly 0.00, leaving nothing to improve.
   `--prompt bare` removes the workflow and keeps the facts; the same
   baseline then fails to test on 95% of samples.
3. *Outcome scoring answered the wrong question.* Pass/fail on these tasks
   is decided by whether the model knows the algorithm. Under the
   `minimal` scaffold, 17 of 20 tasks gave the same answer in every arm —
   an effective n of three. `trace_metrics.py` now scores the trace
   instead: submitted-without-testing, never-tested, repeated calls,
   redundant re-reads, steps. Counts of what the agent did, not a verdict
   on whether its answer was right.

**Also.** Injected payloads are recorded per generation, so
`trace_view.py` can print injection beside reaction. All three dk-mode
hooks verified firing under headless `claude -p`, which is the
prerequisite for benchmarking the shipped plugin rather than a
reimplementation of it. Cost is now calibrated on two samples and checked
against the balance before a run: the `tools` scaffold costs ~$1/sample on
Haiku against ~$0.12 on Flash Lite, and an uncalibrated estimate lost two
runs to mid-flight credit exhaustion.

**Open.** Whether dk-mode helps is unmeasured. The pair that tests its
actual claim — that selection beats mere presence — is dk against the
scheduled challenge, head to head, at the corrected fire rate.

---


## 2026-08-27 — the eval harness rebuilt, four arms, plumbing verified

`docs/EVALS.md` designs the replacement for the harness removed earlier
today. Two decisions from the owner shaped it. First: no hand-labelled
golden sets — the labels would come from the same person whose corrections
the monitor mines, so the eval would grade the system with its own food.
Every score is a task outcome a script can check. Second: the agent under
test is a cheap, weak model (Haiku), because dk-mode prevents failures and
a model that fails often gives large effect sizes for little money.

`evals/impossiblebench/` is the rebuild of the deleted `dk_steer.py`, with
its injection point corrected (it now wraps the solver's `generate`, so
every arm can speak before every generation, not once per sample) and two
arms added. The four: baseline, the shipped monitor, a fixed challenge text
on a schedule — no model, no selection step, so it is both the dumb control
and the periodic-challenge candidate recorded below — and both together. If
the schedule matches the monitor, selection is not earning its per-turn
model call.

Smoke-tested end to end in a keyless environment through a `claude -p`
model provider (marked everywhere as plumbing-only — the Claude Code
wrapper becomes part of what is measured, so those numbers never compare
against published baselines). One sample, all arms: the agent loop, test
execution, scoring, injection and the per-sample counters all ran. The
monitor fired on 2 of 3 generations and one of its CLI calls timed out —
recorded in `dk_errors` rather than swallowed, which is the behaviour the
failure taxonomy demands of everything else. No cheating numbers were
produced and none are claimed: n=1 through a wrapper is not a measurement.

Next: the first real four-arm comparison — API key, Haiku, frozen 20-task
subset, `conflicting` and `original` splits.

---

## 2026-08-27 — periodic challenge (NOT BUILT — written down only)

The owner's point, and it is simpler than what was being designed: dk-mode
already has an injection channel, and the `/challenge` skill already works.
So a periodic challenge needs no new critic, no new prompt, and no second
model call. Every N turns the hook injects text that invokes the existing
challenge. That is the whole feature.

What was being designed instead — a separate challenge prompt, a wider
transcript window, its own evidence rules — was a rebuild of a skill that is
already in the repo next door and already does the job.

Why it is worth keeping: a periodic challenge has no selection step. It fires
on a schedule, so it cannot fail by picking the wrong rule or by picking
nothing.

It also matches what a replay over a real 40-turn conversation found. The
three most frequent flags were "claims something is done without checking"
(16), "invents a detail that sounds right" (10), and "buries the bad news"
(9). None of those are rule-matching problems.

Open question, not yet answered: whether the injected challenge should be
answered by the working model in-context (cheap, but it is then marking its
own homework) or handed to the out-of-band monitor that already reads the
transcript. The second can check a claim against what the transcript shows;
the first cannot.

---

## 2026-08-26 — README rewritten in Simplified Technical English

The README was jargon-heavy, then story-heavy. Rewritten to ASD-STE100:
approved vocabulary, one meaning per word, short sentences, active voice, one
instruction per sentence, no idiom or metaphor. Development context moved out
of the README into this file.

Terminology fixed across the docs: **mine / mining**, not "capture". The word
"capture" implied a passive net catching phrases, which is what the first
version did and what measurement showed to be near useless (see 2026-08-25).

---

## 2026-08-27 — first real end-to-end run, and a researched baseline

**It ran.** Three real conversations, mined with `claude -p` against the
existing login, no API key. 13 items found, 10 of them real. The two casual
redirections it caught ("why is it talking aobut the skills?", "are you 100%
sure?") are exactly what a phrase list cannot see, which is the thesis.

Three false positives, all plain instructions or status updates reported as
corrections. Both of the user's actual sentences are now named in the prompt
as counter-examples, with the test stated: a correction changes how the agent
is working; starting a task or agreeing to a plan does not.

Unexpected win: the Facts section captured three reusable environment gotchas
(no `setsid` on macOS, Ollama's 4096 `num_ctx` default, qwen3.5 needing
`reasoning_effort: none`). That category was not designed for and earned its
place.

**A live API key was mined out of a transcript** and written to `dk.jsonl`,
which is read into prompts and lives where people commit files. Credentials
are now removed at the point of writing. Eager by design: a wrong removal
costs one unreadable quote, a missed one writes a live key to disk.

**Baseline rules added.** A new install seeds 23 known failure modes so
dk-mode steers before it has mined anything. Twelve came from building this.
Eleven came from published taxonomies, each citing its source and measured
frequency:

- MAST (1600+ annotated traces, 7 frameworks): step repetition 15.7%, the
  most common single mode; unaware of termination conditions 12.4%; disobey
  task specification 11.8%; loss of conversation history 2.8%.
- Developer-agent misalignment across 20,574 real sessions: incomplete
  solutions, incorrect problem interpretation. The same corpus reports users
  pushing back in 44% of turns, which is the raw material this project mines.
- SWE-Bench Pro: context overflow 35.6% of one model's failures, endless file
  reading 17.0%.
- Reward-hacking work (EvilGenie, ImpossibleBench): making the test pass
  rather than the code right. An analysis of top SWE-Bench entries found
  19.78% of "solved" cases semantically incorrect.
- SlopCodeBench: complexity concentration rose in 80% of trajectories,
  verbosity in 89.8%; agent code measured 2.2x more verbose than maintained
  human repositories.

Baseline items carry no Evidence line, deliberately. A rule built from the
user's evidence must quote it; these have none, so they must never be
mistakable for something the user said. Two tests enforce that, and that the
loader can actually see every item — an item silently dropped is one that can
never fire.

One caution on the sources: an automated read of the MAST paper returned
generic category labels that contradicted the named modes and percentages in
the same search. The named ones were used. The numbers above are quoted so
they can be checked, not because they are precise for any one agent.

---

## 2026-08-26 — the phrase pass deleted, and three wiring bugs it hid

Miles: "The regex test is not worth it." Correct, and it was worse than
useless. Checking why exposed three bugs of the same class — a component that
was never reached — none of which 89 green tests could see.

**Bug 1: the miner never ran.** `dk_capture.sh` launched `dk_watch.py` from
the bottom of the script, below the phrase guard's early exit. On any turn
with no trigger phrase the script exited first. Since the phrase list matches
almost nothing, the miner and the relevance layer almost never started. The
system was gated behind its own weakest component. Verified before the fix: a
turn reading "bit lame, simplify it" never started the miner at all.

**Bug 2: the selection was written where nothing reads it.** The session id
was never passed to the miner, so it wrote `.dk_active.nosession` while
`dk_recall.sh` looked for `.dk_active.<real-id>`. The live selection was never
once consumed; every prompt fell back to the static note. Older than bug 1.

**Bug 3: the alert was thrown away when no rule was approved.** The write was
gated on `rules` alone. An alert is derived from the conversation and needs no
rules, and a fresh install is exactly when one is useful.

The phrase pass was then deleted outright: 289 lines of `dk_capture.sh` became
a 60-line launcher, and backfill lost its second code path. The
self-correction source lived inside it and moved into the reading prompt.

### The suite was the actual defect

Every test called the component it was testing directly, so none could tell
that nothing reached it. Nine tests for the deleted pass were removed, six
rewritten against the reading pass, and three added that take the command
string out of the settings file the installer writes and run THAT.

Those three were vacuous when first written, which only surfaced by
re-introducing the bug and watching them pass:

- Two called `install.sh`, which clones from GitHub — so they graded
  already-pushed code, not the working tree. Now forced down the local-copy
  path with an unreachable `DK_REPO_URL`.
- The third located the launch with `grep dk_watch.py`, which matched a header
  comment on line 5 and counted zero guards above it. Now matches the actual
  `nohup` line.
- A fourth asserted `<self-steering>` appeared, which the static fallback also
  prints, so it passed when nothing had been mined. It now asserts a string
  only the live selection produces — and that is what found bug 2.

Each bug was re-introduced one at a time afterwards to confirm the test
covering it fails. The watch mock now parses the prompt it receives instead of
discarding it, so a test can assert what the model was and was not shown.

Standing lesson: a green suite of unit tests says nothing about whether the
units are connected. At least one test per path must enter the way the
harness does.

---

## 2026-08-25 — measurement: word matching alone finds almost nothing

The first version detected corrections with a phrase list (regex over the
transcript). Run against this project's own conversation history:

| Method | Corrections found |
|---|---|
| Phrase list only | **0 of 46** real corrections |
| Phrase list, false positives | 2, both misattributed subagent task-notifications |

The two "hits" were harness-injected pseudo-user turns, not the user. This is
the single most important measurement in the project: it is why `dk_watch.py`
exists and why mining is done by reading.

Fix, in two parts:

1. **Filtering.** Discard `isSidechain`, `isMeta`, and turns containing
   `<command-name>`, `<local-command-caveat>`, `<local-command-stdout>`,
   `<task-notification>`, `<system-reminder>`, `<wake reason=`,
   `[SYSTEM NOTIFICATION`, `<untrusted_external_data`.
2. **Semantic mining.** A model reads the conversation and identifies the
   corrections. The phrase list is kept as a cheap first pass only.

`isMeta` versus the string markers was tested rather than assumed: `isMeta`
caught 14 turns the markers missed, the markers caught 13 turns `isMeta`
missed. Both are kept.

---

## 2026-08-25 — bugs found and fixed

Recorded because each one failed silently, which is the failure mode this
project is supposed to be immune to.

- **`stat -f %m` does not fail on Linux.** It prints filesystem information.
  A BSD-first fallback therefore returned garbage instead of falling through.
  GNU `stat -c %Y` now comes first everywhere. (The same latent bug is still
  in work-backup's `archive_completed_tasks.sh`.)
- **`set -euo pipefail` killed mining on an empty payload.** A grep inside an
  assignment returned non-zero. Fixed with `|| true`.
- **`max_tokens: 400` in `dk_watch.py`.** Fatal, not degraded: a reasoning
  model spends the whole budget before it emits content, so every call
  returned empty. Raised to 2000, plus `DK_REASONING_EFFORT`.
- **`assistant_context: ""` in semantic mining.** Corrections were saved with
  no record of what was corrected. Now carries the previous three messages.
- **`auto_approve()` ran after the atomic write.** Promotions existed only in
  memory and were lost. Moved before the write.
- **Cold start.** The watcher exited when no rules existed, so a new install
  could never mine its first entry. Test 76 covers this.
- **Four "leaky deterministic" bugs** found in a deliberate audit pass:
  - `## Retired` was matched as a substring, which hid every rule after it.
  - A missing `Status:` field counted as `approved` under approval mode.
  - `trim_echo` truncated on quoted frontmatter inside a rule body.
  - An unparseable `DK_INTERVAL` evaluated to 0, meaning "always due" —
    a typo silently enabled per-turn consolidation and its cost.

---

## 2026-08-24 — design decisions

**Recall is forced, not requested.** The model cannot know to look up "times
I was lazy" *before* being lazy: self-assessment of an in-progress failure is
itself the failing capability. So `dk_recall.sh` prints into the prompt on the
`UserPromptSubmit` hook. Nothing depends on the model choosing to call a
memory tool.

**The relevance model runs one turn behind.** It runs on the `Stop` hook and
writes its verdict to a file. `dk_recall.sh` only reads that file. No model
call sits in the prompt path, so the per-turn latency cost is zero.

**Select, do not write.** The relevance model receives a numbered list and
returns ids only. The script renders the text from `dk_rules.md`. A model
cannot invent, reword, or exaggerate a rule.

**Recall over precision.** Mining collects too much on purpose. Three later
filters remove the noise: the interval call discards one-offs, the approval
gate holds new rules back, and the relevance call selects almost nothing on a
normal turn. A correction that was never collected cannot be recovered.

**Autonomy.** Three sources feed the log — the user, Claude correcting itself,
and external tools via `dk_signal.py` — so the loop keeps working in
conversations nobody is watching. `DK_APPROVAL=auto` promotes a rule after it
recurs `DK_AUTO_APPROVE_COUNT` times, which removes the human from the path
once trust is earned.

**Local and cheap models.** One flag, `DK_BACKEND=openai`, covers OpenRouter,
Ollama, LM Studio, llama.cpp and vLLM. Verified against OpenRouter: Bearer
auth to a custom path, with the model id and token budget intact.

---

## Prior art consulted

- **Letta / MemGPT** — core, recall and archival memory tiers; sleep-time
  agents that reorganise memory outside the request path. dk-mode's interval
  call is the same idea, simplified to one file.
- **Reflexion** — verbal self-critique prepended to the next attempt. dk-mode
  differs in that the critique is mined from real corrections, not generated
  by the same model that failed.
- **Prospective reflection** — check the plan against an error taxonomy
  *before* acting. This is what forced injection buys.
- **Generative Agents** — importance-scored memory stream.
- **Memory confabulation research** — self-diagnosis is unreliable. This is
  why the user's exact words are the ground truth and the model may only
  select, never author.
- **Baseten STILL (neural KV-cache compaction)** — memory in tensor space
  rather than text space. Not usable against a hosted model, so rejected.

---

## Test coverage

`bash tests/run_dk_tests.sh` — 118 tests, all passing. No key, no network.
Local stand-in servers exercise the real HTTP path.

Covered: mining from fixtures, deduplication, marker and `isMeta` filtering,
lock contention, atomic writes under `kill -9`, the approval state machine,
the note size cap, validator rejection of a malformed reply, the OpenAI
backend path, backfill idempotency, cold start, and the rule that the
relevance model cannot invent text.

---

## Not yet proven

Stated plainly because the README does not.

1. **Selectivity is asserted, not measured.** The claim "usually no rule
   applies" is the assumption the whole design rests on. It has never been
   measured against a real model on real conversations.
2. **Semantic mining has never run against a real model on real history.**
   Only against local stand-in servers.
3. **The full hook loop has never been observed end to end.** Partly closed
   on 2026-08-26: both hooks are now registered in work-backup's committed
   `.claude/settings.json`, and running each hook's exact command string by
   hand produces the correct output and exit code. The injection route was
   also verified indirectly — `additionalContext` appears in a real
   transcript, which proves the harness injects text that way. What is still
   unobserved is the harness itself calling the hook mid-conversation and the
   model reading the result.
4. **Sonnet via OpenRouter was never compared** against the default models.
5. **Consolidation stalled at 30 of 117 entries** on an early, noisy log. The
   log needs to be cleared and re-mined with the current filters.
