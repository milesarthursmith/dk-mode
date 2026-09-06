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
# cli: the `claude` login on this machine (Anthropic models). openrouter: the
# same Claude Code binary pointed at OpenRouter's Anthropic-format endpoint,
# which is how the ORIGINAL stuck sessions ran (google/gemini-2.5-flash inside
# the Claude Code harness). Needs OPENROUTER_API_KEY.
BACKEND = os.environ.get("REACT_BACKEND", "cli")
PROJ = os.path.expanduser("~/.claude/projects/-opt-jinja")

HOOK = """#!/usr/bin/env bash
# Inject the note for this moment, once, the way dk_recall.sh does (a cat).
cat "%s"
"""


def trust_workdir():
    """Claude Code ignores a project's .claude/settings.json allow list until
    the project is marked trusted in ~/.claude.json."""
    p = os.path.expanduser("~/.claude.json")
    try:
        cfg = json.load(open(p))
    except (OSError, ValueError):
        cfg = {}
    proj = cfg.setdefault("projects", {}).setdefault(build.WORK, {})
    if not proj.get("hasTrustDialogAccepted"):
        proj["hasTrustDialogAccepted"] = True
        json.dump(cfg, open(p, "w"), indent=2)


def openrouter_usage():
    """Real spend so far on the OpenRouter key (USD), or None."""
    import urllib.request
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return None
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/credits",
                                     headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())["data"]["total_usage"]
    except Exception:
        return None


def nested_env():
    """Environment for the nested Claude Code. Scoping of THIS session must
    not leak into it: the extra directory list and the lowered
    auto-compaction threshold. For openrouter, start from nothing, or the
    binary keeps the host login and sends no auth header at all."""
    if BACKEND == "openrouter":
        env = {"HOME": os.path.expanduser("~"), "PATH": build.ENV["PATH"],
               "ANTHROPIC_BASE_URL": "https://openrouter.ai/api",
               "ANTHROPIC_AUTH_TOKEN": os.environ["OPENROUTER_API_KEY"],
               "DISABLE_TELEMETRY": "1", "LANG": os.environ.get("LANG", "C.UTF-8")}
        for k in ("HTTPS_PROXY", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE",
                  "REQUESTS_CA_BUNDLE", "PIP_CERT", "GIT_SSL_CAINFO"):
            if os.environ.get(k):
                env[k] = os.environ[k]
        return env
    env = dict(build.ENV)
    for k in ("CLAUDE_ADDITIONAL_DIRECTORIES", "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD",
              "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"):
        env.pop(k, None)
    return env


def main():
    moment, arm, note = sys.argv[1], sys.argv[2], sys.argv[3]
    out = os.path.join(HERE, "runs", moment, arm)
    os.makedirs(out, exist_ok=True)
    sid = str(uuid.uuid4())
    key, msgs, cut = build.locate(moment)
    pristine = build.reset_workdir()
    n_run, mism = build.replay(msgs, cut, lambda s: None, pristine)
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

    trust_workdir()
    cmd = ["claude", "-p", "--resume", sid, "--model", MODEL, "--max-turns", MAX_TURNS,
           "--output-format", "json", prompt]
    t0 = time.time()
    usage0 = openrouter_usage() if BACKEND == "openrouter" else None
    r = subprocess.run(cmd, cwd=build.WORK, env=nested_env(), capture_output=True, text=True,
                       timeout=3600, stdin=subprocess.DEVNULL)
    secs = round(time.time() - t0)
    usage1 = openrouter_usage() if BACKEND == "openrouter" else None
    spent = (round(usage1 - usage0, 4) if usage0 is not None and usage1 is not None
             else None)
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
    # cost_usd is Claude Code's own estimate at Anthropic prices; for the
    # openrouter backend it is wrong, and openrouter_spent_usd is the truth.
    summary = {"moment": moment, "arm": arm, "session": sid, "model": MODEL,
               "backend": BACKEND, "prefix_turns": n,
               "max_turns": MAX_TURNS, "prompt": prompt, "note": note,
               "before_left": left, "after_left": left2, "grader_after": line2,
               "num_turns": res.get("num_turns"), "cost_usd": res.get("total_cost_usd"),
               "openrouter_spent_usd": spent,
               "secs": secs, "exit": r.returncode, "result_tail": (res.get("result") or "")[-1500:]}
    json.dump(summary, open(os.path.join(out, "summary.json"), "w"), indent=1)
    print(f"[{arm}] done: {left} -> {left2} failing, {res.get('num_turns')} turns, "
          f"${res.get('total_cost_usd')} (cli estimate), openrouter ${spent}, "
          f"{secs}s, exit {r.returncode}", flush=True)
    if r.returncode:
        print(r.stderr[-800:])


if __name__ == "__main__":
    main()
