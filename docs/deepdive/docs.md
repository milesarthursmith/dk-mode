# Deep dive: documentation and strategy drift (reader report, 2026-09-06)

I have everything I need. Here is the deep dive.

---

# dk-mode documentation and strategy layer: deep dive

Terms used below. A **wedge** is a stretch where the coding agent is stuck but keeps working (repeating an edit, chasing the wrong region). A **moment** is a frozen transcript prefix used by the replay bench. A **sense** is a deterministic signal (a repeat count, an error streak) shown to the watcher as an annotation. The **watcher** is the stateful LLM overseer that SHAPE.md says is the product. The **counter** is the free, rule-only baseline (`evals/bench/baseline_counter.py`).

## 1. The story the docs tell, and where they disagree

### In order

**08-24/25: a self-steering memory.** First commit `2829975 2026-08-25 "dk-mode v0.1.0: self-steering memory for Claude Code"`. The design decisions (`docs/log.md:1313-1343`) are: recall forced onto the prompt by a `UserPromptSubmit` hook; a "relevance model" one turn behind on `Stop`; "Select, do not write" (`log.md:1325-1327`); collect too much, filter later; auto-approval after `DK_AUTO_APPROVE_COUNT` recurrences (`log.md:1334-1338`). The product is: mine the user's corrections, sort them into rules, inject the applicable rule.

**08-25/26: phrase matching dies.** The regex phrase list found "0 of 46 real corrections" (`log.md:1258-1265`). Mining moves to a model. Deleting the phrase pass exposed three wiring bugs, including that the live selection "was never once consumed" (`log.md:1214-1216`).

**08-27: the product that still ships.** Baseline rules (23) added (`log.md:1165-1184`). Shipped as a plugin (`7b2847b`). The tripwire is added ("Speak during a turn", `f994c1f`) and hooks.json gets its third entry. The running brief is added (`c05c9ad`). README and MECHANISM are rewritten in Simplified Technical English (`log.md:1131-1141`; last README commit `1d270d1 2026-08-27`). The old eval harness is deleted and EVALS.md designs its replacement: "No hand labels anywhere in this design" (`docs/EVALS.md:7`), Haiku as agent (`EVALS.md:37-51`), a scheduled `challenge-N` control (`EVALS.md:92-99`).

**08-28: selectivity is false.** First paid run: the monitor fired on 92% of generations (`log.md:1002-1008`). The prompt is gated so "the last assistant message [must] BE the violation" (`log.md:1021-1025`; commit `bc26cf1`). On the maths band, dk ties the dumb schedule (`log.md:957-975`).

**08-29: the gate is reversed, every instrument nulls.** The 08-28 gate "bought the 92%->46% fire-rate fix by making the monitor myopic ... arc rules had been structurally disabled" (`log.md:722-726`). A tiered 100-message window replaces it (`log.md:731-740`; `c6aa992`). Payload ablation: nothing beats "Try harder." (`log.md:837-858`). Reasoning-model monitor: "buys nothing" (`log.md:791-795`). Real-hooks LiveCodeBench: "Nothing separates" (`log.md:607-616`).

**08-30/31: the deterministic layer looks like the value.** SWE-bench three-arm, then replication: "the per-turn model call that selects WHAT to inject ... has never once separated from a dumb scheduled nudge. The honest product conclusion: the value, if any, lives in the deterministic layer (static note + tripwire, which cost nothing), not in the monitor" (`log.md:486-490`). Trace analysis: "cadence beats diagnosis" (`log.md:437-444`). The muting bug: an empty verdict suppressed the static note (`log.md:392-400`). The goal-mode marathon: live layer "SILENT for both dk marathons" through a six-attempt wedge, balance $0.75 (`log.md:359-365, 379`).

**09-01: three positions in one day.** Morning: "the user was right: the evals ran a stale build, and the current one catches the wedge" (`log.md:278-324`), with "Standing corrections to previous conclusions" (`log.md:313-319`). Afternoon: the replay bench says that story "is WRONG at n=10: the current build is the worst variant on both axes" (`log.md:257-263`), and concludes "the TRIGGER should be a deterministic counter ... with the model composing only the alert text" (`log.md:271-275`). That becomes `docs/redesign.md`'s "v2 architecture" (`0c91089`: "Deterministic triggers (Tier A)... The model composes, never judges (Tier C)"). Same day, `ee062ad` writes SHAPE.md: "a stateful LLM watcher ... non-negotiable" (`docs/SHAPE.md:1-5`) and marks redesign's architecture superseded (`docs/redesign.md:44-53`).

