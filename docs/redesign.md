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

## The v2 architecture

1. **Deterministic triggers (Tier A), running on every event.**
   Extend dk_tripwire with: identical tool+args counters (3 -> nudge,
   5 -> escalate; cycle lengths 1-5 to catch ping-pong), error streaks
   (3), no-state-change windows (no file mtime delta / driver score flat
   across N attempts), and cross-window repetition read from the brief's
   attempt ledger. Thresholds are the field's convergent numbers.

2. **The brief becomes a structured attempt ledger (Tier B).**
   Keep dk_watch's per-stop brief, but make it machine-readable:
   ATTEMPTS (edit-target x count), test-status timeline, turn of last
   state change. Written by the model as today; READ by Tier A. This is
   the novel bit the research says nobody has shipped.

3. **The model composes, never judges (Tier C).**
   When Tier A fires, the LLM writes the alert and must include external
   facts: the exact repeated hunk, the unchanged failing assertion, the
   count of identical attempts. Naming the failing check recovered 45%
   vs 16% for a blind kick (2608.02464). Free-form model judgment of
   "is the agent stuck" is retired; if ever reinstated, Gemini CLI's
   budgeting applies (sparse cadence, high confidence, double-check).

4. **Escalation ladder, biased toward truncation over advice.**
   Injected note -> suggest rollback/re-read -> Stop-block only on
   repeated confirmation. For wedges prefer resample/rollback: advice
   appended to a poisoned context reinforces anchoring (2607.26117);
   rollback-and-retry lifted recovery 52%->73% (2608.02464).

5. **Prevention beats monitoring where possible.**
   Our edit-precision wall (25-30% of samples in every arm) is a
   feedback-quality problem: SWE-agent's linter-in-the-edit-command was
   worth +3 SWE-bench points by making the loop unenterable
   (2405.15793). Out of dk-mode's scope but the single best-evidenced
   fix for the failure class that dominated our traces.

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

No judgment-based prompt clears 50%. The deterministic-trigger variant
(Tier A reading the ledger) is the next thing on the bench.
