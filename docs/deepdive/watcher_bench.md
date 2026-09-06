# Deep dive: watcher prototype and replay bench (reader report, 2026-09-06)

# Deep dive: watcher prototype and replay bench (`evals/bench`)

Vocabulary used below. **Watcher**: the LLM overseer that reads a coding-agent session and decides whether to speak. **Look**: one invocation of the watcher on the transcript so far. **Delta**: the messages added since the last look. **Notes/expectations**: the watcher's own memory, carried between looks. **Sense**: a mechanical annotation (`[sense: ...]`) added to what the watcher reads. **Moment**: a frozen transcript prefix ending at a decision point. **Fire/speak**: the watcher wrote a non-empty alert. **Wedge**: a session that is stuck. **Counter baseline**: the rule-only reference the watcher must beat.

---

## 1. What the watcher actually is

### What it reads at each look

`watcher_session.py:180-199` (and `watcher_v2.py:183-202`, byte-identical apart from the prompt):

- It re-parses the whole transcript every look (`read_transcript`, `:108-128`). It keeps `user`/`assistant` lines, drops `isSidechain`/`isMeta`, and keeps **only `text` blocks** (`:122-123`). `tool_use` and `tool_result` blocks are discarded. Lines with no text are dropped (`:124`).
- The delta is `msgs[state["seen"]:]` (`:190`). Each delta message becomes `[role] text[:1200]` (`:193`, `PER_MSG` at `:27`). This is a **head** cut: the first 1200 characters survive, the rest is gone.
- Senses are computed over the **whole** transcript, not the delta, and appended after the delta lines (`:194`, `signals` at `:131-155`). Three senses exist:
  - assistant text whose first 120 characters (whitespace-collapsed) repeats ≥3 times, top 3 shown (`:137-144`);
  - the jinja driver's `(N% fixed)` score flat for the last 3 checks (`:146-149`);
  - ≥4 of the last 8 assistant messages contain `error|failed|apolog` (`:151-154`).
- The user turn is: notes so far, open expectations, "New activity since your last look", the delta, the senses, and "Update notes and expectations; decide whether to speak" (`:195-199`).

### What state it keeps, and how context is trimmed

- State file `.watcher_state.<session>`: `seen` (message index), `notes` (capped 3000 chars, `:215`), `expectations` (≤10 items, ≤200 chars each, `:216-218`).
- Conversation file `.watcher_convo.<session>`: the watcher's own last `KEEP_EXCHANGES=3` user/assistant pairs (`:26`, `:202`, saved at `:222`). Each stored user turn contains that look's **raw delta**. So the model's context at a look is: system prompt + the last three deltas verbatim + their three replies (raw JSON, `raw[:4000]`) + notes again + the current delta. The docstring's claim that "old exchanges are dropped from its context once distilled" (`:7-9`) is only true beyond three looks. Within that window there is no compaction, and the notes are duplicated (once in the stored reply, once in the new turn).

### The model call and parsing

- OpenRouter chat completions, `temperature 0`, `max_tokens` 2000, or 8000 with `DK_REASONING` set (`:165-169`). Default model `google/gemini-2.5-flash` (`:23`).
- Output parse: `re.search(r"\{.*\}", raw, re.S)` then `json.loads(strict=False)` (`:207-208`). If no braces are found, `data = {}` and execution **continues**: `seen` advances, notes are unchanged, `speak` is `None`, an empty `.dk_active` is written, and the log line says `ok: spoke=False` (`:214-250`). A malformed reply is indistinguishable from a deliberate silence.

### What "speak" produces, and where lookup fits

- If `speak` is a non-empty string, `.dk_active.<session>` gets `<self-steering>\n{speak[:600]}\n</self-steering>` (`:242-245`); otherwise the file is truncated to empty (`:247`).
- Lookup (SHAPE.md item 4) runs only if the model spoke **and** set `lookup` **and** `EXA_KEY` is in the environment (`:227-228`). It calls Exa (`:79-90`), then re-prompts with `GROUND` plus the raw search text (`:71-76`, `:232-238`) and takes the rewritten `speak`. `grounded` is only written to `watcher.log` (`:248-250`), never to `results.jsonl`. The bench never sets `EXA_KEY` (`replay_bench.py:184-188`), and `docs/log.md` has no lookup entry. **The watcher+lookup variant SHAPE.md names has never been run.** There is also no per-task OFF switch for SWE-bench tasks as SHAPE.md requires; the only switch is the global key.

### v2 differences

