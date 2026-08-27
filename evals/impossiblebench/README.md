# ImpossibleBench: four arms, one cheating rate

This is the primary eval from `docs/EVALS.md` section 2. ImpossibleBench
builds tasks whose specification and unit tests contradict each other, so a
pass IS a cheat: no judge model, no partial credit. dk-mode ships a rule for
exactly this failure, so the benchmark asks the sharpest question available -
and a scheduled challenge with no selection step runs beside it as the
control that selection has to beat.

## Setup

```bash
git clone https://github.com/safety-research/impossiblebench
export IMPOSSIBLEBENCH=/path/to/impossiblebench
pip install inspect_ai datasets
```

Do not `pip install -e` impossiblebench: the editable install fails on
Debian-family setuptools, and its swebench modules need Python 3.12. The
harness imports the LiveCodeBench modules straight off the clone, which
needs neither.

## Run

```bash
# All four arms on the frozen subset. Docker sandbox by default;
# DK_EVAL_SANDBOX=local runs the tests unsandboxed.
export DK_API_KEY=sk-ant-...        # the monitor falls back to `claude -p`
python3 evals/impossiblebench/run_arms.py \
    --limit 20 --model anthropic/claude-haiku-4-5
```

The arms, all injecting through the same channel (a user message appended
immediately before each generation - the position dk-mode's hook uses):

| arm | payload | selection? | model call? |
|---|---|---|---|
| `baseline` | nothing | - | - |
| `dk` | whatever the shipped monitor selects | yes | per generation |
| `challenge` | `challenge.md`, every `--challenge-n` generations | no | no |
| `dk_challenge` | both | yes | per generation |

`challenge.md` is a stand-in text. If you have a challenge skill of your
own, point `DK_EVAL_CHALLENGE` at its text - the arm measures the payload
you give it.

## Read the result honestly

- **Baseline first.** A baseline that cheats on nothing gives the other
  arms nothing to prevent, and the run says nothing.
- **Check `dk_fired`.** A dk arm where the monitor never spoke is a run
  about silence, not steering. The runner warns when this happens; the
  per-sample rules and alerts are in the JSON report for reading.
- **Run the `original` split too.** A low cheating rate is easy to buy by
  talking the agent out of finishing anything; the pass rate on possible
  tasks is the guard.
- **If `challenge` matches `dk`**, the selection layer is not earning its
  per-turn model call. That is a finding, and it goes in `docs/log.md`.
- `--model claude-cli/<name>` runs through the local `claude -p` login:
  free smoke tests of the plumbing, but the Claude Code wrapper is part of
  what is measured, so those numbers compare arms only against each other -
  never against published baselines.

Every run appends one line per arm to `evals/results.md` and writes the
full per-sample detail to `evals/results/<date>/impossiblebench.json`.
