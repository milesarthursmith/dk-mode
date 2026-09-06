"""Take each moment's note from its session's watcher pass, and make the
counter baseline's note for it, into notes/<moment>.watcher.txt and
notes/<moment>.counter.txt.

A moment is a prefix of a session's transcript; the note it gets is the one
the watcher wrote at the look taken over exactly that prefix (watch.py
takes one look before each driver message and one at the end). The pass's
looks.json records the prefix length of every look.

Usage: notes.py <looks.json> <moment> [<moment> ...]
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(os.path.dirname(HERE), "bench")
NOTES = os.path.join(HERE, "notes")


def transcript_for(moment):
    return json.load(open(os.path.join(HERE, f".build_{moment}.json")))["transcript"]


def main():
    looks = json.load(open(sys.argv[1]))
    os.makedirs(NOTES, exist_ok=True)
    for moment in sys.argv[2:]:
        tp = transcript_for(moment)
        n = len(open(tp, encoding="utf-8").read().splitlines())
        # the look over this prefix; the pilot pass counted lines from 1, so
        # its prefix lengths are one higher than the current builds'
        cands = [l for l in looks if abs(l["upto_line"] - n) <= 1]
        if not cands:
            raise SystemExit(f"{moment}: no look ends at line {n} "
                             f"(looks end at {[l['upto_line'] for l in looks]})")
        look = min(cands, key=lambda l: abs(l["upto_line"] - n))
        said = look["said"].strip()
        with open(os.path.join(NOTES, f"{moment}.watcher.txt"), "w") as f:
            f.write(f"<self-steering>\n{said}\n</self-steering>\n" if said else "")
        print(f"{moment}: look {look['look']} (prefix {look['upto_line']} lines, "
              f"transcript {n}): {said[:100] if said else '(silent)'}")
        mem = os.path.join(HERE, ".counter_mem")
        os.makedirs(mem, exist_ok=True)
        subprocess.run([sys.executable, os.path.join(BENCH, "baseline_counter.py"), tp],
                       env=dict(os.environ, DK_MEM=mem, DK_SESSION="s"), check=True)
        c = open(os.path.join(mem, ".dk_active.s")).read()
        with open(os.path.join(NOTES, f"{moment}.counter.txt"), "w") as f:
            f.write(c)
        print(f"    counter: {c.strip().splitlines()[1][:100] if c.strip() else '(silent)'}")


if __name__ == "__main__":
    main()
