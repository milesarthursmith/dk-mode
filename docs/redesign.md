# dk-mode v2: evidence-backed redesign

Synthesis of the full eval programme (docs/log.md, 2026-08-30..09-01) and
three deep-research passes (production harness practice, monitoring/
self-correction literature, cheap eval methodology). Every design choice
below cites either our own measurements or primary sources gathered
2026-09-01.

## What the evidence established

**Our four-instrument null was predictable.** Placebo-controlled studies
(arXiv:2607.26117, 2607.12962) show injected feedback works by
*perturbing* the generation state, not informing it - templated text ties
model-written text. Intervention timing has near-zero human
inter-annotator reliability (Saturation Trap, 2606.04296) and a critic
with AUROC 0.94 at predicting failure still moved outcomes -26..+2.8pp
when allowed to act (Intervention Paradox, 2602.03338). A monitor cannot
beat a schedule at a job with no stable ground truth.

**The wedge phenomenon has a name.** "False success": 75.8% of failing
self-assessing coding-agent trajectories carry confident success claims,
and LLM judges are fooled by exactly that language (2606.09863). Stateful
detectors beat per-frame judges by margins that GROW with failure
duration (2608.02464). Our monitor's per-frame judgment reading "I'll fix
it now" every turn is the textbook victim.

**The field's revealed preference is deterministic.** OpenHands (4
identical action+observation pairs / 3 errors / 6-event ping-pong),
opencode (3 identical calls nudge, 5 escalate), Aider (3 reflections),
SWE-agent (3 requeries, $3 budget), Cursor (25-call checkpoint). Exactly
one production harness runs an LLM loop-judge - Gemini CLI - and it
gates it to every 5-15 turns after turn 30, bounded window, 0.9
confidence, double-confirmed by a second model, and still fills an issue
tracker with false positives. The published positive result for our
shape of system is LivePlan (2608.06701): deterministic rules judge,
LLM only composes the advice; +9.9pp on SWE-bench, ~$0.08/instance.

**One genuinely open niche.** No shipped harness or paper has the
intervention policy read a continuously compacted state log. Detectors
read raw recent events (and opencode has a filed bug: cross-window
repetition evades them). dk-mode's brief is exactly the artifact that
fixes that - it just was never wired to the trigger.

## The v2 architecture — superseded, see docs/SHAPE.md

The architecture originally drafted here (deterministic triggers gating
a model that only composes messages) is RETIRED as a product direction.
The decided shape (docs/SHAPE.md, 2026-09-01, non-negotiable) is a
stateful LLM watcher: one continuous monitor conversation per session,
judgement deciding when to speak, deterministic signals demoted to
annotations on the evidence the watcher reads, expectation/credibility
tracking against the agent's own claims. The counter-gated design
survives only as a bench baseline the watcher must beat.

What carries over unchanged from the evidence: alerts must contain
external facts (the exact repeated hunk, the unchanged failing
assertion, attempt counts - 45% vs 16% recovery, arXiv:2608.02464);
prevention beats monitoring for edit-precision loops (linter-in-edit,
+3 SWE-bench pts, arXiv:2405.15793); and per-frame stateless judging is
dead for the reasons docs/log.md documents.

## The eval funnel (replaces one-shot A/Bs)

- Tier 0 (free): deterministic trace checks over every recorded session;
  doubles as label QA.
- Tier 1 (~$0.005/call): replay bench (evals/bench) - detection metrics
  only (recall at a fixed fire budget, FP on HARD negatives, onset lead
  time), paired per-moment. Fix from research: label moments by process,
  not outcome (lucky passes contaminate "healthy"); add OOD moments from
  public trajectory sets (nebius/SWE-agent-trajectories, TRAIL).
- Tier 2 (~$0.10-0.50/branch): checkpoint-and-branch at labeled wedge
  moments - monitor-on vs monitor-off continuations from the same frozen
  state, plus same-arm control forks as the noise floor (Replay Gap
  protocol, 2608.08239: action-log re-execution, 99.99% fidelity, no
  CRIU needed). This tier measures the reaction effect replay cannot.
- Tier 3 ($2-10/session): ONE paired A/B for the surviving challenger.
  Endpoint: pass^k / flake-rate on the flaky-instance subset (a monitor
  is a reliability intervention; mean resolve rate is the least
  sensitive endpoint). Paired differences, clustered SEs (2411.00640),
  sequential stopping so duds exit early.

## Bench results to date (Tier 1, 18 moments from the marathon logs)

    variant     wedge recall   healthy FP
    arc-patch       5/10          0/8     <- prompt permitting arc evidence
    stale           4/10          2/8     <- what all published arms ran
    current         2/10          3/8     <- what ships today

No stateless prompt clears 50%. Next on the bench: the stateful
watcher (docs/SHAPE.md; prototype evals/bench/watcher_session.py) via
sequential replay, against these rows and a counter-gated baseline.