**09-02: bench machinery.** Vocabulary and lookup added to SHAPE (`c539279`, `9cc0834`). HANDOVER.md written (`6983c5b`, dated "as of 2026-09-01" at `docs/HANDOVER.md:1`). Terminal-Bench 2 corpus mined, "all process-labeled" (`log.md:230-232`). The counter "sets the bar" (`log.md:208-219`). Stage 1: watcher vs counter p=0.12, "kill criterion NOT cleared as written" (`log.md:188-201`). Cadence: "not the lever" (`log.md:153-170`).

**09-03:** a selectivity-first prompt "costs recall, buys nothing"; "none beats the $0 counter on frontier-agent semantic wedges" (`log.md:132-134`).

**09-05: labels replaced by judgment.** "The bench's ground truth was wrong in kind" (`log.md:35-40`). Four LLM-subagent readers relabel 160 moments; they disagree with the prefixes on 48 (`log.md:42-61, 108`). Rescored: watcher 48/78 vs counter 31/78, p=0.005; "The stage-1 kill criterion ... is met on the full corpus" (`log.md:67-88`). Reasoning ON is worse (`log.md:91-105`). CLAUDE.md is added with rule one (`99342eb`). The same day, one commit earlier, `a0c62ef "bench: healthy = new high-water mark; 3 plateau-bounce moments dropped"` changed a labelling rule.

**09-06: the funnel and the tests are challenged.** TIERS.md: the tier-1 pass "is carried by the easy corpus"; on frontier agents 23/40 vs 16/40, p=0.19 (`docs/TIERS.md:26-45`); "the bar silently became the counter" (`TIERS.md:49`); alert quality by reading: 24 same / 20 partial / 4 wrong of 48; "the honest tier-1 number is not 48 of 78. It is 24 of 78" (`TIERS.md:195-196`); "It never widened the frame" (`TIERS.md:189`). TESTS.md: the suite was red for six days; it "certifies the design SHAPE.md rejects" (`docs/TESTS.md:20-38`); the watcher "has zero tests" (`TESTS.md:35`).

**What it is now.** `hooks/hooks.json:8,18,28` ships `dk_capture.sh` -> `dk_watch.py` (`scripts/dk_capture.sh:72`), `dk_recall.sh`, and `dk_tripwire.py`. That is the 08-27 design: a stateless per-stop rule selector, a static note, and a counter guard. SHAPE calls the first "dead" (`SHAPE.md:94-97`) and the third "Not built" (`SHAPE.md:48-49`). The product per SHAPE, `evals/bench/watcher_session.py`, is not wired to any hook, has no tests, and has only been run on frozen transcripts.

### Where the docs disagree about what the product is

| Doc | What the product is |
|---|---|
| `README.md:3-5` | "holds a set of rules about how it goes wrong, and puts the applicable rule in front of Claude at the moment Claude is about to break it." Four things: baseline rules, mining, per-turn reminder, mid-turn tripwires (`README.md:19-44`). |
| `.claude-plugin/plugin.json` description | "Ships 23 known agent failure modes ... puts the applicable rule in front of Claude". |
| `docs/MECHANISM.md:46-48` | "an out-of-band runtime monitor over an agent's trace, with an episodic memory consolidated from past corrections, which injects a critic's note into the next prompt." |
| `docs/EVALS.md:91, 159-166` | The thing under test is "the monitor's selection + alert, as shipped"; the knobs are "The monitor prompt in dk_watch.py" and "The rule texts in templates/baseline_rules.md". |
| `docs/redesign.md:44-53` (as first written) | Deterministic triggers gate; model composes. Now marked superseded. |
| `docs/SHAPE.md:3-5` | "an LLM watching the session evolve ... This is the product. Everything else in the repo serves it." |
| `docs/HANDOVER.md:5-8` | "Can I replace myself with another LLM?" A stateful watcher. |
| `CLAUDE.md:8-12` | "a stateful LLM watcher whose JUDGMENT decides." |

