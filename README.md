# dk-mode

**Self-steering for Claude Code** - memory mined from your own corrections,
forced back into every prompt.

Named for the Dunning-Kruger problem it exists to counter: the model is at
its most confidently wrong exactly when it cannot self-assess the failure in
progress - it does not know to look up "times I was lazy" *before* being
lazy, because that judgment is the capability that is failing.

Standard agent memory waits for the model to invoke a retrieval tool — which
fails precisely where it matters most, for the reason above. dk-mode makes
the loop self-steering instead - the system, not the model's judgment,
decides what gets recalled:

1. **Capture** (Stop hook) — after each turn, a regex pass over the
   transcript spots steering events and saves them VERBATIM — plus what the
   agent had just said — to an append-only log. Three sources, tagged:
   - `human` — you correcting it ("you didn't run the tests", "that's not
     what I asked") or setting a rule ("from now on always X").
   - `self` — the agent correcting *itself* mid-run ("I was wrong", "that
     didn't work"). This is what makes the loop work in an agent's own
     chats, where no human is present to correct anything.
   - anything else — a verifier, test gate, review agent or CI pushing an
     event through `dk_signal.py` (below).

   The phrase list is only the floor. Measured over a real 46-message
   session it caught **zero** of the user's actual corrections — people
   steer by redirecting ("bit lame", "simplify", "that's not the point"),
   not by saying "you didn't". So the relevance layer's per-turn call does
   double duty and **reads** each turn for steering the phrases cannot see
   (a model given the same criteria — though not the production prompt path —
   found 14 across 25 substantive turns of that session). It returns
   message ids; the script copies the text verbatim, so it reports where the
   steering was, never what was said.

   Tuned for recall on purpose: false positives are filtered downstream by
   the consolidator, the approval gate and the repetition threshold, but a
   missed correction is invisible forever.
2. **Consolidate** (background, cadence configurable down to per-turn) — a
   strong model sorts new entries into Mistake Patterns / Standing Rules /
   Facts, merges repeats, discards false positives, and rewrites a small
   (~100 token) reminder note. Its output is structurally validated before
   it replaces anything; the raw log is never modified, so any bad
   consolidation is recoverable.
3. **Relevance** (`dk_watch.py`, background) — the point of the whole
   thing. A model reads the turn that just happened and decides which of
   the known failure modes are *live right now* — not true in general, but
   about to be run into, judging from what the agent just said and what you
   just asked. Most turns it selects nothing, which is the correct answer.
   It can also emit one blunt situational alert ("you just said the tests
   pass without running them this turn"). The model only **selects ids**;
   the script renders the text from the rules file, so it can never invent
   a rule, and in approval mode it can only pick items you approved.
   Runs on the Stop hook, one turn behind, because an LLM call inside the
   prompt path would stall every message by seconds — and a conversation's
   situation persists across turns, so the lag costs nothing.
4. **Recall** (UserPromptSubmit hook) — injects that live selection into the
   prompt, instantly (a file read, never an LLM call). Forced, not
   retrieved: the model cannot miss it or forget to look. Falls back to the
   static top-5 note when the watcher is off, hasn't run yet, or its
   selection has gone stale — so the system is never worse than
   always-on rules. Also the watchdog: it announces in-context when capture
   has been silent 21+ days or consolidation has failed 3 runs straight — a
   notification nobody reads is not an alarm.
5. **Backfill** — mine PREVIOUS sessions. Claude Code keeps every
   transcript at `~/.claude/projects/<project>/<session>.jsonl`;
   `dk_backfill.sh` sweeps them all through the exact same capture logic,
   so memory is seeded from real history instead of starting empty.

**[How it works, with diagrams →](docs/MECHANISM.md)**

Everything in the distilled file must trace to something you actually said,
quoted verbatim with a date. Prior art: Reflexion (post-hoc self-critique
prepended to later attempts), prospective reflection (plan checked against
known error patterns before acting), Letta/MemGPT sleep-time agents (a
second model curating what the first is forced to see).

## Running with nobody watching

Nothing in the loop needs a human. Capture picks up the agent's own
self-corrections, consolidation and relevance run themselves, and approval
has a mode where evidence rather than a person does the approving:

```bash
export DK_APPROVAL=auto        # a pattern approves itself once it recurs
export DK_AUTO_APPROVE_COUNT=3 # ...this many times (default)
```

One incident may be noise; the same failure recurring three times across
sessions has proven itself. Below the threshold an item stays pending and
steers nothing, so a one-off never becomes a rule. You can still overrule
anything with `/dk-review` — `auto` removes the dependency on you, it
doesn't remove the veto.

**Feeding it machine steering.** Anything that tells an agent it got
something wrong is a steering event, and can report itself:

```bash
dk_signal.py --kind verdict --source my-verifier \
  --text "FIX: heading promises a calculator the page does not contain" \
  --context "shipped /heating-costs"
```

Wire it into a verifier, a ship gate, a failing-test handler, a review
subagent — anything you already run that catches the agent being wrong. Those entries flow through the same consolidation as your own
corrections, so a gate's repeated complaint becomes a standing rule exactly
like your repeated correction does. It exits 0 even when dk-mode isn't
installed — a telemetry call must never fail the pipeline reporting it.

The consolidator is told to weight the sources differently (a human's
correction is the strongest evidence, ordinary iteration like a test failing
then being fixed is explicitly not a mistake pattern), and it discards
one-offs.

## Install

```bash
git clone https://github.com/milesarthursmith/dk-mode.git
cd dk-mode
./install.sh --target /path/to/your/project
```

This pins a copy at `<project>/.claude/vendor/dk-mode/` (gitignore
`.claude/vendor/`), seeds `<project>/.claude/memory/dk_rules.md` if
absent, and registers the two hooks in `<project>/.claude/settings.json` —
preserving whatever is already there. If the settings edit is blocked (some
managed environments gate hook registration), it prints the exact JSON block
to paste by hand and still succeeds. `--no-hooks` skips registration
entirely; `--update` re-pins the vendor copy to the newest tag. Re-running
is always safe: it never overwrites existing memory.

**Start by mining, always.** An empty rules file steers nothing, and the
loop cannot learn what it never saw — so the first thing any install should
do is read the history that already exists:

```bash
.claude/vendor/dk-mode/scripts/dk_backfill.sh --target /path/to/your/project
python3 .claude/vendor/dk-mode/scripts/dk_consolidate.py --drain
```

## Trying it locally (OpenRouter, or any OpenAI-compatible endpoint)

The two model-calling stages speak the OpenAI chat format when
`DK_BACKEND=openai`, so OpenRouter works with nothing but a URL, a key and a
model id. The two stages are separately configurable on purpose: **relevance
runs on every turn and is a fast classification, consolidation runs
occasionally and is a judgement call** — so pay for the second, not the first.

```bash
export DK_BACKEND=openai
export DK_API_URL=https://openrouter.ai/api/v1/chat/completions
export DK_KEY_FILE=~/.claude/secrets/openrouter_key   # or ANTHROPIC_API_KEY-style env
export DK_WATCH_MODELS=openai/gpt-5.6-luna            # per-turn, cheap
export DK_MODELS=openai/gpt-5.6-terra                 # weekly, better judgement
```

Check the current model list and prices at openrouter.ai/models before
committing to an id — they change.

**Smoke-test it in one command, without touching your real memory:**

```bash
bash tests/run_dk_tests.sh        # 85 tests, mocked models, no key needed
```

**Then prove the real endpoint works, on a scratch project:**

```bash
mkdir -p /tmp/dktest && ./install.sh --target /tmp/dktest --no-hooks
CLAUDE_PROJECT_DIR=/tmp/dktest python3 scripts/dk_watch.py --capture-only \
  ~/.claude/projects/<some-project>/<a-session>.jsonl
cat /tmp/dktest/.claude/memory/dk.jsonl      # what it found in that session
```

If that prints entries, the endpoint, key and model are all good. If it
prints nothing, look at `dk_watch.log` (under `~/Library/Logs` on a Mac) —
every failure is recorded there with the reason.

**Then mine for real and consolidate:**

```bash
./scripts/dk_backfill.sh --target ~/workspace     # reports found-by-reading vs phrase-match
CLAUDE_PROJECT_DIR=~/workspace python3 scripts/dk_consolidate.py --drain
```

Cost control while experimenting: `DK_WATCH=0` turns the per-turn call off
entirely, `DK_INTERVAL` controls how often consolidation runs, and
`DK_BATCH` lowers how many entries go into each consolidation call.

## Configuration

All optional, via environment variables (set them inline in the hook command
string in settings.json to scope them per-project):

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | unset | Primary API key source for the consolidator. |
| `DK_KEY_FILE` | unset | Path to a file containing the key; used if the env var is unset. If neither resolves, consolidation silently skips (capture + recall still work). |
| `DK_BACKEND` | `anthropic` | `anthropic` (hosted) or `openai` for any OpenAI-compatible server — Ollama, LM Studio, llama.cpp, vLLM. See **Running it locally** below. |
| `DK_MODELS` | `claude-fable-5,claude-opus-5` (hosted) / `qwen2.5:14b-instruct` (local) | Comma-separated, tried in order. |
| `DK_TIMEOUT` | `180` hosted / `600` local | Seconds per request; local CPU inference is slow. |
| `DK_USER_NAME` | unset | Your name, used in the consolidation prompt ("the user (Name)"). |
| `DK_WATCH` | `1` | The relevance layer. `0` disables it — recall then injects the static note on every prompt (the dumb mode). |
| `DK_WATCH_MODELS` | `claude-haiku-4-5-20251001` hosted / your local model | Selection is a fast cheap judgment, unlike consolidation — separate knob on purpose. |
| `DK_WATCH_TURNS` | `6` | How many recent messages the relevance layer reads. |
| `DK_WATCH_MAX_TOKENS` | `2000` | Reply budget for the relevance call. Was 400, which left a reasoning model no room to answer at all — it returned empty content on every call, a silent total failure. |
| `DK_REASONING_EFFORT` | unset | Passed to an OpenAI-compatible server (`none` turns thinking off). Belt to `DK_WATCH_MAX_TOKENS`'s braces for local thinking models. |
| `DK_BATCH` | `200` | Entries per consolidation batch. Lower it for a small local model. |
| `DK_ACTIVE_TTL` | `3600` | Seconds a live selection stays valid before recall falls back to the static note. |
| `DK_SESSION_ID` | unset | Scopes the live selection to one conversation. Claude Code supplies it via the hook payload; set it only when driving the scripts by hand. |
| `DK_BACKFILL_SEMANTIC` | `1` | Read history as well as phrase-match it during backfill. Setting `0` makes mining history nearly useless — it is there for debugging, not for saving money. |
| `DK_INTERVAL` | `7d` | Consolidation cadence: `Nd`/`Nh`/`Nm`, bare seconds, or `per-turn`/`always`/`0` for every prompt (for cost-insensitive background/autonomous agents). |
| `DK_APPROVAL` | `0` | `0` off, `1` a human approves everything, `auto` repetition approves it (see **Running with nobody watching**). When on, new items land as `Status: pending`, are HELD OUT of the injected note (the validator rejects any consolidation that leaks a pending reminder line into it), and each prompt gets a one-line nudge. Review with `/dk-review` (or `scripts/dk_review.py --list/--approve/--reject` — approval rebuilds the note immediately, rejection preserves the item under Retired). Turn off once the consolidator has earned trust. |
| `DK_AUTO_APPROVE_COUNT` | `3` | Occurrences before `DK_APPROVAL=auto` promotes a pending item. |
| `DK_LOG_DIR` | `~/Library/Logs` or `~/.claude/logs` | Where consolidation error detail is written (never /tmp). |
| `DK_SCAN_LINES` | `150` | Transcript lines the capture hook scans; `0` = whole file (what backfill uses). |
| `DK_API_URL` | api.anthropic.com | Test override (the test suite points it at a local mock). |

## Running it locally

Your corrections are the most personal data in the workspace, and
consolidation is the only stage that leaves the machine. Point it at a local
model and nothing does:

```bash
ollama serve && ollama pull qwen2.5:14b-instruct   # once
export DK_BACKEND=openai                            # OpenAI-compatible wire format
export DK_API_URL=http://localhost:11434/v1/chat/completions   # this is the default
export DK_MODELS=qwen2.5:14b-instruct
```

No API key is needed in this mode (the hosted path still requires one). Same
for LM Studio (`http://localhost:1234/v1/chat/completions`), llama.cpp
`--server`, or vLLM — only the URL and model name change.

Worth knowing: consolidation is a judgment task (is this a repeat? is this a
false positive? what warning line actually lands?), so a small local model
will merge less cleverly than a frontier one. The structural validator, the
"never invent, quote verbatim" rule and the immutable raw log all still
apply, and approval mode (below) is the real safety net — with `DK_APPROVAL=1`
nothing a local model proposes steers anything until you approve it. A
sensible split is local for privacy, hosted for quality; the raw log is
never modified either way, so you can re-run consolidation on a different
backend by resetting `consolidated_through`.

## Files it owns in your project

- `.claude/memory/dk.jsonl` — raw captures, one JSON per line, verbatim,
  append-only, never edited by machine. Each entry: `ts` (original message
  time), `uuid` (dedupe), `source` (`human` / `self` / a machine source), `kind`
  (correction / instruction / self-correction / verdict / test-failure /
  review), `signal`, `text`, `assistant_context`, `cwd`.
- `.claude/memory/dk_rules.md` — the distilled file: the inject block plus
  Mistake Patterns / Standing Rules / Facts / Retired, each item with
  verbatim Evidence, dates, a Count, and (in approval mode) a Status.
  Machine-rewritten; hand-edit freely to retire or fix an item. Default is
  zero-touch (no approve-each-memory chore); `DK_APPROVAL=1` adds the
  human sign-off gate for the training period.
- `.claude/memory/.dk_state` — scheduling state (flat key=value).
- `.claude/memory/.dk_active` — the current live selection, rewritten after
  each turn by the relevance layer. Empty file = nothing is live right now.

## Tests

```bash
bash tests/run_dk_tests.sh          # sandboxed, no key or network needed
bash tests/run_dk_tests.sh --live   # + one real-API behavioural test
```

The main suite fakes the API with a local server so failure modes the real
API can't produce on demand (garbage output, mid-write crashes, races) are
covered; `--live` verifies the real model's judgment (merging repeats,
keeping verbatim evidence, discarding a planted false positive). Run after
any change to the scripts.
