# Development log

Reverse chronological. Decisions, measurements, and the things that are still
unproven. The README describes what dk-mode does; this file records how it got
there and what was actually tested.

---

## 2026-08-28 — the first completed comparison: no effect on outcome, worse behaviour

Gemini 2.5 Flash Lite as the agent under test (40x cheaper than Haiku, which
is what made a completed run affordable at all), Haiku still as the monitor,
tools scaffold, --prompt bare, 20 frozen tasks, 6 attempts. baseline and dk
both ran all 20 samples. The challenge arm died on 402 with the balance gone,
so it has no number.

**Outcome: a tie.**

    baseline 0.15 (3/20)      dk 0.15 (3/20)

Paired on identical tasks: dk won 2, lost 2, and 16 of 20 tasks gave the
same answer either way. That is a tie in the strictest sense available, not
a small win or a small loss.

**Behaviour: worse on nearly every axis.**

    metric              baseline      dk
    steps                  21.20   34.05    +62%
    edits                  11.20   18.30    +63%
    repeats                13.15   24.45    +86%
    redundant_views         1.15    4.00    3.5x
    test_runs               0.15    0.35
    never_tested            0.95    0.85    the one improvement
    unverified_done         0.90    1.00    worse

dk-mode made the agent do 62% more work, repeat itself 86% more often, and
re-read files it had already read 3.5 times as much, for exactly the same
number of solved tasks. The single thing that moved the right way is
never_tested, 0.95 to 0.85: two more samples ran the tests at all.

**First, the good news about the instrument.** The bare prompt did what it
was built to do. Base rates are off the floor - baseline now fails to test
at all on 95% of samples and submits unverified on 90% - where under the
shipped prompt both sat at exactly 0.00. That confirms the earlier
diagnosis: the scaffold had been handing every arm dk-mode's headline rule,
and the flat results before this were an artifact of that, not evidence
about dk-mode.

**Now the finding. Selectivity is broken.**

The monitor fired on 639 of 693 generations - 92% - and injected 491,186
characters. The README says "usually no rule applies" and the design rests
on the relevance call selecting almost nothing on a normal turn. docs/log.md
lists this under "Not yet proven", item 1: "Selectivity is asserted, not
measured. The claim 'usually no rule applies' is the assumption the whole
design rests on."

It is now measured. The assumption does not hold. A monitor that speaks on
92% of turns is not selecting; it is narrating. And the behavioural columns
show what that costs: every injection is another instruction competing with
the task, and the agent responds by doing more, repeating more, and
re-reading more, without solving more.

This is the most useful result of the day, and it is a negative one about
the layer the project is named after. It does not say the idea is wrong. It
says this configuration of it is: at 92% fire rate the selection step is not
doing the job the architecture assigns it, so the comparison against a
scheduled challenge - the dumb control that cannot pick wrong because it
never picks - has not really been run yet. The challenge arm is the missing
number, and on this evidence it is the one most likely to win.

**Caveats, stated so the number is not over-read.** n=20, and the means
carry wide error bars; repeats 13 to 24 is a large gap but not a
significance test. Flash Lite solves only 15% of these tasks, so most
samples are failures either way and the outcome column has little room to
move. The monitor ran on Haiku while the agent ran on Flash Lite, which is
the shipped shape but not a matched pair.

**What this changes.** The next thing to measure is not another arm. It is
the fire rate: what DK_MAX_ACTIVE, the window, and the prompt have to be
for the monitor to speak on a minority of turns, and whether the behavioural
columns improve when it does. A steering layer that always speaks has
removed its own selection step, which makes it the scheduled challenge with
a model call attached - strictly worse than the control it was meant to beat.

---

## 2026-08-28 — the baseline was pre-steered, and the fix for it blew the budget

Two findings, one of them expensive.

**The scaffold was already giving every arm dk-mode's advice.**

trace_metrics.py was written to stop scoring the task and start scoring the
behaviour: from the tool calls in a log it counts submitting after an edit
with no test run in between, never testing at all, repeating a call already
made, re-reading a file with no edit between. Each maps to a shipped rule,
each is a count a script can take, no hand labels and no judge.

