"""Print what the coding AI did after the resume point, for reading.

Usage: show.py runs/<moment>/<arm> [--full]
"""
import json
import os
import sys


def main():
    d = sys.argv[1]
    full = "--full" in sys.argv
    summ = json.load(open(os.path.join(d, "summary.json")))
    rows = [json.loads(l) for l in open(os.path.join(d, "transcript.jsonl"))]
    start = summ.get("prefix_turns")          # rows written before the resume
    if start is None:                          # older runs: last prompt match
        for i, e in enumerate(rows):
            if e.get("type") == "user":
                c = e["message"]["content"]
                t = c if isinstance(c, str) else " ".join(
                    b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
                if t.strip() == summ["prompt"].strip():
                    start = i
    print(f"# {summ['moment']} / {summ['arm']}  ({summ['before_left']} -> {summ['after_left']} failing, "
          f"{summ['num_turns']} turns, ${summ['cost_usd']:.2f})")
    note = summ.get("note")
    if note and note != "-":
        print("NOTE INJECTED:", open(os.path.join(d, "note.txt")).read().strip().replace("<self-steering>", "").replace("</self-steering>", "").strip())
    print()
    if start is None:
        print("(resume point not found)")
        return
    tc, ta = (2000, 1500) if full else (160, 400)
    for e in rows[start:]:
        if e.get("type") not in ("user", "assistant"):
            continue
        c = e["message"]["content"]
        if isinstance(c, str):
            print(f"[{e['type']}] {c[:ta]}")
            continue
        for b in c:
            if b.get("type") == "text" and b["text"].strip():
                print(f"[{e['type']}] {b['text'][:ta]}")
            elif b.get("type") == "tool_use":
                print(f"  -> {b['name']} {json.dumps(b['input'])[:tc]}")
            elif b.get("type") == "tool_result":
                t = b.get("content")
                t = t if isinstance(t, str) else " ".join(x.get("text", "") for x in t if isinstance(x, dict))
                print(f"  <- {t[:tc]!r}")
    print()
    print("RESULT:", summ.get("result_tail", "")[-600:])


if __name__ == "__main__":
    main()
