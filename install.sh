#!/usr/bin/env bash
# install.sh - install dk-mode into a Claude Code project.
#
# What it does:
#   1. Ensures a pinned clone of dk-mode at <project>/.claude/vendor/dk-mode
#      (latest tag if any, else the default branch). --update refreshes it.
#   2. Bootstraps <project>/.claude/memory/ and seeds dk_rules.md from the
#      template ONLY if absent - never overwrites existing memory. Re-running
#      is always safe.
#   3. Merges the two hook entries (Stop -> dk_capture.sh,
#      UserPromptSubmit -> dk_recall.sh) into <project>/.claude/settings.json,
#      preserving everything already there. If that edit fails for ANY reason
#      (no python, malformed JSON, a permission system blocking settings
#      edits), it prints the exact JSON block and file path for manual paste
#      and still exits 0 - the bootstrap succeeded even if registration
#      didn't. Verify the file actually changed; don't assume.
#
# Usage: install.sh [--target PROJECT_ROOT] [--update] [--no-hooks]
#   --target   project to install into (default: $CLAUDE_PROJECT_DIR, else pwd)
#   --update   fetch + re-pin the vendor clone to the newest tag
#   --no-hooks skip settings.json registration entirely and print the manual
#              block instead (for environments where settings edits are
#              policy-gated and must be made by a person)
#
# Config the CONSUMING project may set (in the hook command string or the
# environment): ANTHROPIC_API_KEY or DK_KEY_FILE, DK_MODELS,
# DK_USER_NAME, DK_INTERVAL, DK_LOG_DIR. See README.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${CLAUDE_PROJECT_DIR:-$(pwd)}"
UPDATE=0
NO_HOOKS=0
REPO_URL="${DK_REPO_URL:-https://github.com/milesarthursmith/dk-mode.git}"

while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET="$2"; shift 2 ;;
    --update) UPDATE=1; shift ;;
    --no-hooks) NO_HOOKS=1; shift ;;
    -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

TARGET="$(cd "$TARGET" && pwd)"
VENDOR="$TARGET/.claude/vendor/dk-mode"
SETTINGS="$TARGET/.claude/settings.json"

pin_latest() {  # inside a clone: check out the newest tag, else stay on branch
  local tag
  tag=$(git -C "$1" tag --sort=-v:refname | head -1)
  if [ -n "$tag" ]; then git -C "$1" -c advice.detachedHead=false checkout -q "$tag"; echo "$tag"; else
    git -C "$1" rev-parse --short HEAD; fi
}

# --- 1. vendor clone --------------------------------------------------------
if [ "$SCRIPT_DIR" = "$VENDOR" ]; then
  pinned="$(git -C "$VENDOR" describe --tags --always 2>/dev/null || echo local)"
  if [ "$UPDATE" = "1" ]; then
    git -C "$VENDOR" fetch -q --tags origin && pinned="$(pin_latest "$VENDOR")"
  fi
elif [ -d "$VENDOR/.git" ]; then
  if [ "$UPDATE" = "1" ]; then
    git -C "$VENDOR" fetch -q --tags origin && pinned="$(pin_latest "$VENDOR")"
  else
    pinned="$(git -C "$VENDOR" describe --tags --always 2>/dev/null || echo unknown)"
  fi
else
  mkdir -p "$(dirname "$VENDOR")"
  if git clone -q "$REPO_URL" "$VENDOR" 2>/dev/null; then
    pinned="$(pin_latest "$VENDOR")"
  elif [ -f "$SCRIPT_DIR/scripts/dk_capture.sh" ]; then
    # Remote unreachable (or repo not created yet): copy the local checkout
    # this installer was run from - working tree, so local edits count.
    mkdir -p "$VENDOR"
    cp -R "$SCRIPT_DIR/scripts" "$SCRIPT_DIR/templates" "$VENDOR/"
    cp -R "$SCRIPT_DIR/tests" "$VENDOR/" 2>/dev/null || true
    cp -R "$SCRIPT_DIR/skills" "$VENDOR/" 2>/dev/null || true
    cp "$SCRIPT_DIR/install.sh" "$VENDOR/" 2>/dev/null || true
    cp "$SCRIPT_DIR/README.md" "$VENDOR/" 2>/dev/null || true
    pinned="local:$(git -C "$SCRIPT_DIR" rev-parse --short HEAD 2>/dev/null || echo copy)"
  else
    echo "could not clone $REPO_URL and no local checkout to fall back to" >&2
    exit 1
  fi
