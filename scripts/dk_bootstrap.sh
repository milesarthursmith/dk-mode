#!/usr/bin/env bash
# dk_bootstrap.sh - create the memory files if they are not there yet.
#
# install.sh does this for a git install. A PLUGIN install never runs
# install.sh: Claude Code copies the plugin in and starts calling the hooks,
# so the first hook to run has to seed its own memory. This is that step.
#
# Idempotent and silent. It never overwrites an existing rules file, so it
# cannot destroy mined memory by running again.
set -uo pipefail

MEM="${1:?usage: dk_bootstrap.sh <memory-dir>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TPL="$(dirname "$HERE")/templates"

# Seed ONLY a directory that has never been used. If dk.jsonl is there but
# the rules file is not, someone deleted the rules on purpose - that is how
# you switch dk-mode off - and recreating it would override that decision.
[ -f "$MEM/dk_rules.md" ] && exit 0
[ -e "$MEM/dk.jsonl" ] && exit 0
mkdir -p "$MEM" 2>/dev/null || exit 0
[ -f "$TPL/dk_rules.md" ] || exit 0

sed "s/^last_verified:.*$/last_verified: $(date +%F)/" \
  "$TPL/dk_rules.md" > "$MEM/dk_rules.md" 2>/dev/null || exit 0
: > "$MEM/dk.jsonl" 2>/dev/null || true

# Seed the researched failure modes unless the user turned them off, so a
# plugin install steers from its first turn rather than after its first mine.
if [ "${DK_BASELINE:-1}" != "0" ] && [ -f "$TPL/baseline_rules.md" ]; then
  RULES="$MEM/dk_rules.md" BASE="$TPL/baseline_rules.md" python3 <<'PYSEED' 2>/dev/null || true
import os, re
rp, bp = os.environ["RULES"], os.environ["BASE"]
rules, base = open(rp, encoding="utf-8").read(), open(bp, encoding="utf-8").read()
items = re.findall(r"^### .*?(?=^### |\Z)", base, re.M | re.S)
rules = rules.replace("## Mistake Patterns\n\n(none captured yet)",
                      "## Mistake Patterns\n\n" + "\n".join(i.rstrip() + "\n" for i in items), 1)
lines = [m.group(1).strip() for m in
         (re.search(r"\*\*Reminder line:\*\* (.+)", i) for i in items) if m]
note = ("<self-steering>\nSelf-steering - check before acting:\n"
        + "\n".join("- " + l for l in lines[:5])
        + "\n(baseline defaults; they are replaced as your own are mined)\n</self-steering>")
rules = re.sub(r"<!-- inject:start -->.*?<!-- inject:end -->",
               "<!-- inject:start -->\n" + note + "\n<!-- inject:end -->",
               rules, count=1, flags=re.S)
open(rp, "w", encoding="utf-8").write(rules)
PYSEED
fi
exit 0
