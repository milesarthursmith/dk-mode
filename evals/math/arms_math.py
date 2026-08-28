"""Three arms on MATH-500: pure task completion, scored against answer keys.

WHY MATHS, after two coding benchmarks. The owner's objection to unit-test
scoring is that a test suite is authored and can be wrong or gameable. A
maths problem is scored against an answer KEY - a fact about the problem -
and `math_verify` decides equivalence deterministically (1/2 == 0.5 ==
\\frac{1}{2}), so completion needs no judge model and no trusted tests.
Two further properties bought cheaply:

  - MATH-500 carries difficulty levels, so banding to "the model solves it
    sometimes" is nearly free. The band is where completion can move at
    all: tasks passed always or never carry no information about steering.
  - Samples are token-light, so the comparison gets real n (hundreds of
    trials) for a couple of dollars.

Stated limits, so the numbers are not over-read: the horizon is short, so
the cross-turn machinery barely engages, and dk-mode's rule list is
coding-flavoured - on maths a good monitor should mostly stay quiet. This
eval is an existence proof that injection can move completion, not the
final word on coding agents.

THE ARMS - identical task, prompt and budget; only the injected policy
differs. The injection rides the same ModelAPI patch as the coding harness
(imported from it), so a finding transfers across both:

    baseline    nothing injected
    dk          the shipped monitor selects before each generation
    challenge   a fixed text every Nth generation - no model, no selection

The agent prompt deliberately does NOT say "check your work": whether the
agent verifies unprompted is the behaviour under test, and the coding
harness already showed a scaffold prompt that pre-installs the discipline
flattens every arm (its README, rule 2).

Use run_math.py, which stages banding and the comparison.
"""
import os
import sys

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import (CORRECT, INCORRECT, Score, accuracy, scorer,
                               stderr)
from inspect_ai.solver import basic_agent, system_message
from inspect_ai.tool import python

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "evals", "impossiblebench"))

# The injection machinery is shared with the coding harness: same contextvar,
# same ModelAPI patch, same per-sample counters (gen_count, dk_fired,
# challenge_fired, injected_chars, dk_payload_log).
from arms import _install_injection, injected  # noqa: E402,F401

SYSTEM = """Solve the mathematics problem you are given. You have a python
tool for any computation you want to run. When you are finished, call
submit() with ONLY the final answer - a number or a LaTeX expression,
nothing else."""


def load_dataset(levels=(4, 5), limit=0, ids=None, seed=41, offset=0):
    """MATH-500, optionally restricted to levels or to an explicit id list
    (the band). Shuffled with a fixed seed so 'first N' is a stable random
    slice rather than the dataset's own ordering; offset draws the next
    slice of the same shuffle, so a widening pass never re-pays for
    problems already banded."""
    import random

    from datasets import load_dataset as hf_load
    rows = hf_load("HuggingFaceH4/MATH-500", split="test")
    samples = []
    for r in rows:
        if ids is not None and r["unique_id"] not in ids:
            continue
        if ids is None and int(r["level"]) not in levels:
            continue
        samples.append(Sample(
            id=r["unique_id"], input=r["problem"], target=r["answer"],
            metadata={"level": int(r["level"]), "subject": r["subject"]}))
    random.Random(seed).shuffle(samples)
    if offset:
        samples = samples[offset:]
    if limit:
        samples = samples[:limit]
    return MemoryDataset(samples)


@scorer(metrics=[accuracy(), stderr()])
def answer_key():
    """Deterministic equivalence against the dataset's answer key.

    math_verify parses both sides and decides mathematical equality, so
    formatting differences (fractions, decimals, boxed answers) do not
    score as failures. No judge model anywhere."""
    from math_verify import parse, verify

    async def score(state, target):
        got = (state.output.completion or "").strip()
        ok = False
        try:
            gold = parse(f"${target.text}$")
            answer = parse(got)
            ok = bool(verify(gold, answer))
        except Exception:
            ok = False
        return Score(value=CORRECT if ok else INCORRECT, answer=got[:100])
    return score


def _task(arm, use_dk=False, challenge_n=0, levels=(4, 5), limit=0,
          ids=None, attempts=1, offset=0, payload="challenge",
          challenger_n=0):
    inner = basic_agent(
        init=system_message(SYSTEM),
        tools=[python(timeout=30)],
        max_attempts=attempts,
    )
    if arm != "baseline":
        inner = injected(inner, arm, use_dk=use_dk, challenge_n=challenge_n,
                         payload=payload, challenger_n=challenger_n)
    else:
        inner = injected(inner, arm)   # counters only; injects nothing
    return Task(
        name=f"math_{arm}",
        dataset=load_dataset(levels=levels, limit=limit, ids=ids,
                             offset=offset),
        solver=inner,
        scorer=answer_key(),
        sandbox=("docker", os.path.join(HERE, "compose.yaml")),
        message_limit=25,
    )


@task
def baseline(limit=0, ids=None, offset=0):
    return _task("baseline", limit=int(limit) if limit else 0, ids=ids,
                 offset=int(offset))


@task
def dk(limit=0, ids=None):
    return _task("dk", use_dk=True, limit=int(limit) if limit else 0, ids=ids)


@task
def challenger(limit=0, ids=None, n=3):
    """The challenge skill run out-of-band: a separate model reads the
    transcript every n generations and injects its adversarial report."""
    return _task("challenger", challenger_n=int(n),
                 limit=int(limit) if limit else 0, ids=ids)


@task
def challenge(limit=0, ids=None, n=3, payload="challenge"):
    """The scheduled arm. `payload` picks the fixed text (see PAYLOADS in
    the shared arms module): challenge, try-harder, goal, goal+rules."""
    return _task(payload, challenge_n=int(n),
                 limit=int(limit) if limit else 0, ids=ids, payload=payload)
