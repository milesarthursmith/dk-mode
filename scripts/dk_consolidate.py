#!/usr/bin/env python3
"""MEMORY CONSOLIDATION: many raw events become fewer durable rules. Letta
calls an agent that does this while idle a sleep-time agent. See
docs/MECHANISM.md section 1.1 for the standard name of every part.

dk_consolidate.py - periodic consolidation for dk-mode.

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
resolution: DK_API_KEY (or legacy ANTHROPIC_API_KEY) env var, else the
file at DK_KEY_FILE; if
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

Config (all optional): DK_API_KEY, DK_KEY_FILE, DK_MODELS
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


def _target_arg():
    """--target DIR, for running this by hand against another project.
    Without it a manual run silently consolidated the WRONG project: ROOT
    fell back to a walk-up from the script, which is dk-mode's own checkout,
    not the project you just mined."""
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


# Manual runs should explain themselves; the hook-kicked background run must
# stay quiet. --drain and --target are only ever typed by a human.
INTERACTIVE = ("--drain" in sys.argv or "--target" in sys.argv
               or sys.stderr.isatty())


def note(msg):
    if INTERACTIVE:
        print("dk-consolidate: " + msg, file=sys.stderr)


# DK_HOME wins over everything: a machine-wide install (install.sh --global)
# points every project at one memory, because a mistake Claude makes is about
# how it behaves, not about which repo it is in. Unset = per-project, as before.
ROOT = (_target_arg() or os.environ.get("DK_HOME")
        or os.environ.get("CLAUDE_PROJECT_DIR") or find_root(SCRIPT_DIR))
# DK_MEM names the memory directory outright. A plugin install has no project
# to hang .claude/memory off - its data lives in ${CLAUDE_PLUGIN_DATA}, which
# survives plugin updates - so the directory is passed directly.
MEM = (os.environ.get("DK_MEM")
       or os.path.join(ROOT, ".claude", "memory"))
RAW = os.path.join(MEM, "dk.jsonl")
RULES = os.path.join(MEM, "dk_rules.md")
MEMLOG = os.path.join(MEM, "log.md")
STATE = os.path.join(MEM, ".dk_state")
LOCK = os.path.join(MEM, ".dk-consolidate.lock")

BACKEND = os.environ.get("DK_BACKEND", "anthropic").strip().lower()
# Thinking models (qwen3, deepseek-r1) spend the whole token budget on
# reasoning and return empty content. "none" turns it off on ollama/vLLM.
REASONING_EFFORT = os.environ.get("DK_REASONING_EFFORT", "").strip()
DEFAULT_URL = ("http://localhost:11434/v1/chat/completions" if BACKEND == "openai"
               else "https://api.anthropic.com/v1/messages")
API_URL = os.environ.get("DK_API_URL", DEFAULT_URL)
# Approval ("training wheels") mode: new items land as pending and are held
# out of the inject note until a human approves them via dk_review.py.
_APPROVAL_RAW = os.environ.get("DK_APPROVAL", "0").strip().lower()
# off | on (a human approves everything) | auto (repetition approves it).
# "auto" is what makes the loop work with nobody watching: one incident may
# be noise, but the same failure recurring N times across sessions has
# proven itself without a human needing to agree. A human can still
# override anything via dk_review.py.
APPROVAL = _APPROVAL_RAW in ("1", "true", "yes", "on", "auto")
AUTO_APPROVE = _APPROVAL_RAW == "auto"
AUTO_APPROVE_COUNT = int(os.environ.get("DK_AUTO_APPROVE_COUNT", "3"))
DEFAULT_MODELS = ("qwen2.5:14b-instruct" if BACKEND == "openai"
                  else "claude-fable-5,claude-opus-5")
MODELS = [m.strip() for m in
          os.environ.get("DK_MODELS", DEFAULT_MODELS).split(",")
          if m.strip()]
USER_NAME = os.environ.get("DK_USER_NAME", "").strip()
USER_REF = f"the user ({USER_NAME})" if USER_NAME else "the user"
BATCH_CAP = int(os.environ.get("DK_BATCH", "200"))
NOTE_MAX_LINES = 12
# Local models on CPU can be slow; give them room without hanging forever.
LOCAL_TIMEOUT = int(os.environ.get("DK_TIMEOUT", "600" if BACKEND == "openai" else "180"))

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
    # DK_API_KEY first: the key is provider-neutral, and dk-mode talks to
    # OpenRouter and local servers as readily as to Anthropic. Reading only
    # ANTHROPIC_API_KEY meant an OpenRouter user had to put an OpenRouter key
    # into a variable named for a different vendor. ANTHROPIC_API_KEY is still
    # honoured so existing installs keep working.
    k = (os.environ.get("DK_API_KEY", "").strip()
         or os.environ.get("ANTHROPIC_API_KEY", "").strip())
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
Claude Code workspace. The raw entries below are STEERING EVENTS captured \
verbatim - moments where the agent was told, by someone or something, that \
it had gone wrong or must do something differently. Each carries the tail of \
what the agent had just said, plus a `source` and a first-guess `kind`:

- source "human": {user_ref} said it. The strongest evidence there is.
- source "self": the agent corrected ITSELF mid-conversation ("I was
  wrong", "that didn't work"). Real evidence of a failure mode, but weaker -
  a plan changing course is not always a mistake worth remembering.
- any other source (a verifier, a test gate, a review agent, CI): a machine
  steered it. Treat a specific, repeated complaint as strong evidence and a
  one-off environment error (a flaky network call, a missing key) as noise.

kind: correction / instruction (a standing rule or preference) /
self-correction / verdict / test-failure / review.

Sort each new entry:
(a) A repeat of an existing Mistake Pattern or Standing Rule -> increment its \
Count, update Last seen to the entry date, and sharpen its wording if the new \
evidence is clearer.
(b) A new recurring-looking mistake by Claude -> a new item under \
## Mistake Patterns.
(c) A standing instruction or preference -> a new or updated item under \
## Standing Rules.
(d) A durable fact worth keeping -> ## Facts.
(e) A one-off, or a false positive -> discard it silently. Be strict here,
especially for machine sources: ordinary iteration (a test failing then
being fixed, a plan being revised, a transient tool error) is NOT a mistake
pattern. Only recurring, avoidable failures earn an item.

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


LAST_ERROR = []


def call_cli(prompt, models, timeout):
    """DK_BACKEND=cli: shell out to the `claude` CLI instead of an API.

    This uses the login you already have, so it needs no API key. The auth
    token lives in the macOS login keychain, which means it works when run by
    hand from a terminal and FAILS under cron, which has no login session
    ("Not logged in"). A LaunchAgent works; cron does not.

    Not recommended for the per-turn hook: that would start a nested `claude`
    process on every turn of every conversation. It is the right choice for
    mining history, for consolidation, and for the smoke test.
    """
    import subprocess
    for model in models:
        cmd = ["claude", "-p", "--model", model] if model else ["claude", "-p"]
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True,
                               text=True, timeout=timeout)
        except FileNotFoundError:
            LAST_ERROR.append("the `claude` CLI is not on PATH")
            return None
        except subprocess.TimeoutExpired:
            LAST_ERROR.append(f"{model}: `claude -p` timed out after {timeout}s")
            continue
        if r.returncode != 0:
            err = (r.stderr or "").strip()[:300]
            if "not logged in" in err.lower():
                err += "  (run `claude` once to log in; cron cannot unlock the keychain)"
            LAST_ERROR.append(f"{model}: `claude -p` exit {r.returncode}: {err}")
            continue
        if r.stdout.strip():
            return r.stdout
        LAST_ERROR.append(f"{model}: `claude -p` returned nothing")
    return None


def call_api(key, prompt):
    """One request per model until one answers. Two wire formats:
    Anthropic messages (default) and OpenAI-compatible chat/completions,
    which is what Ollama, LM Studio, llama.cpp and vLLM all serve - so
    DK_BACKEND=openai + DK_API_URL is how you keep this stage local."""
    if BACKEND == "cli":
        out = call_cli(prompt, MODELS or [""], LOCAL_TIMEOUT)
        if out:
            return out, "claude-cli"
        raise RuntimeError("; ".join(LAST_ERROR) or "`claude -p` produced nothing")
    last_err = None
    for model in MODELS:
        if BACKEND == "openai":
            payload = {
                "model": model,
                "max_tokens": 8000,
                "temperature": 0,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
            }
            if REASONING_EFFORT:
                payload["reasoning_effort"] = REASONING_EFFORT
            body = json.dumps(payload).encode("utf-8")
            headers = {"content-type": "application/json"}
            if key:  # local servers usually need no key; hosted ones do
                headers["authorization"] = f"Bearer {key}"
        else:
            body = json.dumps({
                "model": model,
                "max_tokens": 8000,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            }).encode("utf-8")
            headers = {
                "content-type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            }
        req = urllib.request.Request(API_URL, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=LOCAL_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if BACKEND == "openai":
                choices = data.get("choices") or []
                text = (choices[0].get("message", {}).get("content", "")
                        if choices else "")
            else:
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


def trim_echo(text):
    """Small local models append the CURRENT FILE verbatim after their
    rewrite. Keep only the first complete document: any later `---` line
    immediately followed by `name:` starts an echoed copy."""
    for m in re.finditer(r"(?m)^---[ \t]*\r?\nname:", text):
        if m.start() == 0:
            continue
        # Only treat it as an echoed copy if what follows really is another
        # whole document - otherwise a quoted "---\nname:" inside an
        # Evidence line silently truncated the real file.
        rest = text[m.start():]
        if "<!-- inject:start -->" in rest and "## Mistake Patterns" in rest:
            return text[:m.start()].rstrip() + "\n"
    return text


def validate(text):
    """A malformed rewrite must never reach the hot path."""
    if not text.startswith("---"):
        return "missing frontmatter"
    for marker in ("<!-- inject:start -->", "<!-- inject:end -->",
                   "consolidated_through:", "## Mistake Patterns",
                   "## Standing Rules", "## Retired"):
        if marker not in text:
            return f"missing {marker}"
    if text.count("<!-- inject:start -->") != 1:
        return "duplicated inject block"
    if len(re.findall(r"(?m)^consolidated_through:", text)) != 1:
        return "duplicated frontmatter"
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


def auto_approve(text):
    """Promote pending items that have recurred enough to speak for
    themselves, then rebuild the note deterministically so the promotion
    takes effect immediately rather than a cycle later. The note is rebuilt
    by dk_review's renderer - one definition of that logic, not two."""
    promoted = []

    def bump(m):
        block = m.group(0)
        if not re.search(r"\*\*Status:\*\*\s*pending", block):
            return block
        c = re.search(r"\*\*Count:\*\*\s*(\d+)", block)
        if not c or int(c.group(1)) < AUTO_APPROVE_COUNT:
            return block
        promoted.append(block.splitlines()[0].lstrip("# ").strip())
        return re.sub(r"(\*\*Status:\*\*\s*)pending", r"\1approved",
                      block, count=1)

    # Anchored heading, not a substring: dk_review.py had exactly this bug and
    # documents the fix. A rule whose Evidence quotes "## Retired" would
    # otherwise split the document at the quotation.
    _rm = re.search(r"^## Retired\s*$", text, re.M)
    retired_at = _rm.start() if _rm else -1
    head = text if retired_at < 0 else text[:retired_at]
    tail = "" if retired_at < 0 else text[retired_at:]
    head = re.sub(r"^### .*?(?=^### |^## |\Z)", bump, head, flags=re.M | re.S)
    text = head + tail
    if not promoted:
        return text
    try:
        sys.path.insert(0, SCRIPT_DIR)
        import dk_review
        text = dk_review.rebuild_note(text)
    except Exception as e:                       # never lose the promotion
        log_error(f"auto-approve rendered note fallback: {e}")
    log_error("auto-approved (count >= "
              f"{AUTO_APPROVE_COUNT}): {'; '.join(promoted)}")
    return text


