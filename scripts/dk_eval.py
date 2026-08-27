#!/usr/bin/env python3
"""dk_eval.py - does the runtime monitor speak up at the right moments?

The labeller here is an LLM AS A JUDGE: a model scoring work against written
criteria. That name is correct in this file and nowhere else in dk-mode.

Everything else in this repository tests plumbing. This measures judgement.

THE GROUND TRUTH. A conversation already carries its own labels. If the user
corrected the agent in their next message, something was going wrong in the
turn before it. So for every turn boundary in a real transcript:

    prediction  = did dk-mode fire on this turn?
    truth       = did the user correct the agent in their next message?

That gives three numbers from one run:

    SELECTIVITY  how often it fires at all. High is noisy.
    PRECISION    when it fires, was something actually going wrong?
    RECALL       of the moments that were going wrong, how many did it catch?

HONEST LIMITS, stated because they change how to read the result:
  - The user only corrects failures they NOTICE. A turn with no correction is
    not proof the turn was fine, so RECALL is measured against noticed
    failures only, and true recall is lower.
  - The labeller is a model reading the next message. It is a second opinion,
    not a fact. Use --review to write a file you can correct by hand, then
    --labels to re-score against your own judgement. That is the golden set.
  - Labelling uses a different prompt from the miner, so the miner is not
    grading its own homework. It is not fully independent: both are models.

Usage:
  dk_eval.py <transcript.jsonl> [...]        score them
  dk_eval.py --review out.md <transcript>    also write a file to correct
  dk_eval.py --labels out.md <transcript>    re-score using your corrections
  dk_eval.py --max-turns 40 <transcript>     cap the model calls (default 40)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("DK_HOME", os.path.expanduser("~"))
import dk_watch as W                                          # noqa: E402

LABEL_PROMPT = """Below is what a coding agent said, and then what its user \
said next.

Answer one question: in their reply, is the user telling the agent that \
something it did or said was WRONG?

That includes rejecting the approach, redirecting it, pointing out something \
missed, or dissatisfaction however mild ("bit lame", "that's overcomplicated", \
"simplify", "why is this so slow").

That excludes a new request, a question seeking information, an approval, or \
simply moving on to the next thing. Starting a task and agreeing to a plan \
are not corrections.

Reply with one word: YES or NO.

=== WHAT THE AGENT SAID ===
{agent}

=== WHAT THE USER SAID NEXT ===
{user}
"""


def label_turn(agent_text, user_text):
    """Was the user's next message a correction? Returns True/False/None."""
    out = W.call_model(W.read_key(),
                       LABEL_PROMPT.format(agent=agent_text[:3000],
                                           user=user_text[:1500]))
    if not out:
        return None
    head = out.strip().upper()[:40]
    if "YES" in head:
        return True
    if "NO" in head:
        return False
    return None


def turn_boundaries(msgs):
    """Every point where the agent had spoken and the user replies next.

    That reply is the label for everything the agent just did.
    """
    for i, m in enumerate(msgs):
        if m["role"] != "user" or i == 0:
            continue
        if msgs[i - 1]["role"] != "assistant":
            continue
        yield i


def main():
    argv = sys.argv[1:]
    review_path = labels_path = None
    max_turns = 40
    for flag, setter in (("--review", "review"), ("--labels", "labels"),
                         ("--max-turns", "max")):
        if flag in argv:
            i = argv.index(flag)
            val = argv[i + 1]
            del argv[i:i + 2]
            if setter == "review":
                review_path = val
            elif setter == "labels":
                labels_path = val
            else:
                max_turns = int(val)
    if not argv:
        print(__doc__.strip()[:600], file=sys.stderr)
        return 2

    hand = {}
    if labels_path:
        for line in open(labels_path, encoding="utf-8"):
            if line.startswith("- [") and "]" in line:
                mark = line[3]
                key = line.split("]", 1)[1].strip().split(" ", 1)[0]
                hand[key] = (mark.lower() == "x")

    rules = W.load_rules()
    if not rules:
        print("No rules loaded. Set DK_HOME or CLAUDE_PROJECT_DIR to a "
              "project that has dk_rules.md.", file=sys.stderr)
        return 1

    rows = []
    for path in argv:
        msgs = W._read_messages(path)
        for idx in list(turn_boundaries(msgs))[:max_turns]:
            window = W.recent_exchanges(msgs[:idx], W.EXCHANGES, W.WINDOW_CHARS)
            if not window:
                continue
            convo = "\n\n".join(f'[{m["role"]} id={m["uuid"]}] {m["text"]}'
                                for m in window)
            text = W.call_model(W.read_key(), W.PROMPT.format(
                max_active=W.MAX_ACTIVE,
        brief=W.load_brief() or "(none)",
                rules="\n".join(f'{r["id"]}. {r["heading"]} - {r["looks_like"]}'
                                for r in rules),
                convo=convo))
            parsed = W.parse_selection(text, rules) if text else None
            fired = bool(parsed and (parsed[0] or parsed[1]))
            uid = msgs[idx]["uuid"]
            truth = hand.get(uid)
            if truth is None:
                truth = label_turn(msgs[idx - 1]["text"], msgs[idx]["text"])
            rows.append({
                "uuid": uid,
                "fired": fired,
                "truth": truth,
                "alert": (parsed[1] if parsed else "") or "",
                "agent": msgs[idx - 1]["text"][:200],
                "user": msgs[idx]["text"][:200],
            })
            print(".", end="", flush=True)
    print()

    scored = [r for r in rows if r["truth"] is not None]
    if not scored:
        print("Nothing could be labelled. Is a model reachable?",
              file=sys.stderr)
        return 1

    fired = sum(1 for r in scored if r["fired"])
    tp = sum(1 for r in scored if r["fired"] and r["truth"])
    fp = sum(1 for r in scored if r["fired"] and not r["truth"])
    fn = sum(1 for r in scored if not r["fired"] and r["truth"])
    bad = sum(1 for r in scored if r["truth"])

    def pct(a, b):
        return "n/a" if not b else "%.0f%%" % (100.0 * a / b)

    print()
    print("turns scored:            %d   (%d unlabelled, dropped)"
          % (len(scored), len(rows) - len(scored)))
    print("turns you corrected:     %d" % bad)
    print()
    print("SELECTIVITY  fired on    %s of turns   (%d of %d)"
          % (pct(fired, len(scored)), fired, len(scored)))
    print("PRECISION    when it fired, something was wrong  %s   (%d of %d)"
          % (pct(tp, tp + fp), tp, tp + fp))
    print("RECALL       of the turns you corrected, it caught  %s   (%d of %d)"
          % (pct(tp, tp + fn), tp, bad))
    print()
    print("Read RECALL as 'of the failures you NOTICED'. Failures you did not")
    print("notice are not in the denominator, so true recall is lower.")

    if review_path:
        with open(review_path, "w", encoding="utf-8") as f:
            f.write("# dk-mode eval - correct these labels by hand\n\n")
            f.write("Mark [x] if the user's reply WAS a correction, [ ] if "
                    "not. Then re-run with --labels on this file.\n\n")
            for r in rows:
                mark = "x" if r["truth"] else " "
                f.write("- [%s] %s  (dk-mode %s)\n" % (
                    mark, r["uuid"], "FIRED" if r["fired"] else "was quiet"))
                f.write("      agent: %s\n" % r["agent"].replace("\n", " "))
                f.write("      user:  %s\n" % r["user"].replace("\n", " "))
                if r["alert"]:
                    f.write("      said:  %s\n" % r["alert"])
                f.write("\n")
        print("\nReview file: %s" % review_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
