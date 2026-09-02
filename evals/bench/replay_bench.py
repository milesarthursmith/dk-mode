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
# Corpora the run/run-seq modes sweep. moments/ = our own small-agent runs
# (mechanical wedges); moments_tb/ = frontier-agent Terminal-Bench 2
# trajectories mined by extract_tb.py (semantic wedges + hard negatives).
MOMENT_DIRS = [d for d in os.environ.get(
    "MOMENT_DIRS", f"{MOMENTS}:{os.path.join(HERE, 'moments_tb')}").split(":") if d]
RESULTS = os.path.join(HERE, "results.jsonl")


def _moment_files():
    out = []
    for d in MOMENT_DIRS:
        out += sorted(glob.glob(os.path.join(d, "*.jsonl")))
    return out


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


def extract_swe():
    """Process-labeled moments from the SWE runs (no outcome contamination):
      wedge   >=3 failed Edit results within the last 8 messages of the prefix
      healthy a busy, productive stretch: >=6 distinct tool calls in the last
              10 messages, no failed edits, no repeated identical calls
              (hard negative - active work that must NOT be flagged)
    Prefixes cut at the moment the condition first holds."""
    from inspect_ai.log import read_eval_log
    os.makedirs(MOMENTS, exist_ok=True)
    n = 0
    for f in sorted(glob.glob(os.path.join(REPO, "evals/swe/logs/arms/*.eval"))):
        log = read_eval_log(f, resolve_attachments=True)
        if not log.samples: continue
        arm = log.eval.task.replace("swe_", "")
        for s_ in log.samples:
            rows = []
            for m in s_.messages:
                r = getattr(m, "role", ""); t = getattr(m, "text", "") or ""
                if r == "tool":
                    rows.append(("tool", t[:600], ("String to replace not found" in t
                                 or ("old_string" in t and "not found" in t))))
                elif r in ("user", "assistant") and t.strip() and "<dk-probe>" not in t:
                    calls = [c.function for c in (getattr(m, "tool_calls", None) or [])]
                    rows.append((r, t, calls))
            done = set()
            for i in range(8, len(rows)):
                win = rows[i-8:i]
                fails = sum(1 for x in win if x[0] == "tool" and x[2] is True)
                calls = [c for x in win if x[0] == "assistant" for c in (x[2] or [])]
                if fails >= 3 and "wedge" not in done:
                    label = "wedge"
                elif (len(calls) >= 6 and fails == 0 and len(set(calls)) >= 3
                      and "healthy" not in done and i > 12):
                    label = "healthy"
                else:
                    continue
                done.add(label)
                msgs = [{"type": x[0], "uuid": str(uuid.uuid4()),
                         "message": {"content": x[1]}} for x in rows[:i] if x[0] != "tool"]
                if len(msgs) < 4: continue
                tid = str(s_.id).split("__")[-1]
                name = f"{label}_swe-{arm}_{tid}_ep{getattr(s_, 'epoch', 1)}"
                with open(os.path.join(MOMENTS, name + ".jsonl"), "w") as out:
                    out.write("\n".join(json.dumps(m) for m in msgs))
                n += 1
    print(f"extracted {n} SWE moments -> {MOMENTS}/")


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
    for mf in _moment_files():
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
    files = _moment_files()
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


def _wilson(k, n, z=1.96):
    if not n: return (0, 0)
    p = k / n; d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z * ((p*(1-p)/n + z*z/(4*n*n)) ** 0.5) / d
    return (max(0, c-h), min(1, c+h))


def report():
    from math import comb
    rows = [json.loads(l) for l in open(RESULTS)]
    variants = sorted({r["variant"] for r in rows})
    print(f"{'variant':<20} {'wedge recall [95% CI]':<28} {'healthy FP [95% CI]':<26} n")
    stats = {}
    for v in variants:
        vr = [r for r in rows if r["variant"] == v]
        w = [r for r in vr if r["label"] == "wedge"]
        h = [r for r in vr if r["label"] == "healthy"]
        wf = sum(r["fired"] for r in w); hf = sum(r["fired"] for r in h)
        lo, hi = _wilson(wf, len(w)); lo2, hi2 = _wilson(hf, len(h))
        print(f"{v:<20} {wf}/{len(w)} [{lo:.2f}-{hi:.2f}]{'':<10} {hf}/{len(h)} [{lo2:.2f}-{hi2:.2f}]{'':<8} {len(vr)}")
        stats[v] = {r["moment"]: r["fired"] for r in vr}
    # paired sign test on wedge moments shared by each pair of variants
    print("\npaired (wedge moments both variants saw; McNemar exact):")
    for i, a in enumerate(variants):
        for b in variants[i+1:]:
            shared = [m for m in stats[a] if m in stats[b] and m.startswith("wedge")]
            aw = sum(1 for m in shared if stats[a][m] and not stats[b][m])
            bw = sum(1 for m in shared if stats[b][m] and not stats[a][m])
            n = aw + bw
            p = sum(comb(n, k) for k in range(min(aw, bw)+1)) * 2 / 2**n if n else 1
            print(f"  {a} vs {b}: {aw}-{bw} discordant of {len(shared)}, p={min(p,1):.2f}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "extract":
        extract()
    elif cmd == "extract-swe":
        extract_swe()
    elif cmd == "run":
        env_extra = dict(kv.split("=", 1) for kv in sys.argv[4:])
        run(sys.argv[2], sys.argv[3], env_extra)
    elif cmd == "run-seq":
        env_extra = dict(kv.split("=", 1) for kv in sys.argv[4:])
        run_seq(sys.argv[2], sys.argv[3], env_extra)
    else:
        report()
