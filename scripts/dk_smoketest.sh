#!/usr/bin/env bash
# dk_smoketest.sh - end-to-end test on REAL conversations with a REAL model.
#
# Everything else in this repo is tested against stand-in servers. This is the
# one thing that is not: it mines a few of your actual Claude Code
# conversations with an actual model, then shows you every stage of the result
# so you can judge it yourself.
#
# It is deliberately safe to run:
#   - It installs into a THROWAWAY directory under $TMPDIR. It never touches
#     your real project, your real memory files, or your settings.
#   - It COPIES the transcripts it reads. It never writes to ~/.claude.
#   - It mines the N most recent conversations only (default 3), so a first
#     run costs cents, not dollars.
#
# Usage:
#   bash scripts/dk_smoketest.sh                 # 3 most recent conversations
#   bash scripts/dk_smoketest.sh --count 5
#   bash scripts/dk_smoketest.sh --keep          # leave the scratch dir behind
#
# A model is required. Set one of:
#   DK_API_KEY=sk-...        or  DK_KEY_FILE=/path/to/a/file/holding/the/key
#   DK_BACKEND=openai DK_API_URL=... DK_API_KEY=...      (OpenRouter)
#   DK_BACKEND=openai DK_API_URL=http://localhost:11434/v1/chat/completions
set -uo pipefail

COUNT=3
KEEP=0
PROJECTS="${DK_TRANSCRIPT_DIR:-$HOME/.claude/projects}"
while [ $# -gt 0 ]; do
  case "$1" in
    --count) COUNT="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --transcripts) PROJECTS="$2"; shift 2 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$SCRIPT_DIR")"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/dk-smoketest.XXXXXX")"
PROJ="$SCRATCH/project"
FEED="$SCRATCH/transcripts"
mkdir -p "$PROJ" "$FEED"
cleanup() { [ "$KEEP" = "1" ] || rm -rf "$SCRATCH"; }
trap cleanup EXIT

hr() { printf '\n%s\n' "------------------------------------------------------------"; }

# --- 0. preflight ----------------------------------------------------------
if [ ! -d "$PROJECTS" ]; then
  echo "No transcripts at $PROJECTS" >&2
  echo "That directory is where Claude Code stores conversations." >&2
  exit 1
fi
if [ -z "${DK_API_KEY:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ] \
   && { [ -z "${DK_KEY_FILE:-}" ] || [ ! -f "${DK_KEY_FILE/#\~/$HOME}" ]; } \
   && [ "${DK_BACKEND:-anthropic}" != "openai" ]; then
  echo "No model configured. This test is meaningless without one." >&2
  echo "Set DK_API_KEY, or DK_KEY_FILE, or DK_BACKEND=openai + DK_API_URL." >&2
  exit 1
fi

echo "dk-mode end-to-end test"
echo "  scratch project : $PROJ"
echo "  reading from    : $PROJECTS"
echo "  model backend   : ${DK_BACKEND:-anthropic} at ${DK_API_URL:-the Anthropic API}"
echo "  mining model    : ${DK_WATCH_MODELS:-(default)}"
echo "  sorting model   : ${DK_MODELS:-(default)}"

# --- 1. pick the N most recent conversations -------------------------------
# Python, not a shell pipeline. The first version used `sort -z` and `head -z`,
# which are GNU-only: on macOS `head` has no -z and the whole selection failed
# with "invalid option -- z". Same class of portability bug as `stat -f`, which
# this repo already had once. Python is a dependency anyway and behaves the
# same on both systems.
PROJECTS="$PROJECTS" FEED="$FEED" COUNT="$COUNT" python3 <<'PYPICK'
import os, shutil

src, dst = os.environ["PROJECTS"], os.environ["FEED"]
count = int(os.environ["COUNT"])
found = []
for root, _dirs, files in os.walk(src):
    for name in files:
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(root, name)
        try:
            st = os.stat(path)
        except OSError:
            continue
        if st.st_size > 2048:
            found.append((st.st_mtime, path))
found.sort(reverse=True)
for _mtime, path in found[:count]:
    shutil.copy2(path, os.path.join(dst, os.path.basename(path)))
PYPICK

picked=$(find "$FEED" -name '*.jsonl' | wc -l | tr -d ' ')
if [ "$picked" = "0" ]; then
  echo "Found no conversations over 2k in $PROJECTS" >&2
  exit 1
fi
hr; echo "1. Mining $picked conversation(s):"
for f in "$FEED"/*.jsonl; do
  echo "   $(basename "$f")  ($(wc -l < "$f" | tr -d ' ') messages)"
done

# --- 2. install into the scratch project -----------------------------------
# DK_REPO_URL is forced unreachable so the installer copies THIS working tree
# rather than cloning whatever is on GitHub. Testing pushed code by accident
# is a real trap - it is how three tests in this repo were silently vacuous.
DK_REPO_URL="file:///dk-smoketest-use-local" \
  bash "$REPO/install.sh" --target "$PROJ" --no-hooks >/dev/null 2>&1
if [ ! -f "$PROJ/.claude/memory/dk_rules.md" ]; then
  echo "install failed - no memory files created" >&2; exit 1
fi

# --- 3. mine ---------------------------------------------------------------
hr; echo "2. Reading them with the model. This is the slow part."
export CLAUDE_PROJECT_DIR="$PROJ"
bash "$REPO/scripts/dk_backfill.sh" --target "$PROJ" --transcripts "$FEED"
RAW="$PROJ/.claude/memory/dk.jsonl"
found=$(wc -l < "$RAW" 2>/dev/null | tr -d ' ' || echo 0)

hr; echo "3. What it found ($found item(s)) - YOUR words, copied verbatim:"
if [ "$found" = "0" ]; then
  echo "   NOTHING. Either the model was unreachable (see the warning above),"
  echo "   or these conversations genuinely contain no corrections."
else
  python3 - "$RAW" <<'PY'
import json, sys
for i, line in enumerate(open(sys.argv[1], encoding="utf-8"), 1):
    try:
        e = json.loads(line)
    except ValueError:
        continue
    print(f"\n  [{i}] {e.get('source','?')} / {e.get('kind','?')}  {e.get('ts','')[:10]}")
    print("      said: " + e.get("text", "")[:220].replace("\n", " "))
    ctx = e.get("assistant_context", "").replace("\n", " ")
    print("      about: " + (ctx[-180:] if ctx else "(no context recorded)"))
PY
fi

# --- 4. sort into rules ----------------------------------------------------
hr; echo "4. Sorting those into rules."
python3 "$REPO/scripts/dk_consolidate.py" --drain --target "$PROJ"

hr; echo "5. The rules it wrote:"
sed -n '/^## /,$p' "$PROJ/.claude/memory/dk_rules.md" | head -60

hr; echo "6. What a prompt would receive right now:"
printf '{"prompt":"ship it","session_id":"smoketest"}' \
  | CLAUDE_PROJECT_DIR="$PROJ" bash "$REPO/scripts/dk_recall.sh"

hr
echo "Done. Judge it on section 3: are those real corrections, in your words?"
[ "$KEEP" = "1" ] && echo "Scratch kept at: $SCRATCH"
echo "Nothing outside that directory was written to."
exit 0
