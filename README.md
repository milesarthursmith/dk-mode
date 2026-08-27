# dk-mode

Claude repeats mistakes. dk-mode holds a set of rules about how it goes wrong,
and puts the applicable rule in front of Claude at the moment Claude is about
to break it.

23 rules ship with it, so it works on the first day. Eleven of those come from
published studies of how coding agents fail. Then it learns yours.

The name is short for the Dunning-Kruger effect: a person is most confident
when they are least competent. An agent behaves the same way. It is most sure
of itself when it is wrong, so it never examines its own record. A different
program must do that.

This document uses Simplified Technical English (ASD-STE100).

## What dk-mode does

dk-mode does four things.

**1. It knows how agents fail before it knows you.** 23 rules ship with it.
Eleven come from measured studies - MAST, a study of 20,574 real coding-agent
sessions, SWE-Bench Pro, reward-hacking benchmarks, SlopCodeBench - and each
names its source. Most name the frequency the study measured. The other twelve
come from building this project.

**2. It mines your history.** Claude Code keeps each conversation in a file on
your computer. A model reads these files. It finds each moment when you
corrected Claude, and each moment when Claude corrected itself. dk-mode then
copies those words from the file, with the three messages before each one.

A word search does not do this work. dk-mode had one, and a measurement
removed it: against a real conversation it found 0 of 46 corrections. People
do not announce a correction. They redirect. "bit lame", "simplify" and "why
is this so slow" are all corrections, and no word list finds them.

**3. It gives a reminder at the start of a turn.** After each turn, a model
examines the conversation and decides which rules apply. dk-mode puts those
rules into the next message that Claude reads.

**4. It speaks during a turn.** One turn can run 25 tool calls over ten
minutes. A second hook runs after every tool call and uses no model. It has
three tripwires it can see without one: the same tool call three times, twelve
reads with nothing written, and a test file changed after a test failed.

Steps 3 and 4 are different from a rule in a configuration file, for two
reasons.

**Where the text goes.** dk-mode puts the rule at the end of everything Claude
reads, next to your request, immediately before Claude answers. A rule in a
configuration file sits at the start, often a hundred thousand tokens earlier.
The same words in the two positions do not have the same effect. This is the
more important reason. It is true on every turn.

**When the text appears.** A permanent rule appears on every turn. dk-mode
shows a rule at the moment it applies.

## Where the rules come from

Four sources. Only the first is there on day one. You do no additional work
for the other three.

- **Published research.** The 23 rules described above. They carry
  `Source: baseline` and no evidence quote, because they did not come from
  you. A rule built from your evidence must quote you, and these have nothing
  to quote.
- **You.** You correct Claude in your own words. dk-mode does not need a
  special format.
- **Claude.** Claude corrects itself during a task. An example is "that did
  not work". This source operates when you do not watch the conversation.
- **Your other programs.** A test gate, a review agent, a lint rule or a CI
  step reports a correction directly with `scripts/dk_signal.py`. None of
  these appear in a conversation.

A rule mined from you is better than a supplied one, because it is about you.
When there is not room for every rule, dk-mode keeps yours and drops the
supplied ones. A supplied rule can also become an evidenced one: when your
words match a rule that shipped, dk-mode attaches your quote to it.

## What the monitor knows about the conversation

The per-turn model reads the last two exchanges. That is a small part of a
long conversation, so dk-mode also keeps a **brief**: a short record of what
this conversation is for and where it has got to.

```
GOAL:        Build a CSV parser. Do not add any third-party dependencies.
CONSTRAINTS: no third-party dependencies (stdlib only)
DECIDED:     use the stdlib csv module
OPEN:        implementation and test verification
```

The model writes the brief with the same call it already makes each turn, so
the brief costs no extra call and no extra time. `GOAL` is different: dk-mode
copies it from your first message and the model cannot change it. A brief
written from the previous brief drifts, and after fifty turns the goal becomes
something else. That is the failure the brief exists to prevent.

Nine of the 23 rules need the brief. "Repeats a step already taken", "ignores
a constraint that was stated", "solves a different problem" and "forgets a
decision made earlier" are invisible in two exchanges.

## Install dk-mode

Do these four steps in this sequence. Step 2 is necessary before step 3. If
you mine without a model, dk-mode finds almost nothing.

### 1. Install the code

In Claude Code, type these two lines:

```
/plugin marketplace add milesarthursmith/dk-mode
/plugin install dk-mode@dk-mode
```

That is the whole installation. The plugin carries its own hooks, its own
`/dk-review` command, and its own memory, which lives beside the plugin and
survives an update. There is no file to edit and no settings to merge.

To install from a clone instead - for a single project, or to change the code:

```bash
git clone https://github.com/milesarthursmith/dk-mode.git
cd dk-mode
./install.sh --global
```

`--global` installs dk-mode one time for every project on this computer. It
puts the code and the memory under `~/.claude`, and the three hooks into
`~/.claude/settings.json`. All projects then share one memory. This is
correct for most people: a mistake that Claude makes is a fact about its
behaviour, not about one repository.

To keep dk-mode in one project only, give a path instead:

```bash
./install.sh --target /path/to/your/project
```

Then the memory and the hooks stay in that project. They operate only when
you start Claude Code there.

