# Development log

Reverse chronological. Decisions, measurements, and the things that are still
unproven. The README describes what dk-mode does; this file records how it got
there and what was actually tested.

---

## 2026-08-26 — README rewritten in Simplified Technical English

The README was jargon-heavy, then story-heavy. Rewritten to ASD-STE100:
approved vocabulary, one meaning per word, short sentences, active voice, one
instruction per sentence, no idiom or metaphor. Development context moved out
of the README into this file.

Terminology fixed across the docs: **mine / mining**, not "capture". The word
"capture" implied a passive net catching phrases, which is what the first
version did and what measurement showed to be near useless (see 2026-08-25).

---

## 2026-08-25 — measurement: word matching alone finds almost nothing

The first version detected corrections with a phrase list (regex over the
transcript). Run against this project's own conversation history:

| Method | Corrections found |
|---|---|
| Phrase list only | **0 of 46** real corrections |
| Phrase list, false positives | 2, both misattributed subagent task-notifications |

The two "hits" were harness-injected pseudo-user turns, not the user. This is
the single most important measurement in the project: it is why `dk_watch.py`
exists, why mining is semantic, and why `DK_BACKFILL_SEMANTIC=0` is documented
as debug-only.

Fix, in two parts:

1. **Filtering.** Discard `isSidechain`, `isMeta`, and turns containing
   `<command-name>`, `<local-command-caveat>`, `<local-command-stdout>`,
   `<task-notification>`, `<system-reminder>`, `<wake reason=`,
   `[SYSTEM NOTIFICATION`, `<untrusted_external_data`.
2. **Semantic mining.** A model reads the conversation and identifies the
   corrections. The phrase list is kept as a cheap first pass only.

`isMeta` versus the string markers was tested rather than assumed: `isMeta`
caught 14 turns the markers missed, the markers caught 13 turns `isMeta`
missed. Both are kept.

---

## 2026-08-25 — bugs found and fixed

Recorded because each one failed silently, which is the failure mode this
project is supposed to be immune to.

- **`stat -f %m` does not fail on Linux.** It prints filesystem information.
  A BSD-first fallback therefore returned garbage instead of falling through.
  GNU `stat -c %Y` now comes first everywhere. (The same latent bug is still
  in work-backup's `archive_completed_tasks.sh`.)
- **`set -euo pipefail` killed mining on an empty payload.** A grep inside an
  assignment returned non-zero. Fixed with `|| true`.
- **`max_tokens: 400` in `dk_watch.py`.** Fatal, not degraded: a reasoning
  model spends the whole budget before it emits content, so every call
  returned empty. Raised to 2000, plus `DK_REASONING_EFFORT`.
- **`assistant_context: ""` in semantic mining.** Corrections were saved with
  no record of what was corrected. Now carries the previous three messages.
- **`auto_approve()` ran after the atomic write.** Promotions existed only in
  memory and were lost. Moved before the write.
- **Cold start.** The watcher exited when no rules existed, so a new install
  could never mine its first entry. Test 76 covers this.
- **Four "leaky deterministic" bugs** found in a deliberate audit pass:
  - `## Retired` was matched as a substring, which hid every rule after it.
  - A missing `Status:` field counted as `approved` under approval mode.
  - `trim_echo` truncated on quoted frontmatter inside a rule body.
  - An unparseable `DK_INTERVAL` evaluated to 0, meaning "always due" —
    a typo silently enabled per-turn consolidation and its cost.

---

## 2026-08-24 — design decisions

**Recall is forced, not requested.** The model cannot know to look up "times
I was lazy" *before* being lazy: self-assessment of an in-progress failure is
itself the failing capability. So `dk_recall.sh` prints into the prompt on the
`UserPromptSubmit` hook. Nothing depends on the model choosing to call a
memory tool.

**The relevance model runs one turn behind.** It runs on the `Stop` hook and
writes its verdict to a file. `dk_recall.sh` only reads that file. No model
call sits in the prompt path, so the per-turn latency cost is zero.

**Select, do not write.** The relevance model receives a numbered list and
returns ids only. The script renders the text from `dk_rules.md`. A model
cannot invent, reword, or exaggerate a rule.

**Recall over precision.** Mining collects too much on purpose. Three later
filters remove the noise: the interval call discards one-offs, the approval
gate holds new rules back, and the relevance call selects almost nothing on a
normal turn. A correction that was never collected cannot be recovered.

**Autonomy.** Three sources feed the log — the user, Claude correcting itself,
and external tools via `dk_signal.py` — so the loop keeps working in
conversations nobody is watching. `DK_APPROVAL=auto` promotes a rule after it
recurs `DK_AUTO_APPROVE_COUNT` times, which removes the human from the path
once trust is earned.

**Local and cheap models.** One flag, `DK_BACKEND=openai`, covers OpenRouter,
Ollama, LM Studio, llama.cpp and vLLM. Verified against OpenRouter: Bearer
auth to a custom path, with the model id and token budget intact.

---

## Prior art consulted

- **Letta / MemGPT** — core, recall and archival memory tiers; sleep-time
  agents that reorganise memory outside the request path. dk-mode's interval
  call is the same idea, simplified to one file.
- **Reflexion** — verbal self-critique prepended to the next attempt. dk-mode
  differs in that the critique is mined from real corrections, not generated
  by the same model that failed.
- **Prospective reflection** — check the plan against an error taxonomy
  *before* acting. This is what forced injection buys.
- **Generative Agents** — importance-scored memory stream.
- **Memory confabulation research** — self-diagnosis is unreliable. This is
  why the user's exact words are the ground truth and the model may only
  select, never author.
- **Baseten STILL (neural KV-cache compaction)** — memory in tensor space
  rather than text space. Not usable against a hosted model, so rejected.

---

## Test coverage

`bash tests/run_dk_tests.sh` — 85 tests, all passing. No key, no network.
Local stand-in servers exercise the real HTTP path.

Covered: mining from fixtures, deduplication, marker and `isMeta` filtering,
lock contention, atomic writes under `kill -9`, the approval state machine,
the note size cap, validator rejection of a malformed reply, the OpenAI
backend path, backfill idempotency, cold start, and the rule that the
relevance model cannot invent text.

---

## Not yet proven

Stated plainly because the README does not.

1. **Selectivity is asserted, not measured.** The claim "usually no rule
   applies" is the assumption the whole design rests on. It has never been
   measured against a real model on real conversations.
2. **Semantic mining has never run against a real model on real history.**
   Only against local stand-in servers.
3. **The full hook loop has never been observed end to end.** The injection
   mechanism was verified indirectly: `additionalContext` was found in a real
   transcript, which proves the harness injects text by that route. But no
   `UserPromptSubmit` hook has been registered and watched firing.
4. **Sonnet via OpenRouter was never compared** against the default models.
5. **Consolidation stalled at 30 of 117 entries** on an early, noisy log. The
   log needs to be cleared and re-mined with the current filters.
