"""LiveCodeBench easy+medium as a multi-turn coding eval, built without an LLM.

WHY THIS EXISTS. The ImpossibleBench LiveCodeBench variant is drawn from
LiveCodeBench's HARD split by construction (its generator hard-codes
`if difficulty != 'hard': continue`, and every task id carries the
`lcbhard_` prefix). Published pass@1 for a Flash-Lite-class model on
LCB-hard is 4-7%; our agentic runs measured 0.12-0.17. That is not a
broken harness, it is the wrong instrument: at that rate ~95% of failures
are the model not knowing the algorithm, and a steering layer can only
rescue tasks the model could have solved but botched procedurally.

This module builds the same task SHAPE from LiveCodeBench's easy and
medium problems instead, where a cheap model lands in the 0.6-0.8 band
that leaves procedural failures visible.

NO MODEL IS USED TO BUILD IT. ImpossibleBench transcribes stdin/stdout
problems into unit-test form with Sonnet, which costs money and inserts a
model between the source data and the eval. That is unnecessary for the
LeetCode-derived subset: those problems ship `starter_code` (a class with
a typed method signature) and JSON-encoded functional test cases, so the
conversion is mechanical. Checked on the whole pool: signature arity
matches the test input line count for every problem, 43/43 in the newest
release file.

HELD-OUT SCORING. Each problem carries a couple of public cases and a
dozen private ones (zlib+base64+pickle inside the row). The agent is given
the PUBLIC cases as its test.py, and is scored on the PRIVATE ones, so
hard-coding the visible expectations does not pass. This also keeps the
task honest without a judge model or a hand-authored suite.
"""
import base64
import json
import pickle
import random
import re
import zlib

FILES = ["test.jsonl", "test2.jsonl", "test3.jsonl", "test4.jsonl",
         "test5.jsonl", "test6.jsonl"]
REPO = "livecodebench/code_generation_lite"


def _decode_private(blob):
    try:
        return json.loads(pickle.loads(zlib.decompress(
            base64.b64decode(blob.encode("utf-8")))))
    except Exception:
        return []


def _entry(starter):
    """The method the agent must implement, from the starter signature."""
    m = re.search(r"def (\w+)\(self", starter)
    return m.group(1) if m else ""


def raw_rows():
    """Every LeetCode-style easy/medium problem across the release files."""
    from huggingface_hub import hf_hub_download
    seen, out = set(), []
    for f in FILES:
        path = hf_hub_download(REPO, f, repo_type="dataset")
        for line in open(path):
            r = json.loads(line)
            if r["difficulty"] not in ("easy", "medium"):
                continue
            if not (r.get("starter_code") or "").strip():
                continue          # stdin/stdout problem: not mechanical
            if r["question_id"] in seen:
                continue
            seen.add(r["question_id"])
            out.append(r)
    return out


def test_file(cases, entry, public):
    """A runnable test.py. The same shape scores the run, with the private
    cases substituted, so what the agent develops against and what it is
    judged on differ only in which cases are listed."""
    rows = ",\n".join(
        "    (%r, %r)" % ([l for l in c["input"].split("\n") if l.strip()],
                          c["output"])
        for c in cases)
    return f'''import json
from func import Solution

# {"the cases you can see" if public else "held-out cases"}
CASES = [
{rows}
]


def test_func(sol):
    for i, (args_json, expected_json) in enumerate(CASES):
        args = [json.loads(a) for a in args_json]
        expected = json.loads(expected_json)
        got = sol.{entry}(*args)
        assert got == expected, (
            f"case {{i}}: {entry}(*{{args}}) returned {{got!r}}, "
            f"expected {{expected!r}}")


if __name__ == "__main__":
    test_func(Solution())
    print("All tests passed!")
'''


def func_file(starter):
    """The stub the agent edits: imports it will need, then the signature."""
    return ("from typing import List, Optional, Dict, Tuple, Any\n"
            "import math, collections, itertools, heapq, bisect, re\n\n"
            + starter.rstrip() + "\n        pass\n")


def build(limit=0, ids=None, seed=41, offset=0, easy_frac=0.6):
    """Sample list for inspect. `easy_frac` sets the easy/medium mix, which
    is how the expected pass rate is tuned: easy sits near 0.85 for a cheap
    model and medium near 0.30, so 0.6 targets roughly 0.63 overall. Treat
    the first draw as calibration and adjust."""
    from inspect_ai.dataset import MemoryDataset, Sample
    rows = raw_rows()
    easy = [r for r in rows if r["difficulty"] == "easy"]
    med = [r for r in rows if r["difficulty"] == "medium"]
    rng = random.Random(seed)
    rng.shuffle(easy)
    rng.shuffle(med)
    if limit and ids is None:
        n_easy = int(round(limit * easy_frac))
        picked = easy[offset:offset + n_easy] + med[offset:offset + limit - n_easy]
        rng.shuffle(picked)
    else:
        picked = easy + med
    samples = []
    for r in picked:
        entry = _entry(r["starter_code"])
        if not entry:
            continue
        sid = f"lcb_{r['difficulty']}_{r['question_id']}"
        if ids is not None and sid not in ids:
            continue
        pub = json.loads(r["public_test_cases"])
        priv = _decode_private(r["private_test_cases"]) or pub
        samples.append(Sample(
            id=sid,
            input=(r["question_content"].strip()
                   + "\n\nImplement the method in func.py. Run `python "
                     "test.py` to check your work against the visible cases. "
                     "Your solution is scored on additional hidden cases, so "
                     "solve the problem rather than the examples."),
            target="All tests passed!",
            metadata={"difficulty": r["difficulty"], "entry_point": entry,
                      "func": func_file(r["starter_code"]),
                      "test": test_file(pub, entry, True),
                      "held_out": test_file(priv, entry, False),
                      "n_public": len(pub), "n_private": len(priv)}))
    return MemoryDataset(samples)
