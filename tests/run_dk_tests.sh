#!/usr/bin/env bash
# run_dk_tests.sh - the full test suite for dk-mode
# (dk_capture.sh / dk_recall.sh / dk_consolidate.py / dk_backfill.sh).
#
# One command, hard pass/fail (exits non-zero on any failure). Every test
# runs in a throwaway sandbox with its own fake HOME and memory dir, so the
# suite can never touch real memory files. No network and no API key needed
# for the main suite: consolidate tests point DK_API_URL at mock_api.py,
# a local stand-in serving canned responses through the script's real HTTP
# path. `--live` additionally runs one real-API behavioral test (needs
# ANTHROPIC_API_KEY or DK_KEY_FILE; costs one API call).
#
# Run from anywhere:  bash tests/run_dk_tests.sh [--live]
# Run after ANY change to the scripts.
set -u

TESTS="$(cd "$(dirname "$0")" && pwd)"
FIX="$TESTS/fixtures"
REPO="$(cd "$TESTS/.." && pwd)"
SCRIPTS="$REPO/scripts"
TMPBASE="$(mktemp -d)"
MOCK_PID=""

cleanup() {
  [ -n "$MOCK_PID" ] && kill "$MOCK_PID" 2>/dev/null
  rm -rf "$TMPBASE"
}
trap cleanup EXIT

