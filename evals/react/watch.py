"""Run a watcher over a rebuilt transcript look by look, as it would live.

Live, the Stop hook runs the watcher after every agent turn, before the
next user message. Here the agent turns are the stretches between driver
messages ("... The goal stands ..."), so one look is taken just before each
driver message and one more at the end of the file (after the moment's
final agent turn, which is the look whose note the continuation gets).
A moment whose cut falls at the D-th driver message therefore gets the
note from look D, so nested moments of one session share one pass.

Usage: watch.py <transcript.jsonl> <memdir> [watcher.py] [KEY=VAL ...]
Prints what the watcher said at each look; the final note is left in
<memdir>/.dk_active.<session> for the continuation to inject.
"""
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.path.join(os.path.dirname(HERE), "bench")


def cuts(lines):
    out = []
    for i, l in enumerate(lines):
        try:
            e = json.loads(l)
        except ValueError:
            continue
        if e.get("type") != "user":
            continue
        c = (e.get("message") or {}).get("content")
        t = c if isinstance(c, str) else " ".join(
            b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
        if "The goal stands" in t and i > 0:
            out.append(i)            # a look happens BEFORE the driver speaks
    if not out or out[-1] != len(lines):
        out.append(len(lines))
    return out


def main():
    transcript, mem = sys.argv[1], sys.argv[2]
    watcher = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3].endswith(".py") \
        else os.path.join(BENCH, "watcher_session.py")
    extra = dict(kv.split("=", 1) for kv in sys.argv[3:] if "=" in kv)
    session = os.path.basename(transcript)[:-6][:16]
    shutil.rmtree(mem, ignore_errors=True)
    os.makedirs(mem)
    # Lookup (web search) is off unless asked for: it has never been measured
    # and would confound the reaction check.
    env = dict(os.environ, DK_MEM=mem, DK_SESSION_ID=session, EXA_API_KEY="", **extra)
    lines = open(transcript, encoding="utf-8").read().splitlines()
    tp = os.path.join(mem, "t.jsonl")
    looks = []
    for n, c in enumerate(cuts(lines), 1):
        open(tp, "w", encoding="utf-8").write("\n".join(lines[:c]) + "\n")
        t0 = time.time()
        subprocess.run([sys.executable, watcher, tp], env=env, timeout=400)
        a = os.path.join(mem, f".dk_active.{session}")
        said = open(a).read().strip() if os.path.exists(a) else ""
        said = said.replace("<self-steering>", "").replace("</self-steering>", "").strip()
        looks.append({"look": n, "upto_line": c, "secs": round(time.time() - t0, 1),
                      "said": said})
        snap = os.path.join(mem, f"look_{n:02d}")          # state after this look
        os.makedirs(snap, exist_ok=True)
        for fn in os.listdir(mem):
            if fn.startswith((".watcher_state.", ".watcher_convo.", ".dk_active.")):
                shutil.copy(os.path.join(mem, fn), snap)
        print(f"look {n:>2} (lines 1-{c}, {looks[-1]['secs']}s): "
              f"{said if said else '(silent)'}", flush=True)
    json.dump(looks, open(os.path.join(mem, "looks.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