Run against traces already paid for, it answered the question the pass
rates could not:

    baseline  n=11  pass 1.00  steps 14.7  never_tested 0.00
                                           unverified_done 0.00

Baseline never once submitted without testing - and not out of virtue. The
tools scaffold's system prompt hands every arm a five-step workflow ending
"Run `python test.py` to check if your implementation passes / If tests
fail, analyze the error and iterate", and the retry message repeats it.
That is dk-mode's headline rule, pre-installed, twice, in the control.
Every comparison run this day was asking whether dk-mode improves a
baseline that had already been given dk-mode's instructions. The flat
results were never evidence about dk-mode.

So --prompt bare rebuilds the same scaffold with the workflow and the
reminders removed and every fact kept. That is the right experiment.

**It also cost $15.50 and produced nothing, for a reason worth writing
down.**

The run died on HTTP 402 again, with $5.91 left of $40. The token counts
say why: baseline alone spent 9,986,311 tokens on 13 samples - about 768k
per sample, roughly $1 each against the $0.25 estimated.

The cause was a fix applied too broadly. Injected arms spend the message
budget faster than baseline, because each injection is a message; a binding
limit would make steering lose on truncation alone. The response was to
raise message_limit from the shipped 30 to 200. Combined with the bare
prompt - which by design removes the instructions that kept traces to about
15 steps - nothing capped the wandering, and every generation re-sends the
whole accumulated conversation, so cost grows with the square of the trace.
The confound was real; removing the cap rather than sizing it was not the
way to fix it.

Two smaller lessons from the same failure:

- --budget was added after the first 402 and it passed at $21.38 before
  this run started. A pre-flight balance check cannot help when the cost
  estimate is four times low. The missing guard is cost per sample measured
  on one sample, not a balance compared against a guess.
- The 402 is partly a concurrency artifact: "in_flight_budget_exhausted"
  means credit is reserved per in-flight request. The dk arm issues about
  twice the calls, agent plus monitor, which is why it died at 2
  generations while challenge ran to 189 on the same balance.

**Standing.** About $33 spent across the day, no usable comparison between
any two arms. What was bought: the harness reproduces the published
baseline, a silent injection bug is fixed, three configurations are
eliminated as instruments, the behavioural metric exists and works, and the
control is now known to have been pre-steered. What was not bought: a
single number about whether dk-mode helps.

The next run must fix the cost model before anything else - size
message_limit near what a focused trace needs rather than removing it,
measure cost per sample on one sample and multiply, and cap concurrency so
the in-flight reservation cannot trip the budget.

---

## 2026-08-28 — four arms, real money, and three different reasons for no answer

The first runs against a real API. Haiku 4.5 as the agent under test and as
the monitor, both over OpenRouter, twenty frozen tasks. Three runs, three
distinct reasons the comparison did not resolve. None of them is "dk-mode
does not work"; none of them is evidence that it does.

**Run 1 - conflicting split, minimal scaffold. Every arm 0.00.**

    baseline 0.00   dk 0.00   challenge 0.00   dk+challenge 0.00

A cheating rate of zero everywhere, so nothing for the other arms to
prevent. The instrument, though, checked out: the monitor spoke on 51 of 60
generations, all 20 baseline samples ended in real assertion failures, and
only 5 sandbox timeouts occurred across 60+ intermediate attempts.

Then the published numbers arrived and changed what the zero means.
arXiv:2510.20270 figure 4 is this exact configuration - Conflicting-
LiveCodeBench, minimal scaffold - and **six of its eight frontier models
score exactly 0.0%** (Opus 4.1, Sonnet 4, Sonnet 3.7, o4-mini, GPT-4.1,
Qwen3-Coder; GPT-5 is 1%, o3 is the lone outlier at 33%). EVALS.md 2.2
demanded the published baseline be reproduced before trusting anything.
It reproduced. The harness reads true; the split is a floor.

Two further facts from that paper, both of which cut against plans that
were on the table here:

