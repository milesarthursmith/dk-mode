#!/usr/bin/env python3
"""dk_consolidate.py - periodic consolidation for dk-mode.

Reads the unprocessed tail of .claude/memory/dk.jsonl (verbatim
steering the user gave Claude, captured by dk_capture.sh), asks a strong
model to sort it into Mistake Patterns / Standing Rules / Facts, and
rewrites dk_rules.md - including the small inject block that
dk_recall.sh pastes into every prompt.

Invocation: detached by dk_recall.sh when due (see DK_INTERVAL), or by
hand. `--drain` processes ALL pending entries in successive batches in one
invocation, ignoring the interval - use after dk_backfill.sh has mined a
large history.

Uses the raw Anthropic API over stdlib urllib - no SDK, no venv, and never
the `claude` CLI (headless CLI auth is unreliable in automation). Key
resolution: ANTHROPIC_API_KEY env var, else the file at DK_KEY_FILE; if
neither resolves, exits silently (capture and recall still work without it).

Deliberate properties:
- dk.jsonl is NEVER modified, only read. A bad consolidation is always
  recoverable by resetting consolidated_through and re-running.
- The model's output is structurally validated before it replaces anything;
  a malformed rewrite marks the run FAILED and the old file stays.
- Writes are temp-file-then-rename (atomic).
- Scheduling state lives in .claude/memory/.dk_state (flat key=value,
  atomic writes) - the human-readable memory log gets one heartbeat line per
  run, success or FAILED, but is never parsed for scheduling.
- Detailed errors go to DK_LOG_DIR (default ~/Library/Logs on macOS,
  else ~/.claude/logs) - never /tmp, which the OS cleans.

Config (all optional): ANTHROPIC_API_KEY, DK_KEY_FILE, DK_MODELS
(comma-separated, tried in order), DK_USER_NAME, DK_INTERVAL,
DK_LOG_DIR, DK_API_URL (test override).
"""
import datetime
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def find_root(start):
    """Walk up from the script location to the nearest dir containing
    .claude/ - correct however deep this package is vendored."""
    d = start
    for _ in range(8):
        if os.path.isdir(os.path.join(d, ".claude")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.getcwd()


ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or find_root(SCRIPT_DIR)
MEM = os.path.join(ROOT, ".claude", "memory")
RAW = os.path.join(MEM, "dk.jsonl")
RULES = os.path.join(MEM, "dk_rules.md")
MEMLOG = os.path.join(MEM, "log.md")
STATE = os.path.join(MEM, ".dk_state")
LOCK = os.path.join(MEM, ".dk-consolidate.lock")

API_URL = os.environ.get("DK_API_URL", "https://api.anthropic.com/v1/messages")
# Approval ("training wheels") mode: new items land as pending and are held
# out of the inject note until a human approves them via dk_review.py.
APPROVAL = os.environ.get("DK_APPROVAL", "0").strip().lower() in ("1", "true", "yes", "on")
MODELS = [m.strip() for m in
          os.environ.get("DK_MODELS", "claude-fable-5,claude-opus-5").split(",")
          if m.strip()]
USER_NAME = os.environ.get("DK_USER_NAME", "").strip()
USER_REF = f"the user ({USER_NAME})" if USER_NAME else "the user"
BATCH_CAP = 200
NOTE_MAX_LINES = 12

TODAY = datetime.date.today().isoformat()


def interval_seconds():
    v = os.environ.get("DK_INTERVAL", "7d").strip()
    if v in ("", "0", "per-turn", "always"):
        return 0
    try:
        if v.endswith("d"):
            return int(v[:-1]) * 86400
        if v.endswith("h"):
            return int(v[:-1]) * 3600
        if v.endswith("m"):
            return int(v[:-1]) * 60
        return int(v)
    except ValueError:
        return 7 * 86400


def err_log_path():
    d = os.environ.get("DK_LOG_DIR")
    if not d:
        mac_logs = os.path.expanduser("~/Library/Logs")
        d = mac_logs if os.path.isdir(mac_logs) else os.path.expanduser("~/.claude/logs")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "dk_consolidate.log")


