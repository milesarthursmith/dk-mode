#!/usr/bin/env python3
"""dk_watch.py - the relevance layer ("what applies RIGHT NOW").

The problem this exists for: injecting the same distilled rules into every
prompt is just a longer system prompt. Attention dilutes, and a rule that is
always present is background noise by turn 40. What is wanted instead is a
meta layer that reads the actual conversation, works out which known failure
modes are live in THIS situation, and injects only those - as a challenge,
at the moment it applies.

Why it runs asynchronously: an LLM call inside UserPromptSubmit would stall
every message by seconds. So this runs on the Stop hook instead, one turn
behind - it reads the turn that just happened, decides what is relevant, and
writes the rendered block to .claude/memory/.dk_active. The next prompt's
recall hook reads that file instantly (no LLM in the hot path). A
conversation's situation persists across turns, so one turn of lag costs
almost nothing; the alternative costs latency on every single message.

The model SELECTS, it never WRITES: it returns the ids of relevant rules
plus an optional one-line situational alert, and the script renders the
block from the rules file itself. Same discipline as the consolidator - the
model cannot invent a rule that is not in dk_rules.md, and in approval mode
it can only select items a human already approved.

Degrades silently at every step: no key/model/server, a malformed response,
an unparseable rules file - nothing is written, .dk_active goes stale, and
dk_recall.sh falls back to the static top-N note. The system is never worse
than it was without this layer.

Config: DK_WATCH (0/1, default 1 when a backend is reachable),
DK_WATCH_MODELS (default: cheap/fast - haiku hosted, the local model
otherwise), DK_WATCH_TURNS (how many recent messages to read, default 6),
DK_ACTIVE_TTL (seconds .dk_active stays valid, default 3600), plus the
shared DK_BACKEND / DK_API_URL / DK_KEY_FILE / DK_API_KEY.
"""
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
    d = start
    for _ in range(8):
        if os.path.isdir(os.path.join(d, ".claude")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.getcwd()


# DK_HOME wins over everything: a machine-wide install (install.sh --global)
# points every project at one memory, because a mistake Claude makes is about
# how it behaves, not about which repo it is in. Unset = per-project, as before.
ROOT = (os.environ.get("DK_HOME") or os.environ.get("CLAUDE_PROJECT_DIR")
        or find_root(SCRIPT_DIR))
MEM = os.path.join(ROOT, ".claude", "memory")
RULES = os.path.join(MEM, "dk_rules.md")
SESSION = (os.environ.get("DK_SESSION_ID", "") or "")[:16] or "nosession"
# Scoped per session: an unscoped file meant one chat's verdict was injected
# into another's under the header "relevant to what you are doing right now".
# Concurrent chats on one repo is the normal case, not an edge case.
ACTIVE = os.path.join(MEM, f".dk_active.{SESSION}")
LOCK = os.path.join(MEM, ".dk-watch.lock")
STATE = os.path.join(MEM, ".dk_state")

BACKEND = os.environ.get("DK_BACKEND", "anthropic").strip().lower()
# Thinking models (qwen3, deepseek-r1) spend the budget on reasoning and
# return EMPTY content - a silent total failure, not a degraded one. Two
# defences, because the env var only helps someone who knew to set it:
# "none" turns reasoning off where the server supports it, and the budget is
# no longer knife-edge. The reply is a few dozen tokens of JSON; 400 was an
# arbitrary cap that left no room for any preamble at all.
REASONING_EFFORT = os.environ.get("DK_REASONING_EFFORT", "").strip()
APPROVAL_ON = os.environ.get("DK_APPROVAL", "0").strip().lower() in (
    "1", "true", "yes", "on", "auto")
MAX_TOKENS = int(os.environ.get("DK_WATCH_MAX_TOKENS", "2000"))
API_URL = os.environ.get(
    "DK_API_URL",
    "http://localhost:11434/v1/chat/completions" if BACKEND == "openai"
    else "https://api.anthropic.com/v1/messages")
WATCH_MODELS = [m.strip() for m in os.environ.get(
    "DK_WATCH_MODELS",
    os.environ.get("DK_MODELS", "qwen2.5:14b-instruct") if BACKEND == "openai"
    else "claude-haiku-4-5-20251001").split(",") if m.strip()]
TURNS = int(os.environ.get("DK_WATCH_TURNS", "6"))
TIMEOUT = int(os.environ.get("DK_WATCH_TIMEOUT", "120"))
MAX_ACTIVE = 3

ITEM_RE = re.compile(r"^### .*?(?=^### |^## |\Z)", re.M | re.S)

# Why the model calls failed, in order. Empty means they did not fail.
LAST_ERROR = []


def log(msg):
    """The watcher used to fail in total silence: nine return-0 paths, no
    log, no state. A dead watcher looks exactly like a quiet one."""
    d = os.environ.get("DK_LOG_DIR")
    if not d:
        mac = os.path.expanduser("~/Library/Logs")
        d = mac if os.path.isdir(mac) else os.path.expanduser("~/.claude/logs")
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "dk_watch.log"), "a", encoding="utf-8") as f:
            f.write(f"{__import__('datetime').datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except OSError:
        pass


def mark(ok, why=""):
    """Record health in .dk_state so dk_recall.sh can announce a broken
    watcher, the same way it announces a broken consolidator."""
    st = {}
    try:
        with open(STATE, encoding="utf-8") as f:
            st = dict(l.rstrip("\n").split("=", 1) for l in f if "=" in l)
    except OSError:
        pass
    now = str(int(time.time()))
    st["watch_last_attempt_epoch"] = now
    if ok:
        st["watch_last_ok_epoch"] = now
        st["watch_consecutive_failed"] = "0"
    else:
        st["watch_consecutive_failed"] = str(
            int(st.get("watch_consecutive_failed", "0") or 0) + 1)
        log(f"FAILED: {why}")
    try:
        fd, tmp = tempfile.mkstemp(dir=MEM, prefix=".dk-state-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("".join(f"{k}={v}\n" for k, v in st.items()))
        os.replace(tmp, STATE)
    except OSError:
        pass


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


def field(block, name):
    m = re.search(r"\*\*" + name + r":\*\*\s*(.+)", block)
    return m.group(1).strip() if m else ""


def load_rules():
    """Selectable rules: approved (or unmarked), never Retired."""
    try:
        with open(RULES, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return []
    rm = re.search(r"^## Retired\s*$", text, re.M)   # heading, not substring
    retired_at = rm.start() if rm else -1
    out = []
    for m in ITEM_RE.finditer(text):
        if retired_at >= 0 and m.start() > retired_at:
            continue
        block = m.group(0)
        # Absent Status used to mean "approved", so a malformed or truncated
        # item silently walked through the approval gate. In approval mode,
        # absent means NOT approved.
        status = field(block, "Status")
        if not status:
            status = "pending" if APPROVAL_ON else "approved"
        if not status.startswith("approved"):
            continue          # pending items never steer
        reminder = field(block, "Reminder line")
        if not reminder:
            continue
        out.append({
            "id": len(out) + 1,
            "heading": block.splitlines()[0].lstrip("# ").strip(),
            "looks_like": field(block, "What it looks like"),
            "reminder": reminder,
            "evidence": field(block, "Evidence"),
        })
    return out


def transcript_windows(path, n, whole=False):
    """The recent window, or - for backfill - every window of a whole
    transcript so history is covered rather than sampled."""
    msgs = _read_messages(path)
    if not whole:
        return msgs[-n:]
    cap = int(os.environ.get("DK_BACKFILL_WINDOWS", "40"))
    return [msgs[i:i + n] for i in range(0, len(msgs), n)][:cap] or []


def _read_messages(path):
    """Recent messages with ids - what actually just happened. Ids matter:
    the model points at a message, it never retypes one."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []
    msgs = []
    for line in lines:
        try:
            e = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        # isMeta = harness-injected user turn (skill body, image-paste metadata,
        # Stop-hook feedback). Reading it as the user skews the judgement.
        if (e.get("isSidechain") or e.get("isMeta")
                or e.get("type") not in ("user", "assistant")):
            continue
        c = (e.get("message") or {}).get("content")
        if isinstance(c, str):
            text = c
        elif isinstance(c, list):
            text = "\n".join(b.get("text", "") for b in c
                             if isinstance(b, dict) and b.get("type") == "text")
        else:
            continue
        if not text.strip() or any(m in text for m in (
                # This list is now the ONLY filter. dk_capture.sh carried the
                # full one and was deleted; two markers did not survive the
                # move, and a real run mined
                # "<local-command-stdout>Set model to ...</local-command-stdout>"
                # as if the user had said it. Anything added here must stay here.
                "<command-name>", "<local-command-caveat>",
                "<local-command-stdout>", "<task-notification>",
                "<system-reminder>", "<wake reason=", "[SYSTEM NOTIFICATION",
                "<untrusted_external_data")):
            continue
        msgs.append({"uuid": e.get("uuid", ""), "role": e["type"],
                     "text": text.strip()[:1500],
                     "cwd": e.get("cwd", ""),
                     "ts": e.get("timestamp", "")})
    return msgs


PROMPT = """You are the relevance layer of a self-steering system for a \
coding agent. Below are known failure modes and standing rules for this \
agent (each with an id), and the last few messages of a live conversation.

Decide which rules are LIVE RIGHT NOW - not which are true in general, but \
which this specific situation is about to run into, judging from what the \
agent just said and what the user just asked. Examples of a live rule: the \
agent is about to claim something is finished (a done-claim rule is live); \
the agent is about to build something new (a check-what-exists rule is \
live); the agent gave a shallow answer to a research question (a \
thoroughness rule is live).

Be strict. Most turns have NO live rule - returning an empty list is the \
correct and common answer. Never select a rule just because it is important \
in general. At most {max_active}.

If you see the agent actively about to repeat one of these failures, you may \
add a single short "alert": one blunt present-tense sentence naming what it \
is about to do wrong. No alert unless it is specific to this conversation.

SECOND JOB - capture. The phrase list that feeds this system only matches \
blunt corrections ("you didn't run the tests"). Measured against real \
transcripts it catches almost nothing, because people steer by REDIRECTING, \
not by announcing a correction. So: look at the [user] messages below and \
report any where the user steered the agent - rejected an approach, \
redirected it, expressed dissatisfaction however mildly ("bit lame", "that's \
overcomplicated", "simplify"), pointed out something missed, or stated a \
preference or rule for future work. Casual, sarcastic and indirect wording \
all count. Report the message id and a kind.

Do NOT report: ordinary new requests, questions, approvals, or the user \
simply moving on to the next task. A question that implies the work is \
wrong ("why is this so slow?") IS steering; a question seeking information \
is not.

Also report any [assistant] message where the AGENT corrected ITSELF - said \
its own approach was wrong, that something did not work, that it had made a \
mistake, or that it needed to start over. Mark these with source "self". \
This is weaker evidence than a human correction: a plan changing course is \
not always a failure worth remembering, so only report a clear admission of \
a mistake, not ordinary iteration.

Reply with ONLY a JSON object, no prose, no code fences:
{{"active": [ids], "alert": "..." or null,
 "steering": [{{"id": "<message id>", "source": "human|self",
               "kind": "correction|instruction|preference"}}]}}

=== RULES ===
{rules}

=== RECENT CONVERSATION ===
{convo}
"""



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

def call_model(key, prompt):
    if BACKEND == "cli":
        return call_cli(prompt, WATCH_MODELS or [""], TIMEOUT)
    for model in WATCH_MODELS:
        if BACKEND == "openai":
            body = {"model": model, "max_tokens": MAX_TOKENS, "temperature": 0,
                    "stream": False,
                    "messages": [{"role": "user", "content": prompt}]}
            if REASONING_EFFORT:
                body["reasoning_effort"] = REASONING_EFFORT
            headers = {"content-type": "application/json"}
            if key:
                headers["authorization"] = f"Bearer {key}"
        else:
            body = {"model": model, "max_tokens": MAX_TOKENS, "temperature": 0,
                    "messages": [{"role": "user", "content": prompt}]}
            headers = {"content-type": "application/json", "x-api-key": key,
                       "anthropic-version": "2023-06-01"}
        req = urllib.request.Request(
            API_URL, data=json.dumps(body).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if BACKEND == "openai":
                ch = data.get("choices") or []
                text = ch[0].get("message", {}).get("content", "") if ch else ""
            else:
                text = "".join(b.get("text", "") for b in data.get("content", [])
                               if isinstance(b, dict) and b.get("type") == "text")
            if text.strip():
                return text
        except urllib.error.HTTPError as e:
            # 401 and 404 are configuration errors, not transient ones, and
            # they used to be swallowed here: the run reported "found nothing",
            # which reads as "your history is clean". An auth rejection is not
            # an empty result.
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            LAST_ERROR.append(f"{model}: HTTP {e.code} {e.reason} {detail}".strip())
            continue
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            LAST_ERROR.append(f"{model}: {type(e).__name__}: {e}"[:300])
            continue
    return None


def write_steering(selection, convo, raw_path, memlog):
    """Log steering the model spotted. It supplies an ID and a kind; the
    TEXT is copied verbatim from the transcript, so the model can no more
    invent what the user said than it can invent a rule."""
    # A correction without what it was correcting is unusable later - the
    # consolidator cannot tell a real failure mode from a passing remark.
    # So carry the exchange that led up to it, not just the words.
    # Both roles are addressable: a user message is a correction OF the agent,
    # an assistant message may be the agent correcting ITSELF. The second used
    # to be found by a separate phrase list in dk_capture.sh; that list found
    # nothing and gated the whole system, so it was deleted and its job moved
    # here.
    by_id = {}
    for i, m in enumerate(convo):
        lead = []
        for prev in convo[max(0, i - 3):i]:
            lead.append(f'[{prev["role"]}] {prev["text"][:900]}')
        by_id[m["uuid"]] = dict(m, lead_up="\n\n".join(lead)[-2400:])
    try:
        with open(raw_path, encoding="utf-8", errors="replace") as f:
            seen = f.read()
    except OSError:
        seen = ""
    now = __import__("datetime").datetime.now().astimezone().isoformat(timespec="seconds")
    new = []
    for item in selection[:5]:
        if not isinstance(item, dict):
            continue
        uid = str(item.get("id", ""))
        msg = by_id.get(uid)
        if not msg or f'"{uid}"' in seen:
            continue
        kind = str(item.get("kind", "correction"))[:40]
        # Trust the message's real role over the model's label: if it points
        # at an assistant message it is a self-correction whatever it claims.
        src = "self" if msg["role"] == "assistant" else "human"
        new.append({
            "ts": msg["ts"] or now,
            "session": "",
            "uuid": uid,
            "source": src,
            "kind": kind,
            "signal": "semantic",      # found by reading, not by phrase match
            "text": msg["text"][:600],
            "user_verbatim": msg["text"][:600],
            "assistant_context": msg.get("lead_up", ""),
            "cwd": msg["cwd"],
        })
    if not new:
        return 0
    lock = os.path.join(MEM, ".dk.lock")     # the capture hook's lock
    for _ in range(20):
        try:
            os.mkdir(lock)
            break
        except FileExistsError:
            try:      # every other writer reclaims a stale lock; this didn't,
                      # so one orphaned lock silently dropped every entry
                if time.time() - os.stat(lock).st_mtime > 30:
                    os.rmdir(lock)
                    continue
            except OSError:
                pass
            time.sleep(0.25)
        except OSError:
            return 0
    else:
        log("gave up on .dk.lock - entries dropped")
        return 0
    try:
        with open(raw_path, "a", encoding="utf-8") as f:
            for e in new:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        with open(memlog, "a", encoding="utf-8") as f:
            f.write(f'{__import__("datetime").date.today().isoformat()} '
                    f'| dk-capture | {len(new)} semantic '
                    f'{"entry" if len(new) == 1 else "entries"} (read, not matched)\n')
    except OSError:
        pass
    finally:
        try:
            os.rmdir(lock)
        except OSError:
            pass
    return len(new)


def parse_selection(text, rules):
    """Strictly: ids that exist, an alert that is one short line."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    valid = {r["id"] for r in rules}
    active = [i for i in data.get("active", []) if isinstance(i, int) and i in valid]
    alert = data.get("alert")
    if not isinstance(alert, str) or not alert.strip() or len(alert) > 200:
        alert = None
    steering = data.get("steering")
    if not isinstance(steering, list):
        steering = []
    return active[:MAX_ACTIVE], alert, steering


def render(active_ids, alert, rules):
    """Render the live items as short episodes, not one-liners.

    When the note was injected on EVERY prompt it had to be tiny or it
    became noise. It is now injected only when something is actually live -
    usually nothing at all - so the budget is better spent making the few
    items that do appear carry their evidence: what it looks like, what to
    do, and the words that earned the rule. A bare imperative is easy to
    skim past; the episode behind it is not."""
    by_id = {r["id"]: r for r in rules}
    parts = []
    if alert:
        parts.append(f"! {alert.strip()}")
    for i in active_ids:
        r = by_id[i]
        block = [f"* {r['heading']}"]
        if r.get("looks_like"):
            block.append(f"    what it looks like: {r['looks_like'][:240]}")
        block.append(f"    so: {r['reminder']}")
        if r.get("evidence"):
            block.append(f"    earned by: {r['evidence'][:240]}")
        parts.append("\n".join(block))
    if not parts:
        return ""      # nothing live: inject nothing at all
    return ("<self-steering>\nRelevant to what you are doing right now:\n"
            + "\n".join(parts) + "\n</self-steering>\n")


def atomic_write(path, text):
    fd, tmp = tempfile.mkstemp(dir=MEM, prefix=".dk-active-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def main():
    # --capture-only: mine a historical transcript for steering the phrase
    # list cannot see, without writing a live selection. Backfill used to run
    # phrase-matching alone, which measured 0 real corrections found in a
    # 46-message session - so mining history produced almost nothing.
    argv = [a for a in sys.argv[1:] if a != "--capture-only"]
    capture_only = "--capture-only" in sys.argv
    if not capture_only and os.environ.get(
            "DK_WATCH", "1").strip().lower() in ("0", "false", "no", "off"):
        return 0
    transcript = argv[0] if argv else os.environ.get("DK_TRANSCRIPT", "")
    if not transcript or not os.path.isfile(transcript) or not os.path.isdir(MEM):
        return 0
    key = read_key()
    # Neither a local server nor the `claude` CLI needs a key.
    if not key and BACKEND not in ("openai", "cli"):
        return 0                       # hosted backend with no key: no-op
    try:
        os.mkdir(LOCK)                 # one watcher at a time; no waiting
    except OSError:
        try:
            if time.time() - os.stat(LOCK).st_mtime > 300:
                os.rmdir(LOCK); os.mkdir(LOCK)
            else:
                return 0
        except OSError:
            return 0
    try:
        # No rules yet (fresh install) is NOT a reason to bail: the second
        # job - noticing steering the phrase list misses - is exactly how the
        # rules file gets its first entries. Only relevance needs rules.
        rules = [] if capture_only else load_rules()
        # History is mined in windows so a long session is fully covered,
        # not just its last few turns.
        windows = ([transcript_windows(transcript, TURNS)] if not capture_only
                   else transcript_windows(transcript, TURNS, whole=True))
        convo = windows[0] if not capture_only else None
        if not capture_only and not convo:
            return 0
        if capture_only:
            total = 0
            for w in windows:
                text = call_model(key, PROMPT.format(
                    max_active=MAX_ACTIVE, rules="(none - capture only)",
                    convo="\n\n".join(
                        f'[{m["role"]} id={m["uuid"]}] {m["text"]}' for m in w)))
                if not text:
                    continue
                parsed = parse_selection(text, [])
                if parsed and parsed[2]:
                    total += write_steering(parsed[2], w,
                                            os.path.join(MEM, "dk.jsonl"),
                                            os.path.join(MEM, "log.md"))
            print(f"semantic: {total} entries from {len(windows)} windows")
            return 0
        text = call_model(key, PROMPT.format(
            max_active=MAX_ACTIVE,
            rules=("\n".join(f'{r["id"]}. {r["heading"]} - {r["looks_like"]}'
                             for r in rules) or "(none yet - skip the first job)"),
            convo="\n\n".join(
                f'[{m["role"]} id={m["uuid"]}] {m["text"]}' for m in convo)))
        if not text:
            why = "; ".join(LAST_ERROR) if LAST_ERROR else (
                "every model returned empty content - a thinking model with "
                "too small a token budget does this")
            mark(False, f"no usable content from any model "
                        f"({','.join(WATCH_MODELS)} at {API_URL}): {why}")
            return 0
        parsed = parse_selection(text, rules)
        if parsed is None:
            mark(False, f"unparseable response: {text[:200]!r}")
            return 0                   # malformed: leave the old file to expire
        # Write whenever there is anything to say, or when a previous
        # selection needs clearing. Gating this on `rules` alone threw away
        # the alert - which is generated from the conversation and needs no
        # rules at all - so a project with nothing approved yet could never
        # be warned about anything.
        if rules or parsed[1] or os.path.exists(ACTIVE):
            atomic_write(ACTIVE, render(parsed[0], parsed[1], rules))
        n = write_steering(parsed[2], convo, os.path.join(MEM, "dk.jsonl"),
                           os.path.join(MEM, "log.md")) if parsed[2] else 0
        mark(True)
        log(f"ok: {len(parsed[0])} live, {n} captured, session={SESSION}")
        return 0
    finally:
        try:
            os.rmdir(LOCK)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
