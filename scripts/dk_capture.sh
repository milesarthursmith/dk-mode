#!/usr/bin/env bash
# dk_capture.sh - Stop hook: capture steering-worthy user statements.
#
# Part of dk-mode (capture -> consolidate -> recall). After each turn,
# scan the transcript for things the user said that should stick:
# corrections of Claude ("you didn't run the tests") and standing
# instructions/preferences ("from now on always X"). Save the user's
# VERBATIM words to .claude/memory/dk.jsonl - deliberately no LLM here:
# asking the model to summarise its own mistake is asking the least reliable
# narrator in the room, and a per-turn API dependency is a per-turn failure
# point. The periodic consolidator (dk_consolidate.py) does all
# interpretation in batch.
#
# Also the engine of dk_backfill.sh: with DK_SCAN_LINES=0 it scans a
# WHOLE transcript instead of the recent tail, so historical sessions can be
# mined through this exact same detection logic (never a second copy of the
# patterns - a duplicated definition is how detection silently drifts).
#
# What this script deliberately does NOT do:
# - Never blocks or delays the turn: fast grep guard first, unconditional
#   exit 0 on every path, lock skip-not-block.
# - Never touches any file it doesn't own: only dk.jsonl, its own lock,
#   and one heartbeat line in the memory log.
# - Never writes a heartbeat unless it actually saved an entry - the
#   heartbeat means "captured something", not "ran".
#
# The staleness tripwire in dk_recall.sh is the guard against this script
# silently dying: if nothing is captured for 21+ days, every prompt says so.
#
# Config (all optional):
#   DK_SCAN_LINES  how many recent transcript lines to consider
#                     (default 150; 0 = the whole transcript, for backfill)
#
# CONCURRENCY: takes .claude/memory/.dk.lock (atomic mkdir; skip-not-block;
# 30s stale reclaim). stat is called GNU-form first: on Linux `stat -f %m`
# does NOT fail, it prints filesystem info, so BSD-first ordering silently
# breaks there.
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MEM="$ROOT/.claude/memory"
RAW="$MEM/dk.jsonl"
MEMLOG="$MEM/log.md"
LOCK="$MEM/.dk.lock"
SCAN_LINES="${DK_SCAN_LINES:-150}"

[ -d "$MEM" ] || exit 0

# Hook payload arrives on stdin as JSON. Grab transcript_path + session_id
# with grep/sed - no jq dependency, no python startup on the fast path.
PAYLOAD="$(cat 2>/dev/null || true)"
TRANSCRIPT="$(printf '%s' "$PAYLOAD" | grep -o '"transcript_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*:[[:space:]]*"//; s/"$//' || true)"
SESSION="$(printf '%s' "$PAYLOAD" | grep -o '"session_id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*:[[:space:]]*"//; s/"$//' || true)"
[ -n "$TRANSCRIPT" ] && [ -r "$TRANSCRIPT" ] || exit 0

# --- relevance layer (FIRST - before any guard can exit) --------------------
# This MUST run on EVERY turn. It is both the relevance layer and the real
# miner, and it is the only part that finds how people actually steer
# ("bit lame", "simplify"). It used to sit at the BOTTOM of this script,
# below the phrase guard - so it only ever ran on turns where the phrase list
# matched, which is almost never, and when it did the match was usually noise.
# The whole system was gated behind its own weakest component. Backgrounded
# and detached, so turn end is never delayed by a model call; a silent no-op
# when no backend is configured. Skipped only during backfill (SCAN_LINES=0),
# where there is no "right now" to be relevant to.
if [ "$SCAN_LINES" != "0" ] && [ "${DK_WATCH:-1}" != "0" ]; then
  nohup python3 "$(cd "$(dirname "$0")" && pwd)/dk_watch.py" "$TRANSCRIPT" \
    >/dev/null 2>&1 &
  disown 2>/dev/null || true
fi

