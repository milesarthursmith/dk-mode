# dk-mode

Claude forgets your corrections when a conversation ends. dk-mode mines your
old conversations. It finds the corrections that you make again and again.
It writes them into a file. Then it shows the applicable correction to Claude
at the moment when Claude can make the same mistake.

The name is short for Dunning-Kruger. That is the problem. An agent is most
sure of itself when it is wrong. Thus the agent does not examine its own
record. A different program must do this.

This document uses Simplified Technical English (ASD-STE100).

## What dk-mode does

dk-mode does three things.

**1. It mines your history.** Claude Code keeps each conversation in a file
on your computer. A model reads these files. It finds each moment when you
corrected Claude, and each moment when Claude corrected itself. The script
then copies the words from the file. It also keeps the three messages before
each correction, which show what the correction was about.

A word search does not do this work. dk-mode had one, and a measurement
removed it: against a real conversation it found 0 of 46 corrections. People
do not announce a correction. They redirect. "bit lame", "simplify" and "why
is this so slow" are all corrections, and no word list finds them.

dk-mode also ships 23 known agent failure modes, so it steers on the first
day. Some come from published studies of how agents fail, and each of those
names its source and the frequency the study measured. The others come from
building this. They all carry `Source: baseline` and no evidence quote,
because they did not come from you. Your own mined rules are better, and they
replace these as they accumulate. Use `--no-baseline` at install to start
empty.

**2. It makes rules.** At an interval, a model reads the collected
corrections. The model sorts them. It marks a repeated correction as a rule.
It discards a single event. It writes the result into one file. You can read
this file and change it.

**3. It gives a reminder.** After each turn, a model examines the
conversation. The model selects the rules that apply now. Usually no rule
applies, and dk-mode adds no text. When a rule applies, dk-mode puts that
rule into the next message that Claude reads.

Step 3 is different from a rule in a configuration file. Claude sees a
permanent rule at each turn and ignores it. Claude sees a dk-mode reminder
only at the moment when the rule applies.

## The sources of the corrections

dk-mode uses three sources. You do no additional work for these sources.

- **You.** You correct Claude in your own words. dk-mode does not need a
  special format.
- **Claude.** Claude corrects itself during a task. An example is "that did
  not work". This source operates when you do not monitor the conversation.
- **Your other programs.** A test gate, a review agent or a CI step sends an
  event to `dk_signal.py`.

## Install dk-mode

Do these four steps in this sequence. Step 2 is necessary before step 3. If
you mine without a model, dk-mode finds almost nothing.

### 1. Install the code

```bash
git clone https://github.com/milesarthursmith/dk-mode.git
cd dk-mode
./install.sh --global
```

`--global` installs dk-mode one time for every project on this computer. It
puts the code and the memory under `~/.claude`, and the two hooks into
`~/.claude/settings.json`. All projects then share one memory. This is
correct for most people: a mistake that Claude makes is a fact about its
behaviour, not about one repository.

To keep dk-mode in one project only, give a path instead:

```bash
./install.sh --target /path/to/your/project
```

Then the memory and the hooks stay in that project. They operate only when
you start Claude Code there.

The installer makes the memory files and adds the two hooks. If your system
prevents a change to the settings file, the installer prints the necessary
lines. Then you can add these lines manually. Use `--no-hooks` to prevent the
change. Use `--update` to refresh the code later. It is safe to run the
installer again: it does not replace the memory files.

### 2. Give dk-mode a model

dk-mode makes two different model calls. Set them separately.

- The **per-turn call** does a quick selection. Use a cheap model.
- The **interval call** makes a judgement. Use a better model.

**The simplest option uses no key at all.** If you have the `claude` CLI and
you are logged in, dk-mode can call it:

```bash
export DK_BACKEND=cli
```

This uses the login you already have. The token is in your operating system
keychain, so it operates when you run a command yourself and it FAILS under
cron, which has no login session and cannot open the keychain. Use a
LaunchAgent for scheduled work, or use a key. Also do not select this for the
per-turn hook: it starts a new `claude` process on every turn.

For the Anthropic API, set one variable:

```bash
export DK_API_KEY=sk-ant-...   # or an OpenRouter key, or any other
```

For OpenRouter, or for a different server with the OpenAI format:

```bash
export DK_BACKEND=openai
export DK_API_URL=https://openrouter.ai/api/v1/chat/completions
export DK_KEY_FILE=~/.claude/secrets/openrouter_key   # or use DK_API_KEY
export DK_WATCH_MODELS=openai/gpt-5.6-luna    # per turn, cheap
export DK_MODELS=openai/gpt-5.6-terra         # at an interval, better
```

Examine openrouter.ai/models for the current model names and prices. Ollama,
LM Studio, llama.cpp and vLLM use the same format. Set `DK_API_URL` to the
address of the local server, for example
`http://localhost:11434/v1/chat/completions`. A local server does not need a
key.

Put the same variables into the two hook commands in your settings file.
Then the hooks also have a model.

### 3. Mine your history

An empty file gives no reminders. This step reads your old conversations.

```bash
./scripts/dk_backfill.sh --target ~          # or --target /your/project
python3 scripts/dk_consolidate.py --drain --target ~
```

Read the output of the first command. If it found nothing, dk-mode did not
reach a model. Correct step 2 and run the command again.

### 4. Approve the rules

This step is necessary only with `DK_APPROVAL=1`. dk-mode holds each new rule
back until you approve it.

