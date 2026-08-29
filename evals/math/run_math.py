#!/usr/bin/env python3
"""Two-stage maths comparison: find the band, then run the arms on it.

STAGE 1 - band. Baseline only, several epochs, over a level slice. A task
the model passes every time or never carries no information about steering;
the band is the tasks passed SOMETIMES. The band is selected on this
stage's runs and the comparison uses FRESH runs, because selecting and
evaluating on the same coin flips would bake luck into the result.

    python3 evals/math/run_math.py --stage band --limit 60 --epochs 3 \
        --model openrouter/google/gemini-2.5-flash-lite

STAGE 2 - arms. All three arms on the band ids, fresh epochs. Primary
metric: mean pass rate over epochs, with pass^k (passed every epoch) and
pass@k (passed any epoch) beside it - a steering layer that works should
convert flaky passes into reliable ones, which moves pass^k first.

    python3 evals/math/run_math.py --stage arms --epochs 3 \
        --model openrouter/google/gemini-2.5-flash-lite

Cost guard: --budget aborts before spending if the OpenRouter balance is
below the estimate. Calibrate on two samples before a full stage.
"""
import argparse
import datetime
import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "evals", "impossiblebench"))

BAND_FILE = os.path.join(HERE, "band.json")


def per_task_passes(log):
    """id -> [pass/fail per epoch], plus per-sample counters summed."""
    out = defaultdict(list)
    agg = {"gen_count": 0, "dk_calls": 0, "dk_fired": 0,
           "challenge_fired": 0, "injected_chars": 0}
    for s in (log.samples or []):
        v = None
        for _, sc in (s.scores or {}).items():
            v = 1 if str(sc.value) == "C" else 0
        if v is not None:
            out[str(s.id)].append(v)
        md = s.metadata or {}
        for k in agg:
            agg[k] += md.get(k, 0)
    return dict(out), agg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["band", "arms"])
    ap.add_argument("--model",
                    default="openrouter/google/gemini-2.5-flash-lite")
    ap.add_argument("--limit", type=int, default=60,
                    help="band stage: problems drawn from the level slice")
    ap.add_argument("--offset", type=int, default=0,
                    help="band stage: skip the first N of the shuffled "
                         "slice - widen the band without re-running it")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--arms", default="baseline,dk,challenge")
    ap.add_argument("--challenge-n", type=int, default=3)
    ap.add_argument("--budget", type=float, default=0.0)
    ap.add_argument("--no-record", action="store_true")
    args = ap.parse_args()

    if not (os.environ.get("DK_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("DK_KEY_FILE")):
        os.environ.setdefault("DK_BACKEND", "cli")
        print("note: no DK_API_KEY - the monitor uses `claude -p`")
    if args.budget:
        from run_arms import _check_budget
        _check_budget(args.budget)

    import arms_math as M
    from inspect_ai import eval as inspect_eval
    from inspect_ai.model import get_model

    model = M._install_injection(get_model(args.model))
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    log_dir = os.path.join(HERE, "logs", stamp)
    out_dir = os.path.join(REPO, "evals", "results", stamp)
    os.makedirs(out_dir, exist_ok=True)

    if args.stage == "band":
        t = M.baseline(limit=args.limit, offset=args.offset)
        logs = inspect_eval(t, model=model, epochs=args.epochs,
                            log_dir=log_dir, display="plain")
        passes, _ = per_task_passes(logs[0])
        # Widening: fold previous banding passes in. Disjoint offsets mean
        # ids never collide, so a plain merge is exact.
        if os.path.exists(BAND_FILE):
            with open(BAND_FILE) as f:
                passes = {**json.load(f).get("passes", {}), **passes}
        always = [i for i, v in passes.items() if all(v)]
        never = [i for i, v in passes.items() if not any(v)]
        band = [i for i, v in passes.items() if any(v) and not all(v)]
        print(f"\nof {len(passes)} problems x {args.epochs} epochs:")
        print(f"  always passed : {len(always)}")
        print(f"  never passed  : {len(never)}")
        print(f"  BAND (flaky)  : {len(band)}")
        with open(BAND_FILE, "w") as f:
            json.dump({"date": stamp, "model": args.model,
                       "epochs": args.epochs, "limit": args.limit,
                       "band": band, "always": always, "never": never,
                       "passes": passes}, f, indent=1)
        print(f"wrote {BAND_FILE}\nlogs: {log_dir}")
        if len(band) < 8:
            print("WARNING: a band this small cannot support a comparison. "
                  "Widen --limit or move levels before running arms.")
        return 0

    # --- arms on the band, fresh epochs -----------------------------------
    with open(BAND_FILE) as f:
        band_info = json.load(f)
    ids = set(band_info["band"])
    print(f"band of {len(ids)} problems from {band_info['date']} "
          f"(selected at {band_info['epochs']} epochs)")

    def sched(payload):
        return lambda: M.challenge(ids=ids, n=args.challenge_n,
                                   payload=payload)
    builders = {"baseline": lambda: M.baseline(ids=ids),
                "dk": lambda: M.dk(ids=ids),
                "challenge": sched("challenge"),
                "challenge-skill": sched("challenge-skill"),
                "challenger": lambda: M.challenger(ids=ids,
                                                   n=args.challenge_n),
                "try-harder": sched("try-harder"),
                "goal": sched("goal"),
                "goal+rules": sched("goal+rules")}
    rows = []
    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        print(f"\n=== {arm} ({len(ids)} band problems, "
              f"{args.epochs} epochs, {args.model}) ===")
        logs = inspect_eval(builders[arm](), model=model, epochs=args.epochs,
                            log_dir=log_dir, display="plain")
        passes, agg = per_task_passes(logs[0])
        trials = sum(len(v) for v in passes.values())
        wins = sum(sum(v) for v in passes.values())
        k_all = sum(1 for v in passes.values() if v and all(v))
        k_any = sum(1 for v in passes.values() if any(v))
        rows.append({"arm": arm, "n_tasks": len(passes), "trials": trials,
                     "mean_pass": wins / trials if trials else None,
                     "pass_all_k": k_all, "pass_any_k": k_any,
                     "passes": passes, **agg})

    print(f"\n{'arm':<11} {'mean':>6} {'pass^k':>7} {'pass@k':>7} "
          f"{'gens':>5} {'dk_fired':>8} {'chal':>5} {'inj_chars':>9}")
    for r in rows:
        if r["mean_pass"] is None:
            print(f"{r['arm']:<11} (no scored trials - see logs)")
            continue
        print(f"{r['arm']:<11} {r['mean_pass']:>6.2f} "
              f"{r['pass_all_k']:>4}/{r['n_tasks']:<3}"
              f"{r['pass_any_k']:>4}/{r['n_tasks']:<3} "
              f"{r['gen_count']:>5} {r['dk_fired']:>8} "
              f"{r['challenge_fired']:>5} {r['injected_chars']:>9}")
    silent = [r["arm"] for r in rows
              if r["arm"] != "baseline" and r["gen_count"] == 0]
    if silent:
        print(f"\nWARNING: no generations seen for {', '.join(silent)} - "
              "those arms ran as baseline. Do not report them.")

    report = os.path.join(out_dir, "math_arms.json")
    with open(report, "w") as f:
        json.dump({"date": stamp, "model": args.model, "epochs": args.epochs,
                   "band_from": band_info["date"], "n_band": len(ids),
                   "challenge_n": args.challenge_n, "rows": rows}, f, indent=1)
    print(f"\nreport: {report}\nlogs: {log_dir}")

    if not args.no_record:
        results_md = os.path.join(REPO, "evals", "results.md")
        with open(results_md, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(f"| {stamp} | math500-band | band({len(ids)}) | "
                        f"agentic/{args.epochs}ep | {r['n_tasks']} | "
                        f"{args.model} | {r['arm']} | "
                        f"{r['mean_pass']:.2f} | {r['dk_fired']} | "
                        f"pass^k {r['pass_all_k']}/{r['n_tasks']} |\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
