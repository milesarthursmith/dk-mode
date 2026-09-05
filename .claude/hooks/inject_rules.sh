#!/usr/bin/env bash
# UserPromptSubmit hook: re-inject the two top CLAUDE.md rules on every
# message. Reads sections 1 and 2 of CLAUDE.md so the text has one source.
set -u
root="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
f="$root/CLAUDE.md"
[ -r "$f" ] || exit 0
rules=$(awk '/^## 1\./{p=1} /^## 3\./{p=0} p' "$f")
python3 - "$rules" <<'PY'
import json, sys
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "REMINDER (injected on every message, from CLAUDE.md):\n\n" + sys.argv[1]}}))
PY