README does not link SHAPE.md. Its "More information" section lists only `docs/log.md` and `docs/MECHANISM.md` (`README.md:363-366`). MECHANISM does not mention the watcher, senses, notes, or SHAPE at all (grep: 0 hits for "watcher" or "senses" in MECHANISM.md). So the two documents a newcomer reads first describe the design the spec rejects, and neither says so.

## 2. Claims in README.md and MECHANISM.md the code does not support, or SHAPE.md has rejected

### README.md

1. `README.md:37-39`: "After each turn, a model examines the conversation and decides which rules apply. dk-mode puts those rules into the next message." This is the stateless per-stop judge. `SHAPE.md:94-97`: "Stateless per-stop judging (the dk_watch v1/v2 design) ... that design is dead." Still shipped: `hooks.json:8` -> `dk_capture.sh:72`.

2. `README.md:41-44`: "A second hook runs after every tool call and uses no model. It has three tripwires it can see without one." A count decides to inject (`scripts/dk_tripwire.py:115-136`). `SHAPE.md:48-49`: "guard (retired) - a rule that decides when to intervene. Not built." SHAPE is wrong that it is not built; README is wrong that it is the design. `TESTS.md:28-34` records the contradiction.

3. `README.md:81-82`: "The per-turn model reads the last two exchanges." Code: `scripts/dk_watch.py:115-119` says `DK_WATCH_EXCHANGES` is "Used by the backfill path only; the live window is recent_work() below", a tiered window over 100 assistant messages (`dk_watch.py:120-131`). Changed 08-29 (`log.md:731-740`). README last touched 08-27.

4. `README.md:267-269`: "sends up to about 3,600 tokens ... up to 2,250 of conversation"; `README.md:299`: `DK_WATCH_CHARS` default "9000". Code: `WINDOW_CHARS` default `26000` (`dk_watch.py:131`). The cost table (`README.md:271-275`) is built on the stale number.

5. `README.md:349-352`: the model "may add a single sentence of its own, up to 200 characters ... the only text dk-mode injects that you did not write." Code: cap is 600 (`dk_watch.py:735`; commit `74ce121 "alert cap 300 -> 600"`), the alert is mandatory whenever a rule is selected (`dk_watch.py:448-449`), and it leads the injected block (`dk_watch.py:756-757`). The model-written line is now the main text, not the exception.

6. `README.md:343-346`: "The per-turn model ... replies with numbers only. The text of the reminder comes from your file." Same issue: the rendered block is the model's directive first, then a parenthesised rule line (`dk_watch.py:758-763`).

7. `README.md:7-8`: "23 rules ship with it, so it works on the first day." No measurement supports "works". `log.md:486-490`: the selection layer "has never once separated from a dumb scheduled nudge"; `log.md:607-628`: real-hooks run, "Nothing separates." README mentions none of the nulls.

8. `README.md:157-168` says `DK_BACKEND=cli` covers "two different model calls". `scripts/dk_consolidate.py:19-21` says "never the `claude` CLI (headless CLI auth is unreliable in automation)". The consolidator's code does support cli (`dk_consolidate.py:325, 365`); its own docstring contradicts it. Small, but it shows the docstrings are not maintained either.

### MECHANISM.md

9. `MECHANISM.md:33` names `dk_watch.py` the "runtime monitor" and `MECHANISM.md:46-48` defines the product by it. Rejected by `SHAPE.md:94-97`.

10. `MECHANISM.md:194-196`: "An **empty** live selection is a real answer ... the script prints nothing. This is the normal result." Also `MECHANISM.md:225-227` and `MECHANISM.md:423`: "Usually the file is empty and the script prints nothing." Code since 08-31: an empty selection "must not mute the static note ... Empty falls through" (`scripts/dk_recall.sh:87-95`). The static note is injected on every prompt with no live selection. Test 55 asserts this (`tests/run_dk_tests.sh:585`). MECHANISM documents the muting bug as the design.

11. `MECHANISM.md:202-223`: the block format `! alert / * rule name / what it looks like: / so:` is "a copy of a real run, not an example written by hand." Code `render()` produces alert first, then `(standing rule: <heading> - <reminder> / earned by: ...)` (`dk_watch.py:756-766`; changed 08-29, `log.md:815-824`). The documented block cannot be produced by the shipped code.

12. `MECHANISM.md:277-279`: "What has not been observed is Claude Code actually delivering `additionalContext` into a live turn." Observed 08-30 under real Claude Code: "the dk arm carried 44 static, 38 tripwire and 5 live monitor injections" (`log.md:500-502`). Stale "not proven".

