# Handover to a new session (2026-09-06, late evening)

Read this file first, then CLAUDE.md, then docs/SHAPE.md, then
docs/REACTION.md. docs/DEEPDIVE.md is the audit that led here. Do not read
docs/log.md end to end.

## The goal, in one sentence

Make the watcher say what Miles would say to a stuck coding AI, and show
on ten stuck moments that the AI changes course after hearing it.

Words: **watcher** = the LLM that watches a coding AI's session and
decides whether to speak. **moment** = a frozen transcript prefix cut where
the AI is stuck. **note** = what the watcher says. **counter** = the free
rule-only baseline. **driver** = goal mode's mechanical re-prompt.

## The one rule that matters most

Automatic rules do not work. No counter, threshold, score curve, or
filename decides whether a session is stuck, whether to speak, or what a
label is. Judgment decides. CLAUDE.md rule one; a hook re-injects it.

## Where things stand

1. **All ten moments have a watcher note, or a judged silence.** One
   Sonnet 5 pass per session, look by look (evals/react/notes/). Beside
   the reader's sentence: 4 same, 3 partial (same problem, different next
   step), 3 silent where the reader would speak. The table and the
   reading are in docs/REACTION.md. Nothing was tuned.
2. **The continuation now runs the original stuck model.** OpenRouter
   serves gemini-2.5-flash in Anthropic's format; run.py's
   `REACT_BACKEND=openrouter` points the Claude Code binary at it with a
   minimal environment. Unaided, it stays stuck where Haiku did not.
3. **One full moment on that model: wedge_bare_ep2_8.** nothing 466 to
   539, watcher 466 to 462, counter 466 to 468. The watcher arm followed
   the note (reverted the regression, left the function), the other two
   never left it. Read docs/REACTION.md and the transcripts under
   evals/react/runs/wedge_bare_ep2_8/ before repeating any sentence about
   them.
4. **The seeded bugs are committed before replay** (build.py). git diff
   shows only the AI's edits. The AI's recorded git restore / reset
   commands are pointed at the pristine commit during replay so the
   rebuilt state stays as recorded; all nine rebuilds match their counts.
5. **One session's original grader was broken** (goal-dk HE6z epoch 1:
   wedge_dk_ep1_11/13/15/16). It said "no tests ran" every check, so the
   driver's "785 failing" was false all session; the rebuilt states have
   4, 22, 0 and 22 failing. Cause not found. Say this whenever those four
   moments are discussed.

## What to do next, in order

1. **Waiting on Miles:** the remaining 24 arms cost about $11 at the rate
   seen (the watcher arm on ep2_8 alone was $0.94 because the model
   re-reads whole files). Do not start them without his word. If he says
   go: for each moment in evals/react/build_all.sh plus wedge_bare_ep2_9,
   `REACT_BACKEND=openrouter REACT_MODEL=google/gemini-2.5-flash
   python3 run.py <moment> <arm> notes/<moment>.<arm>.txt` (or `-` for
   nothing). Arms are sequential (they share /opt/jinja). Skip the
   watcher arm where notes/<moment>.watcher.txt is empty (healthy_dk_ep1_11,
   wedge_dk_ep1_11, wedge_dk_ep1_13): it would equal the nothing arm.
   Read each with show.py and write the verdict into REACTION.md.
2. If Miles wants the watcher closer to his voice first: the gap is
   length (50 to 70 words against his 20) and the HE6z silences (it
   trusted the AI's local pytest over the driver's count and did not
   raise the contradiction after look 6). Change the prompt only for a
   reason you can point at in a transcript; then re-run the pass on that
   one session (17 looks, about $0.85) and compare by reading.
3. Then stop and ask Miles what next. Do not widen into the SWE or
   Terminal-Bench corpora: they need containers this environment has not
   got.

## Environment facts that cost time to rediscover

- A fresh container has none of /opt. Rebuild: `python3 -m venv /opt/venv;
  /opt/venv/bin/pip install pytest zstandard`; clone pallets/jinja at
  3.1.2 to /opt/jinja_pristine; copy it to /opt/jinja and `pip install -e
  /opt/jinja` FROM THAT PATH (an editable install of the pristine copy
  makes every build report 0 failing); copy /opt/jinja/tests to
  /opt/pristine_tests. `pip install zstandard` for evallog.py too. Check:
  bugs applied in /opt/jinja give "785 failed, 57 passed".
- OPENROUTER_API_KEY was present this session (about $27 of credit left
  after this session's $1.38). The `claude` CLI on Miles's login is the
  other model access and counts against his plan.
- The nested Claude Code must run with a near-empty environment for the
  openrouter backend, or it keeps the host OAuth and sends no auth header
  (401 "Missing Authentication header"). run.py's nested_env() does this.
- The CLI's total_cost_usd is wrong for foreign models (prices them at
  Anthropic rates); run.py records real spend from OpenRouter's credits
  endpoint as openrouter_spent_usd.
- /opt/jinja must be trusted in ~/.claude.json or the allow list is
  ignored; run.py's trust_workdir() sets it.
- CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=80 and CLAUDE_ADDITIONAL_DIRECTORIES are
  set in this session's environment and must not reach the nested agent.
- Watcher passes read transcripts only and can run alongside a build;
  builds and runs share /opt/jinja and must be sequential.

## What not to repeat

- Do not label moments by rule, tune a prompt by fire rate, or trust a
  number nobody has read the transcripts behind.
- Do not run marathons or bench sweeps. They measured nothing four times.
- Do not paste an untruncated note into docs; the notes are kept in full
  under evals/react/notes/ and runs/.
- Do not trust the CLI's cost figure for a foreign model.

## House rules

- Branch for this session: claude/dk-mode-watcher-alignment-9he3xq (the
  previous branch's history was pulled into it). Never push elsewhere.
- Run `bash tests/run_dk_tests.sh` before committing under scripts/ or
  tests/. Redact secrets. Commit trailers as in the repo's history.
- Plain simple English to Miles. Numbers in a table, not in prose.
- Tell Miles before spending more than $5.
