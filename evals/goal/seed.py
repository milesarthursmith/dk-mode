"""Seed ~20 independent bugs into the dk-goal image's jinja2 checkout.

Line-level mutations (operator flips, off-by-ones, condition inversions)
chosen deterministically, then FILTERED against reality: a candidate is
kept only if, applied alone, the test suite still collects and at least
one test fails. The kept set is applied together and the jointly-failing
test ids recorded - that list is the goal-mode scorer's denominator.

Outputs (committed):
  bugs.patch          the combined mutation diff
  failing_tests.txt   test ids failing under the combined patch
"""
import json
import random
import re
import subprocess
import sys

HERE = "/home/user/dk-mode/evals/goal"
IMG = "dk-goal"
SRC = "/opt/jinja/src/jinja2"

MUTS = [
    (r" == ", " != "),
    (r" != ", " == "),
    (r" < ", " <= "),
    (r" > ", " >= "),
    (r"\bis not None\b", "is None"),
    (r"\+ 1\b", "- 1"),
    (r"\breturn True\b", "return False"),
    (r"\b and \b", " or "),
]


def sh(cmd, timeout=300):
    return subprocess.run(["docker", "run", "--rm", IMG, "bash", "-c", cmd],
                          capture_output=True, text=True, timeout=timeout)


def listing():
    r = sh(f"grep -rn . {SRC} --include='*.py' | head -20000")
    return r.stdout.splitlines()


def main():
    rng = random.Random(7)
    lines = listing()
    cands = []
    for ln in lines:
        m = re.match(r"([^:]+):(\d+):(.*)", ln)
        if not m: continue
        path, no, text = m.group(1), int(m.group(2)), m.group(3)
        if path.endswith(("__init__.py",)) or "/tests" in path: continue
        s = text.strip()
        if not s or s.startswith(("#", '"', "'", "import", "from", "def ", "class ")):
            continue
        if len(s) < 8 or s.startswith("@"): continue
        for pat, rep in MUTS:
            if re.search(pat, text):
                cands.append((path, no, pat, rep))
                break
    rng.shuffle(cands)
    print(f"{len(cands)} candidates", flush=True)

    kept, per_file = [], {}
    for path, no, pat, rep in cands:
        if len(kept) >= 20: break
        if per_file.get(path, 0) >= 3: continue
        mut = (f"python3 - <<'EOF'\n"
               f"import re\n"
               f"p={path!r}; L=open(p).readlines()\n"
               f"L[{no}-1]=re.sub({pat!r},{rep!r},L[{no}-1],count=1)\n"
               f"open(p,'w').writelines(L)\nEOF\n")
        r = sh(mut + "cd /opt/jinja && python -m pytest tests -q -x --no-header 2>&1 | tail -2")
        out = r.stdout
        if "error" in out.lower() and "collect" in out.lower(): continue
        if re.search(r"\b\d+ failed", out):
            kept.append((path, no, pat, rep))
            per_file[path] = per_file.get(path, 0) + 1
            print(f"keep {len(kept):>2}: {path.split('/')[-1]}:{no} {pat}->{rep}", flush=True)

    # combined patch + jointly failing tests
    muts = "\n".join(
        f"python3 - <<'EOF'\nimport re\np={p!r}; L=open(p).readlines()\n"
        f"L[{n}-1]=re.sub({pa!r},{re_!r},L[{n}-1],count=1)\nopen(p,'w').writelines(L)\nEOF"
        for p, n, pa, re_ in kept)
    r = sh(muts + "\ncd /opt/jinja && git diff; echo ===SPLIT===; "
                  "python -m pytest tests -q --no-header 2>&1 | grep FAILED | awk '{print $2}'",
           timeout=600)
    diff, _, failing = r.stdout.partition("===SPLIT===")
    failing = [l.strip() for l in failing.splitlines() if "::" in l]
    open(f"{HERE}/bugs.patch", "w").write(diff.strip() + "\n")
    open(f"{HERE}/failing_tests.txt", "w").write("\n".join(failing) + "\n")
    print(f"\n{len(kept)} bugs, {len(failing)} failing tests")


if __name__ == "__main__":
    sys.exit(main())