export REPO
PASS=0; FAIL=0; CURRENT=""
t()  { CURRENT="$1"; }
ok() { PASS=$((PASS + 1)); printf 'ok   %s\n' "$CURRENT"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL %s - %s\n' "$CURRENT" "${1:-assertion failed}"; }

# --- helpers ----------------------------------------------------------------

sandbox() {
  SB="$(mktemp -d "$TMPBASE/sb.XXXXXX")"
  mkdir -p "$SB/.claude/memory" "$SB/home"
  cp "$REPO/templates/dk_rules.md" "$SB/.claude/memory/dk_rules.md"
  : > "$SB/.claude/memory/dk.jsonl"
  : > "$SB/.claude/memory/log.md"
  RAW="$SB/.claude/memory/dk.jsonl"
  RULES="$SB/.claude/memory/dk_rules.md"
  MEMLOG="$SB/.claude/memory/log.md"
  STATE="$SB/.claude/memory/.dk_state"
  ACTIVEF="$SB/.claude/memory/.dk_active.nosession"   # scoped per session
  KEYF="$SB/home/key"
}

payload() { printf '{"transcript_path":"%s","session_id":"sess1234abcd"}' "$1"; }

# Base env for every script invocation: sandboxed project + HOME, no leaked
# real key, no key file unless a test creates one.
runenv() {
  env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" ANTHROPIC_API_KEY="" \
      DK_KEY_FILE="$KEYF" "$@"
}

run_capture() {  # run_capture <transcript-fixture-path> [extra env pairs...]
  local tp="$1"; shift
  payload "$tp" | runenv "$@" bash "$SCRIPTS/dk_capture.sh"
}

run_recall() { printf '{"prompt":"x"}' | runenv "$@" bash "$SCRIPTS/dk_recall.sh"; }

run_consolidate() {
  runenv DK_API_URL="http://127.0.0.1:${MOCK_PORT:-1}/v1/messages" "$@" \
    python3 "$SCRIPTS/dk_consolidate.py"
}

start_mock() {  # start_mock <md-fixture> [delay-seconds]
  local portf="$TMPBASE/port.$RANDOM"
  python3 "$TESTS/mock_api.py" "$FIX/$1" "$portf" "${2:-0}" &
  MOCK_PID=$!
  for _ in $(seq 1 50); do [ -s "$portf" ] && break; sleep 0.1; done
  MOCK_PORT="$(cat "$portf")"
}

stop_mock() {
  [ -n "$MOCK_PID" ] && kill "$MOCK_PID" 2>/dev/null && wait "$MOCK_PID" 2>/dev/null
  MOCK_PID=""
}

start_watch_mock() {  # start_watch_mock '<json the model returns>'
  local portf="$TMPBASE/wport.$RANDOM"
  python3 "$TESTS/mock_watch_api.py" "$1" "$portf" &
  MOCK_PID=$!
  for _ in $(seq 1 50); do [ -s "$portf" ] && break; sleep 0.1; done
  MOCK_PORT="$(cat "$portf")"
}

checksum() { python3 -c 'import hashlib,sys;print(hashlib.md5(open(sys.argv[1],"rb").read()).hexdigest())' "$1"; }
backdate() { python3 -c 'import os,sys,time;t=time.time()-int(sys.argv[2])*86400;os.utime(sys.argv[1],(t,t))' "$1" "$2"; }
epoch_ago() { python3 -c 'import time,sys;print(int(time.time())-int(sys.argv[1]))' "$1"; }
lines() { wc -l < "$1" | tr -d ' '; }

write_state() {  # write_state <last_attempt_epoch> <status> <consecutive_failed>
  printf 'last_attempt_epoch=%s\nlast_attempt_status=%s\nlast_success_epoch=0\nconsecutive_failed=%s\n' \
    "$1" "$2" "$3" > "$STATE"
}

timed_ms() {  # timed_ms <stdin-payload> <cmd...> -> wall ms
  python3 - "$@" <<'PY'
import subprocess, sys, time
payload, cmd = sys.argv[1], sys.argv[2:]
t = time.perf_counter()
subprocess.run(cmd, input=payload.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(int((time.perf_counter() - t) * 1000))
PY
}

# =============================================================================
echo "== capture =="

t "5. clean transcript captures nothing, no heartbeat"
sandbox; run_capture "$FIX/transcript_clean.jsonl"
if [ ! -s "$RAW" ] && ! grep -q "dk-capture" "$MEMLOG"; then ok; else bad "raw/log dirty"; fi

t "6. clean (no-hit) path is fast (<250ms)"
ms=$(timed_ms "$(payload "$FIX/transcript_clean.jsonl")" \
  env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" bash "$SCRIPTS/dk_capture.sh")
if [ "$ms" -lt 250 ]; then ok; else bad "${ms}ms"; fi

t "7. trigger words in tool output / assistant text / sidechain / commands ignored"
sandbox; run_capture "$FIX/transcript_toolwords.jsonl"
if [ ! -s "$RAW" ]; then ok; else bad "raw: $(cat "$RAW")"; fi

t "9. missing transcript path exits 0, writes nothing"
sandbox
printf '{}' | runenv bash "$SCRIPTS/dk_capture.sh"; rc=$?
if [ "$rc" = "0" ] && [ ! -s "$RAW" ]; then ok; else bad "rc=$rc"; fi

t "10. lock held by another session -> skips without writing"
sandbox; mkdir "$SB/.claude/memory/.dk.lock"
run_capture "$FIX/transcript_correction.jsonl"; rc=$?
if [ "$rc" = "0" ] && [ ! -s "$RAW" ]; then ok; else bad "rc=$rc"; fi
rmdir "$SB/.claude/memory/.dk.lock"

t "10b. isMeta turns are never shown to the model: skill body, image paste, harness filler"
sandbox; echo k > "$KEYF"
ids=$(python3 -c "
import json
ids=[json.loads(l)['uuid'] for l in open('$FIX/transcript_meta.jsonl')]
print(json.dumps({'active':[],'alert':None,
                  'steering':[{'id':i,'source':'human','kind':'correction'} for i in ids]}))")
start_watch_mock "$ids"
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_meta.jsonl"
stop_mock
# The model asked for every id in the file. Only the real human turn can land:
# the rest were filtered out before the prompt, so their ids resolve to nothing.
if grep -qF "you didn't run the tests" "$RAW" \
   && ! grep -q "Base directory for this skill" "$RAW" \
   && ! grep -q "\[Image:" "$RAW" \
   && ! grep -q "Continue from where you left off" "$RAW"; then ok; else bad "raw: $(cat "$RAW")"; fi

t "13. prints the note between the markers, markers stripped"
sandbox; out=$(run_recall)
if printf '%s' "$out" | grep -q "<self-steering>" \
   && printf '%s' "$out" | grep -q "Self-steering - check before acting" \
   && ! printf '%s' "$out" | grep -q "inject:start"; then ok; else bad "out: $out"; fi

t "14. rules file missing -> prints nothing, exits 0"
sandbox; rm "$RULES"; out=$(run_recall); rc=$?
if [ "$rc" = "0" ] && [ -z "$out" ]; then ok; else bad "rc=$rc out: $out"; fi

t "15. markers missing -> prints nothing"
sandbox; grep -v 'inject:' "$RULES" > "$RULES.tmp" && mv "$RULES.tmp" "$RULES"
out=$(run_recall)
if [ -z "$out" ]; then ok; else bad "out: $out"; fi

t "16. raw log 30 days stale -> tripwire line appears"
sandbox; backdate "$RAW" 30; out=$(run_recall)
if printf '%s' "$out" | grep -q "no captures in 30 days"; then ok; else bad "out: $out"; fi

t "17. consecutive_failed >= 3 in state -> broken-not-quiet line"
sandbox; write_state "$(epoch_ago 100)" failed 3
out=$(run_recall)
if printf '%s' "$out" | grep -q "FAILED its last 3 runs"; then ok; else bad "out: $out"; fi

t "18. recall is fast (<250ms)"
sandbox
ms=$(timed_ms '{"prompt":"x"}' \
  env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" ANTHROPIC_API_KEY="" DK_KEY_FILE="$KEYF" bash "$SCRIPTS/dk_recall.sh")
if [ "$ms" -lt 250 ]; then ok; else bad "${ms}ms"; fi

# --- the kick: fires only when due AND pending AND key resolvable -----------
# Sandboxed consolidator replaced with a stub via PATH? No - recall invokes
# the consolidator by its real path next to itself, so stub via a copied
# scripts dir instead.
kick_sandbox() {
  sandbox
  mkdir -p "$SB/stub"
  cp "$SCRIPTS/dk_recall.sh" "$SB/stub/dk_recall.sh"
  cat > "$SB/stub/dk_consolidate.py" <<'STUB'
import os
open(os.path.join(os.environ["CLAUDE_PROJECT_DIR"], "kicked"), "w").write("1")
STUB
  echo '{"ts":"x","uuid":"k1"}' >> "$RAW"   # pending (through-mark is 0)
  echo "dummy-key" > "$KEYF"
}
kick_recall() { printf '{"prompt":"x"}' | runenv "$@" bash "$SB/stub/dk_recall.sh"; }
wait_kicked() { for _ in $(seq 1 30); do [ -f "$SB/kicked" ] && return 0; sleep 0.1; done; return 1; }

t "19. no state yet (never attempted) + pending + key -> kicked"
kick_sandbox; kick_recall >/dev/null
if wait_kicked; then ok; else bad "not kicked"; fi

t "20. no key resolvable -> no kick"
kick_sandbox; rm "$KEYF"; kick_recall >/dev/null; sleep 0.5
if [ ! -f "$SB/kicked" ]; then ok; else bad "kicked"; fi

t "21. ANTHROPIC_API_KEY alone (no key file) -> kicked"
kick_sandbox; rm "$KEYF"
printf '{"prompt":"x"}' | env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" \
  ANTHROPIC_API_KEY="sk-test" DK_KEY_FILE="$KEYF" bash "$SB/stub/dk_recall.sh" >/dev/null
if wait_kicked; then ok; else bad "not kicked"; fi

t "22. nothing pending -> no kick"
kick_sandbox; : > "$RAW"; kick_recall >/dev/null; sleep 0.5
if [ ! -f "$SB/kicked" ]; then ok; else bad "kicked"; fi

t "23. last attempt 3 days ago (success), interval 7d -> not due, no kick"
kick_sandbox; write_state "$(epoch_ago $((3*86400)))" success 0
kick_recall >/dev/null; sleep 0.5
if [ ! -f "$SB/kicked" ]; then ok; else bad "kicked"; fi

t "24. last attempt 8 days ago -> due, kicked"
kick_sandbox; write_state "$(epoch_ago $((8*86400)))" success 0
kick_recall >/dev/null
if wait_kicked; then ok; else bad "not kicked"; fi

t "25. per-turn mode: attempted seconds ago -> still kicked every prompt"
kick_sandbox; write_state "$(epoch_ago 5)" success 0
kick_recall DK_INTERVAL=per-turn >/dev/null
if wait_kicked; then ok; else bad "not kicked"; fi

t "26. 1h interval honored: 30min ago -> no kick; 2h ago -> kick"
kick_sandbox; write_state "$(epoch_ago 1800)" success 0
kick_recall DK_INTERVAL=1h >/dev/null; sleep 0.5
first_no=$([ ! -f "$SB/kicked" ] && echo yes || echo no)
write_state "$(epoch_ago 7200)" success 0
kick_recall DK_INTERVAL=1h >/dev/null
if [ "$first_no" = "yes" ] && wait_kicked; then ok; else bad "first_no=$first_no"; fi

t "27. FAILED last attempt retries after 1 day even on a 7d interval"
kick_sandbox; write_state "$(epoch_ago $((2*86400)))" failed 1
kick_recall >/dev/null
if wait_kicked; then ok; else bad "not kicked"; fi

# =============================================================================
echo "== consolidate =="

consolidate_sandbox() {
  sandbox
  cp "$FIX/raw_entries.jsonl" "$RAW"
  echo "dummy-key" > "$KEYF"
}

t "28. good response -> file replaced, bookmark bumped, heartbeat, state=success, raw untouched"
consolidate_sandbox; raw_sum=$(checksum "$RAW")
start_mock rewritten_rules_good.md; run_consolidate; stop_mock
if grep -q "Count:\*\* 2" "$RULES" \
   && grep -q "^consolidated_through: 4" "$RULES" \
   && grep -q "^last_verified: $(date +%F)" "$RULES" \
   && grep -q "| dk-consolidate | processed 4 entries" "$MEMLOG" \
   && grep -q "^last_attempt_status=success" "$STATE" \
   && grep -q "^consecutive_failed=0" "$STATE" \
   && [ "$(checksum "$RAW")" = "$raw_sum" ]; then ok; else bad "log: $(cat "$MEMLOG"); state: $(cat "$STATE" 2>/dev/null)"; fi

t "29. garbage response -> FAILED, consecutive_failed increments, file untouched"
consolidate_sandbox; rules_sum=$(checksum "$RULES")
start_mock rewritten_rules_garbage.md; run_consolidate; stop_mock
if grep -q "| dk-consolidate | FAILED" "$MEMLOG" \
   && grep -q "^consecutive_failed=1" "$STATE" \
   && [ "$(checksum "$RULES")" = "$rules_sum" ]; then ok; else bad "log: $(cat "$MEMLOG")"; fi

t "30. note over the line cap -> rejected, FAILED, file untouched"
consolidate_sandbox; rules_sum=$(checksum "$RULES")
start_mock rewritten_rules_longnote.md; run_consolidate; stop_mock
if grep -q "FAILED: model output rejected: inject block too long" "$MEMLOG" \
   && [ "$(checksum "$RULES")" = "$rules_sum" ]; then ok; else bad "log: $(cat "$MEMLOG")"; fi

t "31. chatty commentary before frontmatter -> rejected, file untouched"
consolidate_sandbox; rules_sum=$(checksum "$RULES")
start_mock rewritten_rules_commentary.md; run_consolidate; stop_mock
if grep -q "FAILED: model output rejected: missing frontmatter" "$MEMLOG" \
   && [ "$(checksum "$RULES")" = "$rules_sum" ]; then ok; else bad "log: $(cat "$MEMLOG")"; fi

t "32. fenced response accepted, fences stripped, tampered bookmark overridden"
consolidate_sandbox
start_mock rewritten_rules_fenced.md; run_consolidate; stop_mock
if ! grep -q '```' "$RULES" && grep -q "^consolidated_through: 4" "$RULES"; then ok; else bad "head: $(head -8 "$RULES")"; fi

t "33. no key resolvable -> silent no-op, nothing written"
consolidate_sandbox; rm "$KEYF"; rules_sum=$(checksum "$RULES")
run_consolidate; rc=$?
if [ "$rc" = "0" ] && [ ! -s "$MEMLOG" ] && [ "$(checksum "$RULES")" = "$rules_sum" ]; then ok; else bad "rc=$rc log: $(cat "$MEMLOG")"; fi

t "34. lock held -> exits immediately, nothing written"
consolidate_sandbox; mkdir "$SB/.claude/memory/.dk-consolidate.lock"
run_consolidate; rc=$?
if [ "$rc" = "0" ] && [ ! -s "$MEMLOG" ]; then ok; else bad "rc=$rc"; fi
rmdir "$SB/.claude/memory/.dk-consolidate.lock"

t "35. attempted moments ago -> post-lock recheck exits without work"
consolidate_sandbox; write_state "$(epoch_ago 10)" success 0
start_mock rewritten_rules_good.md; run_consolidate; stop_mock
if ! grep -q "dk-consolidate" "$MEMLOG"; then ok; else bad "log: $(cat "$MEMLOG")"; fi

t "36. killed mid-run -> file unchanged, no half-write, no heartbeat"
consolidate_sandbox; rules_sum=$(checksum "$RULES")
start_mock rewritten_rules_good.md 5
# Background python DIRECTLY (not via the runenv function) so kill -9
# reaches the real process, not a wrapper subshell.
env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" ANTHROPIC_API_KEY="" DK_KEY_FILE="$KEYF" \
  DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_consolidate.py" & CPID=$!
sleep 1; kill -9 "$CPID" 2>/dev/null; wait "$CPID" 2>/dev/null
stop_mock
leftover=$(find "$SB/.claude/memory" -name '.dk-rules-*.tmp' | wc -l | tr -d ' ')
if [ "$(checksum "$RULES")" = "$rules_sum" ] && ! grep -q "dk-consolidate" "$MEMLOG" \
   && [ "$leftover" = "0" ]; then ok; else bad "tmp=$leftover log: $(cat "$MEMLOG")"; fi
rmdir "$SB/.claude/memory/.dk-consolidate.lock" 2>/dev/null

t "37. --drain processes the whole backlog in batches, ignoring the interval"
consolidate_sandbox
python3 -c '
import json
with open("'"$RAW"'","w") as f:
    for i in range(450):
        f.write(json.dumps({"ts":"2026-06-01","uuid":f"d{i}","source":"human","kind":"correction","signal":"x","user_verbatim":f"entry {i}"})+"\n")
'
write_state "$(epoch_ago 10)" success 0   # not due - drain must ignore this
start_mock rewritten_rules_good.md
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_consolidate.py" --drain
stop_mock
if grep -q "^consolidated_through: 450" "$RULES" \
   && grep -q "processed 450 entries in 3 batches" "$MEMLOG"; then ok; else bad "rules: $(grep consolidated_through "$RULES"); log: $(cat "$MEMLOG")"; fi

# =============================================================================
echo "== backfill =="

t "38. sweeps all projects' transcripts and is idempotent"
sandbox; echo k > "$KEYF"
PROJ="$SB/home/.claude/projects"
mkdir -p "$PROJ/proj-a" "$PROJ/proj-b"
cp "$FIX/transcript_correction.jsonl" "$PROJ/proj-a/sess-aaaa.jsonl"
cp "$FIX/transcript_deep.jsonl"       "$PROJ/proj-a/sess-bbbb.jsonl"
cp "$FIX/transcript_instruction.jsonl" "$PROJ/proj-b/sess-cccc.jsonl"
# One canned reply per transcript: select every user id it is shown.
start_watch_mock "ALL_USER"
out=$(runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  bash "$SCRIPTS/dk_backfill.sh" --transcripts "$PROJ" --target "$SB")
n1=$(lines "$RAW")
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  bash "$SCRIPTS/dk_backfill.sh" --transcripts "$PROJ" --target "$SB" >/dev/null
n2=$(lines "$RAW")
stop_mock
if [ "$n1" -ge 3 ] && [ "$n2" = "$n1" ] \
   && grep -qF "you skipped the config step" "$RAW" \
   && printf '%s' "$out" | grep -q "scanned 3 transcripts"; then ok
else bad "n1=$n1 n2=$n2 out: $out"; fi

t "38b. backfill mines history by READING it"
sandbox; echo k > "$KEYF"
PROJ="$SB/home/.claude/projects/p"; mkdir -p "$PROJ"
cp "$FIX/transcript_real_missed.jsonl" "$PROJ/s1.jsonl"     # zero phrase matches
ids=$(python3 -c "
import json
ids=[json.loads(l)['uuid'] for l in open('$FIX/transcript_real_missed.jsonl')]
print(json.dumps({'active':[],'alert':None,'steering':[{'id':i,'source':'human','kind':'correction'} for i in ids[:2]]}))")
start_watch_mock "$ids"
out=$(runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  bash "$SCRIPTS/dk_backfill.sh" --transcripts "$PROJ" --target "$SB")
stop_mock
if [ "$(lines "$RAW")" -ge 2 ] && grep -q '"signal": "semantic"' "$RAW" \
   && printf '%s' "$out" | grep -q "new entries"; then ok; else bad "out: $out raw=$(lines "$RAW")"; fi

t "38c. backfill warns loudly when it mines nothing at all"
sandbox
PROJ="$SB/home/.claude/projects/p"; mkdir -p "$PROJ"
cp "$FIX/transcript_real_missed.jsonl" "$PROJ/s1.jsonl"
out=$(runenv bash "$SCRIPTS/dk_backfill.sh" --transcripts "$PROJ" --target "$SB")
if printf '%s' "$out" | grep -q "found NOTHING"; then ok; else bad "out: $out"; fi

t "39. backfill refuses a target with no .claude/memory"
sandbox
if ! runenv bash "$SCRIPTS/dk_backfill.sh" --transcripts "$SB" --target "$SB/home" 2>/dev/null; then ok; else bad "should have failed"; fi

# =============================================================================
echo "== install =="

t "40. install.sh bootstraps a fresh project (local fallback), hooks merged, idempotent"
SB="$(mktemp -d "$TMPBASE/sb.XXXXXX")"; mkdir -p "$SB/home"
env HOME="$SB/home" DK_REPO_URL="/nonexistent/nowhere.git" \
  bash "$REPO/install.sh" --target "$SB" >/dev/null 2>&1
ok1=yes
[ -f "$SB/.claude/vendor/dk-mode/scripts/dk_capture.sh" ] || ok1=no
[ -f "$SB/.claude/memory/dk_rules.md" ] || ok1=no
grep -qF "dk_capture.sh" "$SB/.claude/settings.json" 2>/dev/null || ok1=no
grep -qF "dk_recall.sh" "$SB/.claude/settings.json" 2>/dev/null || ok1=no
env HOME="$SB/home" DK_REPO_URL="/nonexistent/nowhere.git" \
  bash "$REPO/install.sh" --target "$SB" >/dev/null 2>&1
n_stop=$(python3 -c 'import json;print(len(json.load(open("'"$SB"'/.claude/settings.json"))["hooks"]["Stop"]))')
if [ "$ok1" = "yes" ] && [ "$n_stop" = "1" ] \
   && python3 -c 'import json;json.load(open("'"$SB"'/.claude/settings.json"))' 2>/dev/null; then ok; else bad "ok1=$ok1 n_stop=$n_stop"; fi

t "41. install.sh preserves existing hooks when merging"
SB="$(mktemp -d "$TMPBASE/sb.XXXXXX")"; mkdir -p "$SB/.claude" "$SB/home"
cat > "$SB/.claude/settings.json" <<'EOF'
{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "bash existing_hook.sh"}]}]}}
EOF
env HOME="$SB/home" DK_REPO_URL="/nonexistent/nowhere.git" \
  bash "$REPO/install.sh" --target "$SB" >/dev/null 2>&1
if grep -qF "existing_hook.sh" "$SB/.claude/settings.json" \
   && grep -qF "dk_capture.sh" "$SB/.claude/settings.json"; then ok; else bad "$(cat "$SB/.claude/settings.json")"; fi

t "42. install.sh --no-hooks skips registration and prints the manual block"
SB="$(mktemp -d "$TMPBASE/sb.XXXXXX")"; mkdir -p "$SB/home"
out=$(env HOME="$SB/home" DK_REPO_URL="/nonexistent/nowhere.git" \
  bash "$REPO/install.sh" --target "$SB" --no-hooks 2>&1)
if [ ! -f "$SB/.claude/settings.json" ] \
   && printf '%s' "$out" | grep -q "NOT registered" \
   && printf '%s' "$out" | grep -qF 'bash \"${CLAUDE_PROJECT_DIR}' ; then ok; else bad "out: $out"; fi

t "43. install.sh never overwrites an existing dk_rules.md"
SB="$(mktemp -d "$TMPBASE/sb.XXXXXX")"; mkdir -p "$SB/.claude/memory" "$SB/home"
echo "PRECIOUS USER MEMORY" > "$SB/.claude/memory/dk_rules.md"
env HOME="$SB/home" DK_REPO_URL="/nonexistent/nowhere.git" \
  bash "$REPO/install.sh" --target "$SB" --no-hooks >/dev/null 2>&1
if grep -q "PRECIOUS USER MEMORY" "$SB/.claude/memory/dk_rules.md"; then ok; else bad "overwritten"; fi

# =============================================================================
echo "== approval mode =="

t "44. pending items -> nudge line with count; approved-only note; no nudge when none pending"
sandbox; cp "$FIX/rules_mixed_approval.md" "$RULES"
out=$(run_recall)
sandbox; out2=$(run_recall)   # template has no pending items
if printf '%s' "$out" | grep -q "(dk-mode: 2 proposed item(s) awaiting review" \
   && printf '%s' "$out" | grep -q "Done-claims" \
   && ! printf '%s' "$out" | grep -q "MEMORY.md" \
   && ! printf '%s' "$out2" | grep -q "proposed item"; then ok; else bad "out: $out"; fi

t "45. approval-mode consolidation accepts a clean response (pending held out of note)"
consolidate_sandbox
start_mock rewritten_rules_approval_ok.md
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" DK_APPROVAL=1 \
  python3 "$SCRIPTS/dk_consolidate.py"
stop_mock
if grep -q "^consolidated_through: 4" "$RULES" \
   && grep -q '\*\*Status:\*\* pending' "$RULES" \
   && grep -q "| dk-consolidate | processed 4 entries" "$MEMLOG"; then ok; else bad "log: $(cat "$MEMLOG")"; fi

t "46. approval-mode consolidation REJECTS a response leaking a pending line into the note"
consolidate_sandbox; rules_sum=$(checksum "$RULES")
start_mock rewritten_rules_approval_leak.md
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" DK_APPROVAL=1 \
  python3 "$SCRIPTS/dk_consolidate.py"
stop_mock
if grep -q "FAILED: model output rejected: pending item leaked" "$MEMLOG" \
   && [ "$(checksum "$RULES")" = "$rules_sum" ]; then ok; else bad "log: $(cat "$MEMLOG")"; fi

t "47. dk_review: list -> approve takes effect immediately -> reject preserves under Retired"
sandbox; cp "$FIX/rules_mixed_approval.md" "$RULES"
lst=$(runenv python3 "$SCRIPTS/dk_review.py" --list)
runenv python3 "$SCRIPTS/dk_review.py" --approve 1 >/dev/null
after_approve=$(sed -n '/<!-- inject:start -->/,/<!-- inject:end -->/p' "$RULES")
runenv python3 "$SCRIPTS/dk_review.py" --reject 1 >/dev/null
retired=$(sed -n '/^## Retired/,$p' "$RULES")
fails=""
printf '%s' "$lst" | grep -q "1. Rabbit-holing on point fixes" || fails="$fails list1"
printf '%s' "$lst" | grep -q "2. Check MEMORY.md before building" || fails="$fails list2"
printf '%s' "$after_approve" | grep -q "step back and check" || fails="$fails note-not-rebuilt"
grep -A1 "Rabbit-holing" "$RULES" | grep -q '\*\*Status:\*\* approved' || fails="$fails not-approved"
printf '%s' "$retired" | grep -q "Check MEMORY.md before building" || fails="$fails not-retired"
printf '%s' "$retired" | grep -q "rejected $(date +%F)" || fails="$fails no-reject-stamp"
[ "$(runenv python3 "$SCRIPTS/dk_review.py" --list)" = "no proposed items awaiting review" ] || fails="$fails still-pending"
if [ -z "$fails" ]; then ok; else bad "$fails"; fi

t "48. dk_review refuses to write while the consolidate lock is held"
sandbox; cp "$FIX/rules_mixed_approval.md" "$RULES"; rules_sum=$(checksum "$RULES")
mkdir "$SB/.claude/memory/.dk-consolidate.lock"
if ! runenv python3 "$SCRIPTS/dk_review.py" --approve 1 >/dev/null 2>&1 \
   && [ "$(checksum "$RULES")" = "$rules_sum" ]; then ok; else bad "wrote under lock"; fi
rmdir "$SB/.claude/memory/.dk-consolidate.lock"

t "49. install.sh delivers the /dk-review skill into the target project"
SB="$(mktemp -d "$TMPBASE/sb.XXXXXX")"; mkdir -p "$SB/home"
env HOME="$SB/home" DK_REPO_URL="/nonexistent/nowhere.git" \
  bash "$REPO/install.sh" --target "$SB" --no-hooks >/dev/null 2>&1
if [ -f "$SB/.claude/skills/dk-review/SKILL.md" ]; then ok; else bad "skill missing"; fi

# =============================================================================
echo "== local backend (DK_BACKEND=openai) =="

start_openai_mock() {  # start_openai_mock <md-fixture> [delay]
  local portf="$TMPBASE/oport.$RANDOM"
  python3 "$TESTS/mock_openai_api.py" "$FIX/$1" "$portf" "${2:-0}" &
  MOCK_PID=$!
  for _ in $(seq 1 50); do [ -s "$portf" ] && break; sleep 0.1; done
  MOCK_PORT="$(cat "$portf")"
}

t "50. consolidates against a local OpenAI-compatible server with NO api key"
consolidate_sandbox; rm -f "$KEYF"; raw_sum=$(checksum "$RAW")
start_openai_mock rewritten_rules_good.md
env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" ANTHROPIC_API_KEY="" DK_KEY_FILE="$KEYF" \
  DK_BACKEND=openai DK_MODELS="qwen2.5:14b-instruct" \
  DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/chat/completions" \
  python3 "$SCRIPTS/dk_consolidate.py"
stop_mock
if grep -q "^consolidated_through: 4" "$RULES" \
   && grep -q "| dk-consolidate | processed 4 entries" "$MEMLOG" \
   && grep -q "qwen2.5:14b-instruct" "$MEMLOG" \
   && [ "$(checksum "$RAW")" = "$raw_sum" ]; then ok; else bad "log: $(cat "$MEMLOG")"; fi

t "51. local backend output goes through the same validator (garbage rejected)"
consolidate_sandbox; rm -f "$KEYF"; rules_sum=$(checksum "$RULES")
start_openai_mock rewritten_rules_garbage.md
env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" ANTHROPIC_API_KEY="" DK_KEY_FILE="$KEYF" \
  DK_BACKEND=openai DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/chat/completions" \
  python3 "$SCRIPTS/dk_consolidate.py"
stop_mock
if grep -q "| dk-consolidate | FAILED" "$MEMLOG" \
   && [ "$(checksum "$RULES")" = "$rules_sum" ]; then ok; else bad "log: $(cat "$MEMLOG")"; fi

t "52. recall kicks with no key when the backend is local, still skips when hosted+keyless"
kick_sandbox; rm -f "$KEYF"
kick_recall DK_BACKEND=openai >/dev/null
local_kicked=$(wait_kicked && echo yes || echo no)
kick_sandbox; rm -f "$KEYF"
kick_recall >/dev/null; sleep 0.5
hosted_kicked=$([ -f "$SB/kicked" ] && echo yes || echo no)
if [ "$local_kicked" = "yes" ] && [ "$hosted_kicked" = "no" ]; then ok; else bad "local=$local_kicked hosted=$hosted_kicked"; fi

# =============================================================================
echo "== runtime monitor (dk_watch) =="

run_watch() {  # run_watch <transcript> [extra env...]
  local tp="$1"; shift
  runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" "$@" \
    python3 "$SCRIPTS/dk_watch.py" "$tp"
}

watch_sandbox() { sandbox; cp "$FIX/rules_mixed_approval.md" "$RULES"; echo k > "$KEYF"; }

t "53. selects only the live rule and renders its reminder (model picks, script renders)"
watch_sandbox
start_watch_mock '{"active":[1],"alert":null}'
run_watch "$FIX/transcript_doneclaim.jsonl"; stop_mock
# id 1 = first approved item in the fixture = "Claiming done without verifying"
if grep -q "never say a check passed unless you ran it this turn" "$ACTIVEF" \
   && grep -q "Relevant to what you are doing right now" "$ACTIVEF"; then ok; else bad "active: $(cat "$ACTIVEF" 2>/dev/null)"; fi

t "53b. a live item is rendered as an episode: what it looks like, what to do, what earned it"
a="$ACTIVEF"
if grep -q "what it looks like:" "$a" && grep -q "so: " "$a" && grep -q "earned by:" "$a"; then ok; else bad "$(cat "$a")"; fi

t "54. recall prefers the live selection over the static note"
out=$(run_recall)
if printf '%s' "$out" | grep -q "never say a check passed unless you ran it this turn" \
   && ! printf '%s' "$out" | grep -q "Self-steering - check before acting"; then ok; else bad "out: $out"; fi

t "53c. one chat's selection is never injected into another chat's prompt"
sandbox; cp "$FIX/rules_mixed_approval.md" "$RULES"; echo k > "$KEYF"
start_watch_mock '{"active":[1],"alert":"sibling chat verdict","steering":[]}'
runenv DK_SESSION_ID=chat-AAA DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_doneclaim.jsonl"
stop_mock
wrote_a=$([ -s "$SB/.claude/memory/.dk_active.chat-AAA" ] && echo yes || echo no)
# a DIFFERENT chat asks for its prompt
out=$(printf '{"prompt":"x","session_id":"chat-BBB"}' | runenv bash "$SCRIPTS/dk_recall.sh")
# and the owning chat still gets it
out_a=$(printf '{"prompt":"x","session_id":"chat-AAA"}' | runenv bash "$SCRIPTS/dk_recall.sh")
if [ "$wrote_a" = "yes" ] \
   && ! printf '%s' "$out" | grep -q "sibling chat verdict" \
   && printf '%s' "$out" | grep -q "Self-steering - check before acting" \
   && printf '%s' "$out_a" | grep -q "sibling chat verdict"; then ok; else bad "B saw: $out"; fi

t "55. empty selection = nothing live -> injects NOTHING (not the static note)"
watch_sandbox
start_watch_mock '{"active":[],"alert":null}'
run_watch "$FIX/transcript_doneclaim.jsonl"; stop_mock
out=$(run_recall)
if [ ! -s "$ACTIVEF" ] \
   && ! printf '%s' "$out" | grep -q "self-steering"; then ok; else bad "out: $out"; fi

t "56. a situational alert is injected above the rules"
watch_sandbox
start_watch_mock '{"active":[1],"alert":"You just said the tests pass without running them this turn."}'
run_watch "$FIX/transcript_doneclaim.jsonl"; stop_mock
if head -3 "$ACTIVEF" | grep -q "without running them this turn"; then ok; else bad "$(cat "$ACTIVEF")"; fi

t "57. pending items can never be selected (ids cover approved only)"
watch_sandbox
# fixture has 1 approved + 2 pending; ask for ids 2 and 3 (out of range)
start_watch_mock '{"active":[2,3],"alert":null}'
run_watch "$FIX/transcript_doneclaim.jsonl"; stop_mock
if [ ! -s "$ACTIVEF" ]; then ok; else bad "leaked: $(cat "$ACTIVEF")"; fi

t "58. malformed model output -> nothing written, old selection left to expire"
watch_sandbox; printf 'PREVIOUS
' > "$ACTIVEF"
start_watch_mock 'sure! here are the rules I think apply: probably all of them'
run_watch "$FIX/transcript_doneclaim.jsonl"; stop_mock
if [ "$(cat "$ACTIVEF")" = "PREVIOUS" ]; then ok; else bad "clobbered"; fi

t "59. stale selection is ignored; recall falls back to the static note"
watch_sandbox; printf '<self-steering>
STALE
</self-steering>
' > "$ACTIVEF"
backdate "$ACTIVEF" 1
out=$(run_recall)
if ! printf '%s' "$out" | grep -q "STALE" \
   && printf '%s' "$out" | grep -q "Self-steering - check before acting"; then ok; else bad "out: $out"; fi

t "60. no key on a hosted backend -> watcher no-ops, static note still injected"
watch_sandbox; rm -f "$KEYF"
MOCK_PORT=1 run_watch "$FIX/transcript_doneclaim.jsonl"
out=$(run_recall)
if [ ! -e "$ACTIVEF" ] \
   && printf '%s' "$out" | grep -q "Self-steering - check before acting"; then ok; else bad "out: $out"; fi

t "61. DK_WATCH=0 disables the layer entirely"
watch_sandbox
start_watch_mock '{"active":[1],"alert":null}'
run_watch "$FIX/transcript_doneclaim.jsonl" DK_WATCH=0; stop_mock
if [ ! -e "$ACTIVEF" ]; then ok; else bad "ran anyway"; fi

t "62. watcher works against a local OpenAI-compatible server with no key"
watch_sandbox; rm -f "$KEYF"
start_watch_mock '{"active":[1],"alert":null}'
runenv DK_BACKEND=openai \
  DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/chat/completions" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_doneclaim.jsonl"
stop_mock
if grep -q "never say a check passed" "$ACTIVEF"; then ok; else bad "active: $(cat "$ACTIVEF" 2>/dev/null)"; fi

t "63. capture hook kicks the watcher (and not during backfill)"
sandbox; cp "$FIX/rules_mixed_approval.md" "$RULES"; echo k > "$KEYF"
mkdir -p "$SB/bin"
cat > "$SB/bin/dk_watch.py" <<'STUB'
import os, sys
open(os.path.join(os.environ["CLAUDE_PROJECT_DIR"], "watched"), "w").write(sys.argv[1])
STUB
cp "$SCRIPTS/dk_capture.sh" "$SB/bin/dk_capture.sh"
payload "$FIX/transcript_correction.jsonl" | runenv bash "$SB/bin/dk_capture.sh"
for _ in $(seq 1 30); do [ -f "$SB/watched" ] && break; sleep 0.1; done
kicked=$([ -f "$SB/watched" ] && echo yes || echo no)
rm -f "$SB/watched"; : > "$RAW"
payload "$FIX/transcript_correction.jsonl" | runenv DK_SCAN_LINES=0 bash "$SB/bin/dk_capture.sh"
sleep 0.5
backfill_kicked=$([ -f "$SB/watched" ] && echo yes || echo no)
if [ "$kicked" = "yes" ] && [ "$backfill_kicked" = "no" ]; then ok; else bad "live=$kicked backfill=$backfill_kicked"; fi

# =============================================================================
echo "== autonomous operation (no human in the loop) =="

t "64. self-correction in an agent's own chat is mined (source=self), no human message needed"
sandbox; echo k > "$KEYF"
start_watch_mock '{"active":[],"alert":null,"steering":[{"id":"a-2","source":"self","kind":"self-correction"}]}'
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_autonomous.jsonl"
stop_mock
if [ "$(lines "$RAW")" = "1" ] \
   && grep -q '"source": "self"' "$RAW" \
   && grep -qF "I never ran the court gate" "$RAW"; then ok; else bad "raw: $(cat "$RAW")"; fi

t "64b. an assistant id is source=self even if the model labels it human"
sandbox; echo k > "$KEYF"
start_watch_mock '{"active":[],"alert":null,"steering":[{"id":"a-2","source":"human","kind":"correction"}]}'
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_autonomous.jsonl"
stop_mock
if grep -q '"source": "self"' "$RAW"; then ok; else bad "raw: $(cat "$RAW")"; fi

t "65. ordinary assistant chatter is not mistaken for self-correction"
sandbox; run_capture "$FIX/transcript_assistant_clean.jsonl"
if [ ! -s "$RAW" ]; then ok; else bad "raw: $(cat "$RAW")"; fi

t "66. dk_signal records a machine steering event, dedupes identical repeats"
sandbox
runenv python3 "$SCRIPTS/dk_signal.py" --kind verdict --source court \
  --text "FIX: heading promises a calculator the page does not contain" \
  --context "shipped /heating-costs" --target heating-costs
runenv python3 "$SCRIPTS/dk_signal.py" --kind verdict --source court \
  --text "FIX: heading promises a calculator the page does not contain" \
  --context "shipped /heating-costs" --target heating-costs
if [ "$(lines "$RAW")" = "1" ] && grep -q '"source": "court"' "$RAW" \
   && grep -q '"target": "heating-costs"' "$RAW" \
   && grep -q "| dk-signal | court/verdict" "$MEMLOG"; then ok; else bad "raw: $(cat "$RAW")"; fi

t "67. dk_signal is a no-op (exit 0) where dk-mode is not installed"
out=$(CLAUDE_PROJECT_DIR="$TMPBASE/nowhere" python3 "$SCRIPTS/dk_signal.py" --text "x" 2>&1); rc=$?
if [ "$rc" = "0" ] && [ -z "$out" ]; then ok; else bad "rc=$rc out: $out"; fi

t "68. DK_APPROVAL=auto promotes a pending item at the count threshold and rebuilds the note"
consolidate_sandbox; cp "$FIX/rules_auto_approve.md" "$RULES"
start_mock rewritten_rules_auto.md
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" DK_APPROVAL=auto \
  python3 "$SCRIPTS/dk_consolidate.py"
stop_mock
# fixture response carries Count 3 on the rabbit-holing item -> auto-approved
note=$(sed -n '/<!-- inject:start -->/,/<!-- inject:end -->/p' "$RULES")
if grep -A2 "Rabbit-holing" "$RULES" | grep -q '\*\*Status:\*\* approved' \
   && printf '%s' "$note" | grep -q "step back and check"; then ok; else bad "note: $note"; fi

t "69. DK_APPROVAL=auto leaves a low-count item pending (repetition is the evidence)"
if grep -A2 "Check MEMORY.md before building" "$RULES" | grep -q '\*\*Status:\*\* pending' \
   && ! printf '%s' "$note" | grep -q "always check MEMORY.md"; then ok; else bad "$(grep -A3 'Check MEMORY' "$RULES")"; fi

t "70. end to end with no human: self-correction -> mined -> live injection"
sandbox; echo k > "$KEYF"
cp "$FIX/rules_mixed_approval.md" "$RULES"
start_watch_mock '{"active":[1],"alert":"You said checks passed without running the gate.","steering":[{"id":"a-2","source":"self","kind":"self-correction"}]}'
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_autonomous.jsonl"
stop_mock
out=$(run_recall)
if [ "$(lines "$RAW")" = "1" ] \
   && grep -q '"source": "self"' "$RAW" \
   && printf '%s' "$out" | grep -q "without running the gate" \
   && printf '%s' "$out" | grep -q "never say a check passed"; then ok; else bad "out: $out raw: $(cat "$RAW")"; fi

# =============================================================================
echo "== semantic capture (what the phrase list cannot see) =="

t "71. harness pseudo-user messages are never captured as the user's words"
sandbox
cat > "$TMPBASE/noise.jsonl" <<'NOISE'
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"<task-notification>agent finished: try again failed, you didn't handle it</task-notification>"}]},"uuid":"n-1","isSidechain":false}
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"<system-reminder>from now on always check this</system-reminder>"}]},"uuid":"n-2","isSidechain":false}
NOISE
run_capture "$TMPBASE/noise.jsonl" DK_WATCH=0
if [ ! -s "$RAW" ]; then ok; else bad "captured noise: $(cat "$RAW")"; fi

