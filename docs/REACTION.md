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

## Changes on 2026-09-06 (evening, second session)

1. **The continuation runs the original model.** An OpenRouter key was
   present this time. OpenRouter serves gemini-2.5-flash in Anthropic's
   message format, so the same Claude Code binary is pointed at it
   (`REACT_BACKEND=openrouter` in run.py, a minimal environment so the
   binary cannot fall back to the host login). The first arm run this way
   (wedge_bare_ep2_8, nothing) stayed stuck exactly where the record
   shows the original stuck; Haiku had not. Real spend per arm is read
   from OpenRouter's credits endpoint, because the CLI prices an unknown
   model at Anthropic rates and reports about fifty times too much.
2. **The seeded bugs are committed before replay.** `git diff` now shows
   only the AI's edits and `git checkout <file>` cannot remove a bug. The
   AI's recorded `git restore <file>` and `git reset --hard` commands are
   pointed at the pristine commit during replay, so the rebuilt state
   stays what the record shows. All nine rebuilds give the same failing
   counts as before the change. One consequence to keep in mind when
   reading: in the continuation, `git checkout -- lexer.py` now restores
   the bugged lexer.py, where in the original it restored the clean one.
3. **One session's original grader was broken.** In goal-dk HE6z epoch 1
   (moments wedge_dk_ep1_11, _13, _15, _16) the scorer's own record says
   "no tests ran" on every check after the first, so the driver's "785
   failing (0% fixed)" was false for the whole session. The AI's local
   pytest was the truth, and the reader's sentences for those moments
   ("settle why the harness says 785 while your run says 842 passed")
   were pointing at a harness fault nobody could fix from inside. The
   rebuilt states here give the honest counts: 4, 22, 0 and 22 failing at
   the four cuts. The driver prompt used for the continuation is still
   the recorded one, so the AI meets the same contradiction the original
   did. The cause of the grader fault was not found; the agent's own
   commands do not touch tests/ or /opt/pristine_tests.

## What the watcher said, moment by moment

One Sonnet 5 pass per session (reasoning off, lookup off), look by look;
the note for a moment is the look over exactly that prefix. Full text of
every look is in evals/react/notes/*.looks.json; the delivered notes in
notes/<moment>.watcher.txt. The reader's sentence is from
evals/bench/labels/judgment.jsonl. "Same" means the note names the same
problem and the same next step as the reader; "partial" the same problem,
a different next step; "silent" the watcher chose not to speak.

| moment | reader's next step | watcher's next step | judged |
|---|---|---|---|
| wedge_bare_ep2_7 | git diff compiler.py and revert; read the full traceback | stop touching visit_Output; re-read the file; fix test_empty_blocks instead | partial |
| wedge_bare_ep2_8 | revert the compiler.py edits; run the one test with --tb=long | revert the last edit (462 to 466); confirm; fix test_empty_blocks | same |
| wedge_bare_ep2_9 | print the code jinja generates; revert the last edit | revert the last edit; move to test_empty_blocks | partial |
| wedge_dk_ep1_10 | git checkout -- lexer.py, stop rewriting by hand | git checkout -- lexer.py | same |
| healthy_dk_ep1_11 | do not re-apply the lstrip_blocks change; run pytest, read the traceback | (silent: the AI had just run the restore it was told to run for eleven looks; the watcher waited one turn) | silent |
| healthy_dk_ep2_6 | git checkout src/jinja2/; then fix the nodes.py == bug | your nodes.py fix is real, keep it; your last message is nonsense; run pytest --tb=short | same |
| wedge_dk_ep1_11 | stop editing parse_tuple; reconcile harness 785 vs local 842 | (silent: local pytest went 14 to 10 to 4 failing, judged real progress) | silent |
| wedge_dk_ep1_13 | same | (silent, same reason) | silent |
| wedge_dk_ep1_15 | stop editing parse_tuple; resolve the contradiction | you swapped in an untested variant and guessed the count; run pytest before claiming | partial |
| wedge_dk_ep1_16 | leave parse_tuple alone; restore the is_tuple_end fix you undid | you stacked two edits without testing; run pytest first | partial |

Two things to say about the silences. On the HE6z session the watcher
had, at look 3, worked out on its own that the AI's `git reset --hard`
had erased uncommitted seeded bugs, and said so; by looks 11 to 14 its
notes still carried "harness 785 vs local 4, unreconciled" but it judged
the local progress real and stayed quiet. Miles's own line quoted in the
prompt ("you said 842 passed. the harness says 785 failing. sort that
out") comes from this session, so this is a real gap between the watcher
and the owner, not a tie. It is left as found; nothing was tuned.

On register: the notes lead with the fact, address the AI as "you", and
give one check. They run 50 to 70 words where the owner would use 20,
and sometimes explain ("because you're editing from a stale mental
model"). The pilot note (ep2_9) opens by mentioning undelivered notes;
the prompt has forbidden that since, and no later note does it.

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
| watcher | 466 | 322 | First words: "The user's note is correct." Reverted the `visit_Output` regression, ran pytest, went to `test_empty_blocks` as told, found the lexer `#bygroup` bug that dropped the leading data token, then a parser `nodes.If` bug. Followed the note to the letter. |
| counter | 466 | 324 | "The system message indicates I need to change my strategy." Ran one test, printed the generated code, then `git diff` and `git checkout src/jinja2/compiler.py`, which removed the seeded bugs in that file along with its own edits, then fixed inversions it saw in the diff of lexer.py and parser.py. Changed course, partly by wiping the file. |

All three transcripts: evals/react/runs/wedge_bare_ep2_9/.

**What the pilot shows.**

1. Delivery and voice work. The AI read the note as a person's message
   ("The user's note is correct") and did exactly what it said. The
   watcher's facts were the reader's facts.
2. This moment cannot credit the note. Haiku 4.5, given nothing but the
   driver's line, also changed course, and went further. The original
   session was stuck because gemini-2.5-flash was stuck; a different
   model dropped into the same state is not. A reaction check that can
   say "the note made the difference" needs a continuation model that
   stays stuck without it. That is the original model, which needs the
   OpenRouter key this environment does not have, or moments where Haiku
   is shown to stay stuck unaided.
3. The instrument leaks the answer. The seeded bugs are uncommitted, so
   `git diff` lists them and `git checkout <file>` removes them. The
   counter arm gained most of its ground that way. The nothing arm read
   the same diff and called the seeded inversions "my changes". Any
   further runs on this corpus should commit the seeded bugs first, so
   the AI's own edits are the only diff.

**Spend.** About $3.50 of CLI usage in total for this session: four
watcher passes over the pilot session (one Haiku, three Sonnet), the
three continuation arms at about $0.45 each, and the first broken
continuation run. Each further moment costs about $1.40 for its three
arms plus a share of one Sonnet watcher pass per session (about $0.05 a
look, 36 looks across the three remaining sessions).