13. `MECHANISM.md:301-308` (window "up to 2,250 tokens"), `MECHANISM.md:318-320` ("9,000 characters"), and `MECHANISM.md:427` ("sends the last 6 messages") give three different windows in one document. None is the shipped tiered window (`dk_watch.py:320-332`).

14. `MECHANISM.md:361-364, 376-383`: "answers with **numbers only**, and at most three ... A model in dk-mode can point at text. It cannot write text." The 600-char mandatory directive (`dk_watch.py:448-455, 735`) is written text. The "safety rule" section describes a property the code no longer has.

15. `MECHANISM.md:474-477`: "Nobody has measured how often a rule is selected ... it has never been counted." Counted 08-28 (92%, `log.md:1002-1004`), and on every run after (46%, 28%, 13%, 9%: `log.md:1014-1018, 757, 910, 742`).

16. `MECHANISM.md:257-279`, section 4.5, the tripwire: "It does not need [a model], because the failure modes worth catching inside a turn have signatures a program can see." This is the sentence CLAUDE.md rule one was written against (`CLAUDE.md:8-12`).

17. `MECHANISM.md:38-44`: "Three words this project does NOT use: guardrail, supervisor, steering." The injected tag is `<self-steering>` in every producer (`dk_watch.py:766`, `dk_tripwire.py:156`, `watcher_session.py:245`, `templates/dk_rules.md:16-19`); `scripts/dk_signal.py:2` "record a steering event"; `scripts/dk_review.py:2` "proposed steering items"; `templates/dk_rules.md:2` "Steer - distilled rules". The table of "standard names" (`MECHANISM.md:31-36`) has no row for watcher, senses, notes, expectations, intervention, or lookup.

## 3. Vocabulary drift

Same thing, different names, by file.

**The LLM that reads the session and decides.**
- "relevance model" / "relevance layer": `log.md:1321`, `log.md:1201`, commit `1dcc9a4`, `dk_recall.sh:26, 126` ("RELEVANCE layer"), test 98 ("selectable by the relevance layer", `run_dk_tests.sh:1247`).
- "the miner": `MECHANISM.md:21`, `README.md:105`, `dk_capture.sh:2`. Also "the per-turn model" (`README.md:81`) and "the monitor" (`README.md:80`) for the same call.
- "runtime monitor" / "critic": `MECHANISM.md:33-34`, `dk_watch.py:2-7`, `dk_recall.sh:21`, `dk_tripwire.py:4`. "meta layer": `dk_watch.py:15`.
- "monitor": `EVALS.md:91`, `redesign.md` throughout, `log.md` 08-28 to 09-01, `HANDOVER.md:36` (for the old design).
- "watcher": in `tests/run_dk_tests.sh` (tests 60-63, 73, 81-82) it means `dk_watch.py`; in `SHAPE.md`, `CLAUDE.md`, `TIERS.md`, `HANDOVER.md`, and `log.md` from 09-01 it means `watcher_session.py`. `TESTS.md:35-37` notes that "The eight mentions of 'watcher' in the suite all refer to dk_watch.py." `SHAPE.md:54` itself says "One continuous **monitor** conversation" while retiring "monitor" as the name.
- "judge": `dk_watch.py:10` "NOT a judge, because it scores nothing"; `CLAUDE.md:43-45` "Judge/watcher runs must use reasoning on ... A judge without reasoning is not a judge"; `SHAPE.md:57` "never a fresh judge shown a snapshot."

**The counter that injects mid-turn.**
- "tripwire": `README.md:42`, `MECHANISM.md:257-275`, `dk_tripwire.py`, tests 108-114.
- "guard (retired)": `SHAPE.md:48-50`, where it is "Not built." `CLAUDE.md:22` calls `baseline_counter.py` "the retired guard", not `dk_tripwire.py`. `TESTS.md:28` calls `dk_tripwire.py` "a counter guard."
- "deterministic triggers (Tier A)": `redesign.md` original v2 text.
- "tripwire" also means something else: the 21-day staleness warning in `dk_recall.sh:105` ("Staleness tripwire") and test 16 ("raw log 30 days stale -> tripwire line appears", `run_dk_tests.sh:174`). Two unrelated mechanisms share the word.

