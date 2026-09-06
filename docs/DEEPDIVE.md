# dk-mode: whole-system deep dive (2026-09-06)

Four readers each took one layer of the repo and read it in full: the
shipped plugin, the watcher prototype and replay bench, the evaluation
programme, and the documentation. Their reports are in docs/deepdive/.
This document is the synthesis, plus the checks I ran myself on the
claims that matter most. Every number below is either reproduced here
or cited to a report section.

Words used. The **watcher** is the LLM overseer that reads a coding
agent's session and speaks when it goes off track. A **wedge** is a
stretch where the agent stays busy but stops making progress. A
**moment** is a frozen transcript prefix the bench replays. A **sense**
is a mechanical signal (a repeat count) shown to the watcher as text.
The **counter** is the free rule-only baseline the watcher must beat.

## Verdict in one paragraph

dk-mode is three systems that do not agree with each other. What ships
(hooks/hooks.json) is the 2026-08-27 design: a per-stop rule selector, a
static note pasted into every prompt, and a three-strikes tripwire.
docs/SHAPE.md declares two of those three dead. The product SHAPE
describes, the stateful watcher, exists only as a bench prototype with
zero tests, no hook, and four production-breaking gaps. The evidence
for that prototype is one replay bench whose labels were rule-derived
until yesterday, whose readers could see the old labels in the
filenames, and whose "fired or not" metric flattered the watcher by
about two to one against a reading of what it actually said. The
documentation describes the dead design as current, never mentions the
product, and carries at least twelve decisions recorded as final that
were later reversed without annotation. Nothing in the repo has ever
measured whether any intervention changed what an agent did next.

## The system in one picture

    ships today            product per SHAPE          measures it              documents it
    ------------           -----------------          -----------              ------------
    dk_recall.sh           watcher_session.py         replay_bench.py          README, MECHANISM  (08-27 design)
    dk_watch.py (dead)     (unwired, untested)        score_judgment.py        SHAPE, CLAUDE.md   (09-01 design)
    dk_tripwire.py (guard) senses/notes/lookup        labels/judgment.jsonl    HANDOVER, redesign (stale)
    dk_consolidate.py                                 labels/alert_quality     log.md (append-only, unannotated)

## Findings by layer

### 1. The shipped plugin (docs/deepdive/plugin.md)

- **It is the rejected design, component for component.** The Stop
  hook launches dk_watch.py, the stateless per-stop judge SHAPE calls
  dead. The PostToolUse hook is dk_tripwire.py, a counter that injects
  text when the same call repeats three times: the guard SHAPE says was
  "not built". It is built, wired, and has seven green tests.
- **The tripwire's counts never reach any watcher.** dk_capture.sh
  deletes the tripwire state file before launching the monitor. The one
  legitimate use of those counts under SHAPE (as a sense) is closed by
  ordering.
- **Silence is overridden by a schedule.** Since 08-31 an empty verdict
  falls through to the static note on every prompt. SHAPE rejects
  scheduled fixed text as the product mechanism. Test 55 now asserts it.
- **The third tripwire cannot fire.** It reads a payload key named
  `tool_output`; Claude Code sends `tool_response` (confirmed against the
  installed binary). The tests pass because the fixtures use the wrong
  key too. README advertises three tripwires; two exist.
- **Concrete bugs found by reading:** tripwire state has no lock and
  loses updates under parallel tool calls; a malformed model reply
  leaves the previous verdict injected for up to an hour as "relevant
  right now"; deleting dk_rules.md (the documented off switch) does not
  stop model calls or alert injection; consolidation fails permanently
  once the rules file outgrows the 8000-token reply budget; the
  /dk-review skill hardcodes a path that only exists for install.sh
  installs; the window sent to the provider, the brief, and the alert
  are never redacted, only the mined file is; README tells users to put
  the key in settings.json, which this repo's own gitignore un-ignores.
- **Cost is about double the README's figure**: roughly 6 to 9 thousand
  input tokens per turn, $24 to $36 a month at 100 turns a day on Haiku.

### 2. The watcher prototype and the bench (docs/deepdive/watcher_bench.md)

