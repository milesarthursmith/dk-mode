---
name: dk-review
description: Review dk-mode's proposed memory items (approval mode). Use when the user runs /dk-review, says "dk review", or a prompt shows "(dk-mode: N proposed item(s) awaiting review)". Lists pending mistake patterns / rules mined from the user's own corrections, and applies their approve/reject verdicts.
---

# dk-review

dk-mode is in approval ("training wheels") mode: the consolidator
proposes memory items mined from the user's verbatim corrections, but
nothing steers behaviour until the user approves it. This skill is the
review flow.

1. Run: `python3 "$CLAUDE_PROJECT_DIR/.claude/vendor/dk-mode/scripts/dk_review.py" --list`
2. Show the user the pending items exactly as listed - the evidence lines
   are their own words; do not paraphrase them.
3. Ask which to approve and which to reject (numbers). Batch verdicts are
   fine ("approve all", "reject 2, approve the rest").
4. Apply with `--approve N [N...]` and/or `--reject N [N...]`. Approval
   takes effect immediately (the injected note is rebuilt on the spot);
   rejected items are preserved under Retired, never deleted.
5. Confirm the result by reading back the rebuilt note (the block between
   the inject markers in `.claude/memory/dk_rules.md`).

Notes:
- Never approve or reject on the user's behalf - the whole point is human
  sign-off. If they ask "what do you think?", give a recommendation, then
  wait for their verdict.
- When the user says they trust it enough to stop reviewing, tell them to
  remove `DK_APPROVAL=1` from the hook command in `.claude/settings.json`
  - do not edit that file yourself unless asked.
