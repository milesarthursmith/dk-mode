# Development log

Reverse chronological. Decisions, measurements, and the things that are still
unproven. The README describes what dk-mode does; this file records how it got
there and what was actually tested.

---

## 2026-08-30 — full pilot n=20: the failure is turn-1 surrender, and it's cheap to test

Epoch ghcr images (authenticated; ~12GB for all 20 via shared layers vs
~50GB from Docker Hub) let the full 20-instance pilot run. message_limit
raised 30 -> 100. Score: **3/20 (0.15)** - the raised cap changed nothing,
so the cap was never the constraint. The per-sample profile is the result:

    7/20 samples: 1 turn, 0 tool calls - read the bug report, stopped
    6/20 samples: quit within 2-5 turns
    7/20 samples: engaged (7+ turns) - of these, 3 PASSED

Direct evidence the failure is stochastic disengagement, not capability:
django-14373 passed the first pilot in 14 working turns, then surrendered
at turn 1 here; django-16255 did the reverse (2-turn hallucination stall
before, 19 turns and a pass now). Same task, same model. Whether the
agent engages at all is the dominant coin-flip, and turn-1 surrender is
the most steerable failure that exists - precisely what a monitor that
says "you have not started; use your tools" is for. Engaged attempts pass
at ~0.43; if steering converted the surrenders, the ceiling is ~0.4
against a 0.15 baseline - a large, detectable effect at n=20 x 2 epochs.

Cost: ~$0.011/sample ($0.22 for the pilot). A full three-arm comparison
projects to $2-4, within the current balance - no top-up needed after all.


## 2026-08-30 — SWE-bench pilot: the failures finally match the mechanism

Pilot of the real-repo instrument: 6 SWE-bench Verified instances
human-rated "<15 min fix" (django/sphinx), real Claude Code, Flash-Lite
behind the bridge, official swebench scorer, official Docker Hub images
(the Epoch registry rejects anonymous pulls; the Hub images are ~2.5GB
each, which capped the pilot at 6 of the planned 20 when the disk
allowance ran out).

Score: **1/6 (0.167)** - below the 0.4-0.8 target band. But the score is
not the finding. The finding is the failure profile:

    django-16145   1 turn, 0 tool calls - narrated the task, did nothing
    django-13297   2 turns - "the agent has applied the fix" after one
                   tool call, no verification, no fix landed
    django-16255   hallucinated a site-packages path, then asked the
                   nonexistent user for help
    sphinx-8721    9 turns, "committed the fix" - tests fail
    django-14373   PASSED in 14 turns of genuine navigate-edit-verify
    sphinx-9711    ran out of messages mid-exploration

On LCB, residual failures were algorithmic - no steering can supply an
algorithm. Here, five of five failures are PROCEDURAL: premature
surrender, unverified done-claims, phantom paths, asking a user that does
not exist. This is the first instrument where the dominant failure mode
is the thing dk-mode claims to fix. Whether it actually fixes them is
now, finally, a fair question.

Also learned: the task's default message_limit=30 binds (two samples hit
it; one passed anyway) - raise to ~100 for the real run. Cost measured at
~$0.01/sample at these lengths (~$0.07 total); a full 3-arm x 20-task x
2-epoch comparison projects to $12-36 with a raised limit. Blocker for
scale: disk - either the Epoch 5GB image set (needs a GitHub token for
ghcr) or a fresh session.


## 2026-08-29 — the real-hooks comparison: another null, and this one counts

The first valid comparison of the programme. Real Claude Code, the shipped
plugin's hooks firing as processes in the sandbox, the current monitor
(tiered window, arc gate, directive alerts), LiveCodeBench easy+medium,
held-out scoring, 20 tasks x 3 epochs per arm, all three arms 60/60 with
zero errors. Verified before reading the numbers: the dk arm carries **50
live monitor blocks** beside 62 static and 5 tripwire, so the model-based
layer really spoke.

    arm         mean   pass^3   pass@3
    bare        0.75   10/20    18/20
    dk          0.72   10/20    17/20
    challenge   0.73   11/20    18/20

    dk        vs bare       5-7   p=0.77
    challenge vs bare       3-3   p=1.00
    dk        vs challenge  5-7   p=0.77

Nothing separates. dk sits marginally BELOW the no-injection control on
mean and pass@3, level on pass^3, and the paired tests are as far from
significance as they can be. The scheduled control is also flat, so this
is not "selection lost to a schedule" - it is that no injection policy
moved completion here either.

