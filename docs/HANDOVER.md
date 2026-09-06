# Handover to a new session (2026-09-06)

This replaces the 2026-09-01 handover, which was stale. Read this file
first, then CLAUDE.md, then docs/SHAPE.md, then docs/DEEPDIVE.md. Do not
read docs/log.md end to end; it is 1400 lines of history and many of
its conclusions were later reversed.

## Kickoff message (paste this to start the new session)

    You are starting fresh on dk-mode. Read docs/HANDOVER.md first and
    follow it. Your one goal: make the watcher say what I would say,
    and prove it on ten stuck moments where the coding AI then changes
    course. Do not tune scores. Do not add rules or counters that
    decide anything. Read transcripts and use judgment. Talk to me in
    plain simple English. Tell me before spending more than $5.

## The goal, in one sentence

Make the watcher say what Miles would say to a stuck coding AI, and
show on ten stuck moments that the AI changes course after hearing it.

That is the whole goal. Detection rates, p-values, and benches are only
tools toward it. If a step does not move toward that sentence, skip it.

## What dk-mode is

A program that watches a coding AI while it works, the way a person
would. When the AI gets stuck or wanders off the task, the program says
so, in one or two sentences, with the concrete fact the AI has not
noticed. Miles's phrase: "can I replace myself with another LLM?"

Words you will see:
- **watcher**: the LLM that watches and decides whether to speak.
- **wedge**: a stretch where the AI stays busy but makes no progress.
- **moment**: a frozen transcript prefix used to test the watcher.
- **sense**: a mechanical hint (like "same message repeated 5 times")
  shown to the watcher as text. It informs. It never decides.
- **intervention**: what the watcher says when it speaks.

## The one rule that matters most

Automatic rules do not work. No counter, threshold, score curve, or
filename decides whether a session is stuck, whether to speak, or what
a label is. Judgment decides. This rule was broken repeatedly in the
last two weeks and every time it cost days. CLAUDE.md rule one has the
full text and a hook re-injects it on every message.

## Where things stand

What is true, checked on 2026-09-06 (docs/DEEPDIVE.md has the details):

1. The installed plugin (hooks/hooks.json) is the old August 27 design:
   a per-stop rule picker, a fixed note on every prompt, and a
   three-repeat tripwire. SHAPE.md rejects two of the three. It is
   worse than a plain counter at spotting stuck sessions (4 of 12
   versus 12 of 12). Leave it alone unless the goal needs it removed.
2. The real watcher is evals/bench/watcher_session.py. It is a
   prototype. It has no tests, no hook, and these known gaps:
   - it reads only the AI's words, never the commands it ran or the
     errors it got;
   - it cuts every message at 1200 characters, so it often never reads
     the task;
   - it uses the env var DK_SESSION but the hooks pass DK_SESSION_ID;
   - a reply with no JSON is recorded as silence, not as an error.
3. There are 160 labelled moments in evals/bench/moments/ and
   moments_tb/. Labels are in evals/bench/labels/judgment.jsonl: one
   reader per moment, decided by reading. They are the best ground
   truth we have, and they are still only one model's opinion. The
   readers could see the old labels in the filenames.
4. What the watcher says was read once (labels/alert_quality.jsonl).
   Of 48 correct fires, 24 said what a human would, 20 were vague, 4
   were wrong. It never once said "you edited the test file" or "you
   had a working answer and abandoned it."
5. Nobody has ever checked whether the AI changes course after being
   told. That is the gap the goal closes.
6. Money: about $28 on the OpenRouter key. The judgment reading costs
   subagent time, not dollars. A ten-moment continuation run costs
   roughly $10 to $15.

## What to do, in order

1. Fix what the watcher reads. Render tool calls and tool results into
   its input, head and tail, so error lines survive. Put the task
   statement, in full, into every look. Stop the 1200-character cut.
   No API spend.
2. Fix what it is asked for. The prompt should require: the fact the AI
   has not seen, or the claim the record contradicts. Never a
   restatement of the last output. Never a question. Never
   encouragement. Mark what was observed versus guessed.
3. Re-run the watcher on the 160 moments (about $5). Have a reader
   compare each alert against labels/judgment.jsonl by reading, as
   labels/alert_quality.jsonl did. Count "says what a human would."
4. The reaction check. Pick ten own-corpus moments (moments/, the
   jinja goal-mode runs) where the alert was judged right. Rebuild the
   container state by replaying the recorded tool calls (evals/goal has
   the setup). Continue each three ways for 15 to 20 turns: with the
   watcher's alert, with a plain counter's templated alert, with
   nothing. Judge by reading: changed course, ignored, made it worse.
5. Report the result in plain English, with the transcripts. That is
   the deliverable. Then stop and ask Miles what next.

## What not to repeat

- Do not build labels from rules, score curves, or filename prefixes.
- Do not tune a prompt by fire rate. That is how the old monitor went
  blind.
- Do not run an end-to-end marathon or a Terminal-Bench sweep. They
  cost $12 to $3600 and measured nothing four times.
- Do not trust a number until a person has read the moments behind
  it. Ask Miles to read a sample.
- Do not call a run "the judge" without saying whether reasoning was
  on. Reasoning-on made the watcher quieter in the one run tried.
- Do not paste an untruncated alert into docs; check
  evals/bench/results.jsonl stores it in full (2000 chars).
- Do not append to docs/log.md as the only record. Add a dated entry,
  but keep docs/HANDOVER.md current by rewriting it.

## Files that matter

- CLAUDE.md: the rules for the assistant. Read every time.
- docs/SHAPE.md: the product spec. Non-negotiable.
- docs/DEEPDIVE.md and docs/deepdive/*.md: the full audit of every
  layer, with file and line references.
- docs/TIERS.md, docs/TESTS.md: why the old eval plan and test suite
  cannot answer the product question.
- evals/bench/watcher_session.py: the prototype to fix.
- evals/bench/replay_bench.py, score_judgment.py: the bench and scorer.
  Known bench bugs to fix before trusting a re-run: a fire is counted
  only at the last look; a failed look inherits the previous verdict;
  the "still failing" chunk cut matches AI narration.
- evals/bench/labels/: judgment.jsonl, alert_quality.jsonl,
  alert_pairs.json.
- tests/run_dk_tests.sh: plumbing tests for the old plugin. Run before
  committing under scripts/ or tests/. It tests nothing about judgment.

## House rules

- Branch: claude/impossiblebench-four-arm-eval-xo8m9d. Never push
  elsewhere.
- Redact secrets before any commit. GitHub push protection has caught
  one already.
- Every commit message ends with the Co-Authored-By and Claude-Session
  trailers used in this repo's history.
- Plain simple English to Miles. Define a project word the first time
  you use it. Numbers go in a table, not in prose.