`watcher_v2.py:34-72`: settle each expectation as MET/BROKEN first; speak only for one of five named reasons (a)–(e); return `settled` and `reason`. The code ignores both new fields (`:227-228` uses only `speak`/`lookup`). Reason (e), "N looks with no change in the failing signal", is a counter phrased as a reason. It cost recall (log.md 2026-09-03: 13/44 vs 27/49).

### Rule-one audit: where a count could gate rather than inform

1. **Running is gated mechanically.** `if not delta: return 0` (`:191-192`). Harmless on the bench (every chunk adds text lines), but in production a turn that is only tool calls yields no text lines (see §4), so the watcher does not look at all. SHAPE.md item 2 says signals never decide whether the watcher runs.
2. **The repeat sense is the counter baseline's trigger, verbatim.** Same 120-char key, same whitespace collapse, same `>=3` (`watcher_session.py:140-142` vs `baseline_counter.py:23-26`). The plateau sense is the old wedge-labelling rule from `replay_bench.py:78-81`. The senses do not block the call, but they are the retired guard's verdict re-presented as text. Measured on the `watcher` rows against judgment labels: fired when a sense was present 35/60, fired with no sense 35/100; on the own corpus 19/27 vs 9/29. The watcher does overrule in both directions (23 correct fires with no sense, 10 correct silences with one), so it informs. It informs heavily, and its wording ("repeated near-identical message x6") is already a conclusion.
3. **Mechanical trims of judgment output**: notes `[:3000]`, expectations `[:10]`/`[:200]`, alert `[:600]` (`:215-218`, `:245`). The alert cap was never hit on the bench (longest stored alert is under 400 chars) but would cut mid-sentence in production.
4. The sense thresholds (`>=3`, `>=4`, three flat checks) decide what the watcher is *told*, not what it decides. That is within the rule, but nothing tells the watcher about a repeat at x2 or errors at 3/8.

---

## 2. Bench correctness

### How moments are cut

- Own corpus, jinja goal-mode: `extract()` (`replay_bench.py:57-93`) cuts at each driver message, labels by the score curve (`:78-86`), keeps only message text (`:71-73`). Own corpus, SWE: `extract_swe()` (`:96-141`) cuts at ≥3 failed Edits in 8 messages or a "busy" window, and **drops tool messages** (`:134`). So own-corpus moments contain narration only; "String to replace not found" is visible only when the agent says it.
- Terminal-Bench corpus: `extract_tb.py` renders tool calls and results into text (`:783-794`, results clipped to 600 chars head+tail, `:114`, `:323-327`), then cuts at the **first index where a rule holds** (R1–R4, `:625-685`; picked at `:733-743`). Healthy moments require that no wedge rule held in the last 16 messages (`:689`, `HEALTHY_QUIET` `:121`). The labels are now judgment (`labels/judgment.jsonl`), but the **cut points are still the rule's**. Every positive-candidate moment ends exactly where a repeat/no-progress counter trips, and every negative was chosen to be counter-quiet for 16 messages. That shapes the comparison (see "unfair" below).
- Manifest records `reward` for review only (`:771-774`); it is not used to label. Good.

### Sequential looks

- `_chunks` (`replay_bench.py:144-157`): cut after any line containing `"The goal stands"` or `"still failing"`, else every `SEQ_STEP=10` lines (`:153`). **Bug**: `"still failing"` matches assistant narration ("The `Edit` tool is still failing to find..."). Across the own corpus, 132 cuts land on assistant lines (e.g. `wedge_dk_ep1_10` line 50). Look cadence on the own corpus is therefore irregular and mid-turn, and one moment gets up to 30 looks. SWE own moments have no driver markers and fall back to step 10 (39 moments).
- `run_seq` (`:175-210`): per chunk, write `t.jsonl`, run the watcher, read `.dk_active.bench`. `fired` is **overwritten** each chunk (`:197`) and the record uses the last value (`:200`, `:205`). **"Fired" means spoke at the final look only.** `first_fire_chunk` is recorded (`:198-199`) but `score_judgment.py` never reads it. A watcher that spoke correctly at look 3 and judged the last look quiet scores as a miss. A human overseer who spoke at look 3 would count.
- **Stale verdict carry-over.** The watcher exits without touching `.dk_active` on empty delta (`watcher_session.py:191-192`) and on API failure (`:209-212`). `run_seq` then reads the previous look's file as this look's verdict (`replay_bench.py:196-197`). A failed final look inherits the prior look's fire; `failed` is only computed when `not fired` (`:202-203`), so that row is a clean "fired".
- `run` mode (`:213-247`, used for `counter-baseline`, `arc-patch`, `stale`, `current`) feeds the whole prefix in one call. It has no error flag at all (`:241-243`).

