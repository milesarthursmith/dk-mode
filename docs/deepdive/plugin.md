# Deep dive: the shipped plugin (reader report, 2026-09-06)

# dk-mode shipped code: deep dive (read-only)

Vocabulary used below, from docs/SHAPE.md:39-50. **Watcher**: the stateful LLM overseer that is the product. **Senses**: deterministic signals (counts, streaks) that annotate what the watcher reads and never decide anything. **Intervention**: text the watcher injects when it decides to speak. **Guard**: a rule that decides when to intervene; SHAPE says "Not built". **Wedge**: a session stuck in a loop or off-goal.

Headline: the plugin that ships in `hooks/hooks.json` is, component for component, the design SHAPE.md rejects. The stateful watcher (`evals/bench/watcher_session.py`) is not wired to any hook. docs/TESTS.md:20-38 already says this; the code confirms it.

---

## 1. What actually runs on a user's machine

### Hook registration

`hooks/hooks.json` registers three command hooks, all with `DK_MEM="${CLAUDE_PLUGIN_DATA}/memory"`:
- `Stop` -> `scripts/dk_capture.sh` (hooks.json:8)
- `UserPromptSubmit` -> `scripts/dk_recall.sh` (hooks.json:18)
- `PostToolUse` -> `scripts/dk_tripwire.py` (hooks.json:28), no `matcher`, so it fires on every tool including MCP tools.

`${CLAUDE_PLUGIN_DATA}` resolves to `~/.claude/plugins/data/<plugin-id>/` per the Claude Code plugin reference (fetched today). So a plugin install has one memory directory shared by every project on the machine.

The `install.sh` path is the alternative for git installs: it clones into `<target>/.claude/vendor/dk-mode` (install.sh:61,85), seeds memory (105-145), copies the skill (149-152), and merges the same three hooks into `settings.json` (200-243), with `DK_HOME="$HOME"` baked in for `--global` (158,167-168).

### Per-turn data flow, in order

**A. User presses enter -> `dk_recall.sh` (synchronous, blocks the prompt).**
1. Runs `dk_bootstrap.sh` (recall.sh:53). Bootstrap seeds `dk_rules.md` from `templates/dk_rules.md` plus the 23 baseline items and a pre-rendered five-line inject block on first use only (bootstrap.sh:19-48).
2. Reads the hook payload from stdin, extracts `session_id` with grep/sed, truncates to 16 chars (recall.sh:65,79-80).
3. If `.dk_active.<session>` exists, is younger than `DK_ACTIVE_TTL` (3600 s) and is non-empty, prints it verbatim (recall.sh:81-96). Otherwise prints the block between `<!-- inject:start -->` and `<!-- inject:end -->` in `dk_rules.md` (recall.sh:98-101). That static block is five model- or template-written reminder lines.
4. Appends warning lines by rule: no captures in 21+ days (105-114), N pending items (118-124), watcher failed 3+ times (128-131), consolidator failed 3+ times (134-137).
5. If a key or keyless backend is available, unprocessed lines exist in `dk.jsonl`, and the interval (default 7 d) has elapsed, spawns `dk_consolidate.py` with `nohup` (162-195).
6. Everything it prints becomes context the agent reads. Confirmed against the Claude Code hooks doc: for `UserPromptSubmit`, "Claude Code adds plain-text stdout as context that Claude can see and act on".

No model call here. No python unless bootstrap seeds.

**B. Agent runs tools -> `dk_tripwire.py` after every tool call (synchronous).**
1. Reads payload, opens `.dk_trip.<session16>` JSON (tripwire.py:57-73).
2. Counts: SHA-1 of `(tool, sorted tool_input)` (86-96); reads without a write (103-107); a "failed test" flag set when the input text matches a test-runner name and the output matches a failure regex (109-110).
3. Fires each of three warnings at most once per state file (115-136) and returns it as `hookSpecificOutput.additionalContext` wrapped in `<self-steering>` (153-157). That text is appended to the tool result the agent reads.
4. No model call. No lock on the state file.