```bash
python3 scripts/dk_review.py --list --target ~
python3 scripts/dk_review.py --approve 1 2 5 --target ~
```

In Claude Code, the `/dk-review` command does the same steps.

## Test dk-mode

1. Run the test suite. It uses local test servers. It does not need a key.

```bash
bash tests/run_dk_tests.sh
```

2. Install dk-mode into a temporary project. Then mine one old conversation
   with a real model.

```bash
mkdir -p /tmp/dktest && ./install.sh --target /tmp/dktest --no-hooks
CLAUDE_PROJECT_DIR=/tmp/dktest python3 scripts/dk_watch.py --capture-only \
  ~/.claude/projects/<a-project>/<a-session>.jsonl
cat /tmp/dktest/.claude/memory/dk.jsonl
```

If the output shows words that you recognise, dk-mode operates correctly. If
the output is empty, read `dk_watch.log` for the cause. On a Mac, this file
is in `~/Library/Logs`.

## Settings

All of these settings are optional. Most installations set only the first
four.

dk-mode is not specific to one model vendor. It speaks two request formats:
the Anthropic format and the OpenAI format. OpenRouter, Ollama, LM Studio,
llama.cpp and vLLM all use the OpenAI format. Therefore dk-mode can use
almost any model.

### The model

| Setting | Default | Function |
|---|---|---|
| `DK_API_KEY` | — | The key for the model calls, for any vendor. `ANTHROPIC_API_KEY` also operates, for an older installation. |
| `DK_KEY_FILE` | — | A file that contains the key. Use this instead of `DK_API_KEY`. If you set neither one, the model stages do nothing and say so. |
| `DK_BACKEND` | `anthropic` | The request format. Set it to `openai` for OpenRouter, Ollama, LM Studio, llama.cpp or vLLM. Set it to `cli` to call the `claude` command with your existing login and no key. |
| `DK_API_URL` | the Anthropic API | The address for the requests. Set it to the address of your server. |
| `DK_MODELS` | Fable, then Opus | The models for the interval call. Use a comma between the names. dk-mode tries them in sequence. |
| `DK_WATCH_MODELS` | Haiku | The model for the per-turn call. Use a cheap model. |

A local server does not need a key. Set `DK_BACKEND=openai` and `DK_API_URL`,
and dk-mode operates with no key.

### The behaviour

| Setting | Default | Function |
|---|---|---|
| `DK_APPROVAL` | `0` | Set it to `1` to approve each new rule before use. Set it to `auto` to approve a rule after a number of occurrences. |
| `DK_AUTO_APPROVE_COUNT` | `3` | The number of occurrences for `auto`. |
| `DK_INTERVAL` | `7d` | The interval between the interval calls. Examples: `1h`, `per-turn`. |
| `DK_USER_NAME` | — | Your name. The model then knows who "the user" is. |
| `DK_WATCH` | `1` | Set it to `0` to stop the per-turn call. |
| `DK_SCAN_LINES` | `150` | The quantity of the conversation to read. Set it to `0` to read all of it. |

### The less usual settings

| Setting | Default | Function |
|---|---|---|
| `DK_BATCH` | `200` | The quantity of corrections for one interval call. Decrease it for a small local model. |
| `DK_REASONING_EFFORT` | — | Set it to `none` to stop the reasoning stage of a local model. |
| `DK_WATCH_MAX_TOKENS` | `2000` | The maximum length of the reply to the per-turn call. A reasoning model needs a large value. |
| `DK_TIMEOUT` | `180` / `600` | The number of seconds to wait. A local model is slower. |
| `DK_LOG_DIR` | `~/Library/Logs` | The directory for the error logs. |
| `--no-baseline` (install flag) | off | Start with no rules at all, instead of the 23 baseline failure modes. |
| `DK_HOME` | — | The directory that holds `.claude/memory`. `install.sh --global` sets it in the hooks. It has priority over the project. |
| `DK_SESSION_ID` | — | Claude Code sets this variable. It keeps the reminders of one conversation separate from a different conversation. |

## The files in your project

- `.claude/memory/dk.jsonl` — each correction, in the original words.
  dk-mode only adds to this file.
- `.claude/memory/dk_rules.md` — the sorted rules. You can read this file.
  You can change it. You can delete a rule that you do not agree with.
- `.claude/memory/.dk_state` and `.claude/memory/.dk_active.<conversation>` —
  the internal records.

## Credentials

People paste keys into conversations. dk-mode reads conversations, so it
removes anything that looks like a credential before it writes: API keys,
tokens, private keys, and any long value after a word such as `secret` or
`password`. The text becomes `[REDACTED-SECRET]`.

This is deliberately eager. A wrong removal costs one unreadable quote. A
missed one writes a live key into a file that is read into prompts.

## Limits and failures

A model in dk-mode cannot invent a rule. The per-turn model receives a
numbered list of the rules. It replies with numbers only. The text of the
reminder comes from your file. The interval model must quote your words as
evidence. dk-mode examines the new file before it replaces the old file.

dk-mode continues to operate after a failure. If a model does not reply, if a
key is absent, or if a reply is incorrect, dk-mode shows a short fixed list.
After three failures in sequence, dk-mode reports the failure in the
conversation.

dk-mode collects too much rather than too little. The interval call discards
the unnecessary corrections. But dk-mode cannot recover a correction that it
did not collect.

## More information

- [docs/log.md](docs/log.md) — the development record and the measurements.
- [docs/MECHANISM.md](docs/MECHANISM.md) — the internal design, with
  diagrams.
