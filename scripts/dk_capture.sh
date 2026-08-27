#!/usr/bin/env bash
# dk_capture.sh - Stop hook: start the miner after each turn.
#
# Part of dk-mode (mine -> consolidate -> recall). This script is now only a
# launcher. All detection lives in dk_watch.py, which reads the conversation
# with a model.
#
# It used to also carry a phrase list ("you didn't", "from now on", ...) that
# matched the transcript directly. That was deleted, for two measured reasons:
#
#   1. It did not work. Against a real transcript it found 0 of 46 real
#      corrections, and both of its two "hits" were subagent notifications
#      misread as the user. People steer by redirecting - "bit lame",
#      "simplify", "why is this so slow" - and no word list catches that.
#   2. It was actively harmful. The phrase check ran FIRST and exited the
#      script when it found nothing, and the launcher below sat underneath
#      it. So the miner only started on turns the word list matched, which is
#      almost never. The whole system was gated behind its weakest part, and
#      every test passed while it happened, because each test called the piece
#      it was testing directly and none asked whether anything reached it.
#
# The self-correction source ("the agent said its own approach was wrong")
# also lived in that phrase list. It moved into dk_watch.py's prompt rather
# than being dropped.
#
# Never blocks or delays a turn: the miner is backgrounded and detached, and
# every path here exits 0.
#
# Config (all optional):
#   DK_WATCH       0 disables mining entirely.
#   DK_SCAN_LINES  0 means a backfill sweep is driving this; the live miner is
#                  skipped, because history has no "right now" to be relevant
#                  to. dk_backfill.sh calls dk_watch.py --capture-only itself.
set -euo pipefail

# DK_HOME wins over everything: a machine-wide install points every project
# at one memory. Unset = per-project, as before.
ROOT="${DK_HOME:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"
# DK_MEM names the memory directory outright (plugin installs use
# ${CLAUDE_PLUGIN_DATA}, which has no .claude/ layout of its own).
MEM="${DK_MEM:-$ROOT/.claude/memory}"
SCAN_LINES="${DK_SCAN_LINES:-150}"

# A plugin install has no install.sh step, so seed on first use.
bash "$(cd "$(dirname "$0")" && pwd)/dk_bootstrap.sh" "$MEM" 2>/dev/null || true
[ -d "$MEM" ] || exit 0

# Hook payload arrives on stdin as JSON. grep/sed rather than jq: no
# dependency, no interpreter startup before we know there is work to do.
PAYLOAD="$(cat 2>/dev/null || true)"
TRANSCRIPT="$(printf '%s' "$PAYLOAD" | grep -o '"transcript_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*:[[:space:]]*"//; s/"$//' || true)"
[ -n "$TRANSCRIPT" ] && [ -r "$TRANSCRIPT" ] || exit 0

# The session id MUST reach the miner. It names the file the miner writes its
# selection to, and dk_recall.sh reads that file by the session id in its own
# payload. This was never passed, so the miner wrote .dk_active.nosession
# while recall looked for .dk_active.<real-id> and always fell back to the
# static note. The relevance layer produced answers nothing ever read.
SESSION="$(printf '%s' "$PAYLOAD" | grep -o '"session_id"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*:[[:space:]]*"//; s/"$//' || true)"

# Nothing may sit between here and the launch. Anything that can exit early
# above the miner is the bug described in the header.
if [ "$SCAN_LINES" != "0" ] && [ "${DK_WATCH:-1}" != "0" ]; then
  DK_SESSION_ID="${DK_SESSION_ID:-$SESSION}" \
  nohup python3 "$(cd "$(dirname "$0")" && pwd)/dk_watch.py" "$TRANSCRIPT" \
    >/dev/null 2>&1 &
  disown 2>/dev/null || true
fi

exit 0