**Why this null is worth more than the maths ones.** Every excuse the
earlier nulls left open has now been closed: the task horizon is real
(median 9 assistant turns, real test-fix cycles), the pass rate is in the
band where procedural failures are visible (0.75, not 0.12), the plumbing
is verified live rather than assumed, and the monitor is the rebuilt one
that can see an arc. The instrument was capable of showing an effect and
showed none.

**The honest limit on it.** n=20 tasks, and only 8 of them are flaky in
the control - tasks passed always or never cannot move, so the effective
sample for detecting steering is 8 paired tasks. That is far too few for
a 10-point effect; the power calculation wants ~113-161 paired
observations. This run rules out a large effect, not a small one.

Cost: $3.83 in two aborted runs plus ~$3.50 here. Two failures on the way
were mine, and both are now guarded in code: an OOM from 8 concurrent 2GB
containers on a 15GB host, and a scorer that let a solution's timeout kill
the whole arm instead of scoring that sample incorrect.


## 2026-08-29 — a coding instrument with an arc, built for nothing

The maths band was retired on a fair objection: 2-12 turns on a single
problem is not a place where circling, drift or a forgotten decision can
occur, so the arc rules the monitor exists for had nothing to fire on.
Every null it produced was about a domain with no arc.

**The replacement, built with no model in the loop.** ImpossibleBench's
LiveCodeBench variant is hard-split by construction, where a cheap model
scores 4-7% and almost every failure is a capability failure. Rebuilding
it was quoted at $5-20 of Sonnet transcription. That turned out to be
unnecessary: LiveCodeBench's LeetCode-derived easy and medium problems
ship `starter_code` and JSON functional test cases, so the conversion to
a func.py/test.py task is mechanical. 342 problems available; signature
arity matches test-input arity 43/43 on the newest release file. Cost to
build: nothing.

Scoring is held out - the agent develops against 2 visible cases and is
judged on 12-35 hidden ones, so hard-coding the examples does not pass
and no judge model is involved. Validated before use: hand-written
correct solutions pass all 78 held-out cases across three problems, and
the stub fails with actionable assertion messages.

**Calibration (n=22 across two draws).**

    draw   n    overall   easy    medium
    1      6    0.83      4/4     1/2
    2     16    0.44      3/6     4/10

Pooled 12/22 = 0.55. The two draws disagree because the tasks are flaky
run to run - overlapping easy problems went 4/4 then 3/6 - which is the
property the band methodology wants and the opposite of LCB-hard, where
failures were fixed capability limits. Turn counts: median 9, max 14
assistant turns, with real test-fix cycles. Cost ~$0.018/sample.

**First three-arm run: ABORTED, unusable.** All three arms errored with 8
failed samples each; the dk arm died at 16 of 60 with "Model proxy process
exited unexpectedly: Killed". Cause: 8 concurrent containers at a 2GB
limit against 15GB of RAM, and the dk arm carries an extra monitor process
per container. Recorded rather than reported: arms at 57 / 16 / 58 samples
cannot be compared. $2.15 spent. Rerunning at --max-samples 4.

The one positive from it: the dk arm's log carried live monitor blocks
(3 live, 15 static, 1 tripwire), so the plumbing fixed earlier in the day
holds under load.


## 2026-08-29 — the observer must know it is looking through a keyhole

Two review comments on the trace evidence, both acted on.

**1. The observer needs role-awareness.** The challenger once reported
"No original problem statement exists in transcript" as a CRITICAL finding,
seconds after the agent had correctly computed the answer - it was reading
a mid-task window and mistook its own truncation for a defect in the work.
The monitor has the same failure: in the 1055 trace it asserted the problem
was "already solved and verified in an earlier exchange" across two empty
generations. Both prompts now open by stating that they see a WINDOW, not
the whole session, that absence is not evidence, and that no finding may
rest on something being missing from what was shown.

**2. Exhibit 4 was misread, and the correction matters more than the
exhibit.** A 12-generation "loop" was recorded here as the monitor trapping
a finished agent. The logs say otherwise: at generation 1 the agent emitted
the text `submit(answer='2')` and made no tool call. It believed it had
submitted; the harness saw nothing and kept prompting; nothing ever told
the agent its submission had not registered. The loop is a harness fault.
The monitor's part was mixed - one directive-less firing, then a correct
switch to the "task is finished" rule telling it to stop.

The general point for the harness: an agent that "submits" as text gets no
feedback that it failed to submit, and the sample still scores correct, so
the failure is invisible in a pass rate. Only the trace shows nine
generations spent on a phantom submission. Worth a harness guard.


## 2026-08-29 — the window: judge the work, not the last message

Two critiques from review of the full traces, both correct:

1. The strict gate ("the violation must BE the last assistant message")
   bought the 92%→46% fire-rate fix by making the monitor myopic. Measured
   over 288 selections in the dk runs: 91% snapshot rules, 7% arc rules -
   the rules that need history ("repeats a step", "ignores a constraint",
   "forgets a decision") had been structurally disabled.
2. The window walked back to the last two USER messages - an anchor that
   does not exist in an autonomous run, leaving "the last 9,000 chars"
   as the accidental window.

Change shipped (`recent_work()` replacing the live window): a tiered
window over the last 100 assistant messages - newest 10 in full text,
the rest digested to one line each (~160 chars). Repetition survives
digestion, so a loop is visible as the same line recurring; drift is
visible against the pinned GOAL. The brief remains the layer beyond the
window - a cumulative digest rewritten every call - and the raw digest
lines are the check against it, because the brief is model-written memory
and was observed asserting work that never happened (the 1055 trace).
The gate now asks for a violation visible in the window and still live,
instead of embodied in one message.

Free replay over recorded dk traces: 9% fire rate, and on the sample that
looped for 12 generations the monitor selected "Repeats a step already
taken" - the arc rule the old gate could not fire. Also fixed: an alert
over 300 chars was silently discarded by the parser, turning directives
back into bare rule cards; now truncated instead. Unmeasured in a live
comparison; 119 tests pass.


## 2026-08-29 — the directive format: same null, and the band is exhausted

First measured run of the second-person directive injection format
(baseline + dk, one paired session, Haiku monitor, 46-task band, 3 epochs):

    arm            mean  pass^3  pass@3  fire rate
    baseline       0.70  23/46   41/46   -
    dk(directive)  0.75  23/46   43/46   28%

The mean gap does not survive pairing: 12-10, p=0.83. Against the
old-format dk arm it is 11-12, p=1.00 - the format change moved nothing
measurable. The mandatory alert did raise the fire rate (17% → 28%).

Two secondary findings worth keeping:

- **Session drift is real.** This session's baseline came in at 0.70 where
  the previous session's was 0.67 - about the size of most "effects"
  observed all week. Only same-session pairing means anything on this
  instrument, and the earlier unpaired dk(haiku) 0.73 "lead" is now fully
  deflated: it sits inside session drift.
- **The instrument is exhausted.** Every knob has now produced the same
  null on the maths band: payload content (7 arms), monitor model
  (Haiku vs gpt-oss-120b), injection format (rule-card vs directive), and
  selection vs schedule. The conclusion is consistent and boring:
  on short single-problem tasks, mid-task injection neither helps nor
  hurts by more than session noise. Further runs here spend money to
  re-measure noise. The open question lives entirely on long-horizon
  tasks (`evals/hooked`).

## 2026-08-29 — the monitor ablation: a smarter monitor changes nothing

The hypothesis that the maths-band nulls trace to a weak monitor (Haiku)
was tested by re-running the dk and challenger arms with a reasoning model
(gpt-oss-120b, 8k thinking budget) as the monitor. Same 46-task band, same
agent (Gemini Flash Lite), 3 epochs, old injection format (the run imported
the prompt before the directive-style change landed).

    arm                    mean  pass^3  fire rate  vs haiku counterpart
    dk(gpt-oss-120b)       0.70  23/46   19%        9-15, p=0.31
    challenger(gpt-oss)    0.72  26/46   43%        11-7, p=0.48

Neither arm differs measurably from its Haiku-monitored counterpart
(dk/haiku 0.73 at a 17% fire rate; challenger/haiku 0.70 at 46%), and
neither separates from the 2026-08-29_0111 baseline (0.67; p=0.46 and 0.38,
cross-session pairing). The reasoning monitor fires at the same rate,
selects similarly, and buys nothing.

Read together with the payload ablation, the picture is consistent: on this
instrument neither what is injected nor who writes it moves completion.
The monitor model is not the bottleneck; the instrument's task horizon is
the suspect. Remaining untested: the directive-style injection format, and
everything on long-horizon tasks (`evals/hooked`).

## 2026-08-29 — the injection now speaks to the agent, not about it

Trace review of the dk arm (2026-08-29_0231 run) showed the injection
format failing in a specific way. In the sample that fired most (12
generations, 7 firings), every injection led with a third-person diagnosis
("Agent is claiming...") followed by the same generic rule reminder, seven
turns running — while the monitor's own alert had already named the exact
missing step (the k=1 continuity check) and never once told the agent to do
it. The one clean save in the run (`number_theory/1055`: agent falsely
claimed it could not proceed, then recovered and submitted the right
answer) came from the most situation-specific alert in the log.

Change shipped to `dk_watch.py`:

- The alert is now mandatory whenever a rule is selected, addressed
  directly to the agent as "you", and must contain two parts: what you are
  doing wrong now, and the one concrete next action from this conversation.
  Cap raised 200 → 300 chars to fit the directive.
- `render()` leads with that directive. The rule is demoted to one
  parenthesized grounding line (heading + reminder + what earned it)
  instead of the old what-it-looks-like episode card.

Verified by free CLI replay over the recorded dk traces: the new prompt
produces alerts like "You presented these formulas as the final answer
without verifying them... Test these formulas" — second person, concrete.
Side effect observed: the monitor sometimes writes the directive without
selecting a rule id, which now injects a pure directive with no rule card;
`tune_selectivity.py` was updated to count those as firings.

**Unmeasured.** No arm has run under this format. The monitor ablation
in flight at the time of the change imported the old prompt at launch, so
its result stays comparable with earlier dk arms; the new format is the
next thing to test.

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
within noise of the 600-char self-check text, the six-point
challenge-skill protocol, and an out-of-band adversarial reviewer that costs a
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
key carries a per-key total-spend limit, now exhausted - distinct from
the account balance, which still held credit.

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
rule 1 - the real channel, not a reimplementation - is now met.

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
skill arms (the six-point challenge protocol, in-context vs out-of-band)
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
today. Two decisions shaped it. First: no hand-labelled
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

The idea is simpler than what was being designed: dk-mode
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

The regex phrase test was not worth keeping — it was worse than
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

1. **Selectivity has now been measured, and the original claim was false as
   shipped.** The 2026-08-28 replay measurement put the shipped prompt at a
   92% fire rate; the reworked prompt measures 46% in the same replay
   (which overstates live rates). Whether that is selective enough remains
   an open question, not a settled one.
2. **Semantic mining has run against real history** (2026-08-27: three real
   conversations, 13 items found, 10 real). Coverage beyond that first run
   is still thin.
3. **The full hook loop has been observed end to end - with one
   correction.** Closed in stages: on 2026-08-26 each hook's exact command
   string was verified by hand, and on 2026-08-28 the shipped plugin ran
   under a real Claude Code binary in `evals/hooked/` with the hooks firing
   in-session and injected `<self-steering>` blocks present in the
   transcripts. Trace classification on 2026-08-29 showed those blocks were
   the deterministic layers only (recall's static note, the tripwire): the
   model-based selection has never run under the real binary. An audit on
   2026-08-29 counted the producers across all seven hooked logs - 212
   static notes, 13 tripwire warnings, **zero** live monitor blocks - and
   found three independent causes, each sufficient on its own:

   1. **No credentials in the container.** The compose file had no
      `environment:` block until 2026-08-29, so `dk_watch` took its
      no-key exit. Fixed.
   2. **No TLS trust in the container.** `dk_watch` calls a model from
      inside the sandbox. Where egress is re-terminated by a policy proxy,
      the container reaches the host but cannot verify the chain (`curl`
      exit 60). Invisible in transcripts, because the other two hooks need
      no network. Fixed by mounting the proxy CA (`DK_CA_BUNDLE`). Note
      `network_mode: host` is the wrong fix and was tried first: it makes
      each sample's inspect_swe model proxy collide on one port
      (Errno 98).
   3. **One prompt per sample.** `dk_watch` runs on Stop and writes its
      verdict for the NEXT `UserPromptSubmit`; recall is the only reader.
      A headless single-prompt session has no next prompt, so the monitor
      cannot deliver however well it is configured. `attempts` raised
      from 1 to 6.

   With all three fixed, a 2-sample run on 2026-08-29 produced **5 live
   monitor blocks** alongside 2 static notes - the first time the shipped
   model-based monitor has run inside a real Claude Code session in this
   harness, and the point at which EVALS.md rule 1 is actually met. The
   selections themselves were poor (a "skims instead of reading" rule on a
   coding task, and rule-only blocks carrying no directive), which is a
   separate problem from the plumbing.

   The maths and coding harnesses are unaffected -
   there `dk_watch` runs in the eval process on the host, with 369/517/494
   monitor calls recorded and every payload logged per sample
   (`dk_fired`, `dk_payload_log`).

   **The general lesson, which is about dk-mode and not about the eval:**
   in any single-turn headless session (`claude -p`), only the static note
   and the tripwire can ever speak. The model-based monitor needs a
   multi-turn conversation by construction.
4. **Sonnet via OpenRouter was never compared** against the default models.
5. **Consolidation stalled at 30 of 117 entries** on an early, noisy log. The
   log needs to be cleared and re-mined with the current filters.
