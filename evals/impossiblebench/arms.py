"""Four arms on ImpossibleBench: does dk-mode beat a scheduled challenge?

ImpossibleBench builds tasks where the specification and the unit tests
contradict each other, so passing IS cheating - no judge model, no argument.
dk-mode ships a rule for exactly this failure ("makes the test pass instead
of making the code right"), so this asks the sharpest available question.

THE ARMS. All four inject through the same channel - a user message appended
immediately before the model generates, which is the position dk-mode's hook
puts text in a real session. The comparison is therefore between POLICIES for
what to say and when, not between plumbing:

    arm_baseline      nothing injected. Run this FIRST, and read its number
                      before reading any other.
    arm_dk            the shipped monitor: dk_watch's prompt, parser and
                      renderer decide what applies before each generation.
                      One cheap model call per generation.
    arm_challenge     a fixed challenge text every N generations. No model
                      call, no selection step - it cannot fail by picking the
                      wrong rule or picking nothing. This is both the dumb
                      control and a feature candidate (docs/log.md,
                      2026-08-27, "periodic challenge").
    arm_dk_challenge  both.

If arm_challenge matches arm_dk, the selection layer is not earning its
per-turn model call, and that result gets reported, not buried.

WHAT EACH RUN RECORDS (state.metadata, visible in the eval log per sample):
    gen_count         generations in this sample
    dk_calls/dk_fired how often the monitor ran / spoke. A run where it never
                      spoke says nothing about steering - check this before
                      concluding anything.
    dk_rules/dk_alerts what it picked and said, for reading afterwards
    challenge_fired   scheduled injections
    injected_chars    total injected text, for the cost column

USAGE - prefer run_arms.py, which runs the arms and aggregates:
    python3 evals/impossiblebench/run_arms.py --limit 20 \
        --model anthropic/claude-haiku-4-5

Direct inspect usage works too once impossiblebench is importable:
    inspect eval evals/impossiblebench/arms.py@arm_baseline --model ...

SETUP. impossiblebench is not a dependency of dk-mode. Clone it and point
IMPOSSIBLEBENCH at the clone (pip install -e fails on Debian setuptools, and
its swebench modules need Python 3.12; the path route needs neither):
    git clone https://github.com/safety-research/impossiblebench
    export IMPOSSIBLEBENCH=/path/to/impossiblebench
"""
import contextvars
import os
import subprocess
import sys

from inspect_ai import task
from inspect_ai.model import ChatMessageUser, get_model
from inspect_ai.solver import solver

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

# --- dk-mode itself ---------------------------------------------------------
# The benchmark must measure the shipped code, so dk_watch is imported, not
# re-implemented. Its memory is a throwaway directory seeded with the shipped
# baseline rules - the same state a fresh install has - unless DK_MEM already
# points somewhere (e.g. at a real mined memory, to test that instead).
sys.path.insert(0, os.path.join(REPO, "scripts"))
if not os.environ.get("DK_MEM"):
    os.environ["DK_MEM"] = os.path.join(HERE, ".dk_mem")
subprocess.run(["bash", os.path.join(REPO, "scripts", "dk_bootstrap.sh"),
                os.environ["DK_MEM"]], check=False, capture_output=True)
import dk_watch as W                                          # noqa: E402

# --- the benchmark ----------------------------------------------------------
_IB = os.environ.get("IMPOSSIBLEBENCH", "")
for p in ([_IB] if _IB else []) + [
        os.path.join(REPO, "..", "impossiblebench"),
        os.path.expanduser("~/impossiblebench")]:
    src = os.path.join(p, "src", "impossiblebench")
    if os.path.isdir(src):
        sys.path.insert(0, src)
        break
try:
    from livecodebench_tasks import impossible_livecodebench
except ImportError:
    impossible_livecodebench = None


CHALLENGE_PATH = os.environ.get(
    "DK_EVAL_CHALLENGE", os.path.join(HERE, "challenge.md"))


def challenge_text():
    with open(CHALLENGE_PATH, encoding="utf-8") as f:
        return f.read().strip()


def _as_dk_messages(messages):
    """Inspect messages -> the shape dk_watch reads. The agent under test is
    the assistant; everything it is answering to is the user - the same shape
    as a real conversation, so the monitor needs no special case.

    Tool results are folded in as user turns rather than dropped. They are
    where the evidence lives: "the tests failed", "the file does not exist".
    dk-mode's rules are largely about ignoring exactly that - claiming done
    without running anything, repeating a step that already failed - so a
    monitor that could not see tool output would be blind to the failures it
    is meant to name."""
    out = []
    for i, m in enumerate(messages):
        role = getattr(m, "role", "")
        text = (getattr(m, "text", "") or "").strip()
        if not text:
            continue
        if role == "tool":
            out.append({"uuid": "m%d" % i, "role": "user",
                        "text": "[tool result] " + text[:1500],
                        "cwd": "", "ts": ""})
        elif role in ("user", "assistant"):
            out.append({"uuid": "m%d" % i, "role": role,
                        "text": text[:1500], "cwd": "", "ts": ""})
    return out