- **The watcher has never seen a tool call.** Its transcript reader
  keeps text blocks only. On the bench that was hidden because the
  corpus was pre-rendered to text. On a real Claude Code transcript it
  would see narration and never a command, an output, or an error.
- **It has not read the task on about half the corpus.** Messages are
  head-cut at 1200 characters. Every own-corpus moment opens with about
  7 KB of system reminders before the task text, so the goal it holds
  in its notes is inferred from narration.
- **The senses are the counter's rule, re-presented as text.** Same
  120-character key, same whitespace collapse, same threshold of three.
  The watcher does overrule them in both directions (23 correct fires
  with no sense, 10 correct silences with one), so they inform rather
  than decide. They inform heavily.
- **Session id mismatch.** The watcher reads DK_SESSION; the capture
  hook exports DK_SESSION_ID. Wired as-is, the watcher would write a
  verdict file the recall hook never reads. Verified by grep.
- **Silent failures.** A reply with no JSON braces is recorded as a
  deliberate silence and the position marker still advances. A failed
  look leaves the previous verdict in place, which the bench then reads
  as this look's verdict.
- **Bench scoring:** "fired" means fired at the final look only. A
  watcher that spoke correctly at look three and fell quiet counts as a
  miss. The `still failing` chunk cut matches agent narration, so look
  cadence on the own corpus is irregular. The default `report` command
  still scores by filename prefix.
- **Lookup has never been run.** The bench never sets the search key.
  The watcher+lookup variant SHAPE names as a bench variable has no
  rows.

### 3. The evaluation programme (docs/deepdive/evals.md)

- **Thirty-one instrument runs, none of which measured the product.**
  Every hooked end-to-end run (LiveCodeBench, two SWE runs, the goal
  marathon) used a gitignored plugin snapshot with no versioned build
  hash, later found stale. The maths band had no arc. ImpossibleBench
  had an effective n of three. The marathon is n=2 with within-arm
  spread of 0.6.
- **The prompt that made the monitor blind was chosen by fire rate.**
  tune_selectivity.py picked the variant that fired least on replayed
  traces, never against an outcome. That variant shipped and was later
  confirmed as the flaw.
- **Label problems that survive the judgment relabel:** the readers were
  handed file paths containing `wedge_` and `healthy_`, so 70 percent
  agreement with the old labels is an upper bound on independence;
  extract_tb.py prioritised passing trials when picking healthy
  candidates; a label rule was edited on 09-05 in the watcher's favour
  hours before rule one was written; the bench excludes errors under 3
  seconds while CLAUDE.md says 5.
- **Pseudo-replication.** Seven own-corpus wedge moments are growing
  prefixes of one session. I re-ran the paired test collapsing moments
  to one vote per session family: 30 families, watcher wins 11, counter
  wins 1, p=0.006. The own-corpus result survives; the frontier-corpus
  result (p=0.19) was never significant.
- **The repo holds both positions on reasoning.** CLAUDE.md rule 3 says
  a judge without reasoning is not a judge. The 09-05 log says
  reasoning-on was worse (paired p=0.029, one run). Fixed below.

### 4. Documentation and tests (docs/deepdive/docs.md, docs/TESTS.md)

- **README and MECHANISM describe the dead design as current** and do
  not link SHAPE. A newcomer would build the 08-27 product, tune two
  settings that no longer govern the live window, and expect an
  injection format the code cannot produce.
- **Twelve decisions recorded as final and reversed without annotation**,
  including "no hand labels anywhere" (EVALS.md, reversed 09-05), "the
  trigger should be a deterministic counter" (log 09-01 afternoon,
  reversed by SHAPE the same day), "guard: not built" (SHAPE, false
  since 08-27), and HANDOVER.md's "read this first" with a $0.66
  balance and 59 moments.
- **Vocabulary:** the same model call is the relevance model, the
  miner, the per-turn model, the monitor, the runtime monitor, the
  critic, and the watcher, depending on the file. "Watcher" in the test
  suite means dk_watch.py; everywhere else it means watcher_session.py.
  "Tripwire" names two unrelated mechanisms. "Rules" are the product in
  README and the forbidden thing in CLAUDE.md.
- **The test suite** was red for six days, certifies the rejected
  design, has zero tests for the product, and cannot see judgment.