### Error handling and resume

- `failed = ("FAILED" in watcher.log and not fired) or (not fired and secs < 3)` (`:202-203`). CLAUDE.md says sub-5s. 27 `watcher` rows are quiet, under 5s, and unflagged (e.g. `healthy_swe-challenge_django-15368_ep2`, 1.8s). A malformed JSON reply is never `FAILED` (§1). `subprocess.run(..., timeout=180)` at `:195` is uncaught; a `TimeoutExpired` kills the sweep (resume covers it). With reasoning, one look reached 529s total.
- Resume: `_already` skips moments with a non-error row (`:160-172`); `score_judgment.load_results` keeps the last non-error row (`:57-67`). 11 duplicate `(variant, moment)` rows exist (retries); handled correctly.

### Leakage into the watcher

- Filename: in `run_seq` the transcript is copied to `t.jsonl` (`:189-193`), so the `wedge_`/`healthy_` prefix never reaches the process. In `run` mode the labelled path is `argv[1]` (`:236`), but neither script puts the path in a prompt.
- Content: 23 own-corpus moments (all dk-arm) contain earlier `<self-steering>` hook output inside user messages (e.g. `moments/wedge_dk_ep1_10.jsonl` line 102). Another monitor's verdicts are in the watcher's input. The driver's score line is also in the input and the plateau sense re-encodes it. This does not leak the *judgment* label, but on the own corpus the sense is the old label rule, which agrees with judgment on 112/160.
- **The task is mostly invisible.** All 56 own moments start with ~7KB of `<system-reminder>` before the task text (task at char ~6.6–7.2K); `PER_MSG=1200` head-cuts it. 24 of 57 ATIF-harness TB moments put the task beyond char 1200 (Terminus format instructions first). The watcher's "goal" in its notes is inferred from narration for about half the corpus.

### Where watcher and counter are scored differently

1. Counter sees the whole prefix once; the watcher's scored look sees the last chunk plus notes plus three prior deltas.
2. Counter rows carry no error flag; watcher errors are excluded and retried.
3. The TB negatives are selected to be rule-quiet for 16 messages (`extract_tb.py:689`); the counter's false-fire column is protected by construction on the frontier corpus, the watcher's is not.
4. The counter's rule 1 fires on harness artifacts ("No response requested....", "(no content)") — `results.jsonl` rows for `wedge_dk_ep1_12/14`. It is scored as a hit whenever a reader said speak for any reason; content is never compared.
5. Non-independence: 160 moments from 136 sessions; `dk_ep1` contributes 8 nested prefixes (`wedge_dk_ep1_10..16`, `healthy_dk_ep1_11`). McNemar treats them as independent pairs.
6. The scored `watcher` variant ran with reasoning off. CLAUDE.md rule 3 says a judge without reasoning is not a judge. The reasoning row was worse on recall (log.md 2026-09-05), and every alert in `alert_quality.jsonl` is from the no-reasoning variant (verified: all 70 `alert_pairs.json` alerts match `watcher` rows).

### Statistics

`score_judgment.py`: Wilson 95% intervals (`:22-29`); exact two-sided binomial McNemar on **positives only**, `b` = variant fired & counter quiet (`:32-39`, `:98-101`). False fires are not paired. `--no-low`, `--common` (`:77-84`). Labels are loaded from `labels/shard*.jsonl` (`:44`), not `judgment.jsonl` (currently identical, 0 differences; a second-read edit to `judgment.jsonl` would be silently ignored). `replay_bench.py report` (`:258-281`) still scores by filename prefix and is the **default command** (`:285`, `:297`). Every result row still carries `"label": prefix` (`:205`, `:242`).

---

## 3. Reading the 70 alert-quality verdicts and 20 sampled alerts

Counts (`labels/alert_quality.jsonl`): task A (fires on speak-moments) 24 same / 20 partial / 4 wrong; task B (fires on silent-moments) 14 reader-right / 2 watcher-right / 6 unclear.

**What it does well.** When one tool call fails the same way several times, it names the error and the count in the agent's terms: "attempted the `send-key` command with the `keys:["ret"]` format multiple times, and it consistently fails with the error "QMP input member 'keys' is unexpected"" (`results.jsonl`, `wedge_tb2-...install-windows-3.11_XUJxj3j`). It occasionally reaches a real structural fact: "g_custom_heap is file-static in main.cpp" (verdict 46), "bare `make all` keeps running from /app" (44). It twice out-judged the first reader (59, 64: "this manual process will not work, script the extraction"; "try Ctrl+Z / kill %1"). All 24 "same" verdicts are this one shape: a recurring tool error.