**C. Agent stops -> `dk_capture.sh` (synchronous, returns in ms) -> `dk_watch.py` (detached).**
1. Capture runs bootstrap again (capture.sh:45), extracts `transcript_path` and `session_id` by grep/sed (51,59), deletes the tripwire state file (66), then `nohup`s `dk_watch.py <transcript>` with `DK_SESSION_ID` set (70-75). It prints nothing; Stop stdout goes to the debug log only (hooks doc).
2. `dk_watch.py` resolves `MEM`, per-session `ACTIVE` and `BRIEF` paths (watch.py:76-90), takes a memory-wide lock `.dk-watch.lock` and exits silently if held (92, 800-809).
3. Reads the whole transcript, keeps only `user`/`assistant` text blocks, drops `isSidechain`/`isMeta` and any message containing one of eight harness marker strings, and truncates each message to 1500 chars (367-409).
4. Builds the window: newest 10 assistant messages in full, the next 90 digested to 160 chars, interleaved user messages in full, capped at 26,000 chars (320-354, 128-131).
5. Loads selectable rules from `dk_rules.md`: approved items above `## Retired`, capped at 40 with mined items kept over baseline (244-288).
6. One model call: `PROMPT` (412-488) with brief, numbered rules, and the window. Default backend Anthropic Messages, model `claude-haiku-4-5-20251001`, `temperature 0`, `max_tokens 2000`, timeout 120 s, no thinking parameter on the Anthropic path (110-113, 541-548). Reasoning is only sendable on the OpenAI-format path (535-536).
7. Parses JSON: `active` ids, `alert` (kept up to 600 chars), `steering` ids, `brief` (707-741).
8. Writes `.dk_brief.<session>` with `GOAL:` forced to the first user message's first 300 chars (210-241, 861).
9. Writes `.dk_active.<session>` = `render()` output: the alert first, then `(standing rule: <heading> - <reminder> earned by: <evidence[:240]>)` per active id, or an empty file when nothing is live (744-766, 868-869).
10. Appends mined steering messages, redacted, with up to three preceding messages, to `dk.jsonl` and a line to `log.md` under `.dk.lock` (620-704, 870-871).
11. Writes `.dk_state` health keys and a line to `dk_watch.log` under `~/Library/Logs` or `~/.claude/logs` (143-182, 872-873).

**D. Every 7 days (default) -> `dk_consolidate.py` (detached).**
1. Sends the entire current `dk_rules.md` plus up to 200 raw `dk.jsonl` lines to a model and asks for the whole file rewritten (consolidate.py:261-318, 545-565). Default models `claude-fable-5,claude-opus-5`, `max_tokens 8000` (131-132, 389).
2. Structurally validates the reply (473-498), optionally auto-approves items with `Count >= 3` (501-538), and atomically replaces `dk_rules.md` (588-592). The five lines inside the inject block, which step A.3 pastes into every prompt of every session, are written by this model.

### What gets injected into the agent, and when

| Path | Text | Author | When |
|---|---|---|---|
| UserPromptSubmit stdout | alert (<=600 chars) + standing-rule lines | Haiku free text + rules file | Next prompt after the turn the watcher judged; up to 3600 s stale |
| UserPromptSubmit stdout | 5-line static note | consolidator model, or baseline template | Every prompt where the live file is absent, stale, or empty |
| UserPromptSubmit stdout | 4 warning lines | shell script | By threshold rules |
| PostToolUse additionalContext | 3 fixed warnings | script constants | When a counter crosses a threshold |

---

## 2. Where the shipped code contradicts SHAPE.md and rule one

**2.1 `dk_tripwire.py` is the retired guard, shipped.** SHAPE.md:48-50 defines the guard as "a rule that decides when to intervene. Not built." SHAPE.md:91-93 rejects "counter-gated architectures". `dk_tripwire.py:115-136` is exactly that: `count >= REPEAT_LIMIT` injects; `reads >= 12` injects; `write to test path after failed test` injects. No model anywhere. It is registered in `hooks/hooks.json:23-31` and has seven green tests (tests 108-114). CLAUDE.md §1 says "If you catch yourself writing `if pct > ...: label = ...`, stop." `dk_tripwire.py:115` is that line.

Its counts are never fed to the watcher as senses. Nothing in `scripts/` reads `.dk_trip.*` except the tripwire itself (grep confirmed), and `dk_capture.sh:66` deletes the file before launching the watcher at line 72. So even the one legitimate use of these counts under SHAPE (annotate the delta) is closed by ordering.

What would have to change: stop returning `additionalContext`; write the counts to a per-session sense file; have the watcher read them into `[sense: ...]` lines; delete the three warning strings. Or delete the hook.

