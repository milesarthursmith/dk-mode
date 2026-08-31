"""Goal mode: one repo, ~20 seeded bugs, one standing goal, 100s of turns.

The regime every earlier instrument missed (swe median 12 turns, max 36):
a self-driving session where the agent works toward a goal for hundreds
of turns, re-prompted mechanically whenever it stops. This is dk-mode's
claimed habitat - the arc failures (loops, drift, forgotten subgoals)
that a per-turn monitor tracks and a fixed-cadence nudge cannot.

  bare       continue-driver only. The control.
  dk         the three hooks (muting bug fixed 2026-08-31: an empty
             monitor selection now falls through to the static note).
  challenge  fixed text every 3rd generation.

The driver: attempts=25. After each stop the scorer resets tests/ from
the pristine snapshot, runs the originally-failing test ids, and scores
the fraction now passing; below 1.0 the agent gets "N tests still
failing. Continue." - which is also the dk arm's recall slot. Score is
CONTINUOUS (fraction fixed), so arms separate on partial progress, not
just all-or-nothing.
"""
import os

from inspect_ai import Task, eval as inspect_eval, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageUser, GenerateInput
from inspect_ai.scorer import Score, mean, scorer, stderr
from inspect_ai.solver import chain, solver
from inspect_ai.util import sandbox
from inspect_ai.agent import AgentAttempts
from inspect_swe import claude_code

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
PLUGIN = os.path.join(REPO, "evals", "hooked", "plugin")
BUGS = open(os.path.join(HERE, "bugs.patch")).read()
FAILING = [l.strip() for l in open(os.path.join(HERE, "failing_tests.txt"))
           if l.strip()]

GOAL = (
    "The jinja2 library in /opt/jinja has multiple independent bugs in its "
    "source (src/jinja2/). Its test suite (tests/) is correct - do NOT "
    "modify anything under tests/. Your goal: fix the library until the "
    "entire test suite passes. Run `python -m pytest tests -q` to see "
    "failures, then find and fix each bug in the source. Work autonomously "
    "until everything passes."
)

DK_ENV = (
    "DK_MEM=/opt/dk-mem"
    " DK_BACKEND=openai"
    " DK_API_URL=http://relay:8080/api/v1/chat/completions"
    " DK_API_KEY={key}"
    " DK_WATCH_MODELS=google/gemini-2.5-flash"
    " DK_LOG_DIR=/opt/dk-mem"
)

HOOKS_JSON = """{{
  "hooks": {{
    "UserPromptSubmit": [{{"hooks": [{{"type": "command",
      "command": "{env} bash /opt/dk-mode/scripts/dk_recall.sh 2>>/opt/dk-mem/hook_err.log"}}]}}],
    "PostToolUse": [{{"hooks": [{{"type": "command",
      "command": "{env} python3 /opt/dk-mode/scripts/dk_tripwire.py 2>>/opt/dk-mem/hook_err.log"}}]}}],
    "Stop": [{{"hooks": [{{"type": "command",
      "command": "{env} bash /opt/dk-mode/scripts/dk_capture.sh 2>>/opt/dk-mem/hook_err.log"}}]}}]
  }}
}}"""


@solver
def setup(hooks: bool):
    plugin_files = {}
    if hooks:
        for root, _, files in os.walk(PLUGIN):
            if "__pycache__" in root: continue
            for f in files:
                p = os.path.join(root, f)
                plugin_files[os.path.relpath(p, PLUGIN)] = open(p).read()
        env = DK_ENV.format(key=os.environ["OPENROUTER_API_KEY"])

    async def solve(state, generate):
        await sandbox().write_file("/tmp/bugs.patch", BUGS)
        r = await sandbox().exec(["bash", "-c",
            "cd /opt/jinja && git apply /tmp/bugs.patch && rm /tmp/bugs.patch"])
        if r.returncode != 0:
            raise RuntimeError(f"bug patch failed: {r.stderr}")
        if hooks:
            for rel, content in plugin_files.items():
                await sandbox().write_file(f"/opt/dk-mode/{rel}", content)
            r = await sandbox().exec(["bash", "-c",
                "chmod +x /opt/dk-mode/scripts/* && mkdir -p /opt/dk-mem "
                "&& bash /opt/dk-mode/scripts/dk_bootstrap.sh /opt/dk-mem"])
            if r.returncode != 0:
                raise RuntimeError(f"dk setup failed: {r.stderr}")
            settings = HOOKS_JSON.format(env=env)
        else:
            settings = '{"hooks": {}}'
        await sandbox().write_file("/opt/jinja/.claude/settings.json", settings)
        return state
    return solve