## What I checked myself

| claim | check | result |
|---|---|---|
| shipped monitor is worse than the counter | scored its 15 judgment-labelled bench rows | fires on 4 of 12 speak-moments; counter and watcher 12 of 12 |
| own-corpus result is pseudo-replication | collapsed to one vote per session family | 11 vs 1, p=0.006, survives |
| readers saw old labels | opened labels/shard0.txt | paths contain wedge_/healthy_ |
| tripwire reads the wrong key | grep tripwire and the installed binary | tripwire reads tool_output; binary uses tool_response |
| watcher/recall session mismatch | grep DK_SESSION | capture exports DK_SESSION_ID, watcher reads DK_SESSION |
| reasoning-on truncation | direct call, one wedge moment | finish=stop, 766 reasoning tokens, full JSON: the recall drop is real |

## What is actually established

Stated as a referee would.

1. On frozen transcripts of small agents looping on one edit, a
   gemini-2.5-flash stateful watcher fires on more reader-marked
   speak-moments than a three-repeat counter (25 of 38 vs 15 of 38,
   p=0.006, survives session collapse). Same false-fire rate.
2. On frozen transcripts of frontier agents, it does not separate from
   the counter (23 of 40 vs 16 of 40, p=0.19).
3. Of its 48 fires on speak-moments, a second reader judged 24 to name
   the same problem a human would, 20 to miss the cause one level down,
   4 to be wrong. All 24 are the single-recurring-error shape. Zero of
   70 alerts questioned task compliance or noticed abandoned correct
   work.
4. Turning reasoning on made the same watcher quieter, not sharper (one
   run).
5. No measurement anywhere in the repo shows any intervention changing
   what an agent did next, or a session ending better. That is the
   product question and it is untouched.
6. Every label rests on one LLM reader per moment who could see the old
   label in the filename. No human has read a moment.

## What to do, ranked

1. **Free, first: Miles reads a sample.** Twenty of the 22 disputed
   fires and the 30 missed speak-moments. evals/bench/review_stage1.md
   is already formatted for it. Until a human has read a moment, every
   number above is one model agreeing with another.
2. **Fix what the watcher reads before touching what it thinks.** Render
   tool calls and results into its input; put the task statement, in
   full, into every look; stop head-cutting at 1200 characters. The 20
   partial alerts are almost all facts that were in a tool output the
   watcher never saw. This is the change most likely to move both the
   frontier-corpus recall and the alert quality, and it costs nothing
   to build.
3. **Change the standard for speaking in the prompt.** Say the fact the
   agent has not seen or the claim the record contradicts. Never a
   restatement of the last output, never a question, never
   encouragement. Mark observed versus guessed. All four wrong alerts
   were guesses stated as facts.
4. **Fix the bench so it measures what a human would count:** a fire at
   any look counts; a failed look writes an empty verdict; parse
   failures are errors; pair on sessions; retire the prefix-scoring
   `report` command; drop the `still failing` cut. Then re-run the
   plain watcher and the reading of its alerts. Single-digit dollars.
5. **The reaction check, about $10 to $15.** Ten own-corpus moments
   where the alert was judged "same". Rebuild the container state by
   replaying the tool calls, continue three ways for 15 to 20 turns:
   the watcher's alert, the counter's templated alert, nothing. Judge
   by reading whether the agent changed approach. This is the cheapest
   experiment that can kill the product. It cannot confirm it.
6. **Only then, a stronger watcher model** on the 104 frontier moments.
7. **Ship or unship.** Either wire the watcher into the Stop hook with
   the four production gaps closed and plumbing tests written, or
   remove the two rejected components from hooks.json and say in the
   README what remains. Shipping the dead design under the new spec is
   the worst of both.
8. **One current-state document** (docs/STATUS.md) that is rewritten,
   not appended: what ships, what the product is, one vocabulary table,
   a decision ledger with standing/reversed/voided, every mechanical
   number that still decides something with its status. README and
   MECHANISM get a one-line banner pointing at it.

## Contradictions fixed in this commit

- CLAUDE.md rule 3 said reasoning must be on. The evidence says
  reasoning-on was worse in one run and the reason is not understood.
  The line now says that, and calls it open.