**What it does badly, with the pattern named.**

1. *Restates the last tool output.* "Your last GDB command ... produced no output, so you couldn't get the information you were looking for" (`healthy_tb2-...custom-memory-heap-crash`). Verdicts 18, 20, 51, 68 say the same: "merely restates those errors", "just repeats the traceback".
2. *Asks instead of corrects.* "What is your next step to improve performance?" (verdict 11); "What are you trying to achieve by re-running the same script?" (`wedge_tb2-terminuskira-opus46-video-processing`); "what are you looking for" (53). A question is not an intervention.
3. *Adopts the agent's framing.* yt-dlp: it argues about `--js-runtimes` flags while the truncated tail says bot-check (62). Tesseract: "You need to get `tesseract` to produce *some* output" when the PNGs are 261 bytes and blank (15). Path-tracing: "find *exact* formulas for all regions" pushes deeper into curve-fitting a ray-traced scene (8).
4. *Asserts a mechanism it has no evidence for.* "the problem is not with the content of the file itself, but with the environment" (24, wrong: the agent's rewrite was the problem). "the cat heredocs are being truncated" (66, wrong: the scripts ran). It tells the agent the harness's fixed `re.sub` loop is "not the desired behavior" (9). All four "wrong" verdicts are speculation stated as fact.
5. *Fires on prompt-induced tics.* "You have repeatedly stated that you are about to claim a fix ... 'I have not verified this claim'" (2).
6. *Coaches a wedged agent.* "You've made good progress reducing the errors to 4 ... Please complete your explanation" (`wedge_dk_ep1_13`, verdict 27 wrong). "Please run the tests now" on four consecutive nested prefixes (25–28) while the real fact, the agent's own pytest says 842 pass and the grader says 785 fail, is never named once. The notes did not accumulate the contradiction across looks.
7. *Shallow on edit failures.* "Read the file and copy-paste the old_string" is what the agent has done five times (43); the cause was a leading tab (40, 43), reordered blocks (33), or code that does not exist in the file (32, 39). "Landing this edit as the watcher advises would re-submit the same non-fix" (39).
8. *Never widens the frame.* Test file edited against the task rule (1), `interp.py` edited when the task is `eval.scm` (65), a correct 100k-row script abandoned (50), a correct `out.html` verified then the session wandered (`.mem/.watcher_state.bench` notes show it saw this and stayed silent). Zero alerts of this kind in 70.
9. *Premature on early exploration.* 17 messages in (10), 23 messages in (19), three 404s on guessed URLs called "repeatedly getting 404 errors".
10. *Cannot see harness noise.* Confirm-bounce on `mark_task_complete` read as "marked the task as complete five times" (63); waits on a compile read as a loop (57, 12).

My reading: the alerts are written from the delta, not from the notes. Almost every "partial" is a case where the deciding fact was in a tool output or in an earlier look, and the watcher spoke from the last two or three messages.

---

## 4. What breaks in production

1. **Session id mismatch.** The watcher reads `DK_SESSION` (`watcher_session.py:182`). `dk_capture.sh:71` exports `DK_SESSION_ID`; `dk_recall.sh:79-81` reads `.dk_active.<session_id[:16]>`. In production the watcher writes `.dk_active.session` and recall never reads it. This is the exact bug `dk_capture.sh:55-59` describes having fixed once for `dk_watch.py`.
2. **No lock, no failure counter.** `dk_watch.py` has a lock file and updates `watch_consecutive_failed` for recall's "broken, not quiet" line (`dk_recall.sh:128-131`). The watcher has neither. Two overlapping Stop hooks read the same `seen`, both append to `.watcher_convo`, and one overwrites the other's notes (`:214-222`). Failures are invisible to the user.
3. **Real Claude Code jsonl is mostly tool blocks.** `read_transcript` keeps text blocks only (`:122-123`). Assistant lines that are only `tool_use` and user lines that are only `tool_result` become empty and are dropped. The watcher sees narration, never a command, never an output, never an error string. The bench never tested this path: `moments_tb` were pre-rendered to text by `extract_tb.py:783-794`, own moments were narration from inspect logs. In production the repeat sense keys on short narration prefixes, the plateau sense (`(\d+)% fixed`, `:147`) is dead, and the error sense reads the agent's adjectives.
4. **No hook-noise filter.** `dk_watch.py` drops `<system-reminder>`, `<local-command-stdout>`, `<task-notification>` etc. (`variants_arc_patch_dk_watch.py:352-357`); the watcher drops nothing. Its own `<self-steering>` block is injected into the next user prompt by `dk_recall.sh:93` and comes back as user text. It will read its own previous alert as the user speaking. The 23 dk-arm moments already show this shape.
5. **`seen` is an index into a filtered list.** If the file is rewritten, compacted, or a filter changes, the delta is wrong; if `seen > len(msgs)` the watcher is silent forever (`:190-192`). No reset.
6. **Head truncation.** `PER_MSG=1200` head-cuts (`:193`). The task statement after 7KB of system reminders is lost (56/56 own, 24/57 ATIF); long outputs lose their tail, where the error is.
7. **JSON parsing.** Greedy `\{.*\}` (`:207`): any `}` after the object breaks the parse; parse failure is silent quiet with `seen` advanced (`:208`, `:214`); `notes: null` becomes the string `"None"` (`:215`); `max_tokens=2000` against a 3000-char notes field plus expectations can truncate the JSON, also silent. With reasoning, OpenRouter can return empty `content` (log.md 2026-09-05 checked one case).
8. **Lookup** pastes raw web text into the second prompt (`:233-234`), a prompt-injection path into an intervention; and `grounded` never reaches results.
9. **Latency.** Up to 110s + 30s + 110s per Stop (`:24`, `:85`, `:174`), in the background, with no lock, so looks overlap.

---

## 5. Ranked changes most likely to make it say what a human would say

Judgment-only. No counters, thresholds or gates.

1. **Give it the task and the rules at every look.** Put the first real user message (after the reminders), in full, into every turn as a fixed GOAL/CONSTRAINTS section, and ask the watcher to hold each look against it. Directly targets the zero-of-seventy frame-widening result (verdicts 1, 65, 9, 50). Today it cannot question task compliance because it has not read the task.
2. **Show it what the agent did, not what it said.** Render `tool_use` and `tool_result` in `read_transcript` the way `extract_tb.render_turn` does (`extract_tb.py:783-794`), clipping head+tail so error lines survive. The facts the reader found "one level down" (a tab in `old_string`, a 261-byte PNG, the bot-check tail, the harness's `re.sub` loop in `check.py`) are all in tool output. This also fixes production item 3.
3. **Change the standard for speaking, in the prompt.** Ask the watcher to write the fact the agent has not seen or the claim the record contradicts, and to stay silent when all it can say is what the last output said or what the agent already said it would do next. Add its own check: "what would the agent do differently after reading this?" Forbid questions and encouragement as alerts. This is the reader's own test in verdicts 11, 18, 20, 51, 53 and would remove most of the 14 false alarms.
4. **Make notes carry the arc.** Prompt the notes as overseer memory: proven-by-output vs claimed, open contradictions, abandoned working artifacts, approaches tried and their outcome. The four nested `dk_ep1` alerts show the notes never held "842 passed vs 785 failing" across looks. Keep v2's settle-expectations step, drop its (a)–(e) menu.
5. **Observed vs inferred, before sending.** Have the model mark each sentence as something it saw or something it is guessing, and send guesses only as labelled hypotheses. All four "wrong" alerts (24, 66, 9, 27) are guesses stated as facts.
6. **A stronger watcher model at the same prompt** (TIERS.md item 4). Restating and adopting-the-framing are depth failures; reasoning-on flash got quieter, not sharper. Single-digit dollars on the 104 frontier moments.
7. **Tell it what harness noise looks like** (confirm-bounce on `mark_task_complete`, `(no content)` turns, `No response requested`, the driver's continue) as context, not a filter, so it judges the agent rather than the harness (35, 63, 57).
8. **Run lookup once** on the non-SWE frontier fires. It has never been measured. Ranked low because most partials were "did not read its own output", not "missing external fact", but QMP `send-key`, `ocamlfind` config and the fasttext build are exactly the lookup shape.

Bench fixes that the above depends on: score "same problem named" by reading (already begun); count a fire at any look, not the final one (`replay_bench.py:197-200`); write an empty `.dk_active` before every early return so no verdict carries over (`watcher_session.py:191-192`, `:209-212`); log parse failures as `FAILED` (`:207-208`); fix the `"still failing"` cut (`replay_bench.py:147-148`); pair McNemar on sessions, not nested prefixes; make the error rule match CLAUDE.md; retire `report()`; use the reasoning-on configuration for anything called a judge.