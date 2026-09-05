"""Score bench variants against the JUDGMENT labels (labels/shard*.jsonl).

The labels are not derived from any rule. Four readers read every moment's
transcript in full and decided, as a human overseer would, whether to
speak at that point. A moment where they said speak=true is a positive;
speak=false is a negative. The old wedge_/healthy_ filename prefixes are
ignored here (they encoded staging and outcome, not the judgment).

For each variant in results.jsonl: recall on positives, false-fire rate
on negatives, with Wilson 95% intervals, plus paired McNemar against the
counter baseline on the same moments.
"""
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def mcnemar(b, c):
    """Exact binomial p for discordant pairs b (A fired, B not) and c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def load_labels():
    lab = {}
    for f in sorted(glob.glob(os.path.join(HERE, "labels", "shard*.jsonl"))):
        for line in open(f):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            lab[r["moment"]] = r
    return lab


def load_results():
    res = {}
    for line in open(os.path.join(HERE, "results.jsonl")):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("error"):
            continue
        res.setdefault(r["variant"], {})[r["moment"]] = bool(r["fired"])
    return res


def main():
    lab = load_labels()
    res = load_results()
    pos = {m for m, r in lab.items() if r["speak"]}
    neg = {m for m, r in lab.items() if not r["speak"]}
    print(f"judgment labels: {len(lab)} moments, speak={len(pos)}, silent={len(neg)}\n")
    base = res.get("counter-baseline-seq") or res.get("counter-baseline", {})
    rows = []
    for v in sorted(res, key=lambda v: -len(res[v])):
        fired = res[v]
        P = [m for m in pos if m in fired]
        N = [m for m in neg if m in fired]
        if len(P) + len(N) < 20:
            continue
        tp = sum(fired[m] for m in P)
        fp = sum(fired[m] for m in N)
        rl, rh = wilson(tp, len(P))
        fl, fh = wilson(fp, len(N))
        # paired vs counter on positives: b = variant fired & counter quiet
        b = sum(1 for m in P if m in base and fired[m] and not base[m])
        c = sum(1 for m in P if m in base and not fired[m] and base[m])
        rows.append((v, tp, len(P), rl, rh, fp, len(N), fl, fh, b, c, mcnemar(b, c)))
    print(f"{'variant':22s} {'recall':>14s} {'95% CI':>13s} {'false fire':>12s} {'95% CI':>13s} {'vs counter b/c':>15s} {'p':>6s}")
    for v, tp, np_, rl, rh, fp, nn, fl, fh, b, c, p in rows:
        print(f"{v:22s} {tp:3d}/{np_:<3d} {tp/np_:5.0%}  [{rl:4.0%},{rh:4.0%}]   {fp:3d}/{nn:<3d} {fp/nn:5.0%}  [{fl:4.0%},{fh:4.0%}]   {b:3d}/{c:<3d}       {p:6.3f}")
    if "--disagree" in sys.argv:
        print("\nprefix vs judgment disagreements:")
        for m, r in sorted(lab.items()):
            pre = m.split("_")[0]
            if (pre == "wedge") != bool(r["speak"]):
                print(f"  {m}: judgment speak={r['speak']} ({r.get('confidence','?')})")


if __name__ == "__main__":
    main()
