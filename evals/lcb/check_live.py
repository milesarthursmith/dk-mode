#!/usr/bin/env python3
"""Did the model-based monitor actually speak? Run before reporting a dk arm.

Three separate bugs have produced a dk arm that injected only the static
recall note and the tripwire while looking, in every transcript, exactly
like a working one. This counts the producers so that cannot happen
silently again.
"""
import glob
import sys

from inspect_ai.log import read_eval_log


def classify(text):
    if "check before acting" in text:
        return "static"
    if "standing rule" in text or "Relevant to what you are doing" in text:
        return "live"
    return "tripwire"


def main():
    for f in sorted(glob.glob(sys.argv[1] + "/*.eval")):
        log = read_eval_log(f, resolve_attachments=True)
        kinds = {"static": 0, "live": 0, "tripwire": 0}
        for s in (log.samples or []):
            for m in s.messages:
                t = getattr(m, "text", "") or ""
                if "<self-steering>" in t:
                    kinds[classify(t)] += 1
        n = len(log.samples or [])
        c = sum(1 for s in (log.samples or [])
                for v in (s.scores or {}).values() if str(v.value) == "C")
        print(f"{log.eval.task:<16} n={n:<4} pass={c/n if n else 0:.2f}  {kinds}")
        if kinds["live"] == 0 and "dk" in log.eval.task:
            print("   WARNING: no live monitor blocks - this dk arm ran as "
                  "deterministic hooks only. Do not report it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
