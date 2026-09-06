# The tests are broken — what 119 green tests certify (2026-09-06)

tests/run_dk_tests.sh is "the full test suite for dk-mode". On
2026-09-06 it reports 119 passed. Before this morning it reported 118
passed, 1 failed, and had done so since 2026-08-31 without anyone
noticing. This document says what the suite actually tests, what it
cannot test, and what it certifies that the project has rejected.

## 1. The suite was red for six days and nobody knew

Test 55 asserted that an empty monitor verdict injects nothing. On
2026-08-31 dk_recall.sh was changed so that an empty verdict falls
through to the static note, because on an SWE run the empty verdict had
muted every nudge for three turns (the "muting bug"). The code changed;
the test did not. The header of the suite says "Run after ANY change to
the scripts." It was not run. Fixed today: test 55 now asserts the
decided behaviour. A CI workflow (.github/workflows/tests.yml) now runs
the suite on every push so red is visible.

## 2. The suite certifies the design SHAPE.md rejects

Every test exercises the shipped plugin: dk_capture.sh, dk_recall.sh,
dk_consolidate.py, dk_watch.py, dk_tripwire.py (hooks/hooks.json). Two
of those are the rejected shape:

- dk_watch.py is the stateless per-stop judge. SHAPE.md: "that design is
  dead." Tests 53 to 63 certify it.
- dk_tripwire.py is a counter guard. Test 108: "the same call three
  times trips." Test 109: "reading without writing trips." It injects
  text into the agent's tool result when a count is reached, with no
  judgment in the loop. SHAPE.md retires exactly this: "a rule that
  decides when to intervene. Not built." It is built, shipped in
  hooks.json on PostToolUse, and has seven green tests.

The product, evals/bench/watcher_session.py, has zero tests. The eight
mentions of "watcher" in the suite all refer to dk_watch.py. So the
suite is green on the thing the project abandoned and silent on the
thing it is building.

## 3. No test touches judgment, and none can in this form

Every model call in the suite goes to a mock (tests/mock_*_api.py) that
returns canned JSON: a fixed rule selection, a fixed alert, a fixed
rewritten rules file from tests/fixtures. That is the right way to test
plumbing: does the verdict file get written, scoped per session, expire,
fall through. It is the only thing these tests can show. Whether a
verdict is right, whether an alert names the real problem, whether the
watcher would have spoken when a human would: no test asks, because a
canned mock cannot answer. The one test that reaches a real model is
--live, a single call.

A suite of 119 plumbing tests with a product-sized name gave the
programme a false sense of coverage. Four end-to-end instruments
measured nothing (docs/log.md, 2026-08-29 to 08-31) while the suite
stayed green, because green here means "the pipe carries a verdict",
not "the verdict is worth carrying".

## 4. The eval tests were broken in the same way

The replay bench (evals/bench) is the test that matters and its ground
truth was a rule until 2026-09-05: filename prefixes from how a run was
staged and whether its score rose. Readers reading the transcripts
disagreed on 48 of 160. docs/TIERS.md takes that apart tier by tier.
Same failure as section 3: a test that cannot see judgment was treated
as if it could.

## What tests should exist

1. Plumbing tests for the watcher, the same way the old ones test the
   old scripts: state persists across looks, only the delta is fed,
   the conversation window is trimmed, senses are annotations in the
   prompt and never gate a call, lookup runs only when the watcher has
   decided to speak, failures are logged not swallowed. Mocked model,
   no key. None of this exists.
2. Judgment tests are the labelled moments. A test case is a moment
   plus a reader's decision and would_say (labels/judgment.jsonl). The
   watcher passes a case when a reader, reading its alert against the
   transcript, judges it names the same problem. Run rarely, under a
   spend cap, by reading (labels/alert_quality.jsonl is the first run).
   No canned mock, no keyword match, no score threshold.
3. The tripwire tests are re-scoped or retired. Under SHAPE the
   tripwire's counts are senses fed to the watcher. A test may assert
   that a repeated call is annotated; it must not assert that a count
   injects an intervention.
4. The suite runs on every push. Done today.