t "72. REAL corrections from a live transcript that the phrase list misses entirely"
sandbox
run_capture "$FIX/transcript_real_missed.jsonl" DK_WATCH=0 DK_SCAN_LINES=0
missed=$(lines "$RAW")
if [ "$missed" = "0" ]; then ok; else bad "phrase list unexpectedly matched $missed"; fi

t "73. the watcher reads those same messages and captures them verbatim"
sandbox; echo k > "$KEYF"
# the model returns ids only; the script copies the text from the transcript
ids=$(python3 -c "
import json
ids=[json.loads(l)['uuid'] for l in open('$FIX/transcript_real_missed.jsonl')]
print(json.dumps({'active':[], 'alert':None,
  'steering':[{'id':i,'kind':'correction'} for i in ids[:3]]}))")
start_watch_mock "$ids"
# The fixture is five consecutive user messages, which no real conversation
# looks like, so the window has to be told to reach back past two of them.
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" DK_WATCH_EXCHANGES=20 \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_real_missed.jsonl"
stop_mock
if [ "$(lines "$RAW")" = "3" ] \
   && grep -q '"signal": "semantic"' "$RAW" \
   && grep -qF "shit way to test" "$RAW" \
   && grep -q "| dk-capture | 3 semantic entries (read, not matched)" "$MEMLOG"; then ok; else bad "raw: $(cat "$RAW")"; fi

t "73a. a captured correction carries the exchange that led to it"
sandbox; echo k > "$KEYF"
uid=$(python3 -c "
import json
print([json.loads(l)['uuid'] for l in open('$FIX/transcript_correction.jsonl') if json.loads(l)['type']=='user'][-1])")
start_watch_mock "{\"active\":[],\"alert\":null,\"steering\":[{\"id\":\"$uid\",\"kind\":\"correction\"}]}"
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_correction.jsonl"
stop_mock
# the fixture's assistant turn claimed "All 12 tests pass" before the correction
if grep -q "All 12 tests pass" "$RAW" && grep -q '"signal": "semantic"' "$RAW"; then ok; else bad "no context: $(cat "$RAW")"; fi

t "73b. empty model content (thinking model burning its budget) writes nothing, clobbers nothing"
sandbox; echo k > "$KEYF"; printf 'PREVIOUS\n' > "$ACTIVEF"
start_watch_mock ''
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_correction.jsonl"
stop_mock
if [ "$(cat "$ACTIVEF")" = "PREVIOUS" ] && [ ! -s "$RAW" ]; then ok; else bad "active=$(cat "$ACTIVEF")"; fi

t "73c. a failing runtime monitor is announced, not silent"
sandbox; echo k > "$KEYF"
printf 'watch_consecutive_failed=3\n' > "$STATE"
out=$(run_recall)
if printf '%s' "$out" | grep -q "runtime monitor has failed its last 3 runs"; then ok; else bad "out: $out"; fi

t "73d. an unparseable DK_INTERVAL falls back to the default, not to per-turn"
sandbox; echo k > "$KEYF"
mkdir -p "$SB/stub"; cp "$SCRIPTS/dk_recall.sh" "$SB/stub/dk_recall.sh"
cat > "$SB/stub/dk_consolidate.py" <<'STUB'
import os
open(os.path.join(os.environ["CLAUDE_PROJECT_DIR"], "kicked"), "w").write("1")
STUB
echo '{"ts":"x","uuid":"k1"}' >> "$RAW"
write_state "$(epoch_ago 3600)" success 0      # 1h ago: due at per-turn, not at 7d
printf '{"prompt":"x"}' | runenv DK_INTERVAL="7dd" bash "$SB/stub/dk_recall.sh" >/dev/null
sleep 0.5
if [ ! -f "$SB/kicked" ]; then ok; else bad "junk interval behaved as per-turn"; fi

t "74. semantic capture cannot invent text - unknown ids are dropped"
sandbox; echo k > "$KEYF"
start_watch_mock '{"active":[],"alert":null,"steering":[{"id":"does-not-exist","kind":"correction"},{"id":"also-fake","kind":"instruction"}]}'
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_real_missed.jsonl"
stop_mock
if [ ! -s "$RAW" ]; then ok; else bad "invented: $(cat "$RAW")"; fi

t "76. cold start: no rules yet, semantic capture still works (that is how rules begin)"
sandbox; echo k > "$KEYF"   # template rules file has zero approved items
start_watch_mock '{"active":[],"alert":null,"steering":[{"id":"u-c-2","kind":"correction"}]}'
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_correction.jsonl"
stop_mock
if [ "$(lines "$RAW")" = "1" ] && grep -q '"signal": "semantic"' "$RAW"; then ok; else bad "raw: $(cat "$RAW")"; fi

# =============================================================================
# Live test: real key, real endpoint, real model judgment. Opt-in.
if [ "${1:-}" = "--live" ]; then
  echo "== live (real API) =="
  if [ -z "${ANTHROPIC_API_KEY:-}" ] && { [ -z "${DK_KEY_FILE:-}" ] || [ ! -f "${DK_KEY_FILE:-}" ]; }; then
    t "L1. live consolidation"; bad "no key: set ANTHROPIC_API_KEY or DK_KEY_FILE"
  else
    t "L1. live consolidation: real model, valid file, merge + verbatim + discard"
    sandbox
    cp "$FIX/raw_entries.jsonl" "$RAW"
    raw_sum=$(checksum "$RAW")
    env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" \
      ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" DK_KEY_FILE="${DK_KEY_FILE:-}" \
      python3 "$SCRIPTS/dk_consolidate.py"
    fails=""
    grep -q "| dk-consolidate | processed 4 entries" "$MEMLOG" || fails="$fails no-success-heartbeat"
    grep -q "^consolidated_through: 4" "$RULES" || fails="$fails bookmark"
    grep -qF "from now on always check MEMORY.md" "$RULES" || fails="$fails verbatim-evidence"
    grep -qE 'Count:\*\* [2-9]' "$RULES" || fails="$fails merge-count"
    grep -iE '^### .*wifi' "$RULES" >/dev/null && fails="$fails wifi-not-discarded"
    [ "$(checksum "$RAW")" = "$raw_sum" ] || fails="$fails raw-modified"
    if [ -z "$fails" ]; then ok; else bad "$fails; log: $(cat "$MEMLOG")"; fi
  fi
fi

# --- 77-80: manual-run ergonomics -------------------------------------------
# Walking the README as a stranger found these: a manual consolidate ran
# against dk-mode's OWN checkout instead of the project just mined, and said
# nothing at all while doing it. Silent no-op is the failure mode this whole
# project exists to prevent, so both are pinned here.

t "77. --target routes a manual consolidate to the named project, not the script's own tree"
sandbox
cp "$FIX/raw_entries.jsonl" "$RAW"
out=$(cd / && env HOME="$SB/home" ANTHROPIC_API_KEY="" DK_KEY_FILE="$SB/home/nokey" \
  python3 "$SCRIPTS/dk_consolidate.py" --drain --target "$SB" 2>&1)
case "$out" in
  *"project: $SB"*) ok ;;
  *) bad "did not report the --target project; got: $out" ;;