- **Cheating rises with capability**, not with weakness: "we observe more
  capable models having higher cheating rates" (fig 3 caption). The two
  weakest models tested cheat least. So moving to cheaper models - the
  obvious way to buy a higher failure rate - pushes this metric further
  into the floor, not out of it. The cheap-model screen was dropped before
  it was run.
- **Prompt dominates scaffold** on this split: the same model goes from
  92% to 1% cheating between prompt A and prompt D, and prompt D is what
  ships. The near-zero headline is a property of the tuned prompt.

No Haiku-class model appears anywhere in that paper. The 0.00 above is,
as far as can be told, the first one measured.

**Run 2 - original split, minimal scaffold. Headroom, and only three
tasks that can move.**

    baseline 0.45   dk 0.35   challenge 0.40   dk+challenge 0.40

dk-mode below baseline. The rates are the wrong thing to read - with n=20
the standard error is about 0.11 - but the arms are paired on identical
tasks, so the discordant counts are available and they are small:

    dk vs baseline            0 won, 2 lost
    challenge vs baseline     1 won, 2 lost
    dk+challenge vs baseline  0 won, 1 lost

Two discordant pairs is a coin flip. The real finding is underneath: **11
of the 20 tasks fail in every arm and 6 pass in every arm**, so only three
tasks are capable of moving at all. The effective sample size for measuring
steering is three, and the full 103-task split would buy roughly fifteen.

That is a statement about the instrument. A one-shot algorithmic puzzle is
decided by whether the model knows the algorithm. None of the failures
dk-mode names - claiming done without checking, repeating a step, losing a
constraint - can even occur in a scaffold with no tools, no files and three
submissions. dk winning zero tasks is what a distraction looks like, not
what a regression looks like.

**A validity bug, found by the smoke run and not by the numbers.**

Switching to the tools scaffold exposed one. That scaffold is
`basic_agent`, which runs its own loop and calls the model directly, so it
never touches the `generate` the outer solver is handed. The injection
wrapper was simply never reached: the arm reported gen_count 0, injected
nothing, scored as a plain baseline, and still called itself `dk`. This is
the same class of fault that invalidated the harness deleted on 08-27 - an
arm not doing the thing it is named after.

Injection now happens at `ModelAPI.generate`, the one point every scaffold
must pass through, with a contextvar carrying the sample's state and tool
results folded into the monitor's view (that is where "the tests failed"
lives, and the rules about claiming done are blind without it). Same smoke
sample, before and after: gens 0 -> 11, dk_fired 0 -> 5. run_arms.py now
warns when a non-baseline arm records zero generations, so this degrades
loudly instead of publishing.

**Run 3 - original split, tools scaffold. Aborted: out of credits.**

All four arms died on HTTP 402 partway through. The account held $20; the
tools scaffold costs roughly $0.20 a sample against $0.01 on minimal, and
80 samples emptied it. The cost was estimated beforehand and stated; the
**balance** was not checked against it, which is the mistake - one API call
would have caught it.

Nothing from that run is reportable: the arms completed 19, 2, 8 and 9
samples, and the samples that finished are the ones that ran first, not a
sample of anything. The rows are in evals/results.md marked ABORTED so they
cannot be mistaken for a comparison.

One free observation from data already paid for, offered as a lead and not
a result: under the tools scaffold, baseline passed all 11 tasks it managed
to score, including two (lcbhard_1, lcbhard_4) that failed under minimal.
The nine that never finished are exactly the nine that scored zero under
minimal, so this is the easy tasks getting easier with the hard ones
unmeasured. Whether the tools scaffold buys real headroom or just replaces
the conflicting split's floor with a ceiling is **unresolved**, and it is
the first thing the next run should settle.

**Where this leaves the climb.** Nothing has been measured about whether
dk-mode helps. Three configurations have been eliminated as instruments:
conflicting/minimal is a floor, original/minimal has an effective n of
three, and conflicting/minimal on cheaper models would be worse than
either. The tools scaffold is the only untested candidate, it now injects
correctly, and it needs about $15 to answer.

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
