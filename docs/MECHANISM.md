# How dk-mode works

This document uses Simplified Technical English (ASD-STE100). It explains the
mechanism to a reader who has not seen this repository before.

---

## 1. The words in this document

Read this section first. The rest of the document uses these words with
exactly these meanings.

| Word | Meaning |
|---|---|
| **the prompt** | All the text Claude reads before it answers you. Your message is only one part of it. |
| **a turn** | One message from you, and Claude's answer to it. |
| **a hook** | A command that Claude Code runs for you at a fixed moment. You do not start it. It starts itself. |
| **the transcript** | The file that holds a whole conversation. Claude Code writes one for every conversation, on your computer. |
| **a rule** | One known way that Claude goes wrong, with a short line that says what to do instead. |
| **to mine** | To read old conversations and find the corrections in them. |
| **the miner** | The part of dk-mode that mines. |
| **recall** | The part of dk-mode that puts text into the prompt. |
| **the sorter** | The part of dk-mode that turns mined corrections into rules. |

---

## 2. What dk-mode does

dk-mode holds a set of rules about how Claude goes wrong. It puts the
applicable rule in front of Claude at the moment Claude is about to break it.

The rules come from four places. Two are there on the first day. Two fill in
as you work.

### 2.1 Published research (day one, 23 rules)

dk-mode is not empty when you install it. It ships 23 known ways that coding
agents fail. Eleven come from published studies, and each one names its source
and how often that study measured it:

| Source | What it measured | Examples of rules taken from it |
|---|---|---|
| MAST, from 1600+ annotated traces across 7 frameworks | 14 failure modes with frequencies | Step repetition (15.7%, the most common single mode). Unaware that the task is finished (12.4%). Ignores a stated constraint (11.8%). Forgets a decision made earlier. |
| A study of 20,574 real coding-agent sessions | How agents fail their users | Hands back a partial job as though it is complete. Solves a different, easier problem. |
| SWE-Bench Pro | Where models fail on hard tasks | Reads without reaching a decision (context overflow was 35.6% of one model's failures; endless file reading 17.0%). |
| Reward-hacking benchmarks (EvilGenie, ImpossibleBench) | Whether models cheat the test | Makes the test pass instead of making the code correct. One analysis found 19.78% of top SWE-Bench "solved" cases were semantically wrong. |
| SlopCodeBench | How code degrades over long tasks | Puts new logic into functions that already exist (80% of runs). Copies code instead of reusing it (89.8%). |

The other twelve come from building this repository. They cover claiming a job
is done without checking, reporting success when the failure was discarded,
skimming, rebuilding what already exists, agreeing under pressure, writing a
test that cannot fail, testing the parts and never the connections, assuming
the platform you developed on, fixing one case and not the pattern, inventing
a plausible detail, widening the job, and hiding the bad news.

These rules carry `Source: baseline` and **no evidence line**. They did not
come from you. A rule built from your evidence must quote you, and these have
nothing to quote. dk-mode never presents them as something you said.

Install with `--no-baseline` to start with none of them.

### 2.2 Your corrections (mined from your history)

dk-mode reads the conversations already on your computer and finds the moments
you corrected Claude. Section 5 explains how.

A rule mined from you is better than a supplied one, because it is about you.
When there is not room for every rule, dk-mode keeps yours and drops the
supplied ones.

### 2.3 Claude correcting itself

Claude also corrects itself in the middle of a task: the approach failed, it
made a mistake, it must start again. The miner reports these too, with the
source `self`.

This is weaker evidence than your correction, and dk-mode treats it that way.
But it works in conversations nobody watches, which is what lets dk-mode
improve an agent that runs on its own.

### 2.4 Your other programs

Any program that tells an agent it is wrong can report that directly, with
`dk_signal.py`:

```bash
dk_signal.py --kind verdict --source my-verifier \
    --text "FIX: the page promises a calculator it does not contain"
```

A failing gate, a review agent, a lint rule that keeps firing, a test suite:
each is a correction, and none of them appear in a conversation. These entries
go into the same file, under the same lock, and become rules the same way. A
gate that complains twice becomes a standing rule, exactly as your repeated
correction does.

### 2.5 Why all four

A rule written by somebody else tells you how agents fail in general. A rule
mined from your own history tells you how this agent fails **you**. The first
is useful immediately. The second is more accurate. dk-mode starts with the
first and moves toward the second as it learns.

---

## 3. Why it does not offer a tool

Claude cannot decide to look up "times I was lazy" **before** it is lazy. To
see your own mistake while you make it is the ability that has failed. A tool
that Claude chooses to call is therefore no use here. Claude calls it only
when Claude already knows it needs help.

So dk-mode gives Claude no tool. It puts the text into the prompt, and Claude
has no choice about that.

This is the whole idea. Section 4 explains how.

---

## 4. Recall: how text gets into the prompt

This is the central mechanism. Read this section carefully.

### 4.1 The rule that makes it possible

Claude Code has a hook called `UserPromptSubmit`. It runs after you press
enter, and before Claude reads anything.

**Whatever that hook prints is added to the prompt.** Claude then reads your
message and the printed text together. Claude cannot skip the printed text,
and it cannot forget to look for it.

dk-mode registers one script on that hook: `dk_recall.sh`. Everything else in
this repository exists to decide what that script prints.

### 4.2 What the script does

The script reads two files and prints. It calls no model. It uses no network.
It takes a few milliseconds. It always exits with code 0, so it can never stop
your turn.

It looks for these two files, in this order:

1. **`.dk_active.<session-id>`** — the live selection. The miner wrote this
   file at the end of your previous turn. It holds only the rules that apply
   to what is happening now.
2. **`dk_rules.md`** — the standing note. It holds the five most important
   rules. The sorter writes it. The script uses this file only if the first
   file is absent, or if the first file is more than one hour old.

An **empty** live selection is a real answer, not a missing one. It means no
rule applies to this turn, so the script prints nothing. This is the normal
result.

### 4.3 What the printed text looks like

When a rule applies, Claude reads this immediately before your message:

```
<self-steering>
Relevant to what you are doing right now:
! You just said the tests pass. You did not run them this turn.
* Claims done without verifying
    what it looks like: Says the tests pass based on an earlier run.
    so: never say a check passed unless you ran it this turn
</self-steering>
```

That block is a copy of a real run, not an example written by hand.

Four parts:

- The line that starts with `!` is the **alert**. It names what Claude is
  about to do wrong, in this conversation. The model writes this line.
- The line that starts with `*` is the **name of the rule** that applies.
- The line `what it looks like:` describes the mistake.
- The line `so:` says what to do instead.

The last three lines are a copy from `dk_rules.md`. The model selected the
rule by its number. It did not write those words.

When nothing applies, Claude reads nothing. This is important. A rule that
appears on every turn becomes background text, and Claude stops reading it. A
rule that appears only when it applies stays a real interruption.

### 4.4 The warnings

The script also prints one line when something is wrong:

- No corrections mined for 21 days. The miner may be dead.
- Items wait for your approval.
- The miner or the sorter failed its last three runs.

The last one exists because a broken miner and a quiet miner look the same
from outside.

---

## 5. The miner: how the selection is made

Recall only prints a file. This section explains who writes that file.

### 5.1 When it runs

The miner runs on the `Stop` hook. That hook runs after Claude finishes its
answer — that is, **after your turn, not during it**.

This matters. The miner calls a model, and a model call takes seconds. You
never wait for it. It writes its answer to a file, and the **next** prompt
reads that file.

So the miner is always one turn behind. This is correct: it judges the turn
that just finished.

### 5.2 What it is sent

The miner makes one model call per turn. The call has three parts:

| Part | Size | Does it change each turn? |
|---|---|---|
| The instructions | 467 tokens | No |
| The rules, each with a number | 868 tokens for 23 rules | Only when a rule changes |
| The recent messages | up to 2,250 tokens | Yes |
| **Total** | **up to about 3,600 tokens** | |

**The recent messages.** The setting `DK_WATCH_TURNS` controls this, and its
default is **6**. This means the last **6 messages**, not 6 turns. Your
message and Claude's answer are two messages, so 6 messages is about your last
three turns.

Each message is cut at 1,500 characters. So this part is at most 9,000
characters, which is about 2,250 tokens. Usually it is much less.

The number is 6 because the miner judges what happens **now**. A rule applies
because of what Claude just said and what you just asked. Older messages
describe a situation that has changed. They also cost tokens on every turn.
Increase `DK_WATCH_TURNS` if your work has longer arcs. The cost increases at
the same rate.

**The rules.** Each rule is sent as `number. name - what it looks like`. The
model needs the description to judge. The names alone are four times smaller,
but too vague to judge from.

The setting `DK_MAX_RULES` limits this, and its default is **40**. A limit is
necessary: the miner only ever adds rules, so without a limit this part grows
for ever. At 100 rules it is about 3,800 tokens, on every turn, permanently.
When the limit applies, dk-mode keeps the rules mined from you and drops the
supplied baseline rules. Your rules are about you.

### 5.3 What it is not sent

A transcript contains text that looks like your words but is not. Claude Code
writes harness messages with the role "user". dk-mode removes all of these
before the model sees them:

- Messages marked `isSidechain`. These belong to a subagent, not to you.
- Messages marked `isMeta`. The role says user, but you did not type them.
- Messages that contain a harness marker, such as `<command-name>`,
  `<system-reminder>`, `<local-command-stdout>` or `<task-notification>`.

This is not a theoretical risk. Before this filter was complete, a real run
recorded `<local-command-stdout>Set model to ...</local-command-stdout>` as a
correction from the user.

dk-mode also removes anything that looks like a password or a key. People
paste keys into conversations. A real run mined a live key before this was
added.

### 5.4 The two jobs

The miner does two jobs in that one model call.

**Job 1 — which rules apply now.** The model gets the numbered list of rules.
It answers with **numbers only**, and at most three. The script reads those
numbers, finds the matching rules, and writes the text to
`.dk_active.<session-id>`. Recall prints that file on your next turn.

Most turns the answer is an empty list. This is the intended result.

**Job 2 — which messages corrected the agent.** The model reads the recent
messages. It answers with **message identifiers only**. The script finds each
message in the transcript and copies your words exactly into `dk.jsonl`. It
also copies the three messages before yours, so a correction is stored
together with the thing it corrected.

### 5.5 The safety rule

**A model in dk-mode can point at text. It cannot write text.**

Both jobs answer with identifiers. All text comes from a file or from the
transcript. If the model invents an identifier, nothing matches it, and
dk-mode discards it.

This matters because a model does not usually fail by getting one word wrong.
It fails by writing a whole quotation that reads correctly and never happened.

---

## 6. The sorter: how corrections become rules

The sorter runs every 7 days by default. Change this with `DK_INTERVAL`.
Recall starts it in the background when it is due.

It reads the new entries in `dk.jsonl`. Those entries come from all three
mined sources: you, Claude correcting itself, and your other programs through
`dk_signal.py`. Each entry carries a `source` field, and the sorter weighs
them differently - your words are the strongest evidence.

It rewrites `dk_rules.md`. It:

- joins repeated corrections into one rule, and increases its count;
- files a standing instruction, or a durable fact, under its own heading;
- discards a correction that happened only once;
- rewrites the five-line standing note that recall uses as its second choice.

It must quote your words as evidence. dk-mode checks the structure of its
output before that output replaces anything. It never changes `dk.jsonl`, so a
bad sort can always be done again.

If you set `DK_APPROVAL=1`, a new rule waits with the status `pending`.
dk-mode holds it out of the prompt until you approve it with `/dk-review`. If
you set `auto`, a rule approves itself after it occurs `DK_AUTO_APPROVE_COUNT`
times.

---

## 7. One turn, from start to end

This is the same mechanism again, in time order.

1. You type a message and press enter.
2. The `UserPromptSubmit` hook runs `dk_recall.sh`.
3. The script reads `.dk_active.<session-id>`, written at the end of your last
   turn. It prints what that file holds. Usually the file is empty and the
   script prints nothing.
4. Claude reads the printed text and your message together, and answers.
5. Claude finishes. The `Stop` hook runs `dk_capture.sh`, which starts
   `dk_watch.py` in the background and returns immediately.
6. `dk_watch.py` sends the last 6 messages and the rule list to a model.
7. The model answers with two lists of numbers.
8. The script writes the applicable rules to `.dk_active.<session-id>`, and
   any new corrections to `dk.jsonl`.
9. Your next turn starts at step 1, and step 3 reads what step 8 wrote.

You never wait for step 6. It happens after your turn ends.

---

## 8. The files

| File | What it is |
|---|---|
| `dk.jsonl` | Every mined correction: yours, Claude's own, and any reported by `dk_signal.py`. dk-mode only adds to it. Do not read it by hand: it grows without limit. |
| `dk_rules.md` | The rules: the 23 supplied ones and everything mined since. Read it. Change it. Delete a rule you disagree with. |
| `.dk_active.<session>` | The live selection for one conversation. Rewritten every turn. It is per conversation, so one conversation's answer never appears in another. |
| `.dk_state` | Timing, and counts of failures. |

**To switch dk-mode off, delete `dk_rules.md`.** Nothing creates it again.

---

## 9. What it costs

Up to about 3,600 tokens in, and a few hundred out, for each turn. At 100
turns each day:

| Model | Each month |
|---|---|
| `DK_BACKEND=cli` | nothing. It uses the Claude login you already have. |
| Haiku 4.5 | about $16 |
| Sonnet 5 | about $31 |

The per-turn call is a test of strictness, not a summary. On most turns the
correct answer is "no rule applies". A weak model answers "yes" too often.
Then every prompt fills with rules that do not apply, and that is the exact
failure dk-mode exists to prevent. Measure a cheap model on your own
conversations before you trust it.

The sorter is a different job. It runs rarely and it makes real judgements.
Leave `DK_MODELS` at its default.

---

## 10. What is not proven

- **Nobody has measured how often a rule is selected.** "Most turns select
  nothing" is the assumption the whole design rests on. It has never been
  counted.
- The first real run mined 13 items from 3 conversations. 10 were real
  corrections. 3 were ordinary instructions, read wrongly as corrections. The
  instructions to the model were then made stricter, and that change is not
  yet tested against real conversations.
- **The tests cannot judge the quality of a model's answer.** They check that
  the parts connect and that the data is correct. Whether the model judges
  *well* is visible only when you run it and read the result.

`docs/log.md` holds the development history and the measurements.