esac

t "78. a manual consolidate with no key SAYS so instead of exiting silently"
out=$(cd / && env HOME="$SB/home" ANTHROPIC_API_KEY="" DK_KEY_FILE="$SB/home/nokey" \
  python3 "$SCRIPTS/dk_consolidate.py" --drain --target "$SB" 2>&1)
case "$out" in
  *"no API key"*) ok ;;
  *) bad "silent no-op returned; got: [$out]" ;;
esac

t "79. --target after the item numbers does not get parsed as an item number"
sandbox
python3 - "$RULES" <<'PYX'
import re, sys
p = sys.argv[1]; t = open(p).read()
item = ("### Claims done without verifying\n"
        "**Reminder:** never say a check passed unless you ran it this turn\n"
        "**Status:** pending\n**Count:** 2\n\n")
t = re.sub(r"(## Mistake Patterns\s*\n)", r"\1\n" + item, t, count=1)
open(p, "w").write(t)
PYX
out=$(cd / && env HOME="$SB/home" python3 "$SCRIPTS/dk_review.py" \
  --approve 1 --target "$SB" 2>&1)
if printf '%s' "$out" | grep -q "^approved:" \
   && grep -q '\*\*Status:\*\* approved' "$RULES"; then ok
else bad "approve+target failed; got: $out"; fi

