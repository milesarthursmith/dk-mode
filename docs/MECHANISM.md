# How dk-mode works

Every number here was measured on 2026-08-27, on a real install. Where a
figure is a worst case rather than a typical one, it says so.

---

## The problem

Claude cannot look up "times I was lazy" *before* being lazy. Noticing your
own in-progress failure is the capability that is failing. So a memory tool
the model chooses to call is useless here: it gets called when the model
already suspects it needs memory, which is not the moment that matters.

dk-mode therefore does not offer a tool. It puts text into the prompt whether
the model wanted it or not.

---

## The three moving parts

```
        ┌────────────────────────── your turn ends ──────────────────────────┐
        │                                                                    │
   you type ──▶ RECALL ──▶ Claude answers ──▶ MINER ──▶ (writes a file)      │
                  ▲            │                 │                           │
                  │            │                 ├──▶ dk.jsonl   (what you said)
                  │            │                 └──▶ .dk_active (what applies now)
                  │            │                                             │
                  └────────────┴───────── reads both files ──────────────────┘

                   once a week ──▶ SORTER ──▶ dk_rules.md
```

**RECALL** runs on the `UserPromptSubmit` hook, before Claude sees your
message. It reads two files and prints. No model call, no network. Whatever it
prints is added to the prompt.

**MINER** runs on the `Stop` hook, after Claude finishes. It calls a model
once. It does two jobs in that one call, and writes two files.

**SORTER** runs occasionally, by default every 7 days. It reads what the miner
collected and turns it into rules.

The miner runs *after* your turn, not during it. Its answer is used by the
*next* prompt. That is why nothing here adds latency: you are never waiting on
a model call.

---

## What the miner is sent

One call per turn. The prompt has three parts:

| Part | Size | Changes each turn? |
|---|---|---|
| Instructions | 467 tokens | No |
| The rules, listed with ids | 868 tokens at 23 rules | Only when rules change |
| The conversation window | up to 2,250 tokens | Yes |
| **Total** | **up to ~3,600 tokens** | |

### The conversation window - "the 6 turns"

`DK_WATCH_TURNS`, default **6**. It means the last **6 messages** of the
conversation, not 6 exchanges - a user message and Claude's reply are two
messages, so 6 is roughly your last three exchanges.

Each message is truncated at 1,500 characters, so the window is at most
9,000 characters, about 2,250 tokens. Usually far less.

Why 6: the miner is judging what is happening *right now*. A rule is live
because of what Claude just said and what you just asked. Older messages
describe a situation that has moved on, and they cost tokens on every single
turn. Raise it with `DK_WATCH_TURNS` if your work has longer arcs; the cost
is linear.

Messages are filtered before the model sees any of them. Discarded:
`isSidechain` (subagent conversations), `isMeta` (harness-injected turns that
say "user" but you never typed), and anything containing a harness marker
such as `<command-name>`, `<system-reminder>`, `<local-command-stdout>` or
`<task-notification>`. Without this the miner reports the harness talking to
itself as your correction. That is not hypothetical - it happened.

### The rules list

Each rule is sent as `id. heading - what it looks like`. The model needs the
description to judge relevance; headings alone are 4x smaller but too vague
to judge from.

Capped at `DK_MAX_RULES`, default **40**. Mining only ever adds rules, so
without a cap the prompt grows forever - 100 rules would be ~3,800 tokens on
every turn. When the cap bites, rules mined from you beat the shipped
baseline ones: yours are about you.

---

## What the miner does with it

**Job 1 - relevance.** Which rules are live *right now*. Not which are true
in general. It returns **ids only** and at most 3. The script looks those ids
up and writes the rendered text to `.dk_active.<session-id>`.

Most turns the answer is an empty list. That is the intended behaviour: a
rule that appears on every turn is wallpaper by turn 40; a rule that appears
at the moment it applies is a challenge.

**Job 2 - mining.** Which messages steered the agent. It returns **message
ids only**. The script looks each id up in the transcript and copies your
words verbatim into `dk.jsonl`, along with the three messages before it, so a
correction is stored with the thing it was correcting.

**A model in dk-mode can point at things. It cannot write them.** Both jobs
return ids. The text always comes from a file or a transcript. If a model
invents an id, the lookup misses and the entry is dropped.

Anything resembling a credential is removed before writing.

---

## What recall prints

Two tiers:

1. `.dk_active.<session-id>`, written by the miner one turn ago, if it is
   less than `DK_ACTIVE_TTL` seconds old (default 3600). **An empty-but-fresh
   file is a real answer** - nothing applies, so nothing is printed.
2. If that file is absent or stale, the static note from `dk_rules.md` - the
   five most important rules, pre-rendered by the sorter.

Plus, when they apply: a line if nothing has been mined for 21 days, a line if
items are waiting for review, and a line if the miner or the sorter has failed
three times running. The last one exists because a broken miner and a quiet
miner look identical from the outside.

Recall never calls a model and never blocks. Every path exits 0.

---

## The sorter

Runs at `DK_INTERVAL` (default 7 days), in the background, kicked by recall
when it is due. It reads the unprocessed entries in `dk.jsonl` and rewrites
`dk_rules.md`: merging repeats and bumping their count, filing standing
instructions and durable facts, discarding one-offs, and re-rendering the
five-line static note.

It must quote your actual words as evidence. Its output is structurally
checked before it replaces anything, and `dk.jsonl` is never modified - so a
bad sort can always be redone.

With `DK_APPROVAL=1` new rules land as `pending` and are held out of the
prompt until you approve them with `/dk-review`. With `auto` a rule approves
itself once it has recurred `DK_AUTO_APPROVE_COUNT` times.

---

## The files

| File | What it is |
|---|---|
| `dk.jsonl` | Every mined correction, in your words. Append-only. Do not read it by hand; it grows without limit. |
| `dk_rules.md` | The sorted rules, and the pre-rendered note. Readable, editable. Delete a rule you disagree with. |
| `.dk_active.<session>` | This conversation's live selection. Rewritten every turn, per session so one chat's verdict never leaks into another. |
| `.dk_state` | Scheduling and failure counts. |

Delete `dk_rules.md` to switch dk-mode off. Nothing recreates it.

---

## What it costs

Per turn, up to ~3,600 tokens in and a few hundred out. At 100 turns a day:

| Backend | Per month |
|---|---|
| `DK_BACKEND=cli` | nothing - uses your existing Claude login |
| Haiku 4.5 | ~$16 |
| Sonnet 5 | ~$31 |

The per-turn call is a **strictness test**, not a summary. On most turns the
right answer is "no rule applies", and a weak model says yes too often. That
fills every prompt with rules that do not apply, which is the exact failure
dk-mode exists to prevent. Measure a cheap model on your own conversations
before trusting it.

The sorter is a different job: rare, and real judgement. Leave `DK_MODELS`
at the default.

---

## What is not proven

- **Selectivity is asserted, not measured.** "Most turns select nothing" is
  the assumption the whole design rests on. Nobody has counted.
- The first real run mined 13 items from 3 conversations. 10 were real
  corrections; 3 were plain instructions misread as corrections. The prompt
  has since been tightened, and that fix is untested.
- The test suite cannot judge prompt quality. It checks plumbing. Whether the
  model judges *well* can only be seen by running it and reading the output.

`docs/log.md` has the development history and the measurements behind these.
