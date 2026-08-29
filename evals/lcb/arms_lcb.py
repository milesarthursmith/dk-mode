"""Three arms on LiveCodeBench easy+medium, under real Claude Code.

This is the instrument the maths band could not be. Short single-answer
problems gave the steering layer nothing to steer: 2-12 turns, one
problem, no room for a loop or a forgotten decision. Every knob measured
null there, and the arc rules the monitor exists for barely fired.

Here the agent gets a stub, a visible test file, and a shell, and works
until the tests pass or it runs out of attempts - the shape where
circling, drifting off the goal, and declaring done without checking
actually occur.

  bare       no hooks. The control.
  dk         dk-mode's three hooks registered - the shipped plugin.
  challenge  no hooks; a fixed text injected on a schedule. No model and
             no selection, so it cannot pick the wrong rule. If dk does
             not beat this, the per-turn model call is not earning its
             place.

Scored on HELD-OUT tests (see dataset.py): the agent develops against a
couple of visible cases and is judged on a dozen or more hidden ones, so
hard-coding the examples does not pass and no judge model is involved.

THE THREE THINGS THAT MUST BE TRUE for the dk arm to mean anything - all
three failed silently on earlier flights, and the transcript looks
identical when they do (see evals/hooked/compose.yaml):
  1. DK_* credentials reach the container.
  2. The container can verify TLS to the monitor's API (DK_CA_BUNDLE).
  3. attempts > 1, because dk_watch writes its verdict for the NEXT
     prompt and a single-prompt session never has one.
Always confirm live monitor blocks in the log before reporting a dk
number:

    python3 evals/lcb/check_live.py evals/lcb/logs/<stamp>
"""
import os

from inspect_ai import Task, task
from inspect_ai.model import ChatMessageUser, GenerateInput
from inspect_ai.scorer import CORRECT, INCORRECT, Score, accuracy, scorer, stderr
from inspect_ai.solver import chain, solver
from inspect_ai.util import sandbox
from inspect_swe import claude_code

import dataset as D

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

HOOKS_JSON = """{
  "hooks": {
    "UserPromptSubmit": [{"hooks": [{"type": "command",
      "command": "DK_MEM=/opt/dk-mem bash /opt/dk-mode/scripts/dk_recall.sh"}]}],
    "PostToolUse": [{"hooks": [{"type": "command",
      "command": "DK_MEM=/opt/dk-mem python3 /opt/dk-mode/scripts/dk_tripwire.py"}]}],
    "Stop": [{"hooks": [{"type": "command",
      "command": "DK_MEM=/opt/dk-mem bash /opt/dk-mode/scripts/dk_capture.sh"}]}]
  }
}"""

CHALLENGE_PATH = os.environ.get(
    "DK_EVAL_CHALLENGE",
    os.path.join(REPO, "evals", "impossiblebench", "challenge.md"))


@solver
def setup(hooks: bool):
    """Task files and this arm's hook registration. Identical files in
    every arm; only settings.json differs."""
    async def solve(state, generate):
        md = state.metadata
        await sandbox().write_file("func.py", md["func"])
        await sandbox().write_file("test.py", md["test"])
        await sandbox().write_file(
            ".claude/settings.json", HOOKS_JSON if hooks else '{"hooks": {}}')
        return state
    return solve


@scorer(metrics=[accuracy(), stderr()])
def held_out():
    """Run the hidden cases against whatever the agent left in func.py.

    Every failure mode here is a FAILED SAMPLE, never a failed run. The
    hidden cases are larger than the visible ones, so a brute-force
    solution that passes the examples can exceed the time limit on them -
    that is the agent failing the task, not the harness breaking. An
    earlier version let the timeout propagate and it killed two arms
    mid-run at 20 and 14 of 60 samples, which is unusable for a
    comparison and costs the whole spend."""
    async def score(state, target):
        try:
            await sandbox().write_file("held.py", state.metadata["held_out"])
            r = await sandbox().exec(["python", "held.py"], timeout=45)
            ok = r.returncode == 0
            why = (r.stderr or r.stdout or "")
        except Exception as e:                       # timeout, dead sandbox
            ok, why = False, f"{type(e).__name__}: {e}"
        return Score(value=CORRECT if ok else INCORRECT,
                     answer=("passed" if ok else "failed"),
                     explanation=why[-600:])
    return score


def _challenge_filter(every: int):
    """The scheduled control: a fixed text appended to every Nth bridged
    request. No hook, no monitor, no selection step."""
    with open(CHALLENGE_PATH, encoding="utf-8") as f:
        text = f.read().strip()
    state = {"n": 0}

    async def filter(model, input, tools, tool_choice, config):
        state["n"] += 1
        if (state["n"] - 1) % every:
            return None
        return GenerateInput(
            input=list(input) + [ChatMessageUser(content=text)],
            tools=tools, tool_choice=tool_choice, config=config)
    return filter


def _task(name, hooks, limit, ids, easy_frac, challenge_every=0, attempts=6):
    agent = claude_code(
        cwd="/work",
        # > 1 is load-bearing for the dk arm; see the module docstring.
        attempts=attempts,
        # Claude Code validates the model id it is TOLD and rejects
        # non-Anthropic names, so the presented identity is pinned while
        # the bridge serves whatever --model the eval was launched with.
        model_config="claude-haiku-4-5-20251001",
        disallowed_tools=["WebSearch", "WebFetch"],
        filter=_challenge_filter(challenge_every) if challenge_every else None,
    )
    return Task(
        name=f"lcb_{name}",
        dataset=D.build(limit=int(limit), ids=ids, easy_frac=float(easy_frac)),
        solver=chain(setup(hooks), agent),
        scorer=held_out(),
        sandbox=("docker", os.path.join(REPO, "evals", "hooked", "compose.yaml")),
        message_limit=60,
    )


@task
def bare(limit=20, ids=None, easy_frac=0.6):
    """No hooks. Read this arm first."""
    return _task("bare", False, limit, ids, easy_frac)


@task
def dk(limit=20, ids=None, easy_frac=0.6):
    """The shipped plugin, hooks really firing."""
    return _task("dk", True, limit, ids, easy_frac)


@task
def challenge(limit=20, ids=None, easy_frac=0.6, n=3):
    """Fixed text every n generations. No model, no selection."""
    return _task("challenge", False, limit, ids, easy_frac,
                 challenge_every=int(n))