def run_batch(key):
    """Consolidate one batch. Returns (processed_count, note_items, model)
    or raises via fail() on error. Returns (0, 0, None) when nothing is
    pending."""
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
        return 0, 0, None

    prompt = PROMPT_TEMPLATE.format(
        user_ref=USER_REF, note_max=NOTE_MAX_LINES, current=current,
        approval_clause=APPROVAL_CLAUSE if APPROVAL else "",
        entries="\n".join(pending))
    text, model_or_err = call_api(key, prompt)
    if text is None:
        fail(f"API call failed ({model_or_err})")
    text = trim_echo(strip_fences(text))

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
    # Promote anything that has now recurred enough to approve itself -
    # BEFORE the write, or the promotion exists only in memory.
    if AUTO_APPROVE:
        text = auto_approve(text)
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
    return len(pending), note_items, model_or_err


def main():
    drain = "--drain" in sys.argv
    if not os.path.isdir(MEM) or not os.path.isfile(RULES):
        note("no dk-mode memory at %s - is --target/CLAUDE_PROJECT_DIR right?"
             % ROOT)
        sys.exit(0)
    note("project: %s" % ROOT)
    key = read_key()
    # A local OpenAI-compatible server (Ollama/LM Studio/llama.cpp) needs no
    # key; only the hosted path requires one.
    # Neither a local OpenAI-compatible server nor the `claude` CLI needs a
    # key: the CLI uses the login you already have.
    if not key and BACKEND not in ("openai", "cli"):
        note("no API key. Set DK_API_KEY or DK_KEY_FILE, or set "
             "DK_BACKEND=cli to use your existing `claude` login, or "
             "DK_BACKEND=openai for a local server - nothing to do")
        sys.exit(0)
    if not take_lock():
        note("another consolidation holds the lock - skipped")
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
                    note("not due yet (DK_INTERVAL=%s) - use --drain to force"
                         % os.environ.get("DK_INTERVAL", "7d"))
                    sys.exit(0)

        total_processed = 0
        note_items = 0
        batches = 0
        used_model = None
        while True:
            processed, items, used_model = run_batch(key)
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
                      f"{f' in {batches} batches' if batches > 1 else ''} "
                      f"via {used_model}; {note_items} items in note")
    finally:
        try:
            os.rmdir(LOCK)
        except OSError:
            pass


if __name__ == "__main__":
    main()
