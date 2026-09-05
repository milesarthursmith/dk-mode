# dk-mode — rules for the assistant

## 1. MOST IMPORTANT: automatic rules do not work. Use judgment.

Miles has said this repeatedly, and the assistant has broken it repeatedly:
"the automatic rules don't work, how many times do i have to say this."

dk-mode exists because a heuristic (a counter, a score threshold, a
"commands varied" check, a filename prefix) cannot tell a wedge from
progress. THE SHAPE (docs/SHAPE.md) is: a stateful LLM watcher whose
JUDGMENT decides. Deterministic signals are senses. They inform. They
never decide.

This applies to EVERYTHING in the repo, not only the product:

- Never label a bench moment (wedge / healthy / speak / stay silent) by
  a rule. Read the transcript and decide as a human overseer would.
- Never build a ground-truth set, a filter, a gate, a "healthy = score
  went up" shortcut, or any mechanical proxy for "was the session on
  track". If you catch yourself writing `if pct > ...: label = ...`,
  stop. That is the mistake.
- The retired guard (evals/bench/baseline_counter.py) is a bench
  baseline to beat, never a labeler and never the product.
- When judgment is expensive, the answer is to spend on judgment
  (subagents, a reasoning model), not to substitute a heuristic.

Before any labeling, scoring, filtering, or gating change, re-read
this section and docs/SHAPE.md.

## 2. Communicate in plain technical English

Short sentences. Say what a thing is before using its name. Define
every project word the first time it appears in a message (wedge,
moment, sense, watcher). No jargon-only summaries. No numbers in prose
without saying what they mean. When Miles asks "what does this mean",
the answer is a plain explanation, not a restatement.

## 3. Project facts

- Product spec: docs/SHAPE.md (non-negotiable). Vocabulary: watcher,
  senses, notes/expectations, intervention, lookup, guard (retired).
- Experiment log: docs/log.md. Append; do not rewrite history.
- Watcher prototype: evals/bench/watcher_session.py. Judge/watcher
  runs must use reasoning on (DK_REASONING=high). A judge without
  reasoning is not a judge.
- Replay bench: evals/bench/replay_bench.py. Errors (sub-5s or failed
  HTTP calls) are excluded and retried, never counted as verdicts.
- Spend discipline and kill criteria: docs/SHAPE.md. Never launch a
  run that cannot finish on the current balance.
- Redact secrets before any commit. Develop only on the assigned
  branch.