**Deterministic signals.**
- "senses": `SHAPE.md:42-44`, `CLAUDE.md:11`. The output tag is `[sense: ...]` (`watcher_session.py:144, 149, 154`).
- "signals": the function is `signals()` (`watcher_session.py:131`), and `SHAPE.md:42` and `CLAUDE.md:11` say "deterministic signals are senses." `baseline_counter.py:3` "when a deterministic signal trips."
- Nowhere in README or MECHANISM.

**The watcher's memory.**
- "brief" (GOAL/CONSTRAINTS/DECIDED/OPEN): `README.md:83-97`, `dk_watch.py:84-91`, with TRIED added in the prompt (`dk_watch.py:478`). `redesign.md:41-43` calls it an "attempt ledger."
- "notes / expectations": `SHAPE.md:45`, `watcher_session.py:38-44`, `HANDOVER.md:7`.
- Two memories, two schemas, both in code; SHAPE names only one.

**What gets injected.**
- "reminder" (`README.md:37`), "note"/"alert" (`MECHANISM.md:214, 4.5`), "directive" (`log.md:815-824`), "warning" (`dk_tripwire.py:100`), "nudge" (`dk_recall.sh:91`, `log.md:396`), "intervention" (`SHAPE.md:46`), "live monitor blocks" (`log.md:1419`), "alert" (`TIERS.md`). The tag is always `<self-steering>`, a word `MECHANISM.md:44` says the documents avoid.

**"rules".** In README/MECHANISM/templates, "rules" are the product (the 23 failure modes and mined items). In `CLAUDE.md:3` "automatic rules do not work" is the top prohibition. In `extract_tb.py:50-77` "wedge R1..R4" are labelling rules. In `EVALS.md:16` "Rules carried over" are methodology rules. The word is the product in one file and the forbidden thing in the next.

**"wedge" / "moment".** Defined mechanically in `replay_bench.py:9-11` ("score did not move across >=3 consecutive attempts"). Defined by judgment in `CLAUDE.md:8-9`. Never defined in README, MECHANISM, or SHAPE. The judgment labels do not use the word; the key is `speak` (`labels/judgment.jsonl` line 1).

## 4. Decisions recorded as final and later reversed without the record being updated; decisions on evidence the log later voided

1. **"No hand labels anywhere in this design."** `EVALS.md:3-8`, with the reason: the labels would come from the person whose corrections are mined. Reversed 09-05: `labels/judgment.jsonl`, 160 read-and-decide labels (`log.md:42-47`); `CLAUDE.md:16-17` now requires it. EVALS.md unchanged since 08-29 (git log). The structural objection was sidestepped by using LLM subagents as readers (`log.md:108`: "the readers were LLM subagents, not Miles"). TIERS.md says "readers" nine times and never says they were models.

2. **"The agent under test is Haiku."** `EVALS.md:37-51`, with two reasons and a caveat. Every real run used Gemini 2.5 Flash Lite as the agent and Haiku as the monitor (`log.md:984-985, 954-955, 600`). EVALS.md never updated.

3. **The 08-28 gate.** "dk_watch.PROMPT JOB 1 now requires the last assistant message to BE the violation" (`log.md:1023-1025`, commit `bc26cf1`). Reversed 08-29: it "bought the 92%->46% fire-rate fix by making the monitor myopic" (`log.md:722-726`, commit `c6aa992`). Both entries exist. Neither README nor MECHANISM ever described either state.

4. **09-01 morning "Standing corrections to previous conclusions."** `log.md:313-319`: "All dk-vs-challenge nulls and the marathon live-silence apply to the STALE build only." Voided the same afternoon: "Wedge-blindness is real and build-independent" (`log.md:262-263`). Also contradicts the 08-29 entry, which said the real-hooks run used "the monitor [that] is the rebuilt one that can see an arc" (`log.md:626-627`) versus 09-01's "EVERY dk arm ever run ... evaluated the old build" (`log.md:306-307`). No entry is annotated; all three stand.

5. **09-01 afternoon: "the TRIGGER should be a deterministic counter ... That variant needs a small dk_watch code change ... next on the bench."** `log.md:271-275`. Written into `redesign.md` as the v2 architecture, then reversed by SHAPE.md within the day (`ee062ad`). redesign.md got a superseded note (`redesign.md:44-53`); the log entry did not. The decision to reverse cites Miles's statement (`SHAPE.md:6-11`), not a measurement; the 08-30 evidence for the deterministic layer (`log.md:486-490`) was never rebutted by data.

