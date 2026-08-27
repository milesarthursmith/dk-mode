#!/usr/bin/env python3
"""dk_replay.py - run the monitor over a finished conversation.

What would dk-mode have said, turn by turn, if it had been watching?

This exists because self-assessment is unreliable, which is the premise of
the whole project: an agent asked to list its own mistakes reports the ones it
noticed, and the ones it did not notice are exactly the ones that matter. So
instead of asking, replay the conversation through the real monitor and read
what it says.

It uses the shipped code - dk_watch's prompt, parser, renderer and running
brief - so the output is what dk-mode would actually have injected, not a
description of what it might have done. The brief accumulates across the
replay in transcript order, exactly as it would live.

Usage:
  dk_replay.py <transcript.jsonl> [--max-turns N] [--out report.md]
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DK_HOME", os.path.expanduser("~"))
import dk_watch as W                                          # noqa: E402


def main():
    argv = sys.argv[1:]
    out_path, max_turns = None, 60
    for flag in ("--out", "--max-turns"):
        if flag in argv:
            i = argv.index(flag)
            val = argv[i + 1]
            del argv[i:i + 2]
            if flag == "--out":
                out_path = val
            else:
                max_turns = int(val)
    if not argv:
        print(__doc__.strip()[:400], file=sys.stderr)
        return 2

    rules = W.load_rules()
    if not rules:
        print("No rules. Set DK_HOME to a project with dk_rules.md.",
              file=sys.stderr)
        return 1
    by_id = {r["id"]: r for r in rules}

    msgs = W._read_messages(argv[0])
    bounds = [i for i, m in enumerate(msgs)
              if m["role"] == "user" and i and msgs[i - 1]["role"] == "assistant"]
    step = max(1, len(bounds) // max_turns)
    bounds = bounds[::step][:max_turns]

    fired = Counter()
    rows = []
    brief = ""
    for n, i in enumerate(bounds, 1):
        window = W.recent_exchanges(msgs[:i], W.EXCHANGES, W.WINDOW_CHARS)
        if not window:
            continue
        text = W.call_model(W.read_key(), W.PROMPT.format(
            max_active=W.MAX_ACTIVE,
            brief=brief or "(nothing yet - this is the first turn)",
            rules="\n".join(f'{r["id"]}. {r["heading"]} - {r["looks_like"]}'
                            for r in rules),
            convo="\n\n".join(f'[{m["role"]} id={m["uuid"]}] {m["text"]}'
                              for m in window)))
        parsed = W.parse_selection(text, rules) if text else None
        if not parsed:
            print("x", end="", flush=True)
            continue
        active, alert, _steering, new_brief = parsed
        if new_brief:
            # GOAL is re-derived, never taken from the model.
            lines = [ln for ln in new_brief.splitlines()
                     if ln.strip() and not ln.strip().startswith("GOAL:")]
            brief = ("GOAL: " + W.first_request(msgs) + "\n"
                     + "\n".join(lines))[:W.BRIEF_MAX]
        for rid in active:
            fired[by_id[rid]["heading"]] += 1
        rows.append({"n": n, "rules": [by_id[r]["heading"] for r in active],
                     "alert": alert or "",
                     "agent": msgs[i - 1]["text"][:150].replace("\n", " "),
                     "user": msgs[i]["text"][:150].replace("\n", " ")})
        print(".", end="", flush=True)
    print()

    spoke = sum(1 for r in rows if r["rules"] or r["alert"])
    print("\nturns replayed:      %d" % len(rows))
    print("turns it spoke on:   %d (%.0f%%)"
          % (spoke, 100.0 * spoke / max(1, len(rows))))
    print("\nRULES IT FLAGGED, most often first:\n")
    for name, count in fired.most_common():
        print("  %3d  %s" % (count, name))
    if not fired:
        print("  (none)")

    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("# What dk-mode would have said, replayed\n\n")
            f.write("Brief at the end of the replay:\n\n```\n%s\n```\n\n" % brief)
            for r in rows:
                if not (r["rules"] or r["alert"]):
                    continue
                f.write("## turn %d\n\n" % r["n"])
                f.write("- agent: %s\n- user: %s\n" % (r["agent"], r["user"]))
                if r["alert"]:
                    f.write("- **said:** %s\n" % r["alert"])
                for x in r["rules"]:
                    f.write("- rule: %s\n" % x)
                f.write("\n")
        print("\nFull report: %s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
