#!/usr/bin/env python3
"""dk_tripwire.py - PostToolUse hook: speak DURING a turn, not after it.

The runtime monitor runs on Stop, so its note reaches the next prompt. On a
turn that runs 25 tool calls over ten minutes, that is ten minutes late - and
a long unattended turn is exactly what dk-mode is for.

This runs after every tool call and can inject text into the tool result the
agent is about to read, using PostToolUse `additionalContext`.

It calls NO model. It cannot: firing a model call after every tool call would
cost more than the work being watched. It does not need one, because the
failure modes worth catching mid-turn have deterministic signatures:

  REPEATING       the same tool call, with the same input, three times.
                  MAST measured step repetition at 15.7%, the most common
                  single failure mode of any in that taxonomy. It is also the
                  easiest to detect: compare a hash.
  NOT CONVERGING  many reads and searches with nothing written. SWE-Bench Pro
                  measured context overflow at 35.6% of one model's failures
                  and endless file reading at 17.0%.
  EDITING A TEST  a test file changed after a test command failed in this same
                  turn. Reward-hacking benchmarks exist because models do
                  this; one analysis found 19.78% of top SWE-Bench "solved"
                  cases were semantically wrong.

Each tripwire fires AT MOST ONCE per turn. A warning repeated after every tool
call is noise, and noise is the failure this project exists to prevent.

State lives in one small file per session. dk_capture.sh deletes it on the Stop
hook, which is what makes "once per turn" true. Without that deletion the
counters run for the whole session: a tripwire would fire once and stay silent
for every later loop, and 12 reads spread over five unrelated turns would
report as one turn that never converged.

Register it (the plugin does this for you):
    PostToolUse -> dk_tripwire.py
"""
import hashlib
import json
import os
import re
import sys

MAX_READS_WITHOUT_WRITE = int(os.environ.get("DK_TRIP_READS", "12"))
REPEAT_LIMIT = int(os.environ.get("DK_TRIP_REPEATS", "3"))

READ_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "NotebookRead"}
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}
TEST_PATH = re.compile(r"(^|/)(tests?|spec)/|(^|/)test_|_test\.|\.test\.|\.spec\.")
TEST_CMD = re.compile(r"\b(pytest|jest|vitest|go test|cargo test|npm test|"
                      r"unittest|rspec|phpunit|mvn test|gradle test)\b")
FAILED = re.compile(r"\b(FAILED|FAIL|failed|assertion|AssertionError|"
                    r"[1-9]\d* failed|Error:)\b")


def state_path(session):
    mem = os.environ.get("DK_MEM")
    if not mem:
        root = (os.environ.get("DK_HOME") or os.environ.get("CLAUDE_PROJECT_DIR")
                or os.getcwd())
        mem = os.path.join(root, ".claude", "memory")
    return os.path.join(mem, ".dk_trip.%s" % (session or "nosession")[:16])


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"calls": {}, "reads": 0, "writes": 0, "fired": [],
                "failed_test": False}


def save(path, st):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f)
        os.replace(tmp, path)
    except OSError:
        pass


def fingerprint(tool, tool_input):
    """A stable hash of one tool call, so a repeat is detectable.

    Sorted keys, because two calls that differ only in key order are the same
    call and must hash the same.
    """
    try:
        blob = json.dumps(tool_input, sort_keys=True)[:2000]
    except (TypeError, ValueError):
        blob = str(tool_input)[:2000]
    return hashlib.sha1(("%s|%s" % (tool, blob)).encode()).hexdigest()[:16]


def check(st, tool, tool_input, tool_output):
    """Return a warning, or None. Each kind fires at most once per turn."""
    text = json.dumps(tool_input) if not isinstance(tool_input, str) else tool_input

    if tool in READ_TOOLS:
        st["reads"] += 1
    if tool in WRITE_TOOLS:
        st["writes"] += 1
        st["reads"] = 0                        # progress resets the count

    if TEST_CMD.search(text) and FAILED.search(str(tool_output)[:4000]):
        st["failed_test"] = True

    fp = fingerprint(tool, tool_input)
    st["calls"][fp] = st["calls"].get(fp, 0) + 1

    if st["calls"][fp] >= REPEAT_LIMIT and "repeat" not in st["fired"]:
        st["fired"].append("repeat")
        return ("You have now made this exact %s call %d times with the same "
                "input. Repeating an action with no new information between "
                "attempts does not work - it is the most common way agents "
                "fail. Change the approach rather than retry it."
                % (tool, st["calls"][fp]))

    if st["reads"] >= MAX_READS_WITHOUT_WRITE and "converge" not in st["fired"]:
        st["fired"].append("converge")
        return ("You have read or searched %d times in this turn without "
                "changing anything. Say what you are looking for before you "
                "open the next file. If you cannot say it, stop reading and "
                "think." % st["reads"])

    if (tool in WRITE_TOOLS and st["failed_test"]
            and TEST_PATH.search(text) and "testedit" not in st["fired"]):
        st["fired"].append("testedit")
        return ("A test failed in this turn and you are now editing a test "
                "file. Fix the behaviour the test describes. Change a test "
                "only when the test itself is wrong, and say that is what you "
                "are doing.")
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0                               # never break a turn
    tool = payload.get("tool_name", "")
    if not tool:
        return 0
    path = state_path(payload.get("session_id", ""))
    st = load(path)
    warning = check(st, tool, payload.get("tool_input", {}),
                    payload.get("tool_output", ""))
    save(path, st)
    if warning:
        json.dump({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "<self-steering>\n! %s\n</self-steering>"
                                 % warning}}, sys.stdout)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                          # a hook must never fail a turn
        sys.exit(0)
