"""The reaction check: continue a stuck moment three ways and keep the
transcripts.

  nothing   the driver's message only, as the original session got it
  watcher   the same, with the watcher's note injected by a UserPromptSubmit
            hook, the way dk-mode delivers it
  counter   the same, with the counter baseline's templated note

Each arm starts from an identical rebuilt state (build.py) and an identical
conversation, copied under its own session id so the arms never see each
other. The coding AI is Claude Code with Haiku 4.5, as in the original
goal-mode runs, for up to MAX_TURNS tool rounds. Afterwards the grader
runs and the full transcript is kept under runs/<moment>/<arm>/.

Judging whether the AI changed course is done by READING those
transcripts, not by the score; the score is recorded as one fact.

Usage: run.py <moment> <arm> <note-file-or-'-'>
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build                                                # noqa: E402

MODEL = os.environ.get("REACT_MODEL", "claude-haiku-4-5-20251001")
MAX_TURNS = os.environ.get("REACT_MAX_TURNS", "20")
PROJ = os.path.expanduser("~/.claude/projects/-opt-jinja")

HOOK = """#!/usr/bin/env bash
# Inject the note for this moment, once, the way dk_recall.sh does (a cat).
cat "%s"
"""


def main():
    moment, arm, note = sys.argv[1], sys.argv[2], sys.argv[3]
    out = os.path.join(HERE, "runs", moment, arm)
    os.makedirs(out, exist_ok=True)
    sid = str(uuid.uuid4())
    key, msgs, cut = build.locate(moment)
    build.reset_workdir()
    n_run, mism = build.replay(msgs, cut, lambda s: None)
    line, passed, left = build.grade()
    prompt, expected = build.driver_expectation(msgs, cut)
    path, n, chars = build.write_transcript(msgs, cut, sid)
    print(f"[{arm}] state rebuilt: {left} failing (driver said {expected}); "
          f"{len(mism)} mismatches; transcript {n} turns", flush=True)

    # The original sandbox had no network. Deny the commands that would reach
    # it here, so the AI cannot fetch an answer key the original could not.
    settings = {"permissions": {"allow": ["Bash", "Edit", "Write", "Read", "Glob", "Grep"],
                                "deny": ["WebSearch", "WebFetch", "Bash(pip *)", "Bash(pip3 *)",
                                         "Bash(python -m pip *)", "Bash(python3 -m pip *)",
                                         "Bash(curl *)", "Bash(wget *)", "Bash(git clone *)",
                                         "Bash(git fetch *)", "Bash(git pull *)"]}}
    if note != "-":
        note_path = os.path.join(out, "note.txt")
        shutil.copy(note, note_path)
        hook_path = os.path.join(out, "hook.sh")
        open(hook_path, "w").write(HOOK % note_path)
        os.chmod(hook_path, 0o755)
        settings["hooks"] = {"UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": f"bash {hook_path}"}]}]}
    os.makedirs(os.path.join(build.WORK, ".claude"), exist_ok=True)
    json.dump(settings, open(os.path.join(build.WORK, ".claude", "settings.json"), "w"), indent=1)

    cmd = ["claude", "-p", "--resume", sid, "--model", MODEL, "--max-turns", MAX_TURNS,
           "--output-format", "json", prompt]
    t0 = time.time()
    env = dict(build.ENV)
    # Scoping of THIS session must not leak into the nested one: the extra
    # directory list and the lowered auto-compaction threshold.
    for k in ("CLAUDE_ADDITIONAL_DIRECTORIES", "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD",
              "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"):
        env.pop(k, None)
    r = subprocess.run(cmd, cwd=build.WORK, env=env, capture_output=True, text=True,
                       timeout=3600, stdin=subprocess.DEVNULL)
    secs = round(time.time() - t0)
    open(os.path.join(out, "claude_stdout.json"), "w").write(r.stdout)
    open(os.path.join(out, "claude_stderr.txt"), "w").write(r.stderr)
    try:
        res = json.loads(r.stdout)
    except ValueError:
        res = {}
    line2, passed2, left2 = build.grade()
    shutil.copy(path, os.path.join(out, "transcript.jsonl"))
    subprocess.run(["bash", "-c", "git diff > %s" % os.path.join(out, "final.diff")],
                   cwd=build.WORK)
    summary = {"moment": moment, "arm": arm, "session": sid, "model": MODEL, "prefix_turns": n,
               "max_turns": MAX_TURNS, "prompt": prompt, "note": note,
               "before_left": left, "after_left": left2, "grader_after": line2,
               "num_turns": res.get("num_turns"), "cost_usd": res.get("total_cost_usd"),
               "secs": secs, "exit": r.returncode, "result_tail": (res.get("result") or "")[-1500:]}
    json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=1)
    print(f"[{arm}] done: {left} -> {left2} failing, {res.get('num_turns')} turns, "
          f"${res.get('total_cost_usd')}, {secs}s, exit {r.returncode}", flush=True)
    if r.returncode:
        print(r.stderr[-800:])


if __name__ == "__main__":
    main()