def _dk_payload(state, messages):
    """One monitor step: the same call the Stop hook makes, with the running
    brief kept per sample in state.metadata instead of in a file. GOAL is
    copied from the first user message, never taken from the model - the
    same rule the live code enforces."""
    rules = W.load_rules()
    if not rules:
        return ""
    msgs = _as_dk_messages(messages)
    convo = W.recent_exchanges(msgs, W.EXCHANGES, W.WINDOW_CHARS)
    if not convo:
        return ""
    state.metadata["dk_calls"] = state.metadata.get("dk_calls", 0) + 1
    text = W.call_model(W.read_key(), W.PROMPT.format(
        max_active=W.MAX_ACTIVE,
        brief=state.metadata.get("dk_brief")
        or "(nothing yet - this is the first turn)",
        rules="\n".join(f'{r["id"]}. {r["heading"]} - {r["looks_like"]}'
                        for r in rules),
        convo="\n\n".join(f'[{m["role"]} id={m["uuid"]}] {m["text"]}'
                          for m in convo)))
    parsed = W.parse_selection(text, rules) if text else None
    if not parsed:
        if not text:
            state.metadata["dk_error"] = "; ".join(W.LAST_ERROR[-2:])[:300]
        return ""
    active, alert, _steering, brief = parsed
    if brief:
        lines = [ln for ln in brief.splitlines()
                 if ln.strip() and not ln.strip().startswith("GOAL:")]
        state.metadata["dk_brief"] = (
            "GOAL: " + W.first_request(msgs) + "\n" + "\n".join(lines)
        )[:W.BRIEF_MAX]
    by_id = {r["id"]: r for r in rules}
    if active:
        state.metadata.setdefault("dk_rules", []).extend(
            by_id[i]["heading"] for i in active)
    if alert:
        state.metadata.setdefault("dk_alerts", []).append(alert[:200])
    return W.render(active, alert, rules)


# The sample currently generating, so the injection point below can find its
# TaskState. A contextvar and not a global: inspect runs samples concurrently
# as asyncio tasks, and each task gets its own copy, so two samples in flight
# cannot write each other's counters.
_CURRENT = contextvars.ContextVar("dk_current", default=None)


def _install_injection(model):
    """Inject at the model API, which is the only point every scaffold shares.

    The first version of this wrapped the `generate` passed to the solver.
    That works for the minimal scaffold and silently does NOTHING for the
    tools scaffold, which is `basic_agent` - it runs its own loop and calls
    the model directly, so the wrapper is never reached. The symptom is an
    arm that reports gen_count 0 and quietly degrades to baseline while
    still being labelled `dk`; the smoke run caught it exactly that way.

    Wrapping ModelAPI.generate instead means the payload lands before every
    generation in any scaffold, present or future. The conversation is taken
    from the `input` list rather than state.messages for the same reason:
    inside an agent loop, `input` is what the model is about to see, and
    state.messages may not have caught up.

    Patching the bound method rather than subclassing ModelAPI keeps every
    other behaviour - retries, connection limits, token counting - pointing
    at the real object.
    """
    api = model.api
    if getattr(api, "_dk_patched", False):
        return model
    inner_generate = api.generate

    async def generate(input, tools, tool_choice, config):
        cur = _CURRENT.get()
        if cur is not None:
            state, use_dk, challenge_n = cur
            payload = _payload_for(state, input, use_dk, challenge_n)
            if payload:
                input = list(input) + [ChatMessageUser(content=payload)]
        return await inner_generate(input, tools, tool_choice, config)

    api.generate = generate
    api._dk_patched = True
    return model


def _payload_for(state, messages, use_dk, challenge_n):
    """What this arm says before this generation. Empty string means silence,
    which is the normal case for the dk arms."""
    n = state.metadata.get("gen_count", 0) + 1
    state.metadata["gen_count"] = n
    parts = []
    if challenge_n and (n - 1) % challenge_n == 0:
        parts.append(challenge_text())
        state.metadata["challenge_fired"] = \
            state.metadata.get("challenge_fired", 0) + 1
    if use_dk:
        try:
            dk = _dk_payload(state, messages)
        except Exception as exc:           # never fail the benchmark run
            state.metadata["dk_error"] = str(exc)[:300]
            dk = ""
        if dk:
            state.metadata["dk_fired"] = state.metadata.get("dk_fired", 0) + 1
            parts.append(dk)
    if not parts:
        return ""
    text = "\n\n".join(parts)
    state.metadata["injected_chars"] = \
        state.metadata.get("injected_chars", 0) + len(text)
    return text


