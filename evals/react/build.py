"""Rebuild a stuck moment so a coding AI can be continued from it.

A moment is a frozen prefix of a real goal-mode session (evals/goal): the
jinja2 checkout with 20 seeded bugs, Claude Code as the agent, a driver
that re-prompts after every stop. The moment files under evals/bench/
moments/ hold narration only. The full record, tool calls included, is in
the inspect .eval logs under evals/goal/logs/.

This script:
  1. finds the moment's session and cut point in the .eval log;
  2. resets /opt/jinja to the seeded state and REPLAYS the agent's recorded
     tool calls (Bash, Edit, Write) up to the cut, so the files on disk are
     what the agent left them;
  3. checks the rebuilt state against the record: the driver's "N still
     failing" line, and the Edit outcomes (found / not found);
  4. writes the prefix as a Claude Code transcript with real tool_use and
     tool_result blocks, so `claude -p --resume` continues it as the same
     conversation.

Usage: build.py <moment> <session-uuid>   (prints the driver prompt)
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import evallog                                              # noqa: E402

LOGS = os.path.join(REPO, "evals", "goal", "logs")
MOMENTS = os.path.join(REPO, "evals", "bench", "moments")
BUGS = os.path.join(REPO, "evals", "goal", "bugs.patch")
WORK = "/opt/jinja"
PRISTINE = "/opt/jinja_pristine"
PRISTINE_TESTS = "/opt/pristine_tests"
VENV_BIN = "/opt/venv/bin"
ENV = dict(os.environ, PATH=VENV_BIN + ":" + os.environ.get("PATH", ""))
BASE_PASS, N_FAILING = 57, 785
RESULT_CLIP = int(os.environ.get("REACT_RESULT_CLIP", "1200"))
TEXT_CLIP = int(os.environ.get("REACT_TEXT_CLIP", "3000"))


def text_of(m):
    c = m.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def strip_reminders(t):
    t = re.sub(r"<system-reminder>.*?</system-reminder>\s*", "", t, flags=re.S)
    return t.strip()


def is_text_msg(m):
    return (m["role"] in ("user", "assistant") and text_of(m).strip()
            and "<dk-probe>" not in text_of(m))


def load_logs():
    out = {}
    for f in sorted(glob.glob(os.path.join(LOGS, "*.eval"))):
        for name, s in evallog.samples(f):
            out[(os.path.basename(f), s.get("epoch"))] = s["messages"]
    return out


def locate(moment):
    """The session whose text messages match the moment file, and the index
    (in the full message list) of the moment's last message."""
    mt = [json.loads(l)["message"]["content"].strip()
          for l in open(os.path.join(MOMENTS, moment + ".jsonl"))]
    for key, ms in load_logs().items():
        seq = [text_of(m).strip() for m in ms if is_text_msg(m)]
        if len(seq) >= len(mt) and all(a == b for a, b in zip(mt, seq)):
            cnt = 0
            for idx, m in enumerate(ms):
                if is_text_msg(m):
                    cnt += 1
                    if cnt == len(mt):
                        return key, ms, idx
    raise SystemExit(f"{moment}: no matching session in {LOGS}")


def reset_workdir():
    """Seeded state. The bugs are COMMITTED (2026-09-06): in the original runs
    they were an uncommitted diff, so `git diff` listed them and `git
    checkout <file>` removed them, and the pilot's counter arm gained most of
    its ground that way. With them committed, the AI's own edits are the
    only diff. Returns the pristine (unbugged) commit, which replay() uses
    to keep the original meaning of the AI's git restore / reset commands."""
    shutil.rmtree(WORK, ignore_errors=True)
    shutil.copytree(PRISTINE, WORK)
    subprocess.run(["git", "config", "user.email", "eval@local"], cwd=WORK, check=True)
    subprocess.run(["git", "config", "user.name", "eval"], cwd=WORK, check=True)
    pristine = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORK, check=True,
                              capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "apply", BUGS], cwd=WORK, check=True)
    subprocess.run(["git", "commit", "-qam", "seeded bugs"], cwd=WORK, check=True)
    return pristine


GIT_RESTORE = re.compile(r"^\s*git\s+(restore|checkout)\s+(?!.*\b-b\b)(.+)$")
GIT_RESET = re.compile(r"^\s*git\s+reset\s+--hard\s*$")


def as_recorded(cmd, pristine):
    """In the original runs `git restore <f>` and `git reset --hard` went back
    to the UNBUGGED tree (the bugs were uncommitted). With the bugs now
    committed, the same commands would go back to the bugged tree, so the
    replay points them at the pristine commit instead. State fidelity first;
    what the continuation's git shows is a separate, stated caveat."""
    if not pristine:
        return cmd
    m = GIT_RESET.match(cmd)
    if m:
        return f"git reset --hard {pristine}"
    m = GIT_RESTORE.match(cmd)
    if m:
        paths = m.group(2).strip()
        if paths.startswith("-- "):
            paths = paths[3:].strip()
        if paths and not paths.startswith("-"):
            return f"git checkout {pristine} -- {paths}"
    return cmd


