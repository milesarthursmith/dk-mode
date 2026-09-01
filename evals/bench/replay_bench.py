"""Replay bench: test monitor variants against frozen real transcripts.

The marathon cost ~$4 per session and its dk arms answered one question
about one configuration. This answers the same question for ~$0.005 per
call: extract MOMENTS from the .eval logs we already own (a transcript
prefix ending at a decision point, auto-labeled from recorded ground
truth), replay any dk_watch variant over them, score fire-rates.

  wedge    the driver-reported score did not move across >=3 consecutive
           attempts before this point - the monitor SHOULD fire
  healthy  the score just improved - firing here is a false positive
  stall    the agent produced an empty message - should fire

Usage:
  python3 replay_bench.py extract          # build moments/ from eval logs
  python3 replay_bench.py run NAME WATCH_PY [env K=V ...]
  python3 replay_bench.py run-seq NAME WATCH_PY [env K=V ...]
  python3 replay_bench.py report

run-seq is for STATEFUL watchers (docs/SHAPE.md): the moment's prefix is
replayed chunk by chunk (split at driver-continue boundaries) into one
persistent memory dir, so the watcher accumulates notes/expectations
across looks exactly as it would live. Scored on the verdict after the
final chunk; first-fire chunk recorded.

A variant = a dk_watch.py file + env overrides, so prompt edits, window
sizes, monitor models and thresholds all sweep the same way. Results
land in results.jsonl, one line per (variant, moment).
"""
import glob
import json
import os
import re
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
MOMENTS = os.path.join(HERE, "moments")
RESULTS = os.path.join(HERE, "results.jsonl")


def extract():
    from inspect_ai.log import read_eval_log
    os.makedirs(MOMENTS, exist_ok=True)
    n = 0
    for f in sorted(glob.glob(os.path.join(REPO, "evals/goal/logs/*.eval"))):
        log = read_eval_log(f, resolve_attachments=True)
        if not log.samples: continue
        for s in log.samples:
            arm = log.eval.task.replace("goal_", "")
            ep = getattr(s, "epoch", 1)
            msgs, curve = [], []           # (index-in-msgs, pct)
            for m in s.messages:
                r = getattr(m, "role", "")
                t = getattr(m, "text", "") or ""
                if r not in ("user", "assistant") or "<dk-probe>" in t:
                    continue
                msgs.append({"type": r, "uuid": str(uuid.uuid4()),
                             "message": {"content": t}})
                mm = re.search(r"\((\d+)% fixed\)\. The goal stands", t)
                if mm:
                    curve.append((len(msgs), int(mm.group(1))))
            for k in range(len(curve)):
                idx, pct = curve[k]
                if k >= 3 and all(c[1] == pct for c in curve[k-3:k]):
                    label = "wedge"
                elif k >= 1 and pct > curve[k-1][1]:
                    label = "healthy"
                else:
                    continue
                name = f"{label}_{arm}_ep{ep}_{k}"
                with open(os.path.join(MOMENTS, name + ".jsonl"), "w") as out:
                    out.write("\n".join(json.dumps(m) for m in msgs[:idx]))
                n += 1
    print(f"extracted {n} moments -> {MOMENTS}/")


def _chunks(mf):
    """Split a moment at driver-continue messages -> growing prefixes."""
    lines = open(mf).read().splitlines()
    cuts = [i + 1 for i, l in enumerate(lines)
            if "The goal stands" in l or "still failing" in l]
    cuts = [c for c in cuts if c > 2] or [len(lines)]
    if cuts[-1] != len(lines):
        cuts.append(len(lines))
    return [lines[:c] for c in cuts]


