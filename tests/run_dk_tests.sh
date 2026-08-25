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

t "1. correction captured verbatim, kind=correction, source=human"
sandbox; run_capture "$FIX/transcript_correction.jsonl"
if [ "$(lines "$RAW")" = "1" ] && grep -q '"kind": "correction"' "$RAW" \
   && grep -q '"source": "human"' "$RAW" \
   && grep -qF "you didn't actually run the tests" "$RAW"; then ok; else bad "raw: $(cat "$RAW")"; fi

t "2. re-run on same transcript adds nothing (uuid dedupe)"
run_capture "$FIX/transcript_correction.jsonl"
if [ "$(lines "$RAW")" = "1" ]; then ok; else bad "$(lines "$RAW") lines"; fi

t "3. heartbeat written when an entry was saved"
if grep -q "| dk-capture | 1 entry" "$MEMLOG"; then ok; else bad "log: $(cat "$MEMLOG")"; fi

t "4. instruction captured with kind=instruction"
sandbox; run_capture "$FIX/transcript_instruction.jsonl"
if [ "$(lines "$RAW")" = "1" ] && grep -q '"kind": "instruction"' "$RAW"; then ok; else bad "raw: $(cat "$RAW")"; fi

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

t "8. corrupt transcript line tolerated, good entry still captured"
sandbox; run_capture "$FIX/transcript_corrupt.jsonl"
if [ "$(lines "$RAW")" = "1" ] && grep -qF "not what I asked" "$RAW"; then ok; else bad "raw: $(cat "$RAW")"; fi

t "9. missing transcript path exits 0, writes nothing"
sandbox
printf '{}' | runenv bash "$SCRIPTS/dk_capture.sh"; rc=$?
if [ "$rc" = "0" ] && [ ! -s "$RAW" ]; then ok; else bad "rc=$rc"; fi

t "10. lock held by another session -> skips without writing"
sandbox; mkdir "$SB/.claude/memory/.dk.lock"
run_capture "$FIX/transcript_correction.jsonl"; rc=$?
if [ "$rc" = "0" ] && [ ! -s "$RAW" ]; then ok; else bad "rc=$rc"; fi
rmdir "$SB/.claude/memory/.dk.lock"

t "10b. isMeta turns are not the user: skill body, image paste, harness filler"
sandbox; run_capture "$FIX/transcript_meta.jsonl" DK_SCAN_LINES=0
if [ "$(lines "$RAW")" = "1" ] \
   && grep -qF "you didn't run the tests" "$RAW" \
   && ! grep -q "Base directory for this skill" "$RAW" \
   && ! grep -q "\[Image:" "$RAW" \
   && ! grep -q "Continue from where you left off" "$RAW"; then ok; else bad "raw: $(cat "$RAW")"; fi

t "11. default 150-line window misses a signal buried deep; SCAN_LINES=0 catches it"
sandbox; run_capture "$FIX/transcript_deep.jsonl"
deep_default=$(lines "$RAW")
run_capture "$FIX/transcript_deep.jsonl" DK_SCAN_LINES=0
if [ "$deep_default" = "0" ] && [ "$(lines "$RAW")" = "1" ] \
   && grep -qF "you skipped the config step" "$RAW"; then ok; else bad "default=$deep_default after0=$(lines "$RAW")"; fi

t "12. entry keeps the transcript's own timestamp (backfilled history dates right)"
sandbox; run_capture "$FIX/transcript_timestamped.jsonl" DK_SCAN_LINES=0
if grep -q '"ts": "2026-05-15T14:30:00+10:00"' "$RAW"; then ok; else bad "raw: $(cat "$RAW")"; fi

# =============================================================================
echo "== recall =="

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

t "38. sweeps all projects' transcripts, catches deep signals, idempotent"
sandbox
PROJ="$SB/home/.claude/projects"
mkdir -p "$PROJ/proj-a" "$PROJ/proj-b"
cp "$FIX/transcript_correction.jsonl" "$PROJ/proj-a/sess-aaaa.jsonl"
cp "$FIX/transcript_deep.jsonl" "$PROJ/proj-a/sess-bbbb.jsonl"
cp "$FIX/transcript_instruction.jsonl" "$PROJ/proj-b/sess-cccc.jsonl"
out=$(runenv bash "$SCRIPTS/dk_backfill.sh" --transcripts "$PROJ" --target "$SB")
n1=$(lines "$RAW")
runenv bash "$SCRIPTS/dk_backfill.sh" --transcripts "$PROJ" --target "$SB" >/dev/null
n2=$(lines "$RAW")
if [ "$n1" = "3" ] && [ "$n2" = "3" ] \
   && grep -qF "you skipped the config step" "$RAW" \
   && printf '%s' "$out" | grep -q "scanned 3 transcripts"; then ok; else bad "n1=$n1 n2=$n2 out: $out"; fi