**2.2 `dk_watch.py` is the "stateless per-stop judging" SHAPE declares dead.** SHAPE.md:54-57: "One continuous monitor conversation per agent session... never a fresh judge shown a snapshot." SHAPE.md:94-97: "the dk_watch v1/v2 design... that design is dead." `dk_watch.py` makes one fresh single-message request per Stop (840-846). Its only memory is a model-written 1200-char brief it rewrites every turn (233-241). The prompt carries the silence-biased prior SHAPE names: "The correct answer is usually an empty list" (445-446), and forbids exactly the arc-based findings SHAPE wants: "Not a risk, not a tendency, not something the agent is 'about to' do" (440-441). There are no expectations, no credibility tracking, no lookup (SHAPE.md:63-83), no `[sense:` annotations (grep confirmed).

The prototype that matches SHAPE exists at `evals/bench/watcher_session.py:1-60` with the same CLI contract, but no hook points at it.

What would have to change: replace the Stop-hook target with a watcher whose conversation persists per session (messages array on disk, delta-only input, notes as memory), remove the rules-list-selection framing, and move MAX_ACTIVE/alert truncation/silence prior out of the code path.

**2.3 `dk_recall.sh` overrides the judge's silence with a scheduled fixed text.** SHAPE.md:98-99 rejects "Scheduled fixed-text injection as the product mechanism." SHAPE.md:59-63: nothing mechanical decides whether the watcher speaks. `dk_recall.sh:87-101`: an empty live verdict (the model decided nothing is wrong) falls through to the static five-line note, every prompt. docs/TESTS.md:11-16 records this as a deliberate 2026-08-31 change, and test 55 (tests:586-596) now asserts it. So the shipped product speaks on every prompt regardless of judgment. The TTL rule at recall.sh:82-86 is a second mechanical decider: a verdict older than 3600 s is thrown away by clock, not by judgment.

What would have to change: silence means silence. Delete the static-note path (or make its use a watcher decision), delete the TTL.

**2.4 A lock decides whether the watcher runs at all.** SHAPE.md:61: senses "never decide whether the watcher runs". `dk_watch.py:92,800-809`: a memory-wide `.dk-watch.lock`; if another watcher (from any session sharing the plugin data dir) is mid-call, this turn is skipped with no log and no `mark()`. Under a plugin install every project shares one MEM, so two concurrent sessions silently drop each other's looks.

**2.5 Counters decide what becomes a standing rule and what is injected.** `dk_consolidate.py:501-538` auto-approves at `Count >= 3` (default off, but documented as the "no human in the loop" mode, README:293). `dk_review.py:112-133` builds the every-prompt note as "top 5 by Count then recency". The consolidator prompt retires by "older than 60 days and Count under 3" (consolidate.py:298-300). `dk_watch.py:282-287` drops rules by a mined-first sort at 40. Each is a mechanical proxy for "what matters".

**2.6 The watcher cannot use reasoning on the default backend.** CLAUDE.md §3: "Judge/watcher runs must use reasoning on... A judge without reasoning is not a judge." `dk_watch.py:541-544` sends no `thinking` field on the Anthropic path; `DK_REASONING_EFFORT` is only wired for the OpenAI format (535-536).

---

## 3. Bugs, silent failure paths, races, injection, secrets, platform

**3.1 The test-edit tripwire can never fire live.** `dk_tripwire.py:150-151` reads `payload.get("tool_output", "")`. The Claude Code payload key is `tool_response`: the installed binary `/opt/claude-code/bin/claude` contains `tool_response` (including the zod schema `tool_response:se().optional()`) and zero occurrences of `tool_output`. So `FAILED.search("")` never matches, `failed_test` is never set, and the "editing a test file" warning (130-136) is dead. Tests pass because the fixtures feed `tool_output` (tests:1441, 1518). README:41-44 and MECHANISM.md:264-268 advertise three tripwires; two exist.

**3.2 Tripwire state races and pollutes.** Load/modify/save with no lock (66-83). Claude Code runs parallel tool calls and their PostToolUse hooks concurrently, so counters lose updates. Subagent tool calls also fire PostToolUse (likely with the parent `session_id`; unverified) so a subagent's reads count toward the parent's "12 reads without a write". An Esc interrupt does not fire Stop, so `dk_capture.sh:66` never resets and counts carry into the next turn. Legitimate patterns trip it: `git status` three times across three edits is "repeating with no new information" (115-121); twelve `Grep`/`Read` calls in a research task is "not converging" (123-128).

