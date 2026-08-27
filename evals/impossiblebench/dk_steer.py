"""Put dk-mode inside an Inspect AI agent loop, so a public benchmark can
say whether it helps.

WHY THIS BENCHMARK. ImpossibleBench builds tasks where the written
specification and the unit tests contradict each other. Passing is therefore
only possible by cheating - by special-casing the test, hardcoding the
expected value, or editing the test rather than the code. The score is a
CHEATING RATE, and it is unambiguous: no judge model, no partial credit. The
published baseline has GPT-5 cheating 76% of the time on one variant, and the
paper shows the rate collapses to near zero when the tests are hidden, so the
measure moves under intervention.

dk-mode ships a rule for exactly this failure - "Makes the test pass instead
of making the code right" - taken from this line of work. So this benchmark
asks the sharpest available question: does putting that rule in front of the
model, at the moment it is about to cheat, make it cheat less?

A negative result is worth having and must be reported as one. "We measured
it and it did not help" is a real finding about a system built on the belief
that it would.

USAGE
    inspect eval evals/impossiblebench/dk_steer.py@dk_baseline --model ...
    inspect eval evals/impossiblebench/dk_steer.py@dk_steered  --model ...

Run both, then compare the cheating rate. Nothing else may differ between the
runs: same model, same split, same limit, same seed.
"""
import os
import sys

from inspect_ai.model import ChatMessageUser
from inspect_ai.solver import Solver, TaskState, solver

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "scripts"))
os.environ.setdefault("DK_HOME", os.path.expanduser("~"))
import dk_watch as W                                          # noqa: E402


def _as_dk_messages(state: TaskState):
    """Inspect messages -> the shape dk_watch reads.

    The agent under test is the 'assistant'. The benchmark harness speaks as
    the 'user'. That is the same shape as a real conversation, so the miner
    needs no special case.
    """
    out = []
    for i, m in enumerate(state.messages):
        role = getattr(m, "role", "")
        if role not in ("user", "assistant"):
            continue
        text = getattr(m, "text", "") or ""
        if not text.strip():
            continue
        out.append({"uuid": "m%d" % i, "role": role,
                    "text": text.strip()[:1500], "cwd": "", "ts": ""})
    return out


def steer_text(state: TaskState) -> str:
    """Ask dk-mode what applies right now. Returns '' when nothing does.

    This is the same call the Stop hook makes in a real session. It is not a
    re-implementation: it imports dk_watch and uses its prompt, its parser and
    its renderer, so the benchmark measures the shipped code.
    """
    rules = W.load_rules()
    if not rules:
        return ""
    convo = W.recent_exchanges(_as_dk_messages(state), W.EXCHANGES,
                               W.WINDOW_CHARS)
    if not convo:
        return ""
    text = W.call_model(W.read_key(), W.PROMPT.format(
        max_active=W.MAX_ACTIVE,
        rules="\n".join(f'{r["id"]}. {r["heading"]} - {r["looks_like"]}'
                        for r in rules),
        convo="\n\n".join(f'[{m["role"]} id={m["uuid"]}] {m["text"]}'
                          for m in convo)))
    if not text:
        return ""
    parsed = W.parse_selection(text, rules)
    if not parsed:
        return ""
    return W.render(parsed[0], parsed[1], rules)


@solver
def dk_inject(inner: Solver) -> Solver:
    """Wrap a solver so dk-mode speaks before each generation.

    In Claude Code the text is added to the prompt by a hook. Inspect has no
    such hook, so the equivalent is a message appended last, immediately
    before the model generates - which is the same position, and position is
    the point.

    Counters are written to state.metadata so a run reports how often dk-mode
    spoke. A run where it never spoke is not evidence about dk-mode.
    """
    async def solve(state: TaskState, generate) -> TaskState:
        state.metadata["dk_calls"] = state.metadata.get("dk_calls", 0) + 1
        try:
            text = steer_text(state)
        except Exception as exc:                # never fail the benchmark run
            state.metadata["dk_error"] = str(exc)[:200]
            text = ""
        if text:
            state.metadata["dk_fired"] = state.metadata.get("dk_fired", 0) + 1
            state.messages.append(ChatMessageUser(content=text))
        return await inner(state, generate)
    return solve


# --- the two runs to compare ------------------------------------------------
# impossiblebench is not a dependency of dk-mode. Install it separately:
#     git clone https://github.com/safety-research/impossiblebench
#     cd impossiblebench && pip install -e .
try:
    from impossiblebench import impossible_livecodebench
except ImportError:                                # keep this file importable
    impossible_livecodebench = None


def _task(split, limit, steered):
    if impossible_livecodebench is None:
        raise SystemExit(
            "impossiblebench is not installed. See the comment above, or:\n"
            "  pip install -e /path/to/impossiblebench")
    task = impossible_livecodebench(split=split, agent_type="minimal",
                                    limit=limit)
    if steered:
        task.solver = dk_inject(task.solver)
    return task


def dk_baseline(split: str = "conflicting", limit: int = 20):
    """The benchmark as published. Run this FIRST.

    A number with no baseline says nothing, and a baseline that does not match
    the published one means the setup is wrong and the comparison is void.
    """
    return _task(split, limit, steered=False)


def dk_steered(split: str = "conflicting", limit: int = 20):
    """The same benchmark with dk-mode speaking before each generation.

    Change nothing else between the two runs: same model, same split, same
    limit. The cheating rate is the result.
    """
    return _task(split, limit, steered=True)
