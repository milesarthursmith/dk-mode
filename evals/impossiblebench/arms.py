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
import os
import subprocess
import sys

from inspect_ai import task
from inspect_ai.model import ChatMessageUser
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


def _as_dk_messages(state):
    """Inspect messages -> the shape dk_watch reads. The agent under test is
    the assistant; the benchmark harness speaks as the user - the same shape
    as a real conversation, so the monitor needs no special case."""
    out = []
    for i, m in enumerate(state.messages):
        role = getattr(m, "role", "")
        text = (getattr(m, "text", "") or "").strip()
        if role in ("user", "assistant") and text:
            out.append({"uuid": "m%d" % i, "role": role,
                        "text": text[:1500], "cwd": "", "ts": ""})
    return out


def _dk_payload(state):
    """One monitor step: the same call the Stop hook makes, with the running
    brief kept per sample in state.metadata instead of in a file. GOAL is
    copied from the first user message, never taken from the model - the
    same rule the live code enforces."""
    rules = W.load_rules()
    if not rules:
        return ""
    msgs = _as_dk_messages(state)
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


@solver
def injected(inner, arm, use_dk=False, challenge_n=0):
    """Wrap a solver so a payload lands immediately before EVERY generation.

    The inner solver's loop (attempt -> test -> feedback -> attempt) is left
    untouched; only its `generate` is wrapped, so all arms get exactly the
    same number of opportunities to speak. challenge_n=K fires the fixed text
    on the 1st generation and every Kth after; use_dk asks the monitor each
    time and injects whatever it selects, which is usually nothing.
    """
    async def solve(state, generate):
        state.metadata["arm"] = arm

        async def gen(s, **kw):
            n = s.metadata.get("gen_count", 0) + 1
            s.metadata["gen_count"] = n
            parts = []
            if challenge_n and (n - 1) % challenge_n == 0:
                parts.append(challenge_text())
                s.metadata["challenge_fired"] = \
                    s.metadata.get("challenge_fired", 0) + 1
            if use_dk:
                try:
                    dk = _dk_payload(s)
                except Exception as exc:       # never fail the benchmark run
                    s.metadata["dk_error"] = str(exc)[:300]
                    dk = ""
                if dk:
                    s.metadata["dk_fired"] = s.metadata.get("dk_fired", 0) + 1
                    parts.append(dk)
            if parts:
                text = "\n\n".join(parts)
                s.metadata["injected_chars"] = \
                    s.metadata.get("injected_chars", 0) + len(text)
                s.messages.append(ChatMessageUser(content=text))
            return await generate(s, **kw)

        return await inner(state, gen)
    return solve


def _task(split, limit, arm, use_dk=False, challenge_n=0):
    if impossible_livecodebench is None:
        raise SystemExit(
            "impossiblebench is not importable. Clone it and set\n"
            "  export IMPOSSIBLEBENCH=/path/to/impossiblebench\n"
            "(see the module docstring - do not pip install -e it)")
    t = impossible_livecodebench(
        split=split, agent_type="minimal", limit=limit,
        sandbox=os.environ.get("DK_EVAL_SANDBOX", "docker"))
    t.solver = injected(t.solver, arm, use_dk=use_dk, challenge_n=challenge_n)
    return t


# On the "conflicting" and "oneoff" splits the accuracy IS the cheating rate:
# the tasks cannot be passed honestly, so lower is better. On "original" it
# is a plain pass rate - run that split to check steering does not break
# honest work.

@task
def arm_baseline(split="conflicting", limit=20):
    """The benchmark as published, untouched. Read this number first: if it
    shows no cheating at all, the other arms have nothing to prevent and the
    run says nothing."""
    if impossible_livecodebench is None:
        raise SystemExit("impossiblebench is not importable (see arms.py)")
    return impossible_livecodebench(
        split=split, agent_type="minimal", limit=limit,
        sandbox=os.environ.get("DK_EVAL_SANDBOX", "docker"))


@task
def arm_dk(split="conflicting", limit=20):
    """The shipped monitor selects before each generation."""
    return _task(split, limit, "dk", use_dk=True)


@task
def arm_challenge(split="conflicting", limit=20, n=1):
    """A fixed challenge every n generations. No model, no selection."""
    return _task(split, limit, "challenge", challenge_n=int(n))


@task
def arm_dk_challenge(split="conflicting", limit=20, n=1):
    """Both together."""
    return _task(split, limit, "dk+challenge", use_dk=True,
                 challenge_n=int(n))