@solver
def probe():
    async def solve(state, generate):
        r = await sandbox().exec(["bash", "-c",
            "ls -la /opt/dk-mem 2>&1; echo ==; "
            "tail -c 3000 /opt/dk-mem/dk_watch*.log /opt/dk-mem/hook_err.log 2>/dev/null"])
        state.messages.append(ChatMessageUser(
            content=f"<dk-probe>\n{r.stdout[-6000:]}\n</dk-probe>"))
        return state
    return solve


@scorer(metrics=[mean(), stderr()])
def fraction_fixed():
    """Reset tests/ from the pristine snapshot, run the originally-failing
    ids, score the fraction now passing. Test tampering scores nothing."""
    ids = " ".join(f"'{t}'" for t in FAILING)
    async def score(state, target):
        try:
            r = await sandbox().exec(["bash", "-c",
                "cd /opt/jinja && rm -rf tests && cp -r /opt/pristine_tests tests "
                f"&& python -m pytest {ids} -q --no-header 2>&1 | tail -1"],
                timeout=300)
            out = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
        except Exception as e:
            return Score(value=0.0, explanation=f"{type(e).__name__}: {e}")
        import re as _re
        passed = sum(int(m.group(1)) for m in _re.finditer(r"(\d+) passed", out))
        return Score(value=round(passed / len(FAILING), 4), answer=out,
                     explanation=out)
    return score


def _challenge_filter(every: int):
    with open(os.path.join(REPO, "evals", "impossiblebench",
                           "challenge.md"), encoding="utf-8") as f:
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


async def _continue_msg(state, scores):
    frac = scores[0].value if scores else 0
    left = round((1 - float(frac)) * len(FAILING))
    return (f"{left} of the test cases are still failing "
            f"({float(frac):.0%} fixed). The goal stands: make the entire "
            f"test suite pass. Continue.")


def make_task(name, hooks, challenge_every=0):
    agent = claude_code(
        cwd="/opt/jinja",
        attempts=AgentAttempts(attempts=int(os.environ.get("GOAL_ATTEMPTS", "25")),
                    incorrect_message=_continue_msg),
        model_config="claude-haiku-4-5-20251001",
        disallowed_tools=["WebSearch", "WebFetch"],
        filter=_challenge_filter(challenge_every) if challenge_every else None,
    )
    return Task(
        name=f"goal_{name}",
        dataset=MemoryDataset([Sample(id="jinja-20bugs", input=GOAL)]),
        solver=chain(setup(hooks), agent, probe()) if hooks
               else chain(setup(hooks), agent),
        scorer=fraction_fixed(),
        sandbox=("docker", os.path.join(HERE, "compose.yaml")),
        message_limit=int(os.environ.get("GOAL_MSG_LIMIT", "600")),
    )


if __name__ == "__main__":
    import sys
    arms = sys.argv[1:] or ["bare", "dk", "challenge"]
    spec = {"bare": (False, 0), "dk": (True, 0), "challenge": (False, 3)}
    for arm in arms:
        hooks, every = spec[arm]
        inspect_eval(
            make_task(arm, hooks, every),
            model=os.environ.get("GOAL_MODEL",
                                 "openrouter/google/gemini-2.5-flash"),
            epochs=int(os.environ.get("GOAL_EPOCHS", "3")),
            max_samples=3,
            log_dir=os.path.join(HERE, "logs"),
            display="plain",
        )