**3.3 Stale and lagging verdicts.** On a malformed reply the old `.dk_active` is left in place (watch.py:855-857, test 58) and re-injected on every prompt for up to an hour with the header "relevant to what you are doing right now". If the user sends the next prompt before the detached watcher finishes (Haiku takes seconds; timeout 120 s), recall reads the verdict about the turn before last. There is no turn stamp on the file to detect this.

**3.4 "Delete dk_rules.md to switch off" does not switch off.** MECHANISM.md:446 and bootstrap.sh:16-20 make the missing file the off switch. But `dk_watch.py` treats missing rules as `[]` (249-250, 811-814), still calls the model every Stop, still mines into `dk.jsonl`, and still writes an alert to `.dk_active` when `parsed[1]` is set (868-869). `dk_recall.sh:84-97` prints `.dk_active` without checking `RULES`. So spending and injection continue with the rules file deleted; only the static note stops.

**3.5 Consolidation fails permanently as the file grows.** The model must return the whole `dk_rules.md` within `max_tokens 8000` (consolidate.py:389). Past roughly 25-30k chars of rules the reply truncates, `validate()` reports a missing section (477-481), the run is marked FAILED, retried daily (recall.sh:185-187), and after three failures a warning line is injected into every prompt forever (recall.sh:134-137). Input side: 200 entries times up to ~3.6k chars each (text 600 + verbatim 600 + lead-up 2400, watch.py:637,663-665) is ~180k tokens per batch.

**3.6 The consolidator can silently rewrite history.** `validate()` (473-498) checks frontmatter, six markers, one inject block, line count. It does not check that existing items, counts, or Evidence quotes survive. The prompt says "NEVER invent" (293-294); nothing enforces it. README:343-347 and MECHANISM.md:376-380 claim the model "cannot write text". The Reminder lines and the every-prompt inject block are model-written.

**3.7 Prompt-injection paths from transcript content into the agent's prompt.**
- Assistant text blocks are in the window (watch.py:390-391), so anything the agent quoted from a web page or file reaches Haiku, whose free-text `alert` (up to 600 chars, 735) is pasted into the agent's next prompt inside `<self-steering>` (756-757) with no sanitisation.
- User messages, which include pasted content, are mined into `dk.jsonl` and quoted as `earned by:` in the injection (762) and become consolidator input; consolidator output becomes the standing note for every session on the machine.
- The marker filter (394-404) is a substring blacklist. A genuine correction that quotes `<system-reminder>` is dropped whole; a harness message using a marker not in the list is mined as the user's words. Both are the misattribution failure the list exists to prevent.

**3.8 Secrets.**
- Redaction runs only when writing `dk.jsonl` (663-665). The window sent to the model provider (845-846), the model-written brief on disk (241), and the injected alert are unredacted. README:176-183 recommends OpenRouter as a provider, so pasted keys leave the machine for a third party by design.
- README:192 says "Put the same variables into the three hook commands in your settings file", i.e. a key in `.claude/settings.json`. This repo's own `.gitignore:7-8` un-ignores `.claude/settings.json`. Following the README commits the key.
- For a plugin install the hook commands live inside the plugin (`hooks.json`), so the key can only come from the environment Claude Code was launched from. Neither README nor MECHANISM says so.

**3.9 `DK_BACKEND=cli` recursion and self-mining.** README:277 recommends `cli`. Each Stop then runs `claude -p` (watch.py:506-509). With the plugin installed, that nested session fires its own Stop hook, which launches another watcher, which is blocked only because the outer watcher holds the global lock (807). The recursion is bounded by accident. The nested `claude -p` transcripts land in `~/.claude/projects`, which `dk_backfill.sh:30` sweeps in full, so the watcher's own prompts get mined later as "user" steering. `dk_watch.py:500-502` and `dk_consolidate.py:19-20` both say not to use `cli` for the per-turn hook; the README says the opposite.

**3.10 Model id risk.** Watcher default `claude-haiku-4-5-20251001` (watch.py:113) is a date-suffixed id; the current model table lists `claude-haiku-4-5`. If the dated alias is not served, every turn is HTTP 404, the watcher is dead, and after three turns a warning line goes into every prompt. Verify with one call. Consolidator defaults `claude-fable-5,claude-opus-5` are current ids.

