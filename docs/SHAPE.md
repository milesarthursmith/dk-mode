# THE SHAPE — decided 2026-09-01, non-negotiable

dk-mode is an LLM watching the session evolve: consciously summarising,
detecting patterns through judgement, literally as a human overseer
would. This is the product. Everything else in the repo serves it.

## What this means, concretely

1. **The watcher is stateful.** One continuous monitor conversation per
   agent session. At each stop it receives the delta since its last
   look, updates its own running notes in its own context, and decides
   whether to speak. It is never a fresh judge shown a snapshot.

2. **Judgement decides. Nothing mechanical gates the watcher.**
   Deterministic signals (repeat counts, error streaks, score
   plateaus) are SENSES: they annotate the delta the watcher reads.
   They never decide whether the watcher runs or whether it speaks.
   The watcher may overrule them in either direction.

3. **The watcher tracks expectations and credibility.** When the agent
   claims "this will fix X", the watcher records the prediction and
   checks it at the next look. Narration that keeps breaking its
   promises loses the watcher's trust - by judgement, the way a human
   stops believing "almost done" the third time they hear it.

4. **The watcher's notes are its memory.** It self-compacts: notes and
   expectations carry the arc; old raw exchanges can be dropped from
   its context once distilled. Seeing the whole session does not mean
   storing the whole session.

## What is rejected

- Counter-gated architectures (rules decide WHEN, model only writes
  the message). Retired as a product candidate. It may appear in
  benches strictly as a baseline row to beat.
- Stateless per-stop judging (the dk_watch v1/v2 design). The eval
  programme (docs/log.md, 2026-08-30..09-01) established that a fresh
  judge with a silence-biased prior misses multi-turn wedges that are
  obvious in aggregate; that design is dead.
- Scheduled fixed-text injection as the product mechanism. It remains
  the control arm in evals, never the product.

## What the benches are for now

The shape is decided; benches optimise WITHIN it - cadence, watcher
model, note format, when-to-speak calibration, context-compaction
policy - and verify each iteration still clears the baselines
(scheduled text, counter-gated) it must dominate to justify its cost.

Prototype: evals/bench/watcher_session.py (same CLI and handoff
contract as dk_watch, so dk_recall/dk_capture work unchanged).
Migration into scripts/ follows the first bench + branched-fork
validation of a watcher build.
