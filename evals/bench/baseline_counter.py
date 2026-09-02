"""Counter-gated baseline (docs/SHAPE.md: retired as product, kept as the
bench row the watcher must beat). No model call. Fires when a
deterministic signal trips, with a templated alert carrying the fact.

Same CLI/handoff contract as the watcher: argv[1] transcript, writes
$DK_MEM/.dk_active.<session>. Thresholds are the field's convergent
numbers (OpenHands/opencode/Aider: 3-4 repeats)."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from watcher_session import read_transcript  # same parser, same view

MEM = os.environ.get("DK_MEM", ".")
REPEAT = int(os.environ.get("BASE_REPEAT", "3"))


def main():
    msgs = read_transcript(sys.argv[1])
    session = os.environ.get("DK_SESSION", "session")[:16]
    asst = [m["text"] for m in msgs if m["role"] == "assistant"]
    alert = None
    # 1. near-identical assistant messages / commands
    seen = {}
    for t in asst:
        k = re.sub(r"\s+", " ", t[:120]); seen[k] = seen.get(k, 0) + 1
    top = max(seen.items(), key=lambda x: x[1]) if seen else ("", 0)
    if top[1] >= REPEAT:
        alert = (f"You have produced the same step {top[1]} times "
                 f"(\"{top[0][:60]}...\"). Repeating it will not change the "
                 f"result; change the approach.")
    # 2. same error string recurring
    if not alert:
        errs = {}
        for m in msgs[-16:]:
            for e in re.findall(r"([A-Za-z]+Error: [^\n]{5,60})", m["text"]):
                errs[e] = errs.get(e, 0) + 1
        te = max(errs.items(), key=lambda x: x[1]) if errs else ("", 0)
        if te[1] >= REPEAT:
            alert = (f"The error '{te[0]}' has recurred {te[1]} times in your "
                     f"recent steps and your fixes have not changed it. Stop "
                     f"and diagnose its actual cause before editing again.")
    # 3. reported progress plateau
    if not alert:
        pcts = [int(x.group(1)) for t in msgs
                for x in [re.search(r"\((\d+)% fixed\)", t["text"])] if x]
        if len(pcts) >= REPEAT and len(set(pcts[-REPEAT:])) == 1:
            alert = (f"Progress has been flat at {pcts[-1]}% for {REPEAT} "
                     f"checks. Whatever you are doing is not moving the "
                     f"tests; pick a different failing test and start there.")
    active = os.path.join(MEM, f".dk_active.{session}")
    with open(active, "w") as f:
        f.write(f"<self-steering>\n{alert}\n</self-steering>\n" if alert else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
