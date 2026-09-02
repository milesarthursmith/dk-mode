# Handover — state as of 2026-09-01

Read this first, then docs/SHAPE.md. Everything else is history.

## The product, in one line
"Can I replace myself with another LLM?" A stateful LLM watcher observes
a Claude Code session, keeps notes and expectations, and speaks up the
way a human overseer would. Decided, non-negotiable: docs/SHAPE.md.

## What exists
- Prototype watcher: evals/bench/watcher_session.py (same CLI/handoff
  contract as scripts/dk_watch.py; optional Exa-grounded interventions,
  key-gated). Smoke-tested once. Never benched.
- Replay bench: evals/bench/replay_bench.py. Modes: extract (goal logs),
  extract-swe (process-labeled SWE moments), run (stateless variants),
  run-seq (stateful watchers), report (Wilson CIs + paired McNemar).
  Corpus: evals/bench/moments/ = 59 moments (43 wedge, 16 healthy) - but
  41/43 wedges are one mechanical failure (Edit old_string loops from
  small Gemini agents). A semantic-wedge corpus from frontier-agent
  Terminal-Bench trajectories is being mined into evals/bench/moments_tb/
  by evals/bench/extract_tb.py (review before merging).
- Instruments: evals/swe (SWE-bench easy slice, relay topology),
  evals/goal (jinja 20-bug marathon), evals/terminalbench/SCOPING.md
  (feasible via harbor --ak config; $18-22/trial Opus-class - do not run
  unvalidated builds there).
- Shipped plugin fixes this session: recall no longer muted by empty
  verdicts; watch parser tolerates string ids / raw newlines; eval
  plugin snapshot synced to scripts/ (it had been stale for every
  published arm).

## What the evidence says (docs/log.md has the numbers)
Four instruments: the stateless per-stop monitor never beat a scheduled
fixed text. Traces: monitor accurate and obeyed but futile; dominant
failure mechanical (edit precision); stalls prevented by cadence,
only repaired by the monitor; watcher silent through a six-attempt
wedge because the prompt forbade arc evidence. Research (three passes,
docs/redesign.md): literature predicts that null; production harnesses
use counters; nobody has an intervention policy reading a compacted
session log - that niche is ours.

## Spend discipline (SHAPE.md)
Stage 1 bench (cents) -> stage 2 branched forks (~$5) -> stage 3 one
paired A/B (goal-mode ~$10-25; Terminal-Bench $1-4k). Kill criterion at
each stage. Total spent so far ~$40. Balance $0.66.

## Open threads
- Corpus miner running (background agent). Deliverable: moments_tb/ +
  extract_tb.py + report. Merge after reading a sample of moments.
- Waiting on user: OpenRouter top-up (~$1.50 stage 1 / ~$10 through
  stage 2); EXA_API_KEY if the grounded watcher is to be benched.
- Next runs, in order: run-seq watcher vs arc-patch vs a counter-gated
  baseline on the merged corpus; if the watcher wins with a McNemar
  margin, branched forks on 20 wedge moments; only then a Tier-3 run.

## Known weaknesses of the method
Bench measures detection, not value (needs one fork-calibration pass);
labels are heuristic (read a sample); corpus was single-task until the
TB mining lands; results at n=10 wedges are not statistically resolved.
