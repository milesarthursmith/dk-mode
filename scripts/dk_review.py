#!/usr/bin/env python3
"""dk_review.py - approve or reject proposed steering items.

The human half of dk-mode's approval ("training wheels") mode: with
DK_APPROVAL on, the consolidator marks new items `**Status:** pending`
and holds them out of the injected note. This tool lists them and applies
your verdicts - no API call, effect is immediate:

  dk_review.py --list             show pending items with their evidence
  dk_review.py --approve 1 3      approve by number (from --list order)
  dk_review.py --reject 2         move to ## Retired, marked rejected

Approving flips Status and deterministically rebuilds the inject block from
ALL approved items (top 5 by Count then recency, capped at the same limits
the consolidator obeys). Rejecting preserves the item under ## Retired -
history is never silently deleted, and the consolidator is instructed not
to re-propose retired items.

Same discipline as the consolidator: takes the .dk-consolidate.lock so a
review never races a running consolidation, writes via temp-file + atomic
rename, and never touches dk.jsonl.
"""
import datetime
import os
import re
import sys
import tempfile
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def find_root(start):
    d = start
    for _ in range(8):
        if os.path.isdir(os.path.join(d, ".claude")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.getcwd()


def _target_arg():
    """--target DIR, so a manual review can name its project. Without it ROOT
    fell back to a walk-up from the script location, which is dk-mode's own
    checkout rather than the project whose rules you meant to review."""
    if "--target" in sys.argv:
        i = sys.argv.index("--target")
        if i + 1 < len(sys.argv):
            d = os.path.abspath(sys.argv[i + 1])
            # Remove both tokens so the rest of the argument parsing never
            # sees them - "--approve 1 2 --target DIR" must not read DIR as
            # an item number.
            del sys.argv[i:i + 2]
            return d
        del sys.argv[i]
    return None


ROOT = (_target_arg() or os.environ.get("CLAUDE_PROJECT_DIR")
        or find_root(SCRIPT_DIR))
MEM = os.path.join(ROOT, ".claude", "memory")
RULES = os.path.join(MEM, "dk_rules.md")
LOCK = os.path.join(MEM, ".dk-consolidate.lock")
NOTE_MAX_ITEMS = 5
TODAY = datetime.date.today().isoformat()

ITEM_RE = re.compile(r"^### .*?(?=^### |^## |\Z)", re.M | re.S)


def field(block, name):
    m = re.search(r"\*\*" + name + r":\*\*\s*(.+)", block)
    return m.group(1).strip() if m else ""


def heading(block):
    return block.splitlines()[0].lstrip("# ").strip()


def parse_pending(text):
    """Pending item blocks in document order (the numbering --list shows)."""
    return [m.group(0) for m in ITEM_RE.finditer(text)
            if re.search(r"\*\*Status:\*\*\s*pending", m.group(0))]


def approved_items(text):
    out = []
    # Anchor on a real section heading at line start. text.find() matched the
    # string anywhere - including inside a quoted Evidence line - which
    # silently retired every item after it.
    rm = re.search(r"^## Retired\s*$", text, re.M)
    retired_at = rm.start() if rm else -1
    for m in ITEM_RE.finditer(text):
        block = m.group(0)
        if retired_at >= 0 and m.start() > retired_at:
            continue
        status = field(block, "Status") or "approved"  # no Status = approved
        if status.startswith("approved"):
            out.append(block)
    return out


def sort_key(block):
    try:
        count = int(field(block, "Count") or 0)
    except ValueError:
        count = 0
    return (-count, field(block, "Last seen") or "", heading(block))


def rebuild_note(text):
    """Deterministically rebuild the inject block from approved items."""
    items = sorted(approved_items(text), key=sort_key)
    lines = []
    for b in items[:NOTE_MAX_ITEMS]:
        r = field(b, "Reminder line")
        if r:
            lines.append(f"- {r}")
    if not lines:
        lines = ["- (nothing approved yet)"]
    block = "<self-steering>\nSelf-steering - check before acting:\n" + "\n".join(lines) + "\n</self-steering>"
    return re.sub(r"(<!-- inject:start -->\n).*?(\n<!-- inject:end -->)",
                  lambda m: m.group(1) + block + m.group(2), text, flags=re.S)


def atomic_write(text):
    fd, tmp = tempfile.mkstemp(dir=MEM, prefix=".dk-rules-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, RULES)


def take_lock():
    try:
        os.mkdir(LOCK)
        return True
    except FileExistsError:
        try:
            if time.time() - os.stat(LOCK).st_mtime > 600:
                os.rmdir(LOCK)
                os.mkdir(LOCK)
                return True
        except OSError:
            pass
        return False
    except OSError:
        return False


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ("--list", "--approve", "--reject"):
        print(__doc__.strip().splitlines()[0])
        print("usage: dk_review.py --list | --approve N [N...] | --reject N [N...]")
        return 1
    if not os.path.isfile(RULES):
        print(f"no {RULES} - is dk-mode installed here?", file=sys.stderr)
        return 1

    with open(RULES, encoding="utf-8") as f:
        text = f.read()
    pending = parse_pending(text)

    if args[0] == "--list":
        if not pending:
            print("no proposed items awaiting review")
            return 0
        for i, b in enumerate(pending, 1):
            print(f"{i}. {heading(b)} [{field(b, 'Count') or '1'}x]")
            print(f"   reminder: {field(b, 'Reminder line')}")
            print(f"   evidence: {field(b, 'Evidence')[:160]}")
        print(f"\napprove: dk_review.py --approve N [N...]   "
              f"reject: dk_review.py --reject N [N...]")
        return 0

    try:
        nums = sorted({int(n) for n in args[1:]})
    except ValueError:
        print("item numbers must be integers (from --list)", file=sys.stderr)
        return 1
    if not nums or any(n < 1 or n > len(pending) for n in nums):
        print(f"numbers out of range: {len(pending)} pending item(s)", file=sys.stderr)
        return 1

    if not take_lock():
        print("another dk-mode process holds the lock - try again shortly", file=sys.stderr)
        return 1
    try:
        for n in nums:
            block = pending[n - 1]
            if args[0] == "--approve":
                new_block = re.sub(r"(\*\*Status:\*\*\s*)pending",
                                   r"\1approved", block, count=1)
                text = text.replace(block, new_block)
                print(f"approved: {heading(block)}")
            else:
                stamped = block.rstrip("\n") + f"\n**Status:** rejected {TODAY}\n"
                stamped = re.sub(r"\*\*Status:\*\*\s*pending\n", "", stamped, count=1)
                text = text.replace(block, "")
                # Append under ## Retired (created by template; required by validator).
                text = re.sub(r"(^## Retired\s*\n)",
                              r"\1\n" + stamped.replace("\\", "\\\\") + "\n",
                              text, count=1, flags=re.M)
                print(f"rejected -> Retired: {heading(block)}")
        text = re.sub(r"\n{3,}", "\n\n", rebuild_note(text))
        atomic_write(text)
        remaining = len(parse_pending(text))
        print(f"note rebuilt; {remaining} item(s) still pending")
        return 0
    finally:
        try:
            os.rmdir(LOCK)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
