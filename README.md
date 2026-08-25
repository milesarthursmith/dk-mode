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
   transcript spots corrections ("you didn't run the tests", "that's not
   what I asked") and standing instructions ("from now on always X",
   "I prefer Y") and saves your VERBATIM words — plus what Claude had just
   said — to an append-only log. Deliberately no LLM here: your words are
   the ground truth, and asking the model to summarise its own mistake is
   asking the least reliable narrator in the room.
2. **Consolidate** (background, cadence configurable down to per-turn) — a
   strong model sorts new entries into Mistake Patterns / Standing Rules /
   Facts, merges repeats, discards false positives, and rewrites a small
   (~100 token) reminder note. Its output is structurally validated before
   it replaces anything; the raw log is never modified, so any bad
   consolidation is recoverable.
3. **Recall** (UserPromptSubmit hook) — the reminder note is pasted into
   every prompt. Forced, not retrieved: the model cannot miss it or forget
   to look. Also the watchdog: it announces in-context when capture has been
   silent 21+ days or consolidation has failed 3 runs straight — a
   notification nobody reads is not an alarm.
4. **Backfill** — mine your PREVIOUS sessions. Claude Code keeps every
   transcript at `~/.claude/projects/<project>/<session>.jsonl`;
   `dk_backfill.sh` sweeps them all through the exact same capture logic,
   so memory is seeded from real history instead of starting empty.

Everything in the distilled file must trace to something you actually said,
quoted verbatim with a date. Prior art: Reflexion (post-hoc self-critique
prepended to later attempts), prospective reflection (plan checked against
known error patterns before acting), Letta/MemGPT sleep-time agents (a
second model curating what the first is forced to see).

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

Then mine your history:

```bash
.claude/vendor/dk-mode/scripts/dk_backfill.sh --target /path/to/your/project
python3 .claude/vendor/dk-mode/scripts/dk_consolidate.py --drain
```

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
| `DK_INTERVAL` | `7d` | Consolidation cadence: `Nd`/`Nh`/`Nm`, bare seconds, or `per-turn`/`always`/`0` for every prompt (for cost-insensitive background/autonomous agents). |
| `DK_APPROVAL` | `0` | Approval ("training wheels") mode. When `1`, new items land as `Status: pending`, are HELD OUT of the injected note (the validator rejects any consolidation that leaks a pending reminder line into it), and each prompt gets a one-line nudge. Review with `/dk-review` (or `scripts/dk_review.py --list/--approve/--reject` — approval rebuilds the note immediately, rejection preserves the item under Retired). Turn off once the consolidator has earned trust. |
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
  time), `uuid` (dedupe), `source` (`human`; a future capture path may add
  LLM-sourced steering events), `kind` (correction/instruction), `signal`,
  `user_verbatim`, `assistant_context`, `cwd`.
- `.claude/memory/dk_rules.md` — the distilled file: the inject block plus
  Mistake Patterns / Standing Rules / Facts / Retired, each item with
  verbatim Evidence, dates, a Count, and (in approval mode) a Status.
  Machine-rewritten; hand-edit freely to retire or fix an item. Default is
  zero-touch (no approve-each-memory chore); `DK_APPROVAL=1` adds the
  human sign-off gate for the training period.
- `.claude/memory/.dk_state` — scheduling state (flat key=value).

## Tests

```bash
bash tests/run_dk_tests.sh          # 52 tests, sandboxed, no key/network
bash tests/run_dk_tests.sh --live   # + one real-API behavioral test
```

The main suite fakes the API with a local server so failure modes the real
API can't produce on demand (garbage output, mid-write crashes, races) are
covered; `--live` verifies the real model's judgment (merging repeats,
keeping verbatim evidence, discarding a planted false positive). Run after
any change to the scripts.