def run_seq(name, watch_py, env_extra):
    scratch = os.path.join(HERE, ".mem")
    results = open(RESULTS, "a")
    for mf in sorted(glob.glob(os.path.join(MOMENTS, "*.jsonl"))):
        moment = os.path.basename(mf)[:-6]
        subprocess.run(["rm", "-rf", scratch]); os.makedirs(scratch)
        env = dict(os.environ, DK_MEM=scratch, DK_SESSION="bench",
                   DK_API_KEY=os.environ["OPENROUTER_API_KEY"],
                   DK_WATCH_MODELS=os.environ.get("BENCH_MONITOR",
                                                  "google/gemini-2.5-flash"),
                   **env_extra)
        tp = os.path.join(scratch, "t.jsonl")
        first_fire, fired = None, False
        t0 = time.time()
        for ci, chunk in enumerate(_chunks(mf)):
            open(tp, "w").write("\n".join(chunk))
            subprocess.run([sys.executable, watch_py, tp], env=env,
                           capture_output=True, timeout=180)
            a = os.path.join(scratch, ".dk_active.bench")
            fired = os.path.exists(a) and os.path.getsize(a) > 0
            if fired and first_fire is None:
                first_fire = ci
        text = open(a).read().strip() if fired else ""
        rec = {"variant": name, "moment": moment,
               "label": moment.split("_")[0], "fired": fired,
               "first_fire_chunk": first_fire, "alert": text[:400],
               "secs": round(time.time() - t0, 1)}
        results.write(json.dumps(rec) + "\n")
        print(f"{name} {moment}: {'FIRED@' + str(first_fire) if fired else 'quiet'} ({rec['secs']:.0f}s)")
    results.close()


def run(name, watch_py, env_extra):
    scratch = os.path.join(HERE, ".mem")
    results = open(RESULTS, "a")
    files = sorted(glob.glob(os.path.join(MOMENTS, "*.jsonl")))
    fired = {}
    for mf in files:
        moment = os.path.basename(mf)[:-6]
        subprocess.run(["rm", "-rf", scratch])
        os.makedirs(scratch)
        subprocess.run(["bash", os.path.join(REPO, "scripts/dk_bootstrap.sh"),
                        scratch], capture_output=True)
        env = dict(os.environ,
                   DK_MEM=scratch, DK_LOG_DIR=scratch,
                   DK_BACKEND="openai",
                   DK_API_URL="https://openrouter.ai/api/v1/chat/completions",
                   DK_API_KEY=os.environ["OPENROUTER_API_KEY"],
                   DK_WATCH_MODELS=os.environ.get("BENCH_MONITOR",
                                                  "google/gemini-2.5-flash"),
                   **env_extra)
        t0 = time.time()
        subprocess.run([sys.executable, watch_py, mf], env=env,
                       capture_output=True, timeout=180)
        dt = time.time() - t0
        active = glob.glob(os.path.join(scratch, ".dk_active.*"))
        text = open(active[0]).read().strip() if active else ""
        rec = {"variant": name, "moment": moment,
               "label": moment.split("_")[0],
               "fired": bool(text), "alert": text[:400], "secs": round(dt, 1)}
        results.write(json.dumps(rec) + "\n")
        fired[moment] = rec["fired"]
        print(f"{name} {moment}: {'FIRED' if rec['fired'] else 'quiet'} ({dt:.0f}s)")
    results.close()


def report():
    rows = [json.loads(l) for l in open(RESULTS)]
    variants = sorted({r["variant"] for r in rows})
    print(f"{'variant':<22} {'wedge fire (recall)':<20} {'healthy fire (FP)':<18} n")
    for v in variants:
        vr = [r for r in rows if r["variant"] == v]
        for lab, tag in (("wedge", "recall"), ("healthy", "FP")):
            pass
        w = [r for r in vr if r["label"] == "wedge"]
        h = [r for r in vr if r["label"] == "healthy"]
        wf = sum(r["fired"] for r in w); hf = sum(r["fired"] for r in h)
        print(f"{v:<22} {wf}/{len(w):<19} {hf}/{len(h):<17} {len(vr)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "extract":
        extract()
    elif cmd == "run":
        env_extra = dict(kv.split("=", 1) for kv in sys.argv[4:])
        run(sys.argv[2], sys.argv[3], env_extra)
    elif cmd == "run-seq":
        env_extra = dict(kv.split("=", 1) for kv in sys.argv[4:])
        run_seq(sys.argv[2], sys.argv[3], env_extra)
    else:
        report()