t "38b. backfill mines history by READING it, not just phrase-matching"
sandbox; echo k > "$KEYF"
PROJ="$SB/home/.claude/projects/p"; mkdir -p "$PROJ"
cp "$FIX/transcript_real_missed.jsonl" "$PROJ/s1.jsonl"     # zero phrase matches
ids=$(python3 -c "
import json
ids=[json.loads(l)['uuid'] for l in open('$FIX/transcript_real_missed.jsonl')]
print(json.dumps({'active':[],'alert':None,'steering':[{'id':i,'kind':'correction'} for i in ids[:2]]}))")
start_watch_mock "$ids"
out=$(runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  bash "$SCRIPTS/dk_backfill.sh" --transcripts "$PROJ" --target "$SB")
stop_mock
if [ "$(lines "$RAW")" -ge 2 ] && grep -q '"signal": "semantic"' "$RAW" \
   && printf '%s' "$out" | grep -q "found by reading"; then ok; else bad "out: $out raw=$(lines "$RAW")"; fi

t "38c. backfill warns loudly when the semantic pass yields nothing"
sandbox
PROJ="$SB/home/.claude/projects/p"; mkdir -p "$PROJ"
cp "$FIX/transcript_real_missed.jsonl" "$PROJ/s1.jsonl"
out=$(runenv DK_BACKFILL_SEMANTIC=0 bash "$SCRIPTS/dk_backfill.sh" --transcripts "$PROJ" --target "$SB")
if printf '%s' "$out" | grep -q "semantic pass DISABLED"; then ok; else bad "out: $out"; fi

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
echo "== relevance layer (dk_watch) =="

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

t "64. self-correction in an agent's own chat is captured (source=self), no human message needed"
sandbox; run_capture "$FIX/transcript_autonomous.jsonl"
if [ "$(lines "$RAW")" = "1" ] \
   && grep -q '"source": "self"' "$RAW" \
   && grep -q '"kind": "self-correction"' "$RAW" \
   && grep -qF "I never ran the court gate" "$RAW"; then ok; else bad "raw: $(cat "$RAW")"; fi

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

t "70. end to end with no human: self-correction -> consolidation -> live injection"
sandbox; echo k > "$KEYF"
run_capture "$FIX/transcript_autonomous.jsonl" DK_WATCH=0
captured=$(lines "$RAW")
cp "$FIX/rules_mixed_approval.md" "$RULES"
start_watch_mock '{"active":[1],"alert":"You said checks passed without running the gate."}'
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_autonomous.jsonl"
stop_mock
out=$(run_recall)
if [ "$captured" = "1" ] \
   && printf '%s' "$out" | grep -q "without running the gate" \
   && printf '%s' "$out" | grep -q "never say a check passed"; then ok; else bad "out: $out"; fi

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
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" DK_WATCH_TURNS=20 \
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

t "73c. a failing relevance layer is announced, not silent"
sandbox; echo k > "$KEYF"
printf 'watch_consecutive_failed=3\n' > "$STATE"
out=$(run_recall)
if printf '%s' "$out" | grep -q "relevance layer has failed its last 3 runs"; then ok; else bad "out: $out"; fi

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

t "75. semantic capture dedupes against what the phrase list already logged"
sandbox; echo k > "$KEYF"
run_capture "$FIX/transcript_correction.jsonl" DK_WATCH=0
before=$(lines "$RAW")
uid=$(python3 -c "import json;print([json.loads(l)['uuid'] for l in open('$RAW')][0])")
start_watch_mock "{\"active\":[],\"alert\":null,\"steering\":[{\"id\":\"$uid\",\"kind\":\"correction\"}]}"
runenv DK_API_URL="http://127.0.0.1:$MOCK_PORT/v1/messages" \
  python3 "$SCRIPTS/dk_watch.py" "$FIX/transcript_correction.jsonl"
stop_mock
if [ "$before" = "1" ] && [ "$(lines "$RAW")" = "1" ]; then ok; else bad "before=$before after=$(lines "$RAW")"; fi

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

echo
echo "$PASS passed, $FAIL failed  (total $((PASS + FAIL)))"
[ "$FAIL" = "0" ] || exit 1
exit 0