6. **SHAPE stage-1 criterion: "beat the arc-patch prompt."** `SHAPE.md:22-25`. The 09-05 log declares "The stage-1 kill criterion ... is met on the full corpus" against the counter (`log.md:85-88`). `TIERS.md:46-50`: "Arc-patch was run on 18 moments and never on the full corpus; the bar silently became the counter." Then the 09-06 reading voids the 09-05 "met": "Detection rate flattered the watcher" (`TIERS.md:197-198`). SHAPE's criteria are unchanged; the 09-05 entry is unannotated.

7. **"guard (retired) ... Not built."** `SHAPE.md:48-49`. `dk_tripwire.py` was built 08-27 and is in `hooks/hooks.json:23-27`. Never removed, never annotated in SHAPE.

8. **HANDOVER.md** ("Read this first ... Everything else is history", `HANDOVER.md:3`) is itself history: "Never benched" (`:13`, now benched three times), "59 moments" (`:14-16`; now 56 plus 3 in `moments_dropped/`), "Balance $0.66" (`:48`; TIERS.md:99 says about $28), "Next runs" (`:53-55`; done), "labels are heuristic" (`:59`; replaced). Not touched since 09-02.

9. **"Migration into scripts/ follows the first bench + branched-fork validation."** `SHAPE.md:110-111`. `TIERS.md:66-91` argues branched forks "cannot be run on this corpus." The precondition for shipping the product cannot be met as written. SHAPE unchanged.

10. **"Test coverage: 118 tests, all passing"** (`log.md:1365-1367`) and "119 tests pass" (`log.md:747`). `TESTS.md:8-17`: red from 08-31 to 09-06. The log section stands.

11. **"periodic challenge (NOT BUILT — written down only)"** (`log.md:1102`). Built as the `challenge` arm on 08-28. Header never changed. Minor.

12. **`a0c62ef` 2026-09-05 "healthy = new high-water mark"** refined a mechanical label rule hours before `99342eb` added rule one forbidding mechanical labels. `replay_bench.py:80-86` still carries the high-water rule and `report` mode (`replay_bench.py:262-276`) still scores by prefix. `score_judgment.py:6-7` ignores prefixes, but the filenames and `report` do not.

## 5. Rule-one violations that remain in docs or templates

Rule one (`CLAUDE.md:8-12`): counts and thresholds inform; they never decide. Places where a count, threshold, schedule, or prefix decides an outcome and is presented as the design:

1. **The tripwire, as feature #4.** `README.md:41-44`; settings `DK_TRIP_REPEATS` "3" and `DK_TRIP_READS` "12" (`README.md:301-302`); `MECHANISM.md:246-279` with a justification table; `dk_tripwire.py:115-136` injects on the count; `hooks.json:23-27` ships it; tests 108-110 assert it. `TESTS.md:28-34` names it.

2. **Auto-approval by count.** `DK_APPROVAL=auto` "approve a rule after a number of occurrences", `DK_AUTO_APPROVE_COUNT` "3" (`README.md:293-294`; `MECHANISM.md:408-411`; `log.md:1336-1338`; tests 68-69). A count decides which rules become active.

3. **The static note is "top 5 by Count."** `dk_review.py:13-15`; `MECHANISM.md:190-192` "the five most important rules"; `templates/dk_rules.md:10-11` "keep it under 12 lines / ~100 tokens." A count decides what is injected on every prompt with no live selection, which after the 08-31 change is most prompts.

4. **`MAX_ACTIVE = 3`** (`dk_watch.py:133`; `MECHANISM.md:362` "at most three") and **`DK_MAX_RULES` 40 "drops baseline rules before mined ones"** (`README.md:304`). Caps deciding what the model may select from.

5. **The silence prior in the shipped prompt.** `dk_watch.py:445-446`: "If nothing in the window is a live violation, return an empty active list. The correct answer is usually an empty list." `SHAPE.md:95-97` identifies "a fresh judge with a silence-biased prior" as the reason the design is dead. Still shipped.

6. **Tier 0 in redesign.md.** `redesign.md:64-65`: "Tier 0 (free): deterministic trace checks over every recorded session; doubles as label QA." `TIERS.md:15-25` says this is "exactly what CLAUDE.md rule one forbids" and was wrong on 48 of 160. redesign.md's funnel section carries no note.