# Fast guard: any trigger phrase anywhere in the scanned region? This is
# loose on purpose (matches assistant text too); the python step below
# applies the precise, user-message-only matching. Apostrophes are matched
# as `.` so both ' and the curly variant hit. No hit -> done in single-digit
# milliseconds, which is the common case on live turns.
GUARD_RE="nope|wrong|i said|i told you|already told|already said|already asked|i asked you|not what i asked|that.s not what|why did|why didn.t|why would you|why are you|why aren.t you|you didn.t|you did not|you missed|you skipped|you ignored|you were supposed|you keep doing|did you actually|did you even|did you really|lazy|half.assed|sloppy|token gesture|still wrong|still broken|still doesn.t|still not fixed|read it properly|check again|try again|/challenge|remember th|for future reference|for next time|note for the future|from now on|going forward|in future|should always|should never|always do|always use|always check|never do|never use|i prefer|i.d rather|i like it when|rule:|new rule|hard rule|don.t ever|stop doing|i was wrong|i made a mistake|my mistake|correction:|that didn.t work|that was wrong|i should have |scratch that|let me correct|i got that wrong|actually, that"
if [ "$SCAN_LINES" = "0" ]; then
  grep -qiE "$GUARD_RE" "$TRANSCRIPT" 2>/dev/null || exit 0
else
  tail -c 200000 "$TRANSCRIPT" 2>/dev/null | grep -qiE "$GUARD_RE" || exit 0
fi

# --- lock ------------------------------------------------------------------
# mkdir is atomic. Skip-not-block: missing one capture cycle is harmless
# (the transcript is still there next turn; uuid dedupe makes retries safe).
acquired=0
for _ in $(seq 1 40); do
  if mkdir "$LOCK" 2>/dev/null; then acquired=1; break; fi
  if [ -d "$LOCK" ]; then
    mt=$(stat -c %Y "$LOCK" 2>/dev/null || stat -f %m "$LOCK" 2>/dev/null || echo 0)
    age=$(( $(date +%s) - mt ))
    [ "$age" -gt 30 ] && rmdir "$LOCK" 2>/dev/null || true
  fi
  sleep 0.25
done
[ "$acquired" -eq 1 ] || exit 0
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

TRANSCRIPT="$TRANSCRIPT" RAW="$RAW" MEMLOG="$MEMLOG" SESSION="$SESSION" SCAN_LINES="$SCAN_LINES" python3 <<'PY' || true
import json, os, re, datetime

transcript = os.environ["TRANSCRIPT"]
raw_path   = os.environ["RAW"]
memlog     = os.environ["MEMLOG"]
session    = os.environ.get("SESSION", "")
scan_lines = int(os.environ.get("SCAN_LINES", "150") or 0)

# Precise per-kind patterns, applied only to real user message text.
# `.` in place of apostrophes matches both ' and the curly variant.
CORRECTION = [
    r"(?:^|[.!?]\s)(?:no[,.]\s|nope\b|wrong[,.\s])",
    r"\bi (?:said|told you|already (?:told|said|asked)|asked (?:you )?(?:for|to))\b",
    r"\bthat.s not what\b", r"\bnot what i asked\b",
    r"\bwhy (?:did|didn.t|would|are|aren.t) you\b",
    r"\byou (?:didn.t|did not|missed|skipped|ignored|were supposed|keep doing)\b",
    r"\bdid you (?:actually|even|really)\b",
    r"\b(?:lazy|half.assed|sloppy|token gesture)\b",
    r"\bstill (?:wrong|broken|doesn.t|not fixed)\b",
    r"\bread it properly\b", r"\bcheck again\b", r"\btry again\b",
    r"/challenge\b",
]
INSTRUCTION = [
    r"\bremember (?:this|that)\b", r"\bfor future reference\b",
    r"\bfor next time\b", r"\bnote for the future\b",
    r"\bfrom now on\b", r"\bgoing forward\b", r"\bin future\b",
    r"\byou should (?:always|never)\b",
    r"\balways (?:do|use|check)\b", r"\bnever (?:do|use)\b",
    r"\bi prefer\b", r"\bi.d rather\b", r"\bi like it when\b",
    r"\brule:", r"\bnew rule\b", r"\bhard rule\b",
    r"\bdon.t ever\b", r"\bstop doing\b",
]
# Steering does not only come from a human. In an autonomous session
# (a routine, a background agent, a subagent chat) nobody is there to say
# "you didn't run the tests" - but the agent still visibly corrects itself,
# and that is the same signal from a different source. Captured as
# source=self so the consolidator can weigh it accordingly. Programmatic
# steering (a verifier, a test gate, a review subagent) comes in through
# dk_signal.py instead of being guessed at here.
SELF_CORRECTION = [
    r"\bi was wrong\b", r"\bi made a mistake\b", r"\bmy mistake\b",
    r"^correction:", r"\bthat didn.t work\b", r"\bthat was wrong\b",
    r"\bi got that wrong\b", r"\bscratch that\b", r"\blet me correct\b",
    r"\bi should have (?:done|run|ran|checked|used|read|asked|verified|tested|caught|noticed)\b",
    r"\bactually, that.s (?:wrong|not right)\b",
]

