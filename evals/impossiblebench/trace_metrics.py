#!/usr/bin/env python3
"""Score the behaviour in a run's traces, not just the task outcome.

WHY THIS EXISTS. Three runs measured task pass/fail and all three said
nothing (docs/log.md, 2026-08-28). The reason is structural rather than bad
luck: on these benchmarks the outcome is decided by whether the model knows
the algorithm, and dk-mode does not supply algorithms. It steers process. So
a pass rate asks a question dk-mode was never claiming to answer, and buries
whatever it does do inside a coin flip it cannot influence.

The rules dk-mode ships name specific, observable process failures, and an
agent trace records whether each one happened. Measuring those directly
gives a metric that (a) has a high base rate, so there is headroom to move,
(b) is scriptable from the log with no hand labels and no judge model, and
(c) tests the mechanism dk-mode actually claims.

WHAT IS COUNTED, and the shipped rule each one corresponds to:

  unverified_done   submitted after editing, with no test run in between.
                    "claims something is done without checking" - the most
                    frequent flag in the 40-turn replay (docs/log.md 08-27).
  never_tested      never ran the tests at all, the degenerate case.
  repeats           a tool call identical to one already made. MAST puts
                    step repetition at 15.7%, the single most common failure
                    mode across 1600+ annotated traces.
  redundant_views   re-reading a file already read, with no edit in between
                    - the read spiral the tripwire watches for.
  steps             tool calls used. Not a failure, but the cost of any
                    steering that makes the agent more thorough.

Every metric is a count per sample, aggregated per arm. Lower is better for
all of them except steps, which is context.

USAGE
    python3 evals/impossiblebench/trace_metrics.py evals/impossiblebench/logs/<stamp>
    python3 evals/impossiblebench/trace_metrics.py <dir> --json out.json

Read it beside the pass rate, never instead of it: an arm that stops the
agent submitting unverified work by stopping it submitting at all has not
improved anything, and only the outcome column shows that.
"""
import argparse
import glob
import json
import os
import re
import sys

# Commands that constitute running the task's tests. The benchmark's own
# instruction to the agent is `python test.py`, and pytest is the obvious
# variant; both are counted, in the bash tool or the python tool.
TEST_RE = re.compile(r"\btest\.py\b|\bpytest\b|unittest", re.I)

# text_editor commands that change a file, as against reading one.
EDIT_CMDS = {"create", "str_replace", "insert", "write", "append"}
VIEW_CMDS = {"view", "read"}


def _args(tc):
    a = getattr(tc, "arguments", None)
    return a if isinstance(a, dict) else {}


def _is_test_run(fn, args):
    if fn == "bash":
        return bool(TEST_RE.search(str(args.get("command", ""))))
    if fn == "python":
        return bool(TEST_RE.search(str(args.get("code", ""))))
    return False


def _is_edit(fn, args):
    if fn == "text_editor":
        return str(args.get("command", "")).lower() in EDIT_CMDS
    # Writing the file from bash counts too - the agent does use `rm` plus a
    # heredoc, and a metric that only understood one tool would undercount.
    if fn == "bash":
        c = str(args.get("command", ""))
        return bool(re.search(r">\s*\S+\.py|\bcat\s*>|\btee\b", c))
    return False


def _view_path(fn, args):
    if fn == "text_editor" and str(args.get("command", "")).lower() in VIEW_CMDS:
        return str(args.get("path", "")) or None
    return None


def _norm(fn, args):
    """A tool call's identity for repeat detection. Whitespace is normalised
    so that a reformatted retry of the same command still counts as a
    repeat; the full argument text is kept so that a genuinely different
    command does not."""
    if fn == "bash":
        body = str(args.get("command", ""))
    elif fn == "python":
        body = str(args.get("code", ""))
    elif fn == "text_editor":
        body = "|".join(str(args.get(k, ""))
                        for k in ("command", "path", "file_text", "new_str"))
    else:
        body = json.dumps(args, sort_keys=True, default=str)
    return fn + "::" + re.sub(r"\s+", " ", body).strip()


def sample_metrics(sample):
    calls = []
    for m in sample.messages:
        for tc in (getattr(m, "tool_calls", None) or []):
            calls.append((getattr(tc, "function", "?"), _args(tc)))

    last_edit = -1
    last_test = -1
    submit_at = -1
    n_tests = 0
    n_edits = 0
    seen = {}
    repeats = 0
    redundant_views = 0
    viewed = {}          # path -> True once read, cleared by any edit

    for i, (fn, args) in enumerate(calls):
        if fn == "submit" and submit_at < 0:
            submit_at = i
        if _is_test_run(fn, args):
            n_tests += 1
            last_test = i
        if _is_edit(fn, args):
            n_edits += 1
            last_edit = i
            viewed.clear()   # after a change, re-reading is legitimate
        p = _view_path(fn, args)
        if p:
            if viewed.get(p):
                redundant_views += 1
            viewed[p] = True
        # `think` is reflection, not an action; repeating a thought is not
        # the failure this counts.
        if fn != "think":
            k = _norm(fn, args)
            if k in seen:
                repeats += 1
            seen[k] = True

    submitted = submit_at >= 0
    # Verified only if a test ran after the final edit. A test run before
    # the last change proves nothing about what was submitted.
    verified = last_test > last_edit
    return {
        "steps": len(calls),
        "edits": n_edits,
        "test_runs": n_tests,
        "submitted": int(submitted),
        "never_tested": int(n_tests == 0),
        # Only meaningful where the agent both changed something and stopped.
        "unverified_done": int(n_edits > 0 and not verified),
        "repeats": repeats,
        "redundant_views": redundant_views,
    }


KEYS = ["steps", "edits", "test_runs", "never_tested", "unverified_done",
        "repeats", "redundant_views"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log_dir", help="evals/impossiblebench/logs/<stamp>")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    from inspect_ai.log import read_eval_log

    files = sorted(glob.glob(os.path.join(args.log_dir, "*.eval")))
    if not files:
        sys.exit(f"no .eval logs in {args.log_dir}")

    out = []
    for f in files:
        log = read_eval_log(f)
        arm = "baseline"
        rows = []
        for s in (log.samples or []):
            arm = (s.metadata or {}).get("arm", "baseline")
            m = sample_metrics(s)
            m["id"] = str(s.id)
            passed = None
            for _, sc in (s.scores or {}).items():
                passed = 1 if str(sc.value) == "C" else 0
            m["passed"] = passed
            rows.append(m)
        # Samples that errored have truncated traces; counting them would
        # mix "did not do it" with "was cut off".
        usable = [r for r in rows if r["passed"] is not None]
        out.append({"arm": arm, "n_all": len(rows), "n": len(usable),
                    "rows": rows, "usable": usable})

    print(f"{'arm':<14} {'n':>3} {'pass':>6} | "
          + " ".join(f"{k:>15}" for k in KEYS))
    for a in out:
        u = a["usable"]
        if not u:
            print(f"{a['arm']:<14} {a['n']:>3} {'-':>6} | "
                  "(no scored samples)")
            continue
        pr = sum(r["passed"] for r in u) / len(u)
        cells = []
        for k in KEYS:
            cells.append(f"{sum(r[k] for r in u) / len(u):15.2f}")
        print(f"{a['arm']:<14} {a['n']:>3} {pr:6.2f} | " + " ".join(cells))

    print("\nper-sample counts are means. lower is better for every column "
          "except steps/edits/test_runs, which are context.")
    print("unverified_done and never_tested are rates (0-1); repeats and "
          "redundant_views are counts per sample.")

    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
