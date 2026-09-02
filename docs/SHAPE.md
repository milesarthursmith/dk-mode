# THE SHAPE — decided 2026-09-01, non-negotiable

dk-mode is an LLM watching the session evolve: consciously summarising,
detecting patterns through judgement, literally as a human overseer
would. This is the product. Everything else in the repo serves it.

The plain version (Miles, 2026-09-01): "can I replace myself with
another LLM?" The human overseer's job during a long agent session is
mostly watching, remembering what was already tried, and occasionally
saying "you did that already" or "that's not what I asked for". The
product is that job, done by a model, so the human's input becomes
trivial. Every eval question reduces to: does the watcher do what the
absent human would have done, and does the session end better for it.

## Spend discipline (added after burning ~$40 on end-to-end runs)

Not sure we won't burn more. The literature says this shape is hard,
and three instruments measured nothing for the previous design. What is
different now is the order of operations, and each stage has a kill
criterion:

  1. Replay bench (cents): the watcher must beat the arc-patch prompt
     on wedge recall with a McNemar margin AND hold false fires on hard
     negatives. If it cannot detect wedges from frozen transcripts, no
     end-to-end run happens.
  2. Branched forks (~$5): 20 wedge moments, watcher-on vs watcher-off
     continuations. If speaking does not raise recovery over silence,
     stop; the bench is then also calibrated either way.
  3. One paired A/B (~$10-25): only the build that survived 1 and 2,
     on a task family with a 30-50% baseline, pass^k endpoint,
     sequential stopping. If it does not separate, that is the answer.

No further marathon-style runs of unvalidated builds. No arm launched
that cannot finish on the current balance.

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
