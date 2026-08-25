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
shared DK_BACKEND / DK_API_URL / DK_KEY_FILE / ANTHROPIC_API_KEY.
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


ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or find_root(SCRIPT_DIR)
MEM = os.path.join(ROOT, ".claude", "memory")
RULES = os.path.join(MEM, "dk_rules.md")
ACTIVE = os.path.join(MEM, ".dk_active")
LOCK = os.path.join(MEM, ".dk-watch.lock")

BACKEND = os.environ.get("DK_BACKEND", "anthropic").strip().lower()
# Thinking models (qwen3, deepseek-r1) spend the budget on reasoning and
# return EMPTY content - a silent total failure, not a degraded one. Two
# defences, because the env var only helps someone who knew to set it:
# "none" turns reasoning off where the server supports it, and the budget is
# no longer knife-edge. The reply is a few dozen tokens of JSON; 400 was an
# arbitrary cap that left no room for any preamble at all.
REASONING_EFFORT = os.environ.get("DK_REASONING_EFFORT", "").strip()
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
    retired_at = text.find("## Retired")
    out = []
    for m in ITEM_RE.finditer(text):
        if retired_at >= 0 and m.start() > retired_at:
            continue
        block = m.group(0)
        status = field(block, "Status") or "approved"
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


def transcript_tail(path, n):
    """Recent messages with ids - what actually just happened. Ids matter:
    the model points at a message, it never retypes one."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-400:]
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
                "<command-name>", "<local-command-caveat>", "<task-notification>",
                "<system-reminder>", "<wake reason=", "[SYSTEM NOTIFICATION")):
            continue
        msgs.append({"uuid": e.get("uuid", ""), "role": e["type"],
                     "text": text.strip()[:1500],
                     "cwd": e.get("cwd", ""),
                     "ts": e.get("timestamp", "")})
    return msgs[-n:]


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

Reply with ONLY a JSON object, no prose, no code fences:
{{"active": [ids], "alert": "..." or null,
 "steering": [{{"id": "<message id>", "kind": "correction|instruction|preference"}}]}}

=== RULES ===
{rules}

=== RECENT CONVERSATION ===
{convo}
"""


def call_model(key, prompt):
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
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                OSError, ValueError):
            continue
    return None


def write_steering(selection, convo, raw_path, memlog):
    """Log steering the model spotted. It supplies an ID and a kind; the
    TEXT is copied verbatim from the transcript, so the model can no more
    invent what the user said than it can invent a rule."""
    # A correction without what it was correcting is unusable later - the
    # consolidator cannot tell a real failure mode from a passing remark.
    # So carry the exchange that led up to it, not just the words.
    by_id = {}
    for i, m in enumerate(convo):
        if m["role"] != "user":
            continue
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
        new.append({
            "ts": msg["ts"] or now,
            "session": "",
            "uuid": uid,
            "source": "human",
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
            time.sleep(0.25)
        except OSError:
            return 0
    else:
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
    if os.environ.get("DK_WATCH", "1").strip().lower() in ("0", "false", "no", "off"):
        return 0
    transcript = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DK_TRANSCRIPT", "")
    if not transcript or not os.path.isfile(transcript) or not os.path.isdir(MEM):
        return 0
    key = read_key()
    if not key and BACKEND != "openai":
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
        rules = load_rules()
        convo = transcript_tail(transcript, TURNS)
        if not convo:
            return 0
        text = call_model(key, PROMPT.format(
            max_active=MAX_ACTIVE,
            rules=("\n".join(f'{r["id"]}. {r["heading"]} - {r["looks_like"]}'
                             for r in rules) or "(none yet - skip the first job)"),
            convo="\n\n".join(
                f'[{m["role"]} id={m["uuid"]}] {m["text"]}' for m in convo)))
        if not text:
            return 0
        parsed = parse_selection(text, rules)
        if parsed is None:
            return 0                   # malformed: leave the old file to expire
        if rules:
            atomic_write(ACTIVE, render(parsed[0], parsed[1], rules))
        if parsed[2]:
            write_steering(parsed[2], convo,
                           os.path.join(MEM, "dk.jsonl"),
                           os.path.join(MEM, "log.md"))
        return 0
    finally:
        try:
            os.rmdir(LOCK)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
