# Development log

Reverse chronological. Decisions, measurements, and the things that are still
unproven. The README describes what dk-mode does; this file records how it got
there and what was actually tested.

---

## 2026-08-27 — four evals, and the one idea worth keeping

### Periodic challenge (NOT BUILT — written down only)

The owner's point, and it is simpler than what was being designed: dk-mode
already has an injection channel, and the `/challenge` skill already works.
So a periodic challenge needs no new critic, no new prompt, and no second
model call. Every N turns the hook injects text that invokes the existing
challenge. That is the whole feature.

What was being designed instead — a separate challenge prompt, a wider
transcript window, its own evidence rules — was a rebuild of a skill that is
already in the repo next door and already does the job.

Why it is worth keeping: every failure the evals found below is a SELECTION
failure. It picked nothing on two of five baits, and on one case it picked
the opposite rule. A periodic challenge has no selection step. It fires on a
schedule.

It also matches what the replay of a real 40-turn conversation found. The
three most frequent flags were "claims something is done without checking"
(16), "invents a detail that sounds right" (10), and "buries the bad news"
(9). None of those are rule-matching problems.

Open question, not yet answered: whether the injected challenge should be
run by the working model in-context (cheap, but it is then marking its own
homework) or handed to the out-of-band monitor that already reads the
transcript. The second can check a claim against what the transcript shows;
the first cannot.

### Four evals, all against a real model

| eval | result |
|---|---|
| short constraints (6 cases) | no difference. 3 of 6 broken by both arms |
| watched failures (4 cases) | LOST. base broke 2, generic reminder broke 1, dk-mode broke 2 |
| 200 rules at scale (5 baits) | draw on outcome, 25x cheaper than echoing everything |
| long multi-step (3 tasks, 30 steps) | no difference. 1 of 3 broken by both arms |

The watched result is the one that matters most, because those four cases
were built so nothing in the conversation could be echoed back — the cases
dk-mode should win. A generic "be careful and check your work" beat it. On
`repeats-step` dk-mode selected "Stops before the task is finished" and told
an agent stuck in a loop not to stop early. The opposite advice.

The scale run produced the one row that supports the design: on `bait-deps`,
echoing all 200 instructions broke the rule and selecting the single relevant
one held it. Burying is real. But two of the five baits were broken by
nobody, so that run is n=3 and it is 1-1.

`bait-tests` is the other finding: dk-mode selected the RIGHT rule and the
agent broke it anyway. Selection is not the only weak link.

**What holds up after four evals:** the running brief (it still held the goal
and the constraint at the end of all three long tasks, including a 14-step
one) and the deterministic tripwire (which is not exercised by any of these
evals, because they feed text rather than tool calls). Neither needs a model
to choose anything.

**What does not:** rule mining and relevance selection, which is the part
that took the most effort.

### Eval bug found and fixed

The scale runner asked dk-mode to select from `dk_rules.md` (23 baseline
rules) and then measured whether the agent broke one of the 200 project
instructions. The right answer was never in the pool. Three of the five baits
also pointed at the wrong instruction. Both fixed in `787ec60`; the run now
reports selection accuracy separately from the outcome.

It also surfaced a structural limit: at 200 rules only `DK_MAX_RULES` (40)
reach the model, kept oldest-first. A rule mined today loses to one mined a
year ago. That is truncation happening before selection, not selection.

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

`bash tests/run_dk_tests.sh` — 85 tests, all passing. No key, no network.
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
