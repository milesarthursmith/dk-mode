#!/usr/bin/env bash
# dk_recall.sh - UserPromptSubmit hook: force distilled steering into
# every prompt, and kick the periodic consolidation when due.
#
# Part of dk-mode (capture -> consolidate -> recall). Whatever this
# prints is added to the prompt Claude reads - that is the whole mechanism:
# recall is forced, not left to a memory tool call the model may not make.
# (The failure this exists for: the model cannot know to look up "times I
# was lazy" BEFORE being lazy - self-assessment of an in-progress failure is
# itself the failing capability. So the reminder is imposed from outside.)
# The note is pre-rendered by dk_consolidate.py into the inject block of
# dk_rules.md, so this script is greps and seds only - no LLM, no python
# on the hot path.
#
# Also the watchdog for the rest of the loop, because a notification nobody
# reads is not an alarm:
# - 21+ days with no captures -> say so in-context (guards against the
#   capture hook silently dying).
# - 3 consecutive FAILED consolidations -> "broken, not quiet" line.
#
# Deliberately NOT done here:
# - No matching of the prompt text against memories in v1: the failure
#   modes worth warning about ("about to claim done") do not correlate with
#   the user's wording, so keyword matching is guessing dressed as
#   precision. Forward path: the consolidator can render extra keyword-gated
#   lines into the inject block later; this script never needs to change.
# - Never blocks: every path exits 0.
#
# Config (all optional):
#   DK_INTERVAL   consolidation cadence: Nd / Nh / Nm, bare seconds, or
#                    0|per-turn|always (always due). Default 7d.
#   ANTHROPIC_API_KEY / DK_KEY_FILE
#                    key source for the consolidator; if neither resolves,
#                    the kick is skipped silently (capture and recall still
#                    work - e.g. cloud sessions with no key).
#
# Scheduling state lives in .claude/memory/.dk_state (flat key=value,
# written atomically by dk_consolidate.py). The memory log keeps a
# human-readable heartbeat line per run but is never parsed for scheduling.
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MEM="$ROOT/.claude/memory"
RULES="$MEM/dk_rules.md"
RAW="$MEM/dk.jsonl"
STATE="$MEM/.dk_state"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 1. The note: everything between the inject markers, markers stripped.
#    File or block missing -> print nothing (silent no-op).
if [ -r "$RULES" ]; then
  sed -n '/<!-- inject:start -->/,/<!-- inject:end -->/p' "$RULES" 2>/dev/null \
    | grep -v -- '<!-- inject:' || true
fi

# Portable mtime. GNU form FIRST: on Linux `stat -f %m` does not fail, it
# prints filesystem info; on macOS `-c` errors and `-f %m` runs.
mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo 0; }

state_get() { grep "^$1=" "$STATE" 2>/dev/null | head -1 | cut -d= -f2 || true; }

# 2. Staleness tripwire: capture hook silently dead?
if [ -f "$RAW" ] && [ -r "$RULES" ]; then
  mt=$(mtime "$RAW")
  if [ "$mt" -gt 0 ]; then
    age_days=$(( ( $(date +%s) - mt ) / 86400 ))
    if [ "$age_days" -ge 21 ]; then
      echo "(dk-mode: no captures in ${age_days} days - verify the dk_capture Stop hook is firing)"
    fi
  fi
fi

# 2b. Approval nudge: proposed items awaiting human review are held OUT of
#     the note above; one line makes them impossible to forget about.
if [ -r "$RULES" ]; then
  pending_n=$(grep -c '\*\*Status:\*\* pending' "$RULES" 2>/dev/null || true)
  [ -n "$pending_n" ] || pending_n=0
  if [ "$pending_n" -gt 0 ] 2>/dev/null; then
    echo "(dk-mode: $pending_n proposed item(s) awaiting review - run /dk-review)"
  fi
fi

# 3. Broken-not-quiet: 3 consecutive FAILED consolidations (from state file).
cf=$(state_get consecutive_failed); [ -n "$cf" ] || cf=0
if [ "$cf" -ge 3 ] 2>/dev/null; then
  echo "(dk-mode: consolidation has FAILED its last $cf runs - it is broken, not quiet. See the dk_consolidate log under \${DK_LOG_DIR:-~/Library/Logs or ~/.claude/logs})"
fi

# 4. Kick the consolidator when due. All guards are cheap file reads.
#    Due = interval elapsed since last attempt (per-turn/always/0 = always
#    due; a FAILED last attempt retries after at most 1 day, so a transient
#    failure doesn't stall a long interval). Gated on: unprocessed entries
#    exist AND a key is resolvable.
interval_seconds() {
  case "$1" in
    ""|0|per-turn|always) echo 0 ;;
    *d) echo $(( ${1%d} * 86400 )) ;;
    *h) echo $(( ${1%h} * 3600 )) ;;
    *m) echo $(( ${1%m} * 60 )) ;;
    *) echo "$1" ;;
  esac
}

key_available() {
  # A local OpenAI-compatible backend (Ollama/LM Studio/llama.cpp) needs no
  # key, so the kick is gated on the backend instead.
  [ "${DK_BACKEND:-anthropic}" = "openai" ] && return 0
  [ -n "${ANTHROPIC_API_KEY:-}" ] && return 0
  [ -n "${DK_KEY_FILE:-}" ] && [ -f "$DK_KEY_FILE" ] && return 0
  return 1
}

if [ -r "$RULES" ] && [ -f "$RAW" ] && key_available; then
  total=$(wc -l < "$RAW" 2>/dev/null | tr -d ' ' || true)
  done_mark=$(grep -m1 '^consolidated_through:' "$RULES" 2>/dev/null | awk '{print $2}' || true)
  [ -n "$total" ] || total=0
  [ -n "$done_mark" ] || done_mark=0
  if [ "$total" -gt "$done_mark" ] 2>/dev/null; then
    IV=$(interval_seconds "${DK_INTERVAL:-7d}")
    due=1
    if [ "$IV" -gt 0 ]; then
      last_attempt=$(state_get last_attempt_epoch); [ -n "$last_attempt" ] || last_attempt=0
      wait_s="$IV"
      if [ "$(state_get last_attempt_status)" = "failed" ] && [ "$IV" -gt 86400 ]; then
        wait_s=86400
      fi
      [ $(( $(date +%s) - last_attempt )) -ge "$wait_s" ] || due=0
    fi
    if [ "$due" -eq 1 ]; then
      nohup python3 "$SCRIPT_DIR/dk_consolidate.py" >/dev/null 2>&1 &
      disown 2>/dev/null || true
    fi
  fi
fi

exit 0