**3.11 `/dk-review` cannot work under the plugin install.** `skills/dk-review/SKILL.md:13` hardcodes `$CLAUDE_PROJECT_DIR/.claude/vendor/dk-mode/scripts/dk_review.py`, which only exists after `install.sh`. README:117-118 and 217 say the plugin carries a working `/dk-review`. `dk_review.py` would also need `DK_MEM` to find plugin memory; the skill passes nothing.

**3.12 Shared "nosession" files.** If `session_id` is absent from a payload, every such session shares `.dk_active.nosession`, `.dk_brief.nosession`, `.dk_trip.nosession` (watch.py:79, recall.sh:80, tripwire.py:63). That is the cross-chat leak the per-session scoping was added to stop.

**3.13 GOAL is frozen to the first message.** `first_request()` (210-222) takes the first non-filtered user message, 300 chars. A session opened with "hi" or a pasted log carries that as GOAL for its life, and the prompt forbids the model from changing it (431-433). Drift detection then measures drift from the wrong goal.

**3.14 Nag by clock.** `dk_recall.sh:105-114` injects "no captures in N days" into every prompt once `dk.jsonl` is 21 days old. A user whose history is clean and whose system works gets this line on every prompt forever.

**3.15 Platform assumptions.** Transcript path is extracted by grep/sed on raw JSON (capture.sh:51); escaped characters or Windows backslash paths break it. `nohup`, `disown`, `stat -c`/`stat -f` fallback (recall.sh:61), and `bash` are assumed. Older Claude Code without `CLAUDE_PLUGIN_DATA` makes `DK_MEM="/memory"`; bootstrap fails `mkdir`, capture exits at line 46, watch returns at 787, recall prints nothing. A silent no-op with no log.

**3.16 Repo-local dev hook.** `.claude/settings.json` in this repo registers `.claude/hooks/inject_rules.sh`, which pastes CLAUDE.md §1-2 into every prompt. Not shipped by the plugin, but it is the "scheduled fixed-text" mechanism the repo rejects, used to keep the assistant on rule one.

---

## 4. README promises versus code

| README / MECHANISM claim | Code |
|---|---|
| "puts the applicable rule in front of Claude at the moment Claude is about to break it" (README:3-5, 349-350; plugin.json:18) | One turn late by design (watch.py:19-25); prompt forbids "about to" findings (440-441) |
| "The per-turn model reads the last two exchanges", `DK_WATCH_CHARS` default 9000 (README:82, 298-299; MECHANISM:310-320) | Live window is 100 assistant messages, 26,000 chars (watch.py:117-131); exchanges are backfill-only |
| Alert "up to 200 characters" (README:349) | 600 (watch.py:735) |
| "A model in dk-mode cannot invent a rule... replies with numbers only" (README:343-347; MECHANISM:376-380) | True for `active` ids only; consolidator writes all rule text and the every-prompt note (consolidate.py:301-306); validation is structural (473-498) |
| "When nothing applies, Claude reads nothing" (MECHANISM:194-196, 225, 422-423) | Empty verdict injects the static note (recall.sh:87-101) |
| "There is no file to edit and no settings to merge" (README:117-119) | README:192 then requires editing hook commands; for a plugin the key must come from the launch environment, unstated |
| "Use `cli` unless you have a reason not to" (README:277) | "Not recommended for the per-turn hook" (watch.py:500-502); "never the `claude` CLI" (consolidate.py:19-20) |
| Three tripwires (README:41-44; MECHANISM:264-268) | Test-edit tripwire dead: wrong payload key (tripwire.py:151) |
| "/dk-review command does the same steps" (README:217) | Skill path exists only for `install.sh` installs (SKILL.md:13) |
| "To switch dk-mode off, delete dk_rules.md" (MECHANISM:446) | Watcher still calls the model and injects alerts (watch.py:811-814, 868-869; recall.sh:84-97) |
| Injection format with `!`, `*`, `so:` "is a copy of a real run" (MECHANISM:202-212) | `render()` produces alert + `(standing rule: ...)` (watch.py:760-766) |
| "sends the last 6 messages" (MECHANISM:427) | Stale, see above |
| Cost "up to about 3,600 tokens", Haiku ~$16/month (README:267-275; MECHANISM:452-458) | Roughly double, see §5 |
| Credentials removed "before it writes" (README:333-336) | Only for `dk.jsonl`; model request, brief, alert unredacted |