CORRECTION = [re.compile(p, re.I) for p in CORRECTION]
INSTRUCTION = [re.compile(p, re.I) for p in INSTRUCTION]
SELF_CORRECTION = [re.compile(p, re.I | re.M) for p in SELF_CORRECTION]

def text_of(msg):
    """Plain text of a transcript message; '' for tool_result-only content."""
    content = (msg or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""

# Read the scan region of the transcript, tolerating corrupt lines.
try:
    with open(transcript, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
        if scan_lines > 0:
            lines = lines[-scan_lines:]
except OSError:
    raise SystemExit(0)

entries = []
for line in lines:
    try:
        entries.append(json.loads(line))
    except (json.JSONDecodeError, ValueError):
        continue

# uuids already captured (dedupe across re-runs and across backfill sweeps).
seen = set()
try:
    with open(raw_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.search(r'"uuid"\s*:\s*"([^"]+)"', line)
            if m:
                seen.add(m.group(1))
except OSError:
    pass

now_iso = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
new = []
last_assistant = ""
for e in entries:
    etype = e.get("type")
    if etype == "assistant":
        t = text_of(e.get("message"))
        if not t:
            continue
        prior = last_assistant
        last_assistant = t
        if e.get("isSidechain"):
            continue
        uuid = e.get("uuid", "")
        if not uuid or uuid in seen:
            continue
        hit = None
        for rx in SELF_CORRECTION:
            m = rx.search(t)
            if m:
                hit = m.group(0).strip()
                break
        if not hit:
            continue
        seen.add(uuid)
        new.append({
            "ts": e.get("timestamp") or now_iso,
            "session": session[:8] if session else "",
            "uuid": uuid,
            "source": "self",          # the agent steered itself
            "kind": "self-correction",
            "signal": hit,
            "text": t[:600],
            "assistant_context": prior[-500:],
            "cwd": e.get("cwd", ""),
        })
        continue
    # isMeta marks harness-injected user-role turns: a skill body loaded by a
    # slash command, image-paste metadata, "Continue from where you left off",
    # Stop-hook feedback. The role says user; the human did not type it.
    if etype != "user" or e.get("isSidechain") or e.get("isMeta"):
        continue
    t = text_of(e.get("message"))
    if not t:
        continue
    # Not the user talking: slash commands, local-command echoes, and
    # harness-generated pseudo-user messages (subagent completions, system
    # reminders, wake events). Measured against a real transcript, these
    # were the ONLY things the phrase list matched - trigger words quoted
    # inside tool output, attributed to the user.
    if any(marker in t for marker in (
            "<command-name>", "<local-command-caveat>", "<local-command-stdout>",
            "<task-notification>", "<system-reminder>", "<wake reason=",
            "[SYSTEM NOTIFICATION", "<untrusted_external_data")):
        continue
    uuid = e.get("uuid", "")
    if not uuid or uuid in seen:
        continue
    kind = signal = None
    for rx in CORRECTION:
        m = rx.search(t)
        if m:
            kind, signal = "correction", m.group(0).strip()
            break
    if not kind:
        for rx in INSTRUCTION:
            m = rx.search(t)
            if m:
                kind, signal = "instruction", m.group(0).strip()
                break
    if not kind:
        continue
    seen.add(uuid)
    new.append({
        # Prefer the transcript's own timestamp (real time of the message,
        # which matters for backfilled history); fall back to capture time.
        "ts": e.get("timestamp") or now_iso,
        "session": session[:8] if session else "",
        "uuid": uuid,
        "source": "human",
        "kind": kind,
        "signal": signal,
        "text": t[:600],
        "user_verbatim": t[:600],   # kept: existing data/tests use this name
        "assistant_context": last_assistant[-500:],
        "cwd": e.get("cwd", ""),
    })

if new:
    with open(raw_path, "a", encoding="utf-8") as f:
        for entry in new:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    today = datetime.date.today().isoformat()
    sig = new[0]["signal"][:40]
    with open(memlog, "a", encoding="utf-8") as f:
        f.write(f'{today} | dk-capture | {len(new)} '
                f'{"entry" if len(new) == 1 else "entries"} '
                f'(signal: "{sig}") session {session[:8]}\n')
PY

exit 0
