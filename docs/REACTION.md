# The reaction check: does the coding AI change course after the watcher speaks?

Words used. The **watcher** is the LLM that reads a coding AI's session
and decides whether to say something. A **moment** is a frozen prefix of a
real session, cut where the AI is stuck. A **note** is what the watcher
says. The **counter** is the free rule-only baseline (same message every
time a step repeats three times). The **driver** is the mechanical
re-prompt in goal mode: after every stop it reports how many tests still
fail and says "The goal stands. Continue."

## Method

1. **Moments.** Ten own-corpus moments from the jinja2 goal-mode runs
   (evals/goal): the seeded-bug repo, Claude Code as the agent, driver
   re-prompts. All ten are moments a reader, reading the whole transcript,
   marked "speak" (evals/bench/labels/judgment.jsonl). They come from
   four sessions; several are nested prefixes of one session, which is
   said where it matters.
2. **State.** The repo is rebuilt for each moment by replaying the
   recorded tool calls from the inspect log (evals/react/build.py). The
   rebuilt state is checked against the record two ways: the number of
   failing tests must match the driver's own count at that point, and
   every replayed Edit must succeed or fail exactly as it did originally.
3. **Watcher.** The new watcher (evals/bench/watcher_session.py) runs
   over the rebuilt transcript look by look, as it would live: one look
   after each agent turn, before the driver's next message. Its note at
   the moment's final look is the one delivered. Model: Claude Sonnet 5
   through the `claude` CLI, reasoning off, lookup off.
4. **Continuation.** The same coding AI (Claude Code, Haiku 4.5, as in
   the original runs) is resumed from the same conversation and the same
   repo state, three ways: the driver's message alone; the same plus the
   watcher's note, injected by a UserPromptSubmit hook the way dk-mode
   delivers it; the same plus the counter's note. Up to 20 tool rounds.
   The sandbox denies network commands, as the original had no network.
5. **Judgment.** Each continuation is read (evals/react/show.py) and
   judged by hand: changed course, ignored, or made it worse. The grader's
   failing count after the run is recorded as one fact, not as the verdict.

Every transcript is under evals/react/runs/<moment>/<arm>/.

## Caveats stated up front

- The original stuck sessions were driven by gemini-2.5-flash inside the
  Claude Code harness. The continuation here runs Haiku 4.5, because that
  is the model this environment can reach. All three arms use the same
  model and the same state, so the comparison between arms holds; the
  absolute behaviour is Haiku's, not the original agent's.
- The watcher's earlier notes were never delivered in these sessions
  (three of the four sessions had no hook at all). The watcher is told a
  note reached the AI only when it sees it echoed, and never to mention
  its notes.
- The seeded bugs are uncommitted changes, so `git diff` shows them. That
  was true in the original runs too and is left as it was.

## Results

### Pilot: wedge_bare_ep2_9

The moment: the bare-arm session, 41% of tests fixed, stuck for about
twenty turns on `test_item_and_attribute` (a "can only join an iterable"
error), rewriting `_output_const_repr` and `visit_Output` in compiler.py;
the last edit made it worse (462 to 466 failing). The reader's own
sentence for this moment: look at the code jinja actually generates, and
revert the last edit.

Rebuild check: 466 failing here, 466 in the driver's message; 35 replayed
calls, 0 outcome mismatches.

The watcher, three independent Sonnet passes over the same session, look
by look. All three named the same facts at the same looks: the 460 to 650
regression after the three `repr()` edits and why (that function writes
generated source), the 462 to 466 regression from the `visit_Output` edit,
the edit that failed to apply, and an untouched `test_empty_blocks`
failure. What differed between passes was the suggested next step (a
debug print; diffing against upstream; moving to the other test). The
note delivered (pass three, final look) is in
evals/react/notes/wedge_bare_ep2_9.watcher.txt. Its one flaw: it opens by
mentioning notes that were never delivered; the prompt now forbids that.

The counter's note: "You have produced the same step 6 times ('No
response requested....')" - a harness artifact, not the problem.

| arm | failing before | failing after | what it did (read the transcript) |
|---|---|---|---|
| nothing | 466 | 219 | Ran one failing test verbosely, printed the generated code, found the inverted `if node.node is None` in `visit_Filter`, fixed it, then found and fixed the lexer dropping template data. Changed course on its own. |
| watcher | 466 | (running) | |
| counter | 466 | (running) | |
