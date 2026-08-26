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
on your computer. dk-mode reads these files. It finds each moment when you
corrected Claude. It keeps your words. It also keeps the words of Claude
before your correction.

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

Do these steps.

1. Get the code and install it into your project.

```bash
git clone https://github.com/milesarthursmith/dk-mode.git
cd dk-mode
./install.sh --target /path/to/your/project
```

The installer copies the scripts into your project. It makes the memory
files. It adds two hooks to your settings file. If your system prevents a
change to the settings file, the installer prints the necessary lines. Then
you can add these lines manually.

Use `--no-hooks` to prevent the change to the settings file. Use `--update`
to refresh the copy in your project. It is safe to run the installer again.
The installer does not replace the memory files.

2. Mine your history. An empty file gives no reminders.

```bash
./scripts/dk_backfill.sh --target /path/to/your/project
python3 scripts/dk_consolidate.py --drain
```

## Select the models

dk-mode makes two different model calls. Set them separately.

- The **per-turn call** does a quick selection. Use a cheap model.
- The **interval call** makes a judgement. Use a better model.

For OpenRouter, or for a different server with the OpenAI format, set these
variables:

```bash
export DK_BACKEND=openai
export DK_API_URL=https://openrouter.ai/api/v1/chat/completions
export DK_KEY_FILE=~/.claude/secrets/openrouter_key
export DK_WATCH_MODELS=openai/gpt-5.6-luna    # per turn, cheap
export DK_MODELS=openai/gpt-5.6-terra         # at an interval, better
```

Examine openrouter.ai/models for the current model names and prices. Ollama,
LM Studio, llama.cpp and vLLM use the same format. Set `DK_API_URL` to the
address of the local server, for example
`http://localhost:11434/v1/chat/completions`. A local server does not need a
key. If you do not set `DK_BACKEND`, dk-mode calls the Anthropic API.

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

All of these settings are optional.

| Setting | Default | Function |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | The key for the model calls. |
| `DK_KEY_FILE` | — | A file that contains the key. If you set neither variable, the model stages do nothing. |
| `DK_BACKEND` | `anthropic` | Set it to `openai` for OpenRouter, Ollama, LM Studio, llama.cpp or vLLM. |
| `DK_API_URL` | Anthropic | The address for the requests. |
| `DK_MODELS` | Fable, then Opus | The models for the interval call. Use a comma between the names. dk-mode tries them in sequence. |
| `DK_WATCH_MODELS` | Haiku | The model for the per-turn call. Use a cheap model. |
| `DK_WATCH` | `1` | Set it to `0` to stop the per-turn call. |
| `DK_APPROVAL` | `0` | Set it to `1` to approve each new rule before use. Set it to `auto` to approve a rule after a number of occurrences. |
| `DK_AUTO_APPROVE_COUNT` | `3` | The number of occurrences for `auto`. |
| `DK_INTERVAL` | `7d` | The interval between the interval calls. Examples: `1h`, `per-turn`. |
| `DK_USER_NAME` | — | Your name. The model then knows who "the user" is. |
| `DK_BATCH` | `200` | The quantity of corrections for one interval call. Decrease it for a small local model. |
| `DK_REASONING_EFFORT` | — | Set it to `none` to stop the reasoning stage of a local model. |
| `DK_WATCH_MAX_TOKENS` | `2000` | The maximum length of the reply to the per-turn call. |
| `DK_TIMEOUT` | `180` / `600` | The number of seconds to wait. A local model is slower. |
| `DK_LOG_DIR` | `~/Library/Logs` | The directory for the error logs. |
| `DK_BACKFILL_SEMANTIC` | `1` | Set it to `0` to mine with a word match only. Then dk-mode finds almost nothing. Use it only to debug. |
| `DK_SCAN_LINES` | `150` | The quantity of the conversation to read. Set it to `0` to read all of it. |
| `DK_SESSION_ID` | — | Claude Code sets this variable. It keeps the reminders of one conversation separate from a different conversation. |

## The files in your project

- `.claude/memory/dk.jsonl` — each correction, in the original words.
  dk-mode only adds to this file.
- `.claude/memory/dk_rules.md` — the sorted rules. You can read this file.
  You can change it. You can delete a rule that you do not agree with.
- `.claude/memory/.dk_state` and `.claude/memory/.dk_active.<conversation>` —
  the internal records.

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