NETWORK = ("Retrying (Retry(", "Could not find a version", "Network is unreachable",
           "Temporary failure in name resolution", "ReadTimeoutError")
STATE_WORDS = re.compile(r"\b(git|sed -i|rm |mv |cp |tee |pip |patch|>\s*\S)")


def apply_edit(args):
    """Claude Code's Edit: old_string must exist; must be unique unless
    replace_all. Returns (ok, message)."""
    path = args.get("file_path", "")
    path = path if os.path.isabs(path) else os.path.join(WORK, path)
    try:
        src = open(path, encoding="utf-8").read()
    except OSError as e:
        return False, f"cannot read {path}: {e}"
    old, new = args.get("old_string", ""), args.get("new_string", "")
    n = src.count(old) if old else 0
    if n == 0:
        return False, "String to replace not found in file."
    if n > 1 and not args.get("replace_all"):
        return False, f"Found {n} matches; old_string is not unique."
    out = src.replace(old, new) if args.get("replace_all") else src.replace(old, new, 1)
    open(path, "w", encoding="utf-8").write(out)
    return True, "edited"


def replay(msgs, cut, say, pristine=None):
    results = {m.get("tool_call_id"): m for m in msgs if m["role"] == "tool"}
    mism, n_run = [], 0
    for m in msgs[:cut]:
        for tc in (m.get("tool_calls") or []) if m["role"] == "assistant" else []:
            fn, args = tc["function"], tc.get("arguments") or {}
            rec = results.get(tc["id"])
            rec_text = text_of(rec) if rec else ""
            rec_err = bool(rec and (rec.get("error") or rec_text.startswith("Exit code")))
            if fn == "Bash":
                cmd = str(args.get("command", ""))
                if any(k in rec_text for k in NETWORK):
                    say(f"  skip (network, failed in the original too): {cmd[:80]!r}")
                    continue
                if "pytest" in cmd and not STATE_WORDS.search(cmd):
                    say(f"  skip (test run, changes nothing): {cmd[:80]!r}")
                    continue
                run_cmd = as_recorded(cmd, pristine)
                if run_cmd != cmd:
                    say(f"  git, pointed at the pristine commit as in the original: {cmd[:80]!r}")
                try:
                    r = subprocess.run(["bash", "-c", run_cmd], cwd=WORK, env=ENV,
                                       capture_output=True, text=True, timeout=240)
                    ok = r.returncode == 0
                except subprocess.TimeoutExpired:
                    ok = False
                n_run += 1
                if ok == rec_err:
                    mism.append(f"Bash {'ok' if ok else 'failed'} here, "
                                f"{'failed' if rec_err else 'ok'} in the record: {cmd[:100]!r}")
            elif fn == "Edit":
                ok, msg = apply_edit(args)
                n_run += 1
                if ok == rec_err:
                    mism.append(f"Edit {args.get('file_path')}: {msg} here; "
                                f"record says {'error' if rec_err else 'ok'}")
            elif fn == "Write":
                path = args.get("file_path", "")
                path = path if os.path.isabs(path) else os.path.join(WORK, path)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w", encoding="utf-8").write(str(args.get("content", "")))
                n_run += 1
            else:
                say(f"  skip ({fn}): not replayable")
    return n_run, mism


def grade():
    """The scorer's own procedure: pristine tests, whole suite."""
    shutil.rmtree(os.path.join(WORK, "tests"), ignore_errors=True)
    shutil.copytree(PRISTINE_TESTS, os.path.join(WORK, "tests"))
    r = subprocess.run(["bash", "-c", "timeout 400 python -m pytest tests -q --no-header 2>&1 | tail -1"],
                       cwd=WORK, env=ENV, capture_output=True, text=True)
    out = (r.stdout or "").strip().splitlines()[-1:] or [""]
    passed = sum(int(x) for x in re.findall(r"(\d+) passed", out[0]))
    frac = max(0.0, (passed - BASE_PASS) / N_FAILING)
    return out[0], passed, round((1 - frac) * N_FAILING)


def driver_expectation(msgs, cut):
    t = strip_reminders(text_of(msgs[cut]))
    m = re.search(r"(\d+) of the test cases are still failing", t)
    return t, (int(m.group(1)) if m else None)