fi
chmod +x "$VENDOR"/scripts/*.sh "$VENDOR"/scripts/*.py 2>/dev/null || true

# --- 2. bootstrap memory ----------------------------------------------------
mkdir -p "$TARGET/.claude/memory"
RULES="$TARGET/.claude/memory/dk_rules.md"
seeded=no
if [ ! -f "$RULES" ]; then
  sed "s/^last_verified:.*$/last_verified: $(date +%F)/" \
    "$VENDOR/templates/dk_rules.md" > "$RULES"
  seeded=yes
fi
[ -f "$TARGET/.claude/memory/dk.jsonl" ] || : > "$TARGET/.claude/memory/dk.jsonl"

# The /dk-review skill (approval-mode review flow). Copied, not linked,
# so it survives vendor refreshes; overwritten on update to stay current.
if [ -d "$VENDOR/skills/dk-review" ]; then
  mkdir -p "$TARGET/.claude/skills"
  cp -R "$VENDOR/skills/dk-review" "$TARGET/.claude/skills/"
fi

# --- 3. hook registration ---------------------------------------------------
CAPTURE_CMD="bash \"\${CLAUDE_PROJECT_DIR}/.claude/vendor/dk-mode/scripts/dk_capture.sh\""
RECALL_CMD="bash \"\${CLAUDE_PROJECT_DIR}/.claude/vendor/dk-mode/scripts/dk_recall.sh\""
# JSON-escaped variants for the copy-pasteable manual block (the command
# strings contain literal quotes, which must appear as \" inside JSON).
CAPTURE_JSON="$(printf '%s' "$CAPTURE_CMD" | sed 's/"/\\"/g')"
RECALL_JSON="$(printf '%s' "$RECALL_CMD" | sed 's/"/\\"/g')"

MANUAL_BLOCK=$(cat <<EOF
Add to the "hooks" object of $SETTINGS
(append to the existing "Stop" array; create "UserPromptSubmit" if absent):

    "Stop": [
      ...existing entries...,
      { "hooks": [ { "type": "command", "command": "$CAPTURE_JSON" } ] }
    ],
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "$RECALL_JSON" } ] }
    ]
EOF
)

registered=no
merge_out=""
if [ "$NO_HOOKS" = "1" ]; then
  :
elif merge_out=$(SETTINGS="$SETTINGS" CAPTURE_CMD="$CAPTURE_CMD" RECALL_CMD="$RECALL_CMD" python3 - 2>&1 <<'PY'
import json, os, sys, tempfile

path = os.environ["SETTINGS"]
cap = {"hooks": [{"type": "command", "command": os.environ["CAPTURE_CMD"]}]}
rec = {"hooks": [{"type": "command", "command": os.environ["RECALL_CMD"]}]}

try:
    with open(path, encoding="utf-8") as f:
        settings = json.load(f)
except FileNotFoundError:
    settings = {}
hooks = settings.setdefault("hooks", {})

def has_cmd(entries, cmd):
    return any(h.get("command") == cmd
               for e in entries for h in e.get("hooks", []))

changed = False
stop = hooks.setdefault("Stop", [])
if not has_cmd(stop, os.environ["CAPTURE_CMD"]):
    stop.append(cap); changed = True
ups = hooks.setdefault("UserPromptSubmit", [])
if not has_cmd(ups, os.environ["RECALL_CMD"]):
    ups.append(rec); changed = True

if changed:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".settings-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
print("changed" if changed else "already-present")
PY
); then
  # Trust nothing: read the file back and confirm both commands are in it.
  if grep -qF "dk_capture.sh" "$SETTINGS" 2>/dev/null \
     && grep -qF "dk_recall.sh" "$SETTINGS" 2>/dev/null; then
    registered=yes
  fi
fi

# --- summary ----------------------------------------------------------------
echo "dk-mode installed"
echo "  vendor:   $VENDOR (pinned: ${pinned:-unknown})"
echo "  memory:   $TARGET/.claude/memory (dk_rules.md seeded: $seeded)"
if [ "$registered" = "yes" ]; then
  echo "  hooks:    registered in $SETTINGS ($merge_out)"
else
  echo "  hooks:    NOT registered automatically - add them by hand:"
  echo
  echo "$MANUAL_BLOCK"
fi
echo
echo "Optional next steps:"
echo "  bash $VENDOR/scripts/dk_backfill.sh --target $TARGET   # mine previous sessions"
echo "  gitignore: add .claude/vendor/ to $TARGET/.gitignore"
exit 0