t "81. the watcher runs on a turn with NO trigger phrase (it is the real miner)"
sandbox
mkdir -p "$SB/bin"
cat > "$SB/bin/dk_watch.py" <<'PYX'
import sys, os
open(os.environ["WATCH_MARK"], "a").write("ran\n")
PYX
cp "$SCRIPTS/dk_capture.sh" "$SB/bin/dk_capture.sh"
python3 - "$SB/t.jsonl" <<'PYX'
import json, sys
r = {"type": "user", "uuid": "u1", "isSidechain": False,
     "timestamp": "2026-08-26T00:00:00Z",
     "message": {"role": "user", "content": "bit lame, simplify it"}}
open(sys.argv[1], "w").write(json.dumps(r) + "\n")
PYX
MARK="$SB/watch.mark"
printf '{"transcript_path":"%s","session_id":"s1"}' "$SB/t.jsonl" \
  | env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" WATCH_MARK="$MARK" \
        bash "$SB/bin/dk_capture.sh"
sleep 1
if [ -s "$MARK" ]; then ok; else bad "watcher never ran on a no-phrase turn"; fi

t "82. DK_WATCH=0 still suppresses the watcher"
rm -f "$MARK"
printf '{"transcript_path":"%s","session_id":"s1"}' "$SB/t.jsonl" \
  | env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" WATCH_MARK="$MARK" DK_WATCH=0 \
        bash "$SB/bin/dk_capture.sh"
sleep 1
if [ -s "$MARK" ]; then bad "watcher ran despite DK_WATCH=0"; else ok; fi

# =============================================================================
echo "== wiring: enter ONLY through the real hook command =="
# The suite had 89 green tests while the miner never ran on a normal turn.
# Every test called the component it was testing directly, so none could see
# that nothing reached it. These tests take the command string out of the
# settings.json that install.sh actually writes, and run THAT. If a guard is
# ever put in front of the miner again, these fail and the unit tests do not.

hook_cmd() {  # hook_cmd <Stop|UserPromptSubmit> <settings.json>
  python3 -c "
import json, sys
d = json.load(open(sys.argv[2]))
for e in d['hooks'][sys.argv[1]]:
    for h in e['hooks']:
        if 'dk_' in h['command']:
            print(h['command']); raise SystemExit
" "$1" "$2"
}

t "83. the Stop hook mines a turn that contains no trigger phrase at all"
sandbox; echo k > "$KEYF"
PROJ="$SB/proj"; mkdir -p "$PROJ"
# DK_REPO_URL is deliberately unreachable: it forces install.sh to copy the
# local working tree instead of cloning from GitHub. Without it these tests
# install the LAST PUSHED code and pass no matter what is broken here - which
# is exactly what they did when first written.
(cd "$REPO" && DK_REPO_URL="file:///nonexistent-$$" ./install.sh --target "$PROJ" >/dev/null 2>&1)
grep -q "nohup python3" "$PROJ/.claude/vendor/dk-mode/scripts/dk_capture.sh" \
  || bad "vendor copy is not the working tree - test would be vacuous"