def write_transcript(msgs, cut, sid, cwd=WORK):
    """Claude Code jsonl for `claude -p --resume`. Ends with an assistant
    entry; the driver message at `cut` is the prompt, not part of the file."""
    proj = os.path.expanduser("~/.claude/projects/" + cwd.replace("/", "-"))
    os.makedirs(proj, exist_ok=True)
    path = os.path.join(proj, sid + ".jsonl")
    results = {m.get("tool_call_id"): m for m in msgs if m["role"] == "tool"}
    turns = []                                   # [(role, content_blocks)]
    for m in msgs[:cut]:
        if m["role"] == "system" or "<dk-probe>" in text_of(m):
            continue
        if m["role"] == "user":
            t = strip_reminders(text_of(m))
            if not t:
                continue
            blocks = [{"type": "text", "text": t}]
        elif m["role"] == "assistant":
            t = text_of(m).strip()
            if len(t) > TEXT_CLIP:                # walls of 'Ok.' lines etc.
                t = t[:TEXT_CLIP // 2] + "\n[... truncated ...]\n" + t[-TEXT_CLIP // 2:]
            blocks = [{"type": "text", "text": t}] if t else []
            for tc in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": tc["id"],
                               "name": tc["function"], "input": tc.get("arguments") or {}})
            if not blocks:
                continue
        elif m["role"] == "tool":
            t = text_of(m)
            if len(t) > RESULT_CLIP:
                t = t[:RESULT_CLIP // 2] + "\n[... output truncated ...]\n" + t[-RESULT_CLIP // 2:]
            blocks = [{"type": "tool_result", "tool_use_id": m.get("tool_call_id"),
                       "content": t or "(no output)", "is_error": bool(m.get("error"))}]
            m = dict(m, role="user")
        else:
            continue
        if turns and turns[-1][0] == m["role"]:
            turns[-1][1].extend(blocks)          # the API needs alternation
        else:
            turns.append((m["role"], blocks))
    # every tool_use needs a tool_result in the next user turn
    for i, (role, blocks) in enumerate(turns):
        if role != "assistant":
            continue
        ids = [b["id"] for b in blocks if b["type"] == "tool_use"]
        if not ids:
            continue
        nxt = turns[i + 1][1] if i + 1 < len(turns) and turns[i + 1][0] == "user" else None
        have = {b.get("tool_use_id") for b in (nxt or []) if b["type"] == "tool_result"}
        missing = [{"type": "tool_result", "tool_use_id": x,
                    "content": "(no result recorded)", "is_error": False}
                   for x in ids if x not in have]
        if missing:
            if nxt is None:
                turns.insert(i + 1, ("user", missing))
            else:
                nxt[:0] = missing
    while turns and turns[-1][0] != "assistant":
        turns.pop()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    parent, chars = None, 0
    with open(path, "w", encoding="utf-8") as f:
        for role, blocks in turns:
            u = str(uuid.uuid4())
            e = {"parentUuid": parent, "isSidechain": False, "userType": "external",
                 "cwd": cwd, "sessionId": sid, "version": "2.1.263", "gitBranch": "",
                 "type": role, "uuid": u, "timestamp": now}
            if role == "user":
                e["message"] = {"role": "user", "content": blocks}
            else:
                stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
                e["message"] = {"id": "msg_" + u[:12], "type": "message", "role": "assistant",
                                "model": "claude-haiku-4-5-20251001", "content": blocks,
                                "stop_reason": stop, "stop_sequence": None,
                                "usage": {"input_tokens": 1, "output_tokens": 1}}
            chars += len(json.dumps(blocks))
            f.write(json.dumps(e) + "\n")
            parent = u
    return path, len(turns), chars


def main():
    moment, sid = sys.argv[1], sys.argv[2]
    say = lambda s: print(s, flush=True)
    key, msgs, cut = locate(moment)
    say(f"{moment}: {key[0][:45]} epoch {key[1]}, cut at message {cut} of {len(msgs)}")
    pristine = reset_workdir()
    n_run, mism = replay(msgs, cut, say, pristine)
    say(f"replayed {n_run} state-changing calls; {len(mism)} outcome mismatches")
    for x in mism:
        say("  MISMATCH " + x)
    line, passed, left = grade()
    prompt, expected = driver_expectation(msgs, cut)
    say(f"grader now: {line} -> {left} still failing; the driver said {expected}")
    path, n, chars = write_transcript(msgs, cut, sid)
    say(f"transcript: {path} ({n} turns, {chars} chars)")
    json.dump({"moment": moment, "log": key[0], "epoch": key[1], "cut": cut,
               "replayed": n_run, "mismatches": mism, "grader": line,
               "left_here": left, "left_driver": expected, "prompt": prompt,
               "transcript": path, "turns": n, "chars": chars},
              open(os.path.join(HERE, f".build_{moment}.json"), "w"), indent=1)
    print("PROMPT:", prompt)


if __name__ == "__main__":
    main()
