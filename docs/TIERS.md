# The tiers are broken — a challenge to the eval funnel (2026-09-06)

The eval funnel (docs/redesign.md "The eval funnel"; docs/SHAPE.md "Spend
discipline") is four tiers in sequence: tier 0 free trace checks, tier 1
replay bench, tier 2 branched forks, tier 3 one paired A/B. Each tier is a
gate the watcher must pass before money goes to the next. On 2026-09-05
the watcher "passed" tier 1. Before advancing, this document challenges
each tier against what is actually in the repo. Conclusion first: tier 0
violates rule one, tier 1's pass is corpus-dependent and measures the
wrong thing, tier 2 cannot be run on most of the corpus and has no power
where it can, and tier 3 is either unaffordable or the instrument that
already measured nothing four times. The funnel as written cannot answer
the product question. What can is at the end.

## Tier 0: "deterministic trace checks ... doubles as label QA"

Broken by principle, and the damage is measured. Tier 0 is a rule
deciding whether a session was on track. That is exactly what CLAUDE.md
rule one forbids, and the wedge_/healthy_ prefixes that tier 0's logic
produced were wrong on 48 of 160 moments when readers judged the
transcripts (docs/log.md 2026-09-05). Thirty-one "wedge" files were
advancing; seventeen "healthy" files included the worst wedge in the
corpus. A tier whose job is label QA and whose output needed a judgment
pass to correct is not QA. Deterministic checks stay as senses that a
reader or the watcher can see. They never label.

## Tier 1: the replay bench "passed", but look at what passed

The bench replays watcher variants over frozen transcript prefixes
(moments) and scores whether they fired. Against judgment labels the
watcher fires on 48 of 78 speak-moments versus 31 for the free counter,
paired p=0.005. Three problems.

1. The pass is carried by the easy corpus. Split by where the moments
   came from:

       corpus                       speak n   watcher   counter   only-w/only-c   p
       own (gemini/haiku, jinja+SWE)   38        25        15        11 / 1      0.006
       tb2 (frontier agents)           40        23        16        14 / 7      0.19

   On small agents looping on the same edit, the watcher wins clearly.
   On frontier agents in Terminal-Bench 2, which is the product's real
   habitat, it catches 23 of 40 and the counter 16 of 40, and the paired
   test does not separate them. The kill criterion in SHAPE.md says
   "McNemar margin"; on the corpus that matters, there is not one yet.

2. The criterion drifted. SHAPE.md stage 1 names the arc-patch prompt as
   the bar. Arc-patch was run on 18 moments and never on the full
   corpus; the bar silently became the counter. Whether the watcher
   beats the best stateless prompt on 160 moments is unmeasured.

3. Detection is not the job. The bench scores "fired or not". The
   product question is whether what the watcher said is what the absent
   human would have said, and whether the agent would act on it. The
   redesign note admits replay "cannot value" alert quality, then makes
   tier 1 the gate anyway. It can value it, by judgment: every fire has
   its alert text, and every speak-moment has a reader's would_say.
   Comparing them is a reading task, not a rule. That comparison is
   running now (labels/alert_quality.jsonl) and its result is in the
   section below.

4. One reader per moment. Agreement between readers is unmeasured, so
   the 78/82 split has an unknown error bar of its own. The 22 fires on
   silent-moments are being second-read for the same reason.

## Tier 2: branched forks cannot be run on this corpus

Tier 2 is: freeze the environment at a speak-moment, continue twice with
the watcher on and off, measure recovery. Nothing for this exists in the
repo (grep for fork in evals/ returns only the plan). And it cannot be
built for the corpus that matters:

- 104 of the 160 moments are Terminal-Bench 2 trajectories from other
  people's agents (GLM 4.7, Opus 4.6, Opus 4.7 under the terminus, vix
  and wozcode harnesses), mined from the public leaderboard. There is no
  container state to freeze and no agent to continue. A fork would mean
  handing a different model a transcript it did not write and asking it
  to carry on. That is not a continuation; it is a new session with a
  long prompt.
- The 56 own moments come from inspect-ai docker runs (jinja goal mode,
  SWE-bench). Their state at the moment is 100+ turns of edits that
  would have to be replayed tool call by tool call (the Replay Gap
  protocol the plan cites). Buildable, not built, and it only covers the
  corpus where the watcher already wins on detection.
- Power. The plan says 20 moments. With 20 pairs the paired test needs
  roughly six discordant pairs all in one direction before it says
  anything. The Intervention Paradox result the redesign cites (a critic
  with near-perfect detection moved outcomes between -26 and +3 points)
  says the effect can be negative and small. Twenty forks cannot see a
  small effect in either direction, and the same-arm control forks the
  plan adds to set the noise floor halve the budget again.

Tier 2 as designed answers nothing on frontier agents and is underpowered
on small ones.

## Tier 3: the paired A/B is unaffordable where it means something