python3 - "$SB/t.jsonl" <<'PYX'
import json, sys
rows = [
  {"type": "assistant", "uuid": "x1", "isSidechain": False,
   "timestamp": "2026-08-26T00:00:00Z",
   "message": {"role": "assistant", "content": "I built a new helper for this."}},
  {"type": "user", "uuid": "x2", "isSidechain": False,
   "timestamp": "2026-08-26T00:01:00Z",
   "message": {"role": "user", "content": "bit lame, simplify it"}},
]
open(sys.argv[1], "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
PYX
# A realistic project has at least one approved rule; without one the
# selection has nothing to select and the test exercises an empty path.
cp "$FIX/rules_mixed_approval.md" "$PROJ/.claude/memory/dk_rules.md"
start_watch_mock "ALL_USER"
CMD=$(hook_cmd Stop "$PROJ/.claude/settings.json")
printf '{"transcript_path":"%s","session_id":"wire1234"}' "$SB/t.jsonl" \
  | env CLAUDE_PROJECT_DIR="$PROJ" HOME="$SB/home" DK_KEY_FILE="$KEYF" \
        DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
        bash -c "$CMD"
for _ in $(seq 1 40); do [ -s "$PROJ/.claude/memory/dk.jsonl" ] && break; sleep 0.25; done
stop_mock
if grep -qF "bit lame, simplify it" "$PROJ/.claude/memory/dk.jsonl" 2>/dev/null; then ok
else bad "hook did not mine it; raw: $(cat "$PROJ/.claude/memory/dk.jsonl" 2>/dev/null)"; fi

t "84. the UserPromptSubmit hook injects what the Stop hook's run selected"
CMD=$(hook_cmd UserPromptSubmit "$PROJ/.claude/settings.json")
out=$(printf '{"prompt":"ship it","session_id":"wire1234"}' \
  | env CLAUDE_PROJECT_DIR="$PROJ" HOME="$SB/home" bash -c "$CMD")
# Assert the LIVE selection, not just the tag: the static fallback note also
# prints <self-steering>, so the first version of this test passed even when
# the Stop hook had mined nothing at all.
if printf '%s' "$out" | grep -q "MOCK-LIVE-ALERT"; then ok
else bad "static fallback, not the live selection; got: [$out]"; fi

t "85. no path in dk_capture.sh can exit before the miner is launched"
# Structural, deliberately. This is the exact regression: the launch sat below
# a guard's early exit, so it never ran and every unit test still passed.
# Must match the LAUNCH, not a comment naming the file. Written as a grep for
# any dk_watch.py mention first time round, which matched a header comment on
# line 5 and therefore counted zero guards above it - it could never fail.
launch=$(grep -n "nohup python3.*dk_watch.py" "$SCRIPTS/dk_capture.sh" | head -1 | cut -d: -f1)
[ -n "$launch" ] || launch=999
guards=$(awk -v L="$launch" 'NR < L && /exit 0/ && !/^#/ {n++} END {print n+0}' \
         "$SCRIPTS/dk_capture.sh")
# Two are legitimate and must stay: no memory dir, and no readable transcript.
if [ "$guards" -le 2 ]; then ok
else bad "$guards early exits sit above the miner launch (max 2 allowed)"; fi

t "86. an alert still reaches the prompt when no rule is approved yet"
# The write was gated on `rules` alone, so a project with nothing approved
# threw the alert away. An alert is generated from the conversation and needs
# no rules at all - a brand new install is exactly when a warning is useful.
sandbox; echo k > "$KEYF"
start_watch_mock '{"active":[],"alert":"You are about to claim done without running it.","steering":[]}'
runenv DK_SESSION_ID=freshsess DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_autonomous.jsonl"
stop_mock
out=$(printf '{"prompt":"x","session_id":"freshsess"}' | runenv bash "$SCRIPTS/dk_recall.sh")
if printf '%s' "$out" | grep -q "claim done without running it"; then ok
else bad "alert lost with no approved rules; got: [$out]"; fi

t "87. every harness marker is filtered, including the two lost when capture was deleted"
# Found by the real-model smoke test, not by this suite: a deleted script took
# two markers with it, and a live run mined a <local-command-stdout> line as
# the user's own words - the exact misattribution this project was built after.
sandbox; echo k > "$KEYF"
python3 - "$SB/markers.jsonl" <<'PYX'
import json, sys
rows, i = [], 0
for content in ("<command-name>/model</command-name>",
                "<local-command-caveat>caveat</local-command-caveat>",
                "<local-command-stdout>Set model to claude-sonnet-5</local-command-stdout>",
                "<task-notification>agent done</task-notification>",
                "<system-reminder>reminder</system-reminder>",
                "<wake reason=\"external-event\">x</wake>",
                "[SYSTEM NOTIFICATION] x",
                "<untrusted_external_data>x</untrusted_external_data>",
                "you didn't run the tests"):
    rows.append({"type": "user", "uuid": "m%d" % i, "isSidechain": False,
                 "timestamp": "2026-08-26T00:00:00Z",
                 "message": {"role": "user", "content": content}})
    i += 1
open(sys.argv[1], "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
PYX
# The mock selects every id it is SHOWN, so anything filtered cannot be mined.
start_watch_mock "ALL_USER"
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$SB/markers.jsonl"
stop_mock
leaked=""
for m in "command-name" "local-command-caveat" "local-command-stdout" \
         "task-notification" "system-reminder" "wake reason" \
         "SYSTEM NOTIFICATION" "untrusted_external_data"; do
  grep -qF "$m" "$RAW" 2>/dev/null && leaked="$leaked $m"
done
if [ -z "$leaked" ] && grep -qF "you didn't run the tests" "$RAW"; then ok
else bad "leaked:$leaked ; real correction present: $(grep -c "run the tests" "$RAW" 2>/dev/null)"; fi

t "88. --global installs one memory for every project, not a per-project one"
sandbox
FAKEHOME="$SB/fakehome"; mkdir -p "$FAKEHOME"
(cd "$REPO" && HOME="$FAKEHOME" DK_REPO_URL="file:///nope-$$" \
   bash install.sh --global >/dev/null 2>&1)
fails=""
[ -f "$FAKEHOME/.claude/memory/dk_rules.md" ] || fails="$fails no-memory"
[ -f "$FAKEHOME/.claude/vendor/dk-mode/scripts/dk_capture.sh" ] || fails="$fails no-vendor"
# The script path must be absolute and the memory pinned: a global hook runs
# with each project as cwd, so ${CLAUDE_PROJECT_DIR} would point at whatever
# repo is open rather than at the single install.
cmds=$(python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
print('\n'.join(h['command'] for k in d['hooks'] for e in d['hooks'][k] for h in e['hooks']))
" "$FAKEHOME/.claude/settings.json" 2>/dev/null)
printf '%s' "$cmds" | grep -q "DK_HOME=" || fails="$fails no-dk-home"
printf '%s' "$cmds" | grep -q 'CLAUDE_PROJECT_DIR' && fails="$fails leaks-project-dir"
printf '%s' "$cmds" | grep -qF "$FAKEHOME/.claude/vendor" || fails="$fails not-absolute"
if [ -z "$fails" ]; then ok; else bad "$fails; cmds: $cmds"; fi

t "89. DK_HOME overrides the project when both are set"
# The whole point of a global install: whatever repo is open, one memory.
sandbox
OTHER="$SB/other-project"; mkdir -p "$OTHER/.claude/memory"
out=$(printf '{"prompt":"x","session_id":"s"}' | \
  env DK_HOME="$SB" CLAUDE_PROJECT_DIR="$OTHER" HOME="$SB/home" \
      bash "$SCRIPTS/dk_recall.sh")
# $SB has a seeded rules file; $OTHER has an empty memory dir. Reading the
# DK_HOME one is the pass condition.
if printf '%s' "$out" | grep -q "self-steering"; then ok
else bad "read the project dir, not DK_HOME; got: [$out]"; fi

t "90. no GNU-only flags in any shell script (this suite only ever runs on Linux)"
# The suite runs on Linux, so a GNU-only flag passes every test here and fails
# on the user's Mac. It has happened twice: `stat -f` ordering, then `head -z`
# and `sort -z` in the smoke test, which died immediately on macOS with
# "head: invalid option -- z". Checking one command was not enough - this
# checks the class.
fails=""
for f in "$SCRIPTS"/*.sh "$REPO/install.sh"; do
  # Strip comments first: these flags are named in explanatory comments.
  body=$(sed 's/#.*//' "$f")
  printf '%s' "$body" | grep -qE '\b(head|tail|sort|uniq)\b[^|;]*-[a-zA-Z]*z' \
    && fails="$fails $(basename "$f"):null-separated-flag"
  printf '%s' "$body" | grep -qE '\bgrep\b[^|;]*-[a-zA-Z]*P' \
    && fails="$fails $(basename "$f"):grep-P"
  printf '%s' "$body" | grep -qE '\breadlink\b[^|;]*-[a-zA-Z]*f' \
    && fails="$fails $(basename "$f"):readlink-f"
  printf '%s' "$body" | grep -qE '\bdate\b[^|;]*-d ' \
    && fails="$fails $(basename "$f"):date-d"
  printf '%s' "$body" | grep -qE '\bsed\b[^|;]*-i[ ]' \
    && fails="$fails $(basename "$f"):sed-i-gnu-form"
  # stat must try the GNU form FIRST: on Linux `stat -f %m` does not fail, it
  # prints filesystem info, so BSD-first ordering breaks silently.
  if printf '%s' "$body" | grep -q 'stat -f %m'; then
    printf '%s' "$body" | grep -q 'stat -c %Y' \
      || fails="$fails $(basename "$f"):bsd-stat-without-gnu"
    printf '%s' "$body" | grep -qE 'stat -c %Y[^|]*\|\|[^|]*stat -f %m' \
      || fails="$fails $(basename "$f"):stat-wrong-order"
  fi
done
if [ -z "$fails" ]; then ok; else bad "$fails"; fi

# --- 91-93: DK_BACKEND=cli - use the existing claude login, no API key ------

t "91. DK_BACKEND=cli mines with no API key at all"
sandbox
mkdir -p "$SB/bin"
cat > "$SB/bin/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null   # consume the prompt on stdin
echo '{"active":[],"alert":null,"steering":[{"id":"a-2","source":"self","kind":"self-correction"}]}'
STUB
chmod +x "$SB/bin/claude"
env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" DK_KEY_FILE="$SB/home/nokey" \
    ANTHROPIC_API_KEY="" DK_API_KEY="" DK_BACKEND=cli PATH="$SB/bin:$PATH" \
    python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_autonomous.jsonl"
if grep -qF "I never ran the court gate" "$RAW" 2>/dev/null; then ok
else bad "cli backend mined nothing; raw: $(cat "$RAW" 2>/dev/null)"; fi

t "92. a 'not logged in' CLI failure is reported, not silently empty"
sandbox
mkdir -p "$SB/bin"
cat > "$SB/bin/claude" <<'STUB'
#!/usr/bin/env bash
cat >/dev/null
echo "Not logged in" >&2
exit 1
STUB
chmod +x "$SB/bin/claude"
env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" DK_KEY_FILE="$SB/home/nokey" \
    ANTHROPIC_API_KEY="" DK_API_KEY="" DK_BACKEND=cli PATH="$SB/bin:$PATH" \
    DK_LOG_DIR="$SB/logs" \
    python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_autonomous.jsonl"
if grep -qi "not logged in" "$SB/logs/dk_watch.log" 2>/dev/null \
   && grep -qi "keychain" "$SB/logs/dk_watch.log" 2>/dev/null; then ok
else bad "failure not explained; log: $(cat "$SB/logs/dk_watch.log" 2>/dev/null)"; fi

t "93. an HTTP 401 says so instead of looking like an empty history"
sandbox; echo k > "$KEYF"
python3 - "$TMPBASE/p401" <<'PYX' &
import http.server, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        body = b'{"error":{"message":"invalid x-api-key"}}'
        self.send_response(401)
        self.send_header("content-length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
s = http.server.HTTPServer(("127.0.0.1", 0), H)
open(sys.argv[1], "w").write(str(s.server_address[1]))
s.serve_forever()
PYX
MOCK_PID=$!
for _ in $(seq 1 50); do [ -s "$TMPBASE/p401" ] && break; sleep 0.1; done
runenv DK_LOG_DIR="$SB/logs" DK_API_URL="http://127.0.0.1:$(cat "$TMPBASE/p401")/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_autonomous.jsonl"
stop_mock
if grep -q "HTTP 401" "$SB/logs/dk_watch.log" 2>/dev/null; then ok
else bad "401 not surfaced; log: $(cat "$SB/logs/dk_watch.log" 2>/dev/null)"; fi

t "94. credentials in a transcript are redacted before they reach the log"
# A real run mined a live OpenRouter key out of a conversation. dk.jsonl is
# read into prompts and lives where people commit files, so redaction happens
# where it is written.
sandbox; echo k > "$KEYF"
python3 - "$SB/secrets.jsonl" <<'PYX'
import json, sys
rows = [
 {"type": "assistant", "uuid": "s0", "isSidechain": False,
  "timestamp": "2026-08-26T00:00:00Z",
  "message": {"role": "assistant", "content": "I will use the key you gave me."}},
 {"type": "user", "uuid": "s1", "isSidechain": False,
  "timestamp": "2026-08-26T00:01:00Z",
  "message": {"role": "user", "content":
    "no that's wrong. openrouter key sk-or-v1-" + "a"*48 +
    " and sk-ant-api03-" + "b"*40 + " and ghp_" + "c"*30}},
]
open(sys.argv[1], "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
PYX
start_watch_mock "ALL_USER"
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$SB/secrets.jsonl"
stop_mock
fails=""
grep -q "sk-or-v1-aaaa" "$RAW" 2>/dev/null && fails="$fails openrouter-key"
grep -q "sk-ant-api03-bbbb" "$RAW" 2>/dev/null && fails="$fails anthropic-key"
grep -q "ghp_cccc" "$RAW" 2>/dev/null && fails="$fails github-token"
grep -q "REDACTED-SECRET" "$RAW" 2>/dev/null || fails="$fails no-redaction-marker"
grep -qF "no that's wrong" "$RAW" 2>/dev/null || fails="$fails lost-the-correction"
if [ -z "$fails" ]; then ok; else bad "$fails; raw: $(head -c 400 "$RAW" 2>/dev/null)"; fi

t "95. a fresh install ships baseline failure modes and injects them immediately"
sandbox
PROJ="$SB/proj"; mkdir -p "$PROJ"
(cd "$REPO" && DK_REPO_URL="file:///nope-$$" bash install.sh --target "$PROJ" --no-hooks >/dev/null 2>&1)
out=$(printf '{"prompt":"x","session_id":"s"}' | \
  env CLAUDE_PROJECT_DIR="$PROJ" HOME="$SB/home" bash "$SCRIPTS/dk_recall.sh")
fails=""
printf '%s' "$out" | grep -q "nothing captured yet" && fails="$fails empty-note"
printf '%s' "$out" | grep -q "ran it this turn" || fails="$fails no-baseline-in-note"
# Baseline items must never look like the user's own evidence.
grep -q '\*\*Source:\*\* baseline' "$PROJ/.claude/memory/dk_rules.md" \
  || fails="$fails unmarked"
grep -A6 '^### Claims something is done' "$PROJ/.claude/memory/dk_rules.md" \
  | grep -q '\*\*Evidence:\*\*' && fails="$fails fabricated-evidence"
if [ -z "$fails" ]; then ok; else bad "$fails; note: $out"; fi

t "96. --no-baseline leaves a genuinely empty install"
sandbox
PROJ="$SB/proj2"; mkdir -p "$PROJ"
(cd "$REPO" && DK_REPO_URL="file:///nope-$$" bash install.sh --target "$PROJ" \
   --no-hooks --no-baseline >/dev/null 2>&1)
if grep -q "(none captured yet)" "$PROJ/.claude/memory/dk_rules.md" \
   && ! grep -q "Source:\*\* baseline" "$PROJ/.claude/memory/dk_rules.md"; then ok
else bad "baseline leaked into a --no-baseline install"; fi

t "97. every baseline item is complete and none fabricates user evidence"
# The baseline set is the one place rules exist without being mined, so it is
# the one place fabricated provenance could creep in. It must never carry an
# Evidence line, and every item needs a Reminder line or it can never steer.
fails=""
BASE="$REPO/templates/baseline_rules.md"
n=$(grep -c '^### ' "$BASE")
[ "$n" -ge 20 ] || fails="$fails only-$n-items"
[ "$(grep -c '\*\*Evidence:\*\*' "$BASE")" = "0" ] || fails="$fails fabricated-evidence"
# Anchored: the file's own header comment mentions the marker too.
[ "$(grep -c '^\*\*Source:\*\* baseline' "$BASE")" = "$n" ] || fails="$fails unmarked-items"
[ "$(grep -c '\*\*Reminder line:\*\*' "$BASE")" = "$n" ] || fails="$fails missing-reminder"
[ "$(grep -c '\*\*What it looks like:\*\*' "$BASE")" = "$n" ] || fails="$fails missing-description"
[ "$(grep -c '\*\*Status:\*\* approved' "$BASE")" = "$n" ] || fails="$fails not-approved"
if [ -z "$fails" ]; then ok; else bad "$fails"; fi

t "98. the whole baseline set is selectable by the relevance layer"
# An item the loader silently drops is an item that can never fire. The count
# the loader sees must match the count in the file.
sandbox
PROJ="$SB/proj3"; mkdir -p "$PROJ"
(cd "$REPO" && DK_REPO_URL="file:///nope-$$" bash install.sh --target "$PROJ" --no-hooks >/dev/null 2>&1)
infile=$(grep -c '^### ' "$PROJ/.claude/memory/dk_rules.md")
loaded=$(CLAUDE_PROJECT_DIR="$PROJ" python3 -c "
import importlib.util, sys
spec = importlib.util.spec_from_file_location('w', '$SCRIPTS/dk_watch.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(len(m.load_rules()))
")
if [ "$infile" = "$loaded" ]; then ok
else bad "$infile items in the file but the loader sees $loaded"; fi

# --- 99-101: plugin install (no install.sh runs at all) ---------------------

t "99. the plugin manifests are valid and point at files that exist"
fails=""
for f in ".claude-plugin/plugin.json" "hooks/hooks.json" ".claude-plugin/marketplace.json"; do
  python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$REPO/$f" 2>/dev/null \
    || fails="$fails $f:invalid-json"
done
# Every command in hooks.json must reference a script that is actually shipped.
for s in $(python3 -c "
import json, re
h = json.load(open('$REPO/hooks/hooks.json'))
for ev in h['hooks']:
    for e in h['hooks'][ev]:
        for k in e['hooks']:
            m = re.search(r'CLAUDE_PLUGIN_ROOT\}/(\S+?)\"', k['command'])
            if m: print(m.group(1))
"); do
  [ -f "$REPO/$s" ] || fails="$fails missing:$s"
done
if [ -z "$fails" ]; then ok; else bad "$fails"; fi

t "100. a plugin install seeds and mines with no install.sh step"
# Claude Code copies a plugin in and starts calling hooks. Nothing runs
# install.sh, so the first hook has to create its own memory.
sandbox; echo k > "$KEYF"
PR="$SB/proot"; PD="$SB/pdata"
mkdir -p "$PR"; cp -R "$REPO/scripts" "$REPO/templates" "$PR/"
python3 - "$SB/pt.jsonl" <<'PYX'
import json, sys
rows = [
 {"type": "assistant", "uuid": "p0", "isSidechain": False,
  "timestamp": "2026-08-27T00:00:00Z",
  "message": {"role": "assistant", "content": "Done, all tests pass."}},
 {"type": "user", "uuid": "p1", "isSidechain": False,
  "timestamp": "2026-08-27T00:01:00Z",
  "message": {"role": "user", "content": "bit lame, did you actually run them"}},
]
open(sys.argv[1], "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
PYX
start_watch_mock "ALL_USER"
# The exact command string from hooks.json, not a paraphrase of it.
CMD=$(python3 -c "
import json
h = json.load(open('$REPO/hooks/hooks.json'))
print(h['hooks']['Stop'][0]['hooks'][0]['command'])")
printf '{"transcript_path":"%s","session_id":"plugtest"}' "$SB/pt.jsonl" | \
  env CLAUDE_PLUGIN_ROOT="$PR" CLAUDE_PLUGIN_DATA="$PD" HOME="$SB/home" \
      DK_KEY_FILE="$KEYF" DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
      bash -c "$CMD"
for _ in $(seq 1 40); do [ -s "$PD/memory/dk.jsonl" ] && break; sleep 0.25; done
stop_mock
fails=""
[ "$(grep -c '^### ' "$PD/memory/dk_rules.md" 2>/dev/null)" -ge 20 ] \
  || fails="$fails no-baseline-seeded"
grep -qF "did you actually run them" "$PD/memory/dk.jsonl" 2>/dev/null \
  || fails="$fails nothing-mined"
if [ -z "$fails" ]; then ok; else bad "$fails"; fi

t "101. the plugin recall hook injects, and never touches the project directory"
CMD=$(python3 -c "
import json
h = json.load(open('$REPO/hooks/hooks.json'))
print(h['hooks']['UserPromptSubmit'][0]['hooks'][0]['command'])")
PROJ="$SB/someproject"; mkdir -p "$PROJ"
out=$(printf '{"prompt":"ship it","session_id":"plugtest"}' | \
  env CLAUDE_PLUGIN_ROOT="$PR" CLAUDE_PLUGIN_DATA="$PD" HOME="$SB/home" \
      CLAUDE_PROJECT_DIR="$PROJ" bash -c "$CMD")
fails=""
printf '%s' "$out" | grep -q "self-steering" || fails="$fails no-injection"
# A plugin must not scatter memory into whatever repo happens to be open.
[ -d "$PROJ/.claude" ] && fails="$fails wrote-into-the-project"
if [ -z "$fails" ]; then ok; else bad "$fails; out: $out"; fi

t "102. deleting the rules file disables dk-mode; the bootstrap does not undo it"
# Self-seeding exists for a fresh plugin install. It must not resurrect a file
# the user removed on purpose - deleting dk_rules.md is how you turn this off.
sandbox
rm -f "$RULES"                     # dk.jsonl remains: an existing install
out=$(run_recall); rc=$?
if [ ! -f "$RULES" ] && [ -z "$out" ] && [ "$rc" = "0" ]; then ok
else bad "rules resurrected or output produced; rc=$rc out: [$out]"; fi

t "103. the rules sent each turn are capped, and mined rules beat baseline ones"
# Without a cap the per-turn prompt grows forever: mining only ever adds.
sandbox
python3 - "$RULES" <<'PYX'
import re, sys
p = sys.argv[1]; t = open(p).read()
items = []
for i in range(50):                      # 50 baseline-style, no Evidence
    items.append(f"### Baseline item {i}\n**What it looks like:** generic\n"
                 f"**Reminder line:** generic reminder {i}\n"
                 f"**Source:** baseline\n**Status:** approved\n")
for i in range(3):                       # 3 mined, WITH Evidence
    items.append(f"### Mined item {i}\n**What it looks like:** specific\n"
                 f"**Reminder line:** mined reminder {i}\n"
                 f'**Evidence:** User, 2026-08-27: "you did not run it"\n'
                 f"**Status:** approved\n")
t = re.sub(r"(## Mistake Patterns\s*\n)", r"\1\n" + "\n".join(items), t, count=1)
open(p, "w").write(t)
PYX
res=$(CLAUDE_PROJECT_DIR="$SB" DK_MAX_RULES=10 python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('w', '$SCRIPTS/dk_watch.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
r = m.load_rules()
print(len(r), sum(1 for x in r if x['mined']), [x['id'] for x in r] == list(range(1, len(r)+1)))
")
set -- $res
if [ "$1" = "10" ] && [ "$2" = "3" ] && [ "$3" = "True" ]; then ok
else bad "got count=$1 mined=$2 ids-contiguous=$3 (want 10 / 3 / True)"; fi

t "104. the window always reaches back to the user, however long the turn ran"
# A turn is not a message. Claude thinks, calls tools and narrates, and each
# text block is its own entry. Measured on a real conversation, a plain
# last-6-messages window contained NO user message on 33% of turns - so the
# miner judged Claude talking to itself, with no idea what had been asked.
sandbox
python3 - "$SB/long.jsonl" <<'PYX'
import json, sys
rows = [{"type": "user", "uuid": "u1", "isSidechain": False,
         "timestamp": "2026-08-27T00:00:00Z",
         "message": {"role": "user", "content": "bit lame, simplify it"}}]
# One enormous agentic turn: 25 assistant messages after that single request.
for i in range(25):
    rows.append({"type": "assistant", "uuid": "a%d" % i, "isSidechain": False,
                 "timestamp": "2026-08-27T00:0%d:00Z" % (i % 10),
                 "message": {"role": "assistant",
                             "content": "step %d of the work" % i}})
open(sys.argv[1], "w").write("\n".join(json.dumps(r) for r in rows) + "\n")
PYX
res=$(CLAUDE_PROJECT_DIR="$SB" python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('w', '$SCRIPTS/dk_watch.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
msgs = m._read_messages('$SB/long.jsonl')
w = m.recent_exchanges(msgs, 2, 9000)
print(sum(1 for x in w if x['role'] == 'user'), len(w), w[-1]['role'])
")
set -- $res
# Must include the request, must stay bounded, must end on the newest message.
if [ "$1" -ge 1 ] && [ "$2" -le 26 ] && [ "$3" = "assistant" ]; then ok
else bad "users=$1 size=$2 last=$3 (want >=1 user, bounded, newest last)"; fi

t "105. the window is capped so one enormous turn cannot fill the prompt"
res=$(CLAUDE_PROJECT_DIR="$SB" python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('w', '$SCRIPTS/dk_watch.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
msgs = m._read_messages('$SB/long.jsonl')
w = m.recent_exchanges(msgs, 2, 200)          # a deliberately tiny budget
print(sum(len(x['text']) for x in w) <= 400, len(w) > 0)
")
if [ "$res" = "True True" ]; then ok; else bad "cap not honoured: $res"; fi

trip() {  # trip <session> <tool> <input-json> <output>
  printf '{"session_id":"%s","tool_name":"%s","tool_input":%s,"tool_output":%s}' \
    "$1" "$2" "$3" "$4" | DK_MEM="$SB/.claude/memory" \
    python3 "$SCRIPTS/dk_tripwire.py"
}

t "108. the same call three times trips, and trips only once"
sandbox
a=$(trip r1 Grep '{"pattern":"foo"}' '"none"')
b=$(trip r1 Grep '{"pattern":"foo"}' '"none"')
c=$(trip r1 Grep '{"pattern":"foo"}' '"none"')
d=$(trip r1 Grep '{"pattern":"foo"}' '"none"')
fails=""
[ -n "$a$b" ] && fails="$fails fired-too-early"
printf '%s' "$c" | grep -q "additionalContext" || fails="$fails did-not-fire"
printf '%s' "$c" | grep -q "PostToolUse" || fails="$fails wrong-event-name"
[ -n "$d" ] && fails="$fails fired-twice"
if [ -z "$fails" ]; then ok; else bad "$fails"; fi

t "109. reading without writing trips; a write resets the count"
sandbox
for i in $(seq 1 12); do
  out=$(trip r2 Read "{\"file_path\":\"/f$i\"}" '"x"')
done
printf '%s' "$out" | grep -q "without changing anything" || bad "no converge warning"
# A write clears it: the next 11 reads must stay quiet.
sandbox
for i in $(seq 1 11); do trip r3 Read "{\"file_path\":\"/f$i\"}" '"x"' >/dev/null; done
trip r3 Edit '{"file_path":"/a.py"}' '"ok"' >/dev/null
q=""
for i in $(seq 1 11); do q="$q$(trip r3 Read "{\"file_path\":\"/g$i\"}" '"x"')"; done
if printf '%s' "$out" | grep -q "without changing anything" && [ -z "$q" ]; then ok
else bad "reset failed; q=$q"; fi

t "110. editing a test after a test failed trips"
sandbox
trip r4 Bash '"pytest tests/"' '"2 failed\nAssertionError"' >/dev/null
out=$(trip r4 Edit '{"file_path":"tests/test_math.py"}' '"ok"')
# Editing a NON-test file after a failure must stay quiet - that is the fix.
sandbox
trip r5 Bash '"pytest tests/"' '"2 failed\nAssertionError"' >/dev/null
q=$(trip r5 Edit '{"file_path":"src/math.py"}' '"ok"')
if printf '%s' "$out" | grep -q "editing a test file" && [ -z "$q" ]; then ok
else bad "out=$out q=$q"; fi

t "111. ordinary work trips nothing at all"
sandbox
q=$(trip r6 Read '{"file_path":"/a"}' '"x"')
q="$q$(trip r6 Edit '{"file_path":"/a"}' '"ok"')"
q="$q$(trip r6 Bash '"pytest"' '"3 passed"')"
q="$q$(trip r6 Grep '{"pattern":"x"}' '"1 match"')"
if [ -z "$q" ]; then ok; else bad "fired on normal work: $q"; fi

t "112. malformed input never breaks the turn"
sandbox
out=$(echo 'not json at all' | DK_MEM="$SB/.claude/memory" \
      python3 "$SCRIPTS/dk_tripwire.py" 2>&1); rc=$?
if [ "$rc" = "0" ] && [ -z "$out" ]; then ok; else bad "rc=$rc out=$out"; fi

t "113. the installer registers the tripwire on PostToolUse"
sandbox
PROJ="$SB/tw"; mkdir -p "$PROJ"
(cd "$REPO" && DK_REPO_URL="file:///nope-$$" bash install.sh --target "$PROJ" >/dev/null 2>&1)
got=$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
pt = d.get('hooks', {}).get('PostToolUse', [])
print('yes' if any('dk_tripwire' in h.get('command','')
                   for e in pt for h in e.get('hooks', [])) else 'no')
" "$PROJ/.claude/settings.json" 2>/dev/null)
if [ "$got" = "yes" ]; then ok; else bad "not registered"; fi

t "114. the Stop hook clears tripwire state, so 'once per turn' is true"
# Without this the counters run for the whole session: a tripwire fires once
# and stays silent for every later loop, and reads from unrelated turns add up
# into a false warning. The doc claimed once-per-turn; the code did not.
sandbox
fire() {
  printf '{"session_id":"tw1","tool_name":"Grep","tool_input":{"p":"x"},"tool_output":"none"}' \
    | DK_MEM="$SB/.claude/memory" python3 "$SCRIPTS/dk_tripwire.py"
}
for _ in 1 2 3; do a=$(fire); done
printf '{"transcript_path":"/dev/null","session_id":"tw1"}' \
  | env CLAUDE_PROJECT_DIR="$SB" HOME="$SB/home" DK_WATCH=0 bash "$SCRIPTS/dk_capture.sh"
for _ in 1 2 3; do b=$(fire); done
if [ -n "$a" ] && [ -n "$b" ]; then ok
else bad "turn1=$([ -n "$a" ] && echo fired || echo no) turn2=$([ -n "$b" ] && echo fired || echo no)"; fi

t "115. dk_signal.py honours DK_MEM and DK_HOME like every other script"
# It was the only script that ignored both, so a global or plugin install wrote
# its events to a dk.jsonl nothing ever consolidated.
sandbox
python3 "$SCRIPTS/dk_signal.py" --text "the deploy gate rejected this" \
  --source ci >/dev/null 2>&1 <<< "" || true
n1=0
DK_MEM="$SB/.claude/memory" python3 "$SCRIPTS/dk_signal.py" \
  --text "gate rejected this" --source ci >/dev/null 2>&1
n1=$(lines "$RAW")
OTHER="$SB/other"; mkdir -p "$OTHER/.claude/memory"; : > "$OTHER/.claude/memory/dk.jsonl"
DK_HOME="$OTHER" python3 "$SCRIPTS/dk_signal.py" \
  --text "lint keeps failing" --source lint >/dev/null 2>&1
n2=$(lines "$OTHER/.claude/memory/dk.jsonl")
if [ "$n1" -ge 1 ] && [ "$n2" -ge 1 ]; then ok
else bad "DK_MEM=$n1 DK_HOME=$n2 (want both >=1)"; fi

t "116. the smoke test cannot mine into a real memory via an exported DK_HOME"
# Its strongest safety claim was conditional: DK_HOME and DK_MEM outrank the
# scratch project it passes down.
if grep -q '^unset DK_HOME DK_MEM' "$SCRIPTS/dk_smoketest.sh"; then ok
else bad "smoketest does not clear DK_HOME/DK_MEM before running"; fi

t "117. a manual install is told about all three hooks, not two"
# The printed fallback listed Stop and UserPromptSubmit only, so anyone whose
# settings file could not be written automatically silently got no tripwire.
sandbox
PROJ="$SB/mf"; mkdir -p "$PROJ/.claude"; echo 'not valid json' > "$PROJ/.claude/settings.json"
out=$(cd "$REPO" && DK_REPO_URL="file:///nope-$$" bash install.sh --target "$PROJ" 2>&1)
fails=""
printf '%s' "$out" | grep -q "dk_tripwire" || fails="$fails no-tripwire"
printf '%s' "$out" | grep -q "dk_capture"  || fails="$fails no-capture"
printf '%s' "$out" | grep -q "dk_recall"   || fails="$fails no-recall"
if [ -z "$fails" ]; then ok; else bad "$fails"; fi

t "118. a quoted '## Retired' in evidence does not split the rules file"
# dk_review.py documents this bug as fixed; dk_consolidate.py still had it.
sandbox
python3 - "$RULES" <<'PYX'
import re, sys
p = sys.argv[1]; t = open(p).read()
item = ('### Rule whose evidence quotes a heading\n'
        '**What it looks like:** something\n'
        '**Reminder line:** do the thing\n'
        '**Evidence:** User: "put it under ## Retired please"\n'
        '**Status:** approved\n\n'
        '### A later rule that must still be visible\n'
        '**What it looks like:** something else\n'
        '**Reminder line:** do the other thing\n'
        '**Status:** approved\n\n')
open(p, "w").write(re.sub(r"(## Mistake Patterns\s*\n)", r"\1\n" + item, t, count=1))
PYX
n=$(CLAUDE_PROJECT_DIR="$SB" python3 -c "
import importlib.util
spec = importlib.util.spec_from_file_location('w', '$SCRIPTS/dk_watch.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(len(m.load_rules()))
")
if [ "$n" = "2" ]; then ok; else bad "loader sees $n rules, want 2 (the quote split the file)"; fi

t "120. the tripwire hook is not registered when its script is absent"
# An old vendor clone refreshed without --update has no dk_tripwire.py. A hook
# pointing at a missing file runs python3 on nothing after every tool call.
sandbox
PROJ="$SB/noTrip"; mkdir -p "$PROJ"
(cd "$REPO" && DK_REPO_URL="file:///nope-$$" bash install.sh --target "$PROJ" >/dev/null 2>&1)
rm -f "$PROJ/.claude/vendor/dk-mode/scripts/dk_tripwire.py"
rm -f "$PROJ/.claude/settings.json"
(cd "$REPO" && DK_REPO_URL="file:///nope-$$" bash install.sh --target "$PROJ" >/dev/null 2>&1)
got=$(python3 -c "
import json, sys, os
p = sys.argv[1]
d = json.load(open(p)) if os.path.exists(p) else {}
pt = d.get('hooks', {}).get('PostToolUse', [])
print('registered' if any('dk_tripwire' in h.get('command','')
      for e in pt for h in e.get('hooks', [])) else 'absent')
" "$PROJ/.claude/settings.json" 2>/dev/null)
# The installer re-copies the vendor tree, so the file returns and registering
# is correct. What must never happen is registering when it is genuinely gone.
if [ -f "$PROJ/.claude/vendor/dk-mode/scripts/dk_tripwire.py" ]; then
  [ "$got" = "registered" ] && ok || bad "script present but not registered"
else
  [ "$got" = "absent" ] && ok || bad "registered a hook for a missing script"
fi

echo
echo "$PASS passed, $FAIL failed  (total $((PASS + FAIL)))"
[ "$FAIL" = "0" ] || exit 1
exit 0