def log_error(msg):
    try:
        with open(err_log_path(), "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except OSError:
        pass


def heartbeat(summary):
    with open(MEMLOG, "a", encoding="utf-8") as f:
        f.write(f"{TODAY} | dk-consolidate | {summary}\n")


def read_state():
    st = {}
    try:
        with open(STATE, encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    k, v = line.rstrip("\n").split("=", 1)
                    st[k] = v
    except OSError:
        pass
    return st


def write_state(status):
    st = read_state()
    now = str(int(time.time()))
    st["last_attempt_epoch"] = now
    st["last_attempt_status"] = status
    if status == "success":
        st["last_success_epoch"] = now
        st["consecutive_failed"] = "0"
    else:
        st["consecutive_failed"] = str(int(st.get("consecutive_failed", "0") or 0) + 1)
    fd, tmp = tempfile.mkstemp(dir=MEM, prefix=".dk-state-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("".join(f"{k}={v}\n" for k, v in st.items()))
    os.replace(tmp, STATE)


def fail(reason):
    log_error(f"FAILED: {reason}")
    try:
        write_state("failed")
        heartbeat(f"FAILED: {reason[:120]}")
    except OSError:
        pass
    sys.exit(1)


def take_lock():
    """No-wait mkdir lock; reclaim only if 10+ minutes stale."""
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


def read_key():
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if k:
        return k
    path = os.environ.get("DK_KEY_FILE", "").strip()
    if path:
        try:
            with open(os.path.expanduser(path), encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return None
    return None


PROMPT_TEMPLATE = """You maintain the long-term steering-memory file for a \
Claude Code workspace. The raw entries below are things {user_ref} actually \
said, captured verbatim, each tagged with a first-guess kind (correction = \
Claude got something wrong; instruction = a standing rule or preference) and \
the tail of what Claude had just said for context.

Sort each new entry:
(a) A repeat of an existing Mistake Pattern or Standing Rule -> increment its \
Count, update Last seen to the entry date, and sharpen its wording if the new \
evidence is clearer.
(b) A new recurring-looking mistake by Claude -> a new item under \
## Mistake Patterns.
(c) A standing instruction or preference -> a new or updated item under \
## Standing Rules.
(d) A durable fact worth keeping -> ## Facts.
(e) A one-off, or a false positive (the message was not actually a \
correction or instruction - e.g. the user quoting someone, or ordinary task \
wording that tripped the capture filter) -> discard it silently.

Hard constraints:
- NEVER invent a mistake, rule or fact the user's words do not show. Quote \
the user verbatim in each item's Evidence line, with the date.
- Each item keeps the existing shape: heading, **What it looks like:**, \
**Reminder line:**, **Evidence:**, **First seen:** / **Last seen:** / \
**Count:**.
- Move any Mistake Pattern with Last seen older than 60 days and Count \
under 3 to ## Retired. Standing Rules the user stated explicitly are \
evergreen - never retire them for age.
- Then choose the items most worth reminding Claude about on every prompt \
(frequent + recent + costly when forgotten, across patterns AND rules) and \
rewrite the block between <!-- inject:start --> and <!-- inject:end -->: \
keep the <self-steering> wrapper and the "Self-steering - check before acting:" header \
line, one blunt imperative line per item, at most 5 items, the whole block \
within {note_max} lines and roughly 100 tokens.
- Keep the YAML frontmatter and every section heading. Do not change \
consolidated_through (it is maintained by the script).
{approval_clause}
Return ONLY the complete rewritten markdown file. No commentary, no code \
fences.

=== CURRENT FILE ===
{current}

=== NEW RAW ENTRIES ===
{entries}
"""


def call_api(key, prompt):
    last_err = None
    for model in MODELS:
        body = json.dumps({
            "model": model,
            "max_tokens": 8000,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(API_URL, data=body, headers={
            "content-type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        })
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = "".join(b.get("text", "") for b in data.get("content", [])
                           if isinstance(b, dict) and b.get("type") == "text")
            if text.strip():
                return text, model
            last_err = f"{model}: empty response"
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except OSError:
                pass
            last_err = f"{model}: HTTP {e.code} {detail}"
            continue
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            last_err = f"{model}: {e}"
            continue
    return None, last_err


APPROVAL_CLAUSE = """- APPROVAL MODE IS ON. Every NEW item you create must \
carry `**Status:** pending` as the line immediately after its heading. Items \
already carrying `**Status:** approved` keep it - count/date updates never \
change Status. Build the inject block ONLY from items whose Status is \
approved; if none are approved yet, the block's single bullet is \
`- (nothing approved yet)`. Never let a pending item's Reminder line appear \
in the inject block - pending items must not steer behaviour until a human \
approves them.
"""


def pending_reminder_lines(text):
    """Reminder lines of every item marked Status: pending."""
    out = []
    for m in re.finditer(r"^### .*?(?=^### |^## |\Z)", text, re.M | re.S):
        block = m.group(0)
        if re.search(r"\*\*Status:\*\*\s*pending", block):
            r = re.search(r"\*\*Reminder line:\*\*\s*(.+)", block)
            if r:
                out.append(r.group(1).strip())
    return out


def strip_fences(text):
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    return t


def validate(text):
    """A malformed rewrite must never reach the hot path."""
    if not text.startswith("---"):
        return "missing frontmatter"
    for marker in ("<!-- inject:start -->", "<!-- inject:end -->",
                   "consolidated_through:", "## Mistake Patterns",
                   "## Standing Rules", "## Retired"):
        if marker not in text:
            return f"missing {marker}"
    block = text.split("<!-- inject:start -->")[1].split("<!-- inject:end -->")[0]
    n_lines = len([ln for ln in block.splitlines() if ln.strip()])
    if n_lines > NOTE_MAX_LINES:
        return f"inject block too long ({n_lines} lines)"
    if n_lines < 1:
        return "inject block empty"
    if APPROVAL:
        # Deterministic leak check - the model alone isn't trusted to hold
        # pending items out of the note.
        for line in pending_reminder_lines(text):
            if line and line in block:
                return f"pending item leaked into inject block ({line[:60]})"
    return None


def run_batch(key):
    """Consolidate one batch. Returns (processed_count, note_items) or
    raises via fail() on error. Returns (0, 0) when nothing is pending."""
    with open(RULES, encoding="utf-8") as f:
        current = f.read()
    m = re.search(r"^consolidated_through:\s*(\d+)", current, re.M)
    if not m:
        fail("dk_rules.md has no consolidated_through line")
    done = int(m.group(1))

    try:
        with open(RAW, encoding="utf-8", errors="replace") as f:
            raw_lines = f.read().splitlines()
    except OSError:
        raw_lines = []
    pending = raw_lines[done:done + BATCH_CAP]
    if not pending:
        return 0, 0

    prompt = PROMPT_TEMPLATE.format(
        user_ref=USER_REF, note_max=NOTE_MAX_LINES, current=current,
        approval_clause=APPROVAL_CLAUSE if APPROVAL else "",
        entries="\n".join(pending))
    text, model_or_err = call_api(key, prompt)
    if text is None:
        fail(f"API call failed ({model_or_err})")
    text = strip_fences(text)

    problem = validate(text)
    if problem:
        log_error(f"rejected model output: {problem}\n--- output was:\n{text[:2000]}")
        fail(f"model output rejected: {problem}")

    # The script, not the model, owns the bookmark and the date.
    new_done = done + len(pending)
    text = re.sub(r"^consolidated_through:.*$",
                  f"consolidated_through: {new_done}", text, count=1, flags=re.M)
    text = re.sub(r"^last_verified:.*$",
                  f"last_verified: {TODAY}", text, count=1, flags=re.M)
    if not text.endswith("\n"):
        text += "\n"

    fd, tmp = tempfile.mkstemp(dir=MEM, prefix=".dk-rules-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, RULES)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    block = text.split("<!-- inject:start -->")[1].split("<!-- inject:end -->")[0]
    note_items = len([ln for ln in block.splitlines() if ln.strip().startswith("- ")])
    return len(pending), note_items


def main():
    drain = "--drain" in sys.argv
    if not os.path.isdir(MEM) or not os.path.isfile(RULES):
        sys.exit(0)
    key = read_key()
    if not key:
        sys.exit(0)  # no key resolvable: silent no-op
    if not take_lock():
        sys.exit(0)
    try:
        # Re-check dueness after acquiring the lock (a second session may
        # have kicked and finished between our kick and now). --drain skips
        # this - it's a deliberate manual catch-up.
        if not drain:
            iv = interval_seconds()
            if iv > 0:
                st = {}
                try:
                    with open(STATE, encoding="utf-8") as f:
                        st = dict(line.rstrip("\n").split("=", 1)
                                  for line in f if "=" in line)
                except OSError:
                    pass
                last = int(st.get("last_attempt_epoch", "0") or 0)
                if time.time() - last < min(iv, 3600):
                    sys.exit(0)

        total_processed = 0
        note_items = 0
        batches = 0
        while True:
            processed, items = run_batch(key)
            if processed == 0:
                break
            total_processed += processed
            note_items = items
            batches += 1
            if not drain:
                break
        if total_processed:
            write_state("success")
            heartbeat(f"processed {total_processed} entries"
                      f"{f' in {batches} batches' if batches > 1 else ''}; "
                      f"{note_items} items in note")
    finally:
        try:
            os.rmdir(LOCK)
        except OSError:
            pass


if __name__ == "__main__":
    main()