MECHANISM.md:277-279 admits `additionalContext` delivery was unobserved; docs/log.md:359 later records tripwire fires in the hooked eval, so delivery works. That line should be updated.

---

## 5. Cost and latency per turn, as the code stands

**Watcher call, every Stop.** Measured fixed parts: instruction template 3,945 chars (~990 tokens); 23 baseline rules rendered as `id. heading - looks_like` 3,472 chars (~870 tokens); brief up to 1,200 chars (~300). Window: 10 full messages at up to 1,500 chars, up to 90 digest lines at ~165 chars, interleaved user messages, capped at 26,000 chars (~6,500 tokens). Realistic total 6,000-9,000 input tokens; output 300-500 (JSON plus a brief up to 1,000 chars). No prompt caching is requested, and the volatile brief sits before the rules (PROMPT order 480-487), so a cache prefix would not survive anyway.

At Haiku 4.5 rates ($1 in / $5 out per MTok): ~$0.008-0.012 per turn. At 100 turns a day: ~$24-36 a month, versus the README's $16. With `DK_WATCH_MODELS=claude-sonnet-5` ($2/$10): ~$0.016-0.023 per turn, ~$50-70 a month. The call runs detached after Stop, so the user does not wait for it; it can take up to 120 s (`TIMEOUT`) and its result is only read at the next prompt.

**Consolidation.** Default every 7 days, or every prompt with `DK_INTERVAL=per-turn`. Input is the whole rules file plus up to 200 entries at ~3.6k chars each, up to ~190k tokens; output up to 8,000 tokens. On `claude-fable-5` ($10/$50): up to ~$2.3 per full batch, ~$0.1-0.2 for a typical ten-entry batch. Opus 5 fallback is half that.

**Hook latency on the agent's critical path.**
- `UserPromptSubmit`: two bash processes plus a handful of `grep`/`stat` calls, ~20-50 ms, before the model sees the prompt.
- `PostToolUse`: one `python3` start plus JSON read/write per tool call, ~30-80 ms, and the tool result waits for it. On a 25-tool-call turn that is roughly 1-2 s added. With `DK_BACKEND=cli`, each Stop additionally starts a nested `claude` process, several seconds, and consumes subscription quota, so "costs nothing" (README:273) is about dollars only.
- `Stop`: two bash processes and a `nohup` spawn, ~20-40 ms. The watcher reads the entire transcript into memory every Stop (watch.py:371-372), so cost grows with session length.

**Context cost to the agent.** The static note is ~100 tokens on every prompt in every session (recall.sh:98-101). An alert plus up to three standing rules with evidence is up to ~400 tokens. The tripwire adds ~60 tokens per fire.

---

## Files referenced

- /home/user/dk-mode/hooks/hooks.json
- /home/user/dk-mode/install.sh
- /home/user/dk-mode/scripts/dk_capture.sh, dk_recall.sh, dk_bootstrap.sh, dk_backfill.sh, dk_smoketest.sh
- /home/user/dk-mode/scripts/dk_watch.py, dk_tripwire.py, dk_consolidate.py, dk_review.py, dk_signal.py, dk_replay.py
- /home/user/dk-mode/skills/dk-review/SKILL.md
- /home/user/dk-mode/templates/dk_rules.md, baseline_rules.md
- /home/user/dk-mode/README.md, docs/MECHANISM.md, docs/SHAPE.md, docs/TESTS.md, CLAUDE.md
- /home/user/dk-mode/tests/run_dk_tests.sh (tests 53-63, 99-102, 108-114)
- /home/user/dk-mode/evals/bench/watcher_session.py (the SHAPE prototype, unwired)
- /home/user/dk-mode/.gitignore, .claude/settings.json, .claude/hooks/inject_rules.sh

Verification sources outside the repo: Claude Code hooks and plugins reference pages (fetched 2026-09-06) for `CLAUDE_PLUGIN_DATA` semantics and `UserPromptSubmit`/`Stop` stdout handling; the local `/opt/claude-code/bin/claude` bundle for the `tool_response` field name; the claude-api skill's model table for ids and prices.