#!/usr/bin/env python3
"""Read a run the way EVALS.md 2.5 demands: injection beside reaction.

The aggregate columns (fire rate, repeats, redundant views) say THAT the
steering cost something; only the interleaved transcript says WHY. This
prints one sample as a timeline: each generation's injected payload -
recorded in metadata by arms.py, because the ModelAPI patch appends below
the layer inspect logs - followed by what the model did next and what the
tools returned.

    python3 evals/impossiblebench/trace_view.py <logdir-or-.eval> [sample_id]
    python3 evals/impossiblebench/trace_view.py <logdir> --list

Runs from before 2026-08-28 lack dk_payload_log; for those the timeline
still shows the actions, with a note that the payloads were not recorded.
"""
import argparse
import glob
import os
import sys
import textwrap


def _wrap(text, prefix):
    out = []
    for line in (text or "").splitlines() or [""]:
        out.extend(textwrap.wrap(line, width=78 - len(prefix),
                                 initial_indent=prefix,
                                 subsequent_indent=prefix) or [prefix])
    return "\n".join(out)


def show_sample(sample, arm):
    md = sample.metadata or {}
    payloads = {p["gen"]: p["text"] for p in md.get("dk_payload_log", [])}
    print(f"=== sample {sample.id}  arm={arm}  "
          f"gens={md.get('gen_count', '?')} dk_fired={md.get('dk_fired', 0)} "
          f"challenge={md.get('challenge_fired', 0)} ===")
    if not payloads and (md.get("dk_fired") or md.get("challenge_fired")):
        print("  (this run predates payload logging: injections happened "
              "but their text was not recorded; showing actions only)\n")

    gen = 0
    for ev in (sample.events or []):
        if ev.event == "model":
            gen += 1
            if gen in payloads:
                print(f"\n  ┌─ INJECTED before generation {gen} " + "─" * 30)
                print(_wrap(payloads[gen], "  │ "))
                print("  └" + "─" * 60)
            out = getattr(ev, "output", None)
            acts, txt = [], ""
            try:
                m = out.choices[0].message
                txt = (m.text or "").strip()
                for tc in (m.tool_calls or []):
                    a = tc.arguments if isinstance(tc.arguments, dict) else {}
                    brief = next((str(a[k])[:90] for k in
                                  ("command", "code", "path", "answer",
                                   "thought") if a.get(k)), "")
                    acts.append(f"{tc.function}: {brief}")
            except Exception:
                pass
            print(f"\n[gen {gen}] " + ("; ".join(acts) if acts
                                       else (txt[:160] or "(no output)")))
        elif ev.event == "tool":
            r = str(getattr(ev, "result", "") or "")[:140].replace("\n", " ")
            print(f"    -> {getattr(ev, 'function', '?')}: {r}")

    for k, v in (sample.scores or {}).items():
        print(f"\nscore: {v.value}  ({k})")
    if md.get("dk_error"):
        print(f"dk_error: {md['dk_error']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help=".eval file or a logs/<stamp> directory")
    ap.add_argument("sample", nargs="?", default="",
                    help="sample id (default: first sample)")
    ap.add_argument("--arm", default="",
                    help="when given a directory: which arm's log to open")
    ap.add_argument("--list", action="store_true",
                    help="list samples and their counters, then exit")
    args = ap.parse_args()

    from inspect_ai.log import read_eval_log

    files = ([args.path] if args.path.endswith(".eval")
             else sorted(glob.glob(os.path.join(args.path, "*.eval"))))
    if not files:
        sys.exit(f"no .eval files under {args.path}")

    picked = None
    for f in files:
        log = read_eval_log(f, resolve_attachments=True)
        arm = "baseline"
        for s in (log.samples or []):
            arm = (s.metadata or {}).get("arm", "baseline")
        if not args.arm or arm == args.arm:
            picked = (log, arm)
            if args.arm:
                break
    if picked is None:
        sys.exit(f"no log for arm {args.arm!r} in {args.path}")
    log, arm = picked

    if args.list:
        for s in (log.samples or []):
            md = s.metadata or {}
            sc = next((str(v.value) for v in (s.scores or {}).values()), "-")
            print(f"{s.id:<16} score={sc} gens={md.get('gen_count', 0):<3} "
                  f"fired={md.get('dk_fired', 0):<3} "
                  f"payloads={len(md.get('dk_payload_log', []))}")
        return 0

    for s in (log.samples or []):
        if not args.sample or str(s.id) == args.sample:
            show_sample(s, arm)
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
