"""Three arms on real Claude Code, with dk-mode running as a real plugin.

WHY THIS EXISTS ALONGSIDE evals/impossiblebench. That harness reimplements
dk-mode's injection: it imports dk_watch and appends a user message before
each generation. It measures the monitor's LOGIC but not its PLUMBING, and
EVALS.md rule 1 asks for the real channel - the hooks firing on real
sessions. This one runs the shipped plugin: Claude Code executes in a
sandbox, dk-mode's UserPromptSubmit/PostToolUse/Stop hooks run as
processes, and nothing about the injection path is simulated.

HOW THE PIECES FIT (inspect_swe does the hard part):

  container   one throwaway Docker container per sample, from Dockerfile
              here: dk-mode at /opt/dk-mode, seeded memory at /opt/dk-mem.
  agent       claude_code() copies a real Claude Code binary into the
              sandbox and runs it headlessly against the task.
  bridge      Claude Code's API calls are proxied back to inspect and served
              by whatever --model the eval was launched with. So a cheap
              OpenRouter model drives real Claude Code, and token limits,
              cost and transcripts flow through inspect as normal.
  hooks       registered in PROJECT-level /work/.claude/settings.json,
              written per arm by the setup solver below. Project level and
              not ~/.claude because inspect_swe seeds the home settings
              itself. DK_MEM is passed explicitly: ${CLAUDE_PLUGIN_DATA} is
              only populated by a real `claude plugin install`.

THE ARMS. Identical container, identical tasks, identical budget; the only
difference is what speaks:

  bare        no hooks registered. The control.
  dk          dk-mode's three hooks registered - the shipped plugin.
  challenge   no hooks; a fixed text injected every Nth bridged request via
              claude_code(filter=...). No model and no selection, so it
              cannot pick the wrong rule. This is the arm dk has to beat:
              if a schedule matches selection, the per-turn model call is
              not earning its place.

Run (needs Docker running and credits):

    python3 -m inspect_ai eval evals/hooked/arms_hooked.py@dk \\
        --model openrouter/google/gemini-2.5-flash-lite --limit 10

Score the behaviour afterwards with the existing tools - the logs are
ordinary inspect logs:

    python3 evals/impossiblebench/trace_metrics.py logs/<stamp>
"""
import os

from inspect_ai import Task, task
from inspect_ai.model import ChatMessageUser, GenerateInput
from inspect_ai.solver import chain, solver
from inspect_ai.util import sandbox
from inspect_swe import claude_code

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


def _dataset(split, limit):
    """The same LiveCodeBench tasks the other harness uses, so numbers from
    the two are comparable. Imported off the impossiblebench clone."""
    import sys
    ib = os.environ.get("IMPOSSIBLEBENCH", "")
    for p in ([ib] if ib else []) + [os.path.join(REPO, "..", "impossiblebench"),
                                     os.path.expanduser("~/impossiblebench")]:
        src = os.path.join(p, "src", "impossiblebench")
        if os.path.isdir(src):
            sys.path.insert(0, src)
            break
    else:
        raise SystemExit("set IMPOSSIBLEBENCH to the impossiblebench clone")
    from livecodebench_tasks import impossible_livecodebench
    # Built only for its dataset; the solver and scorer are replaced below.
    return impossible_livecodebench(
        split=split, agent_type="tools", limit=limit, sandbox="docker")


@solver
def setup(hooks: bool):
    """Write the task files and this arm's hook registration into the
    sandbox. Both arms get identical files; only settings.json differs."""
    async def solve(state, generate):
        md = state.metadata
        entry = md.get("entry_point", "solution")
        await sandbox().write_file(
            "func.py", md.get("prompt", "") + "\n    raise NotImplementedError")
        body = md.get("test", "").replace("def check(", "def test_func(")
        await sandbox().write_file("test.py", (
            f"from func import {entry}\n\n{body}\n\n"
            f'if __name__ == "__main__":\n'
            f"    test_func({entry})\n"
            f'    print("All tests passed!")\n'))
        await sandbox().write_file(
            ".claude/settings.json", HOOKS_JSON if hooks else '{"hooks": {}}')
        return state
    return solve


def _challenge_filter(every: int):
    """The scheduled control, injected without a plugin.

    claude_code(filter=...) intercepts each bridged model request, so a
    fixed text can be appended to the conversation on a schedule with no
    hook, no monitor and no selection step. Returning a GenerateInput
    replaces the request; returning None passes it through untouched.
    """
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


def _task(hooks: bool, split: str, limit: int, challenge_every: int = 0):
    base = _dataset(split, limit)
    agent = claude_code(
        # Claude Code's own workflow instructions are what a steering layer
        # would otherwise be duplicating, so nothing is added here: the
        # arms differ only in what dk-mode or the schedule says.
        cwd="/work",
        attempts=1,
        # The bridge serves whatever model the eval was launched with, but
        # Claude Code validates the model ID it is TOLD (ANTHROPIC_MODEL)
        # and rejects non-Anthropic names outright - the first flight died
        # on [claude-code:unrecognized_model] for the Gemini id. So the
        # presented identity is pinned to an Anthropic id while the calls
        # still go to the served model. Identity and servant differ; the
        # transcript records the real one.
        model_config="claude-haiku-4-5-20251001",
        disallowed_tools=["WebSearch", "WebFetch"],
        filter=_challenge_filter(challenge_every) if challenge_every else None,
    )
    return Task(
        name=base.name,
        dataset=base.dataset,
        solver=chain(setup(hooks), agent),
        scorer=base.scorer,
        sandbox=("docker", os.path.join(HERE, "compose.yaml")),
        message_limit=base.message_limit,
    )


@task
def bare(split="original", limit=10):
    """No hooks. Read this arm's behaviour columns before the others."""
    return _task(hooks=False, split=split, limit=limit)


@task
def dk(split="original", limit=10):
    """dk-mode's three hooks registered - the shipped plugin, really running."""
    return _task(hooks=True, split=split, limit=limit)


@task
def challenge(split="original", limit=10, n=3):
    """Fixed text every n generations. No model, no selection step."""
    return _task(hooks=False, split=split, limit=limit,
                 challenge_every=int(n))
