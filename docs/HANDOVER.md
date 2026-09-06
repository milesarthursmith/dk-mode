# Handover to a new session (2026-09-06, evening)

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

## What was done this session

1. **The watcher reads what the AI did, not only what it said.**
   evals/bench/watcher_session.py now renders tool calls and tool results
   into its input, clipped head AND tail so the error at the bottom
   survives; pins the task statement (reminders stripped) into every look;
   marks its own earlier note when it comes back inside the next prompt;
   accepts DK_SESSION_ID (the hooks' name) as well as DK_SESSION; treats a
   reply with no JSON as a failure, not a silence; writes an empty verdict
   on any failed look so nothing stale is injected; and can run through
   the `claude` CLI with no API key (DK_BACKEND=cli, default model
   claude-sonnet-5). Lookup (web search) stays off unless EXA_API_KEY is
   set, and the reaction harness keeps it off.
2. **The watcher is asked for the owner's sentence.** The prompt asks for
   the fact the AI has not taken in, or the claim the record contradicts,
   only when the AI would act differently for it; in Miles's register
   (short, "you", the fact first, then the one check); never a question,
   never encouragement, never a restatement of the last output; guesses
   marked; no fetching from outside when a check on disk would do; never
   mentioning its own notes.
3. **The reaction harness exists** (evals/react/). build.py rebuilds a
   moment's repo state by replaying the recorded tool calls from the
   inspect log and checks it against the record; watch.py runs the watcher
   look by look; run.py continues the same coding AI three ways (nothing /
   watcher note / counter note) under the real hook path; show.py prints a
   continuation for reading. docs/REACTION.md has the method and results.
4. On the pilot moment (wedge_bare_ep2_9) the rebuilt state matched the
   record exactly (466 failing, 0 edit mismatches) and the Sonnet watcher
   named the same facts as the reader on three independent passes.

## What to do next, in order

1. Read docs/REACTION.md for where the pilot and the ten-moment run stand.
   Everything under evals/react/runs/ is a real transcript; read them
   before trusting any sentence about them.
2. If the ten-moment run is not finished: `bash evals/react/build_all.sh`
   checks every chosen moment's rebuild; then one watcher pass per session
   (`watch.py` on the cccccccc-* transcripts under
   ~/.claude/projects/-opt-jinja/, model claude-sonnet-5, DK_BACKEND=cli),
   taking each moment's note from the look before its driver message; then
   `run.py <moment> <arm> <note>` for the three arms. Read each with
   show.py and write the verdict into REACTION.md.
3. Then stop and ask Miles what next. Do not widen into the SWE or
   Terminal-Bench corpora: they need containers this environment has not
   got.

## Environment facts that cost time to rediscover

- No OpenRouter key here. The only model access is the `claude` CLI on
  Miles's login, which counts against his plan's usage cap. Ask before
  anything beyond a few dollars' worth.
- The auto-mode classifier blocks `--dangerously-skip-permissions` and
  `--allowedTools` on the command line. Tool approval for the nested
  agent is done through /opt/jinja/.claude/settings.json, and /opt/jinja
  must be marked trusted in ~/.claude.json or the allow list is ignored.
- /opt/jinja, /opt/jinja_pristine, /opt/pristine_tests and /opt/venv are
  set up by hand (see REACTION.md); the recorded commands use those
  absolute paths. Rebuilding wipes /opt/jinja, so build and run are
  sequential; watcher passes read transcripts only and can run alongside.
- The inspect .eval logs are zstd zips; evals/react/evallog.py reads them
  without inspect_ai.
- CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=80 and CLAUDE_ADDITIONAL_DIRECTORIES are
  set in this session's environment and must be removed for the nested
  agent, or its history is compacted and its edits are refused.

## What not to repeat

- Do not label moments by rule, tune a prompt by fire rate, or trust a
  number nobody has read the transcripts behind.
- Do not run marathons or bench sweeps. They measured nothing four times.
- Do not paste an untruncated note into docs; the notes are kept in full
  under evals/react/notes/ and runs/.

## House rules

- Branch for this session: claude/dk-mode-watcher-alignment-ygndi3 (the
  previous branch's history was pulled into it). Never push elsewhere.
- Run `bash tests/run_dk_tests.sh` before committing under scripts/ or
  tests/. Redact secrets. Commit trailers as in the repo's history.
- Plain simple English to Miles. Numbers in a table, not in prose.