7. **The kill-criteria chain in SHAPE.** `SHAPE.md:22-34`: "McNemar margin", "If speaking does not raise recovery over silence, stop." `TIERS.md:116-119`: "each tier is a mechanical rule deciding what to do next ... That is rule one applied to the programme itself." SHAPE is "non-negotiable" and unchanged.

8. **Moment labelling by rule, still in the bench code and its docs.** `replay_bench.py:9-13, 80-86, 98-100, 125-129`; `extract_tb.py:50-77` (R1-R4 and the "healthy" rule); `HANDOVER.md:17-19` presents "process-labeled" as the corpus's virtue. Cutting moments by rule is a sampling choice; naming them `wedge_`/`healthy_` and scoring `report` by that name is labelling.

9. **`challenge-N` as "a feature candidate."** `EVALS.md:92-99`: fires "on a schedule ... That makes it both a feature candidate and the honest control." `SHAPE.md:98-99`: scheduled fixed text is "never the product." EVALS still offers it as a candidate and knob #1 (`EVALS.md:163`).

10. **Mechanical items that are fine as plumbing, but should be labelled as such so they are not mistaken for design:** the 1-hour `DK_ACTIVE_TTL` (`dk_recall.sh:82-86`), the 21-day staleness line (`dk_recall.sh:105-114`), the 3-failure "broken not quiet" line (`dk_recall.sh:128-137`). None of these decide whether to speak to the agent about its work.

11. **One irony worth recording.** `.claude/settings.json` plus `.claude/hooks/inject_rules.sh` inject rule one as fixed text on every message ("REMINDER (injected on every message, from CLAUDE.md)"). That is the scheduled fixed-text mechanism `SHAPE.md:98-99` says is "never the product", used to steer the assistant working on the product. It is not a rule-one violation (it decides nothing), but it is the design the project says does not work.

## 6. What a newcomer would build, and the document that is missing

### From the docs as they stand

A new engineer starts at README, which links only `log.md` and `MECHANISM.md` (`README.md:365-366`). They would build the 08-27 product: baseline rules, correction mining, a cheap per-turn model choosing rule ids ("Haiku 4.5 ... Strict enough", `README.md:274`), a static note, and three counter tripwires. They would tune `DK_WATCH_EXCHANGES` and `DK_WATCH_CHARS=9000`, neither of which governs the live window (`dk_watch.py:117-118, 131`). They would expect a `! / * / what it looks like / so:` block (`MECHANISM.md:202-209`) that the code cannot produce. They would not learn that this design never beat a scheduled nudge on four instruments (`log.md:483-490`), that SHAPE calls it dead, or that `watcher_session.py` exists.

If they found SHAPE.md and HANDOVER.md, they would try to drop `watcher_session.py` in place of `dk_watch.py`, as `SHAPE.md:108-109` promises ("same CLI and handoff contract ... dk_recall/dk_capture work unchanged"). It would not work as promised:
- `dk_capture.sh:71-72` launches `dk_watch.py` by name and exports `DK_SESSION_ID`; `watcher_session.py:182` reads `DK_SESSION`. Session scoping would silently fall to `"session"`, and `dk_recall.sh:79-81` would look for a different file.
- `watcher_session.py:120-125` keeps only `text` content blocks. On a native Claude Code transcript it drops every `tool_use` and every tool result. The watcher would see narration and nothing the agent did. The bench never exposed this because `extract_tb.py:40-45` renders tool calls as text in the moment format.
- The plateau sense matches the bench driver's literal string `(N% fixed)` (`watcher_session.py:147`). It cannot fire in a real session.
- Its prompt has the same silence prior in kind: "Speak ONLY when your accumulated understanding says the session is off track" (`watcher_session.py:51-52`), and reasoning-on made it quieter still (`log.md:98-103`).
- Zero tests (`TESTS.md:35`).

And they would inherit numbers nobody has reconciled: HANDOVER's $0.66 and 59 moments; the 09-05 "criterion met"; the 09-06 "24 of 78."

### What should be built per SHAPE.md