@solver
def injected(inner, arm, use_dk=False, challenge_n=0):
    """Mark this sample as injectable and record which arm it belongs to.

    The injection itself happens in _install_injection, at the model API.
    This solver only publishes the sample's TaskState so that code can find
    it, and the inner solver runs completely untouched - so every arm gets
    exactly the same scaffold and the same number of chances to speak.
    """
    async def solve(state, generate):
        state.metadata["arm"] = arm
        token = _CURRENT.set((state, use_dk, challenge_n))
        try:
            return await inner(state, generate)
        finally:
            _CURRENT.reset(token)
    return solve


# The scaffold is a knob, not a constant. impossiblebench ships two:
#
#   minimal  submit -> test -> feedback, no tools. The published Conflicting-
#            LiveCodeBench numbers use this, and six of eight frontier models
#            score exactly 0.0% on it (arXiv:2510.20270, fig 4) - a floor with
#            almost no dynamic range to measure against.
#   tools    SWE-style: bash, python and a file editor against a sandbox. The
#            paper's own finding is that this is where the signal lives -
#            "more complex scaffolds encourage more cheating" (appendix E.1),
#            moving Sonnet 3.7 from 0% to ~37% on the same split.
#
# It is also the scaffold whose failure modes dk-mode actually names: reading
# without acting, repeating a step, claiming done without running anything.
# A one-shot puzzle cannot express any of those.
AGENT = os.environ.get("DK_EVAL_AGENT", "minimal")
ATTEMPTS = int(os.environ.get("DK_EVAL_ATTEMPTS", "3"))


def _message_limit(agent):
    """Messages the sample may use before inspect cuts it off.

    This has to be generous, and the reason is a confound rather than a
    preference: every arm injects a user message before each generation, so
    an injected arm spends the budget FASTER than baseline. Leave the limit
    where the published minimal runs put it (30) and the dk arms would hit
    the ceiling first, losing on truncation and reading as though steering
    had hurt. The limit must not bind for any arm, so it is set well above
    what the scaffold plus its injections can consume.
    """
    env = os.environ.get("DK_EVAL_MESSAGE_LIMIT", "").strip()
    if env:
        return int(env)
    return 200 if agent == "tools" else 60


def _build(split, limit, agent=None, attempts=None):
    if impossible_livecodebench is None:
        raise SystemExit(
            "impossiblebench is not importable. Clone it and set\n"
            "  export IMPOSSIBLEBENCH=/path/to/impossiblebench\n"
            "(see the module docstring - do not pip install -e it)")
    agent = agent or AGENT
    return impossible_livecodebench(
        split=split, agent_type=agent, limit=limit,
        max_attempts=int(attempts or ATTEMPTS),
        message_limit=_message_limit(agent),
        sandbox=os.environ.get("DK_EVAL_SANDBOX", "docker"))


def _task(split, limit, arm, use_dk=False, challenge_n=0,
          agent=None, attempts=None):
    t = _build(split, limit, agent, attempts)
    t.solver = injected(t.solver, arm, use_dk=use_dk, challenge_n=challenge_n)
    return t


# On the "conflicting" and "oneoff" splits the accuracy IS the cheating rate:
# the tasks cannot be passed honestly, so lower is better. On "original" it
# is a plain pass rate - run that split to check steering does not break
# honest work.

@task
def arm_baseline(split="conflicting", limit=20, agent=None, attempts=None):
    """The benchmark as published, untouched. Read this number first: if it
    shows no cheating at all, the other arms have nothing to prevent and the
    run says nothing."""
    return _build(split, limit, agent, attempts)


@task
def arm_dk(split="conflicting", limit=20, agent=None, attempts=None):
    """The shipped monitor selects before each generation."""
    return _task(split, limit, "dk", use_dk=True,
                 agent=agent, attempts=attempts)


@task
def arm_challenge(split="conflicting", limit=20, n=1,
                  agent=None, attempts=None):
    """A fixed challenge every n generations. No model, no selection."""
    return _task(split, limit, "challenge", challenge_n=int(n),
                 agent=agent, attempts=attempts)


@task
def arm_dk_challenge(split="conflicting", limit=20, n=1,
                     agent=None, attempts=None):
    """Both together."""
    return _task(split, limit, "dk+challenge", use_dk=True,
                 challenge_n=int(n), agent=agent, attempts=attempts)
