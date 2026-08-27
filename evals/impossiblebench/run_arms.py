#!/usr/bin/env python3
"""Run the ImpossibleBench arms and put the numbers side by side.

One command, one comparison, one appended line per arm in evals/results.md -
a climb is only real if last month's number can be re-derived.

    python3 evals/impossiblebench/run_arms.py \
        --limit 20 --model anthropic/claude-haiku-4-5

    --arms baseline,dk,challenge,dk_challenge   (default: all four)
    --split conflicting|oneoff|original         (default: conflicting)
    --limit N        first N samples - the frozen subset (default 20)
    --challenge-n K  fixed text on generation 1 and every Kth after (default 1)
    --model M        the agent under test. claude-cli/<name> uses the local
                     `claude -p` login: smoke tests only, not real numbers.
    --epochs N       repeats per sample (default 1; use 3 for a kept change)
    --no-record      do not append to evals/results.md

The monitor inside arm_dk needs its own model. With DK_API_KEY (or
ANTHROPIC_API_KEY) set it uses the API as shipped; with neither it falls back
to DK_BACKEND=cli, which works wherever `claude -p` is logged in.

On the conflicting/oneoff splits the score is a CHEATING RATE - lower is
better. On original it is a plain pass rate - higher is better; run that
split too before believing a low cheating rate, or the winner may simply be
an arm that talked the agent out of finishing anything.
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

ARM_TASKS = {
    "baseline": "arm_baseline",
    "dk": "arm_dk",
    "challenge": "arm_challenge",
    "dk_challenge": "arm_dk_challenge",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="baseline,dk,challenge,dk_challenge")
    ap.add_argument("--split", default="conflicting")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--challenge-n", type=int, default=1)
    ap.add_argument("--model", default="anthropic/claude-haiku-4-5")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--no-record", action="store_true")
    args = ap.parse_args()

    # The dk arms need a model for the monitor. Default to the CLI when no
    # key is set, so a keyless environment still runs - and say so, because
    # a silent no-op monitor produced a wrong conclusion once already.
    if not (os.environ.get("DK_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("DK_KEY_FILE")):
        os.environ.setdefault("DK_BACKEND", "cli")
        if os.environ["DK_BACKEND"] == "cli":
            print("note: no DK_API_KEY - the monitor uses `claude -p` "
                  "(DK_BACKEND=cli)")

    import claude_cli                                    # noqa: F401
    import arms as A
    from inspect_ai import eval as inspect_eval

    wanted = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in wanted if a not in ARM_TASKS]
    if unknown:
        sys.exit(f"unknown arm(s): {', '.join(unknown)} "
                 f"(choose from {', '.join(ARM_TASKS)})")

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    out_dir = os.path.join(REPO, "evals", "results", stamp)
    os.makedirs(out_dir, exist_ok=True)
    log_dir = os.path.join(HERE, "logs", stamp)

    rows = []
    for arm in wanted:
        kw = {"split": args.split, "limit": args.limit}
        if "challenge" in arm:
            kw["n"] = args.challenge_n
        t = getattr(A, ARM_TASKS[arm])(**kw)
        print(f"\n=== {arm}  ({args.split}, limit {args.limit}, "
              f"model {args.model}) ===")
        logs = inspect_eval(t, model=args.model, epochs=args.epochs,
                            log_dir=log_dir, display="plain")
        log = logs[0]
        row = {"arm": arm, "status": log.status}
        if log.status == "success" and log.results:
            for s in log.results.scores:
                acc = s.metrics.get("accuracy")
                if acc is not None:
                    row["score"] = acc.value
            row["samples"] = log.results.completed_samples
        # Per-sample counters: what the arms actually did.
        agg = {"gen_count": 0, "dk_calls": 0, "dk_fired": 0,
               "challenge_fired": 0, "injected_chars": 0}
        alerts, rules, errors = [], [], []
        for smp in (log.samples or []):
            md = smp.metadata or {}
            for k in agg:
                agg[k] += md.get(k, 0)
            alerts += md.get("dk_alerts", [])
            rules += md.get("dk_rules", [])
            if md.get("dk_error"):
                errors.append(md["dk_error"])
        row.update(agg)
        row["dk_rules_picked"] = rules
        row["dk_alerts"] = alerts[:20]
        row["dk_errors"] = errors[:5]
        rows.append(row)

    label = ("CHEATING RATE (lower is better)"
             if args.split in ("conflicting", "oneoff")
             else "pass rate (higher is better)")
    print(f"\n{'arm':<14} {label:<36} gens  dk_fired  challenge  inj_chars")
    for r in rows:
        score = f"{r.get('score', float('nan')):.2f}" \
            if "score" in r else f"({r['status']})"
        print(f"{r['arm']:<14} {score:<36} {r['gen_count']:<5} "
              f"{r['dk_fired']:<9} {r['challenge_fired']:<10} "
              f"{r['injected_chars']}")
    dk_rows = [r for r in rows if "dk" in r["arm"]]
    if dk_rows and all(r["dk_fired"] == 0 for r in dk_rows):
        print("\nWARNING: the monitor never spoke. This run says nothing "
              "about steering - check dk_errors in the JSON report.")
    for r in dk_rows:
        if r["dk_errors"]:
            print(f"dk errors in {r['arm']}: {r['dk_errors'][0]}")

    report = os.path.join(out_dir, "impossiblebench.json")
    with open(report, "w", encoding="utf-8") as f:
        json.dump({"date": stamp, "model": args.model, "split": args.split,
                   "limit": args.limit, "epochs": args.epochs,
                   "challenge_n": args.challenge_n, "rows": rows}, f, indent=1)
    print(f"\nfull report: {report}\ninspect logs: {log_dir}")

    if not args.no_record:
        results_md = os.path.join(REPO, "evals", "results.md")
        new = not os.path.exists(results_md)
        with open(results_md, "a", encoding="utf-8") as f:
            if new:
                f.write("# Eval results, one line per run\n\n"
                        "| date | benchmark | split | limit | model | arm | "
                        "score | dk_fired | notes |\n|---|---|---|---|---|"
                        "---|---|---|---|\n")
            for r in rows:
                f.write(f"| {stamp} | impossiblebench | {args.split} | "
                        f"{args.limit} | {args.model} | {r['arm']} | "
                        f"{r.get('score', '-')} | {r['dk_fired']} | "
                        f"{'cli-smoke' if args.model.startswith('claude-cli') else ''} |\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