- Terminal-Bench 4.0 with a Sonnet-class agent is ~$1-1.5k, Opus-class
  ~$3.6k (evals/terminalbench/SCOPING.md). Balance is about $28.
- The affordable instrument, the goal-mode marathon ($10-25), is the
  one that measured nothing four times (docs/log.md 2026-08-29..31).
  Those runs used the retired stateless design, so the null does not
  transfer, but the instrument's sensitivity does: three epochs of one
  task with a continuous score separated bare from dk from challenge by
  noise. A pass^k endpoint on a flaky subset needs many more epochs than
  three, and the money is not there.

## What is actually broken, in one sentence each

- Tier 0 is a rule labelling sessions. Rule one says never.
- Tier 1 passed on the corpus that does not matter and measures a proxy.
- Tier 2 cannot be run on the corpus that matters and has no power on
  the one where it can.
- Tier 3 costs 40 to 130 times the balance where it is informative.

The funnel is also a gate chain: each tier is a mechanical rule deciding
what to do next. The decision to spend should be made by reading the
evidence, not by clearing thresholds. That is rule one applied to the
programme itself.

## What can answer the product question with what exists

The product question (SHAPE.md): does the watcher do what the absent
human would have done, and does the session end better for it. The
second half needs money the project does not have. The first half is a
reading task and the material is already on disk.

1. Alert quality by judgment (running). For every watcher fire on a
   speak-moment, a reader compares the alert with the reader's own
   would_say. "Same problem named" is the bar. This replaces "fired or
   not" as the tier 1 metric.
2. Second reads on every disagreement. The 22 watcher fires on
   silent-moments and the 30 speak-moments the watcher missed get a
   second reader. Agreement between readers becomes a measured number,
   and the label set stops being one opinion.
3. Frontier corpus only. Stage-1 pass or fail is decided on the 104
   Terminal-Bench moments. The small-agent corpus is a sanity check,
   not the bar.
4. Model knob before anything else. Every row so far is gemini-2.5-
   flash. One sweep of a stronger watcher model over the 104 frontier
   moments costs single-digit dollars and is the only untested variable
   that could move the p=0.19.
5. Tier 2 replaced by a reaction check that is buildable: for own-corpus
   moments, replay the environment (the Replay Gap protocol), inject the
   alert, and read what the agent does in the next three turns. Judged
   by reading, scored as "changed approach / ignored / made it worse".
   Not a recovery rate; a check that alerts are acted on at all. Ten
   moments is enough to learn whether the mechanism works.
6. Tier 3 waits for money or a sponsor. Say so rather than running a
   marathon that cannot separate.

## Alert quality result

A second reader compared every watcher alert with what the first reader
said should be said, opening the transcript where needed
(labels/alert_quality.jsonl, one verdict and reason per item).

Of the 48 fires on speak-moments:

    same problem named       24    the alert is a fair substitute for a human's
    partial                  20    right area, misses the fact one level down
    wrong                     4    asserts a diagnosis that inverts the truth
    different but valid       0

Of the 22 fires on silent-moments (second read of the transcript):

    first reader right       14    false alarm
    watcher right             2    the first reader excused a real loop
    unclear                   6

What this says, and what "fired or not" could never say:

- The watcher is a fair human substitute on one shape of wedge only: a
  single recurring tool error (the same make error, the same edit
  failing on the same string, seven rewrites of one file). All 24
  "same" verdicts are of that kind.
- It seldom sees the cause behind the repetition. The 20 partials are
  where the reader named the fact one level deeper: a tab in the
  string being matched, an edit that renames nothing, a blank image
  behind the empty OCR, a rendered scene behind the curve-fitting. The
  watcher's advice in those cases ("re-read the file and copy exactly",
  "get tesseract to produce output") keeps the agent inside the loop.
- When it speculates it can invert the truth. All four "wrong" alerts
  assert a diagnosis (environment problem, harness misbehaving) rather
  than naming the loop.
- Most false alarms are restatements of the last tool output or the
  agent's own stated next step. It also fires on prompt-induced verbal
  tics ("I have not verified") as if they were unproven claims.
- It never widened the frame. No alert questioned task compliance (a
  test file edited, an interpreter file edited against the task's
  rule) or noticed that a session had produced a correct artifact and
  then abandoned it. That is where a human overseer's value is highest
  and the watcher contributed nothing.

So the honest tier-1 number is not 48 of 78. It is 24 of 78 alerts that
a human would have been content to have sent, and 0 of 78 that did the
overseer's highest-value job. The counter baseline, by construction,
names the repetition and nothing else; on the 24 it is roughly the
watcher's equal, and on the 20 partials the watcher's extra words did
not help. Detection rate flattered the watcher. The gap to the human is
in what it says, and the bench as designed could not see it.

Second-reader agreement, first measurement: on the 22 disagreements
between watcher and first reader, the second reader sided with the
first on 14, the watcher on 2, and could not decide on 6. That is the
error bar the label set has been missing.