A stateful watcher (`SHAPE.md:54-57`) wired to the Stop hook in place of `dk_watch.py`, fed the delta with senses as annotations (`SHAPE.md:59-63`), keeping notes and expectations (`SHAPE.md:64-69, 84-88`), with lookup only after deciding to speak (`SHAPE.md:70-82`), the tripwire's counts demoted to senses (`TESTS.md:79-82`), the static note and auto-approve counts removed or demoted, and plumbing tests for all of it (`TESTS.md:68-75`). What the evidence says it must also do, and does not yet: name the cause one level down and widen the frame to task compliance and abandoned correct work (`TIERS.md:176-193`).

### The one document that must exist

A single current-state document (call it `docs/STATUS.md` or a rewritten README) that is the only entry point, dated, and rewritten rather than appended. For the docs to be trustworthy it must say:

1. **What ships today and why.** `hooks.json` runs `dk_watch.py`, `dk_recall.sh`, `dk_tripwire.py`. This is the 08-27 design. SHAPE rejects it. It stays wired only because nothing else is. Its measured record: four nulls, 92%->46%->9% fire rates, one clean win (`log.md:386-390`).
2. **What the product is and what it lacks to ship.** SHAPE's watcher; prototype at `evals/bench/watcher_session.py`; the gaps listed above (session env, tool-call visibility, driver-specific sense, tests, wiring); the honest numbers: 24/78 same-problem, 0/78 frame-widening, 14 of 22 false alarms, p=0.19 on the frontier corpus, reasoning-on worse.
3. **One vocabulary table** mapping every retired term to its SHAPE term and the files it still appears in, with the rule "old term = old design." Including: "watcher" in the test suite means `dk_watch.py`; "tripwire" in `dk_recall.sh` means the staleness warning; "brief" and "notes" are two different memories.
4. **A decision ledger.** Every dated decision in section 4 above with a status: standing / reversed by (date, file) / voided by (date, file). This is the only way an append-only log can stop presenting dead conclusions as live. The log stays append-only; the ledger is rewritten.
5. **A list of every mechanical number that still decides something**, each marked either "plumbing, decides nothing about the session" (TTL, staleness, failure counter) or "rule-one violation, scheduled for removal or demotion to a sense" (tripwire injection, auto-approve count, top-5-by-count note, `MAX_ACTIVE`, the silence prior, Tier 0, the prefix labels).
6. **The next measurement and what it would change.** Which line of this document each possible result rewrites. TIERS.md's list (`TIERS.md:121-150`) is the current answer.

Until that exists, README.md and MECHANISM.md need a banner at line 1: "Describes the 2026-08-27 design. Still what ships. Superseded as the product by docs/SHAPE.md (2026-09-01). Several claims below are stale; see docs/STATUS.md." HANDOVER.md should be dated in its filename or deleted, since `HANDOVER.md:3` claims an authority it no longer has.

### Files cited

`/home/user/dk-mode/README.md`, `/home/user/dk-mode/CLAUDE.md`, `/home/user/dk-mode/docs/SHAPE.md`, `/home/user/dk-mode/docs/MECHANISM.md`, `/home/user/dk-mode/docs/EVALS.md`, `/home/user/dk-mode/docs/redesign.md`, `/home/user/dk-mode/docs/HANDOVER.md`, `/home/user/dk-mode/docs/TIERS.md`, `/home/user/dk-mode/docs/TESTS.md`, `/home/user/dk-mode/docs/log.md`, `/home/user/dk-mode/templates/dk_rules.md`, `/home/user/dk-mode/templates/baseline_rules.md`, `/home/user/dk-mode/skills/dk-review/SKILL.md`, `/home/user/dk-mode/hooks/hooks.json`, `/home/user/dk-mode/scripts/dk_watch.py`, `/home/user/dk-mode/scripts/dk_recall.sh`, `/home/user/dk-mode/scripts/dk_capture.sh`, `/home/user/dk-mode/scripts/dk_tripwire.py`, `/home/user/dk-mode/scripts/dk_review.py`, `/home/user/dk-mode/scripts/dk_consolidate.py`, `/home/user/dk-mode/evals/bench/watcher_session.py`, `/home/user/dk-mode/evals/bench/replay_bench.py`, `/home/user/dk-mode/evals/bench/extract_tb.py`, `/home/user/dk-mode/evals/bench/score_judgment.py`, `/home/user/dk-mode/evals/bench/baseline_counter.py`, `/home/user/dk-mode/tests/run_dk_tests.sh`, `/home/user/dk-mode/.claude/settings.json`, `/home/user/dk-mode/.claude/hooks/inject_rules.sh`.