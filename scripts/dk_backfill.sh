#!/usr/bin/env bash
# dk_backfill.sh - mine PREVIOUS sessions for steering.
#
# Claude Code keeps every session transcript on disk under
# ~/.claude/projects/<sanitized-project>/<session-id>.jsonl. This script
# sweeps those historical transcripts through the exact same detection logic
# the live Stop hook uses (dk_capture.sh with DK_SCAN_LINES=0 = scan
# the whole file, not just the recent tail), so the memory gets seeded from
# real past corrections instead of starting empty.
#
# No duplicated detection logic on purpose: a second copy of the patterns is
# how detection silently drifts. This is a thin loop over the real capture
# script; the capture script's uuid dedupe makes the sweep idempotent and
# safe to re-run any time.
#
# Usage:
#   dk_backfill.sh [--transcripts DIR] [--target PROJECT_ROOT]
#
#   --transcripts DIR   where to look for *.jsonl transcripts
#                       (default: ~/.claude/projects, ALL projects - your
#                       corrections behave the same across projects)
#   --target DIR        the project whose .claude/memory receives the
#                       entries (default: $CLAUDE_PROJECT_DIR, else pwd)
#
# After a large backfill, run the consolidator in drain mode to process the
# whole backlog at once:  python3 dk_consolidate.py --drain
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TRANSCRIPTS="${HOME}/.claude/projects"
TARGET="${DK_HOME:-${CLAUDE_PROJECT_DIR:-$(pwd)}}"

while [ $# -gt 0 ]; do
  case "$1" in
    --transcripts) TRANSCRIPTS="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ ! -d "$TARGET/.claude/memory" ]; then
  echo "target $TARGET has no .claude/memory - run install.sh there first" >&2
  exit 1
fi
if [ ! -d "$TRANSCRIPTS" ]; then
  echo "no transcript directory at $TRANSCRIPTS" >&2
  exit 1
fi

RAW="$TARGET/.claude/memory/dk.jsonl"
before=$(wc -l < "$RAW" 2>/dev/null | tr -d ' ' || echo 0)
scanned=0
semantic_total=0

# find -print0 handles any filename; sessions are named <uuid>.jsonl.
while IFS= read -r -d '' t; do
  scanned=$((scanned + 1))
  session="$(basename "$t" .jsonl)"
  # One path only. The phrase-matching pass that used to run alongside this
  # was deleted: it found 0 of 46 real corrections, and its early exit gated
  # the reading pass it was supposed to complement.
  # DK_HOME must be set, not just CLAUDE_PROJECT_DIR: the miner ranks DK_HOME
  # and DK_MEM ABOVE CLAUDE_PROJECT_DIR, so --target was silently ignored for
  # anyone with a global install exported in their shell, and the entries went
  # to the wrong memory.
  sem=$(DK_HOME="$TARGET" DK_MEM="" CLAUDE_PROJECT_DIR="$TARGET" \
          python3 "$SCRIPT_DIR/dk_watch.py" \
          --capture-only "$t" 2>/dev/null | sed -n 's/^semantic: \([0-9]*\).*/\1/p')
  semantic_total=$((semantic_total + ${sem:-0}))
done < <(find "$TRANSCRIPTS" -name '*.jsonl' -type f -print0)

after=$(wc -l < "$RAW" 2>/dev/null | tr -d ' ' || echo 0)
echo "backfill: scanned $scanned transcripts under $TRANSCRIPTS"
echo "backfill: $((after - before)) new entries (total $after) in $RAW"
if [ "$semantic_total" = "0" ]; then
  # Gated on the phrase-match count before, so a run with 3+ phrase hits and a
  # dead model reported success. Phrase hits are mostly noise (measured: 0 of
  # 46 real corrections), so a zero semantic yield is the warning, whatever
  # the phrase pass returned.
  echo "backfill: WARNING - found NOTHING. Reading the conversations is the"
  echo "          only way this mines anything, so check a model is reachable:"
  echo "          DK_API_KEY or DK_KEY_FILE, or DK_BACKEND=openai + DK_API_URL"
  echo "          for a local one. An empty result otherwise means clean history."
fi
if [ "$after" -gt "$before" ]; then
  echo "next: python3 $SCRIPT_DIR/dk_consolidate.py --drain --target $TARGET"
fi