The installer makes the memory files and adds the three hooks. If your system
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
LaunchAgent for scheduled work, or use a key. It adds one or two seconds
per turn, after your turn ends, so you never wait for it.

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

Put the same variables into the three hook commands in your settings file.
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

### Which model to use, and what it costs

The per-turn call sends up to about 3,600 tokens and gets a few hundred back:
467 of instructions, up to 868 of rules, and up to 2,250 of conversation. At
100 turns a day:

| Backend | Cost per month | Notes |
|---|---|---|
| `DK_BACKEND=cli` | nothing | Uses the Claude login you already have. Slower, because it starts a process. |
| Haiku 4.5 | about $16 | The cheapest Claude model. Strict enough. |
| Sonnet 5 | about $31 | Better judgement than this job needs. |

Use `cli` unless you have a reason not to. It costs nothing and needs no key.

**A warning about cheap models here.** This call is a strictness test, not a
summary. On most turns the correct answer is "no rule applies", and a weak
model says yes too often. That fills each prompt with reminders that do not
apply, which is the exact failure dk-mode exists to prevent - a rule that
appears constantly is ignored. Measure a cheap model on your own conversations
before you trust it. Do not assume it behaves like the expensive one.

The interval call is different. It runs rarely and makes real judgements, so
give it a better model: keep `DK_MODELS` at the default.

### The behaviour

| Setting | Default | Function |
|---|---|---|
| `DK_APPROVAL` | `0` | Set it to `1` to approve each new rule before use. Set it to `auto` to approve a rule after a number of occurrences. |
| `DK_AUTO_APPROVE_COUNT` | `3` | The number of occurrences for `auto`. |
| `DK_INTERVAL` | `7d` | The interval between the interval calls. Examples: `1h`, `per-turn`. |
| `DK_USER_NAME` | — | Your name. The model then knows who "the user" is. |
| `DK_WATCH` | `1` | Set it to `0` to stop the per-turn call. |
| `DK_WATCH_EXCHANGES` | `2` | How many of your own messages the miner's window reaches back to include. Two means this exchange and the one before it, however many messages Claude produced inside them. |
| `DK_WATCH_CHARS` | `9000` | The size limit on that window, so one very long turn cannot fill the prompt. |
| `DK_WATCH_TURNS` | `6` | Window size when mining history only. It does not affect live turns. |
| `DK_TRIP_REPEATS` | `3` | How many identical tool calls in one turn before dk-mode says so, without using a model. |
| `DK_TRIP_READS` | `12` | How many reads with nothing written before dk-mode says so. A write resets the count. |
| `DK_BRIEF_CHARS` | `1200` | The size limit on the running brief. |
| `DK_MAX_RULES` | `40` | How many rules are described to the model each turn. At the limit dk-mode drops baseline rules before mined ones. |
| `DK_SCAN_LINES` | `150` | Set it to `0` to stop the live miner. `dk_backfill.sh` sets it to `0` while it reads history. It is not a line count. |

### The less usual settings

| Setting | Default | Function |
|---|---|---|
| `DK_BATCH` | `200` | The quantity of corrections for one interval call. Decrease it for a small local model. |
| `DK_REASONING_EFFORT` | — | Set it to `none` to stop the reasoning stage of a local model. |
| `DK_WATCH_MAX_TOKENS` | `2000` | The maximum length of the reply to the per-turn call. A reasoning model needs a large value. |
| `DK_TIMEOUT` | `180` / `600` | Seconds to wait for the interval call. A local model is slower. |
| `DK_WATCH_TIMEOUT` | `120` | Seconds to wait for the per-turn call. |
| `DK_LOG_DIR` | `~/Library/Logs` on a Mac, else `~/.claude/logs` | The directory for the error logs. |
| `--no-baseline` (install flag) | off | Start with no rules at all, instead of the 23 baseline failure modes. |
| `DK_MEM` | — | The memory directory itself. The plugin sets it to its own data directory. It has priority over `DK_HOME`. |
| `DK_HOME` | — | The directory that holds `.claude/memory`. `install.sh --global` sets it in the hooks. It has priority over the project. |
| `DK_SESSION_ID` | — | `dk_capture.sh` sets this from the hook payload. It keeps the reminders of one conversation separate from a different conversation. |

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

One exception, and it is deliberate. The per-turn model may add a single
sentence of its own, up to 200 characters, that names what is about to go
wrong in this conversation. That line is the only text dk-mode injects that
you did not write. It is a judgement about messages in front of it, not a
claim about the past, so it cannot fabricate something you said.

dk-mode continues to operate after a failure. If a model does not reply, if a
key is absent, or if a reply is incorrect, dk-mode shows a short fixed list.
After three failures in sequence, dk-mode reports the failure in the
conversation.

dk-mode collects too much rather than too little. The interval call discards
the unnecessary corrections. But dk-mode cannot recover a correction that it
did not collect.

## More information

- [docs/log.md](docs/log.md) — the development record and the measurements.
- [docs/MECHANISM.md](docs/MECHANISM.md) — the internal design.
- [scripts/dk_eval.py](scripts/dk_eval.py) — measures whether the monitor
  speaks at the right moments.
- [evals/impossiblebench/](evals/impossiblebench/) — a public benchmark that
  asks whether dk-mode reduces cheating.
