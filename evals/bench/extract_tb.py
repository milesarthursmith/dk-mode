#!/usr/bin/env python3
"""extract_tb.py - process-labeled monitor moments from PUBLIC Terminal-Bench 2
leaderboard trajectories (HF dataset harborframework/terminal-bench-2-leaderboard,
Apache-2.0).

Why: evals/bench/moments/ comes from our own small-Gemini runs and is dominated
by one mechanical failure (Edit old_string mismatch). This pulls transcripts of
COMPETENT agents (Claude Opus 4.6 under WozCode = Claude Code native session
files; Claude Code with GLM-4.7; Claude Opus 4.6 under Terminus 2 = ATIF
trajectories) and cuts moments at points where a PROCESS rule holds. Verifier
outcome (result.json reward) is recorded in the manifest for review only - it
never decides a label.

Usage (all steps idempotent, safe to rerun; nothing is committed):
  python3 extract_tb.py plan     # list dataset trees + all result.json, pick trials -> tb_cache/plan.json
  python3 extract_tb.py fetch    # download planned transcripts, convert, DELETE raw
  python3 extract_tb.py build    # label moments from the converted cache -> moments_tb/
  python3 extract_tb.py all      # plan + fetch + build
  python3 extract_tb.py stats    # bytes downloaded, cache state
Options: --cache DIR (default evals/bench/tb_cache, or $TB_CACHE), --out DIR
(default evals/bench/moments_tb), --keep-raw, --wedges-per-trial N (default 1).

Network: only the HF tree API and resolve/ URLs; goes through $HTTPS_PROXY and
the CA bundle in $SSL_CERT_FILE / $REQUESTS_CA_BUNDLE (or /root/.ccr/ca-bundle.crt).
Every byte fetched is logged to tb_cache/downloads.jsonl.

DATASET LAYOUT (found 2026-09-02)
  submissions/terminal-bench/2.0/<Agent>__<Model>/<job>/<task>__<7char>/
      result.json                    verifier_result.rewards.reward (0/1), exception_info, timings
      verifier/{reward.txt,ctrf.json,test-stdout.txt}
      agent/...                      harness-specific; the ones with real transcripts:
        ClaudeCode__GLM-4.7, WozCode__Claude-Opus-4.6:
            agent/sessions/projects/-app/<uuid>.jsonl   native Claude Code session log
            agent/trajectory.json                       ATIF conversion of the same
        Terminus2__*, Terminus-KIRA__*, Judy__*, Meta-Harness__*, vix__*:
            agent/trajectory.json                       ATIF (steps: user / agent+tool_calls+observation)
        Capy, Crux, Droid, Mux, MAYA, Simplai, copilot-cli, Forge, logos*, ...:
            no per-message transcript (only command stdout or a text log)

MOMENT FORMAT (what replay_bench.py replays): JSONL, one line per message
  {"type": "user"|"assistant", "uuid": ..., "message": {"content": "<text>"}}
An assistant message = one model turn: its text, then one "[tool_use Tool] ..."
line per call. A user message = the tool results of that turn, each rendered
"[tool result: ...]" capped at ~600 chars (head+tail), plus any real user text.
Thinking blocks and sidechains are dropped. Order is preserved.

PROCESS RULES (evaluated after every user message i over msgs[:i+1]; W = last
10 messages; "form", "norm", "files", "err_key", "norm_out" defined in the
feature functions below):
  wedge R1 repeat-cmd   >=3 calls in W with the same norm (near-identical
                        command: whitespace collapsed, digits->N, hex->H) and
                        >=2 of their results have the same norm_out (the
                        output is not changing); OR >=3 assistant messages in
                        W with identical normalized text.
  wedge R2 repeat-err   the same err_key (last error-looking line of a result,
                        normalized) occurs in >=3 distinct user messages of W.
  wedge R3 no-progress  a stretch of >=8 consecutive messages in which no
                        assistant turn introduces a new form or touches a new
                        file (relative to everything earlier in the transcript)
                        AND state is visibly not changing: >=2 substantive
                        results in the stretch are byte-identical (norm_out),
                        or the stretch is >=12 messages and >=3 results are
                        identical after digits->N (score/count churn with no
                        structural change; wait/poll calls excluded from this
                        looser test). Generic "file updated" results never
                        count as identical outputs.
  wedge R4 done-unverified  the transcript ends with a tool-free assistant
                        message that claims completion, and the last
                        substantive tool result before it carries an err_key
                        (declared done on top of an error, no verification).
  The prefix is cut at the FIRST index where a rule holds (R4: at the end).
  healthy (hard negative) at index i>=14: W has >=5 calls with >=4 distinct
                        forms, no norm repeated, no err_key in >=2 user
                        messages, >=2 turns that introduce a new form or file,
                        a successful modifying call (Write/Edit/redirect/
                        install/build) followed by a successful non-modifying
                        call (modify-then-verify), and no wedge rule holding
                        anywhere in the last 16 messages. One per trial, the
                        median candidate.
Output names: <label>_tb2-<harness>-<task>_<trialid>.jsonl, harness in
{wozcode-opus46, claudecode-glm47, terminus2-opus46}; moments_tb/manifest.json
carries per-moment provenance, rule, evidence, cut index, reward.
"""
import re as _re_redact
import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
DATASET = "harborframework/terminal-bench-2-leaderboard"
TREE_API = f"https://huggingface.co/api/datasets/{DATASET}/tree/main/"
RESOLVE = f"https://huggingface.co/datasets/{DATASET}/resolve/main/"
SUB_ROOT = "submissions/terminal-bench/2.0/"

# harness key -> submission dir, transcript kind, how many failed/passed trials to pull
SOURCES = {
    "wozcode-opus46": dict(sub="WozCode__Claude-Opus-4.6", kind="cc", n_fail=24, n_pass=12),
    "claudecode-glm47": dict(sub="ClaudeCode__GLM-4.7", kind="cc", n_fail=18, n_pass=8),
    "terminus2-opus46": dict(sub="Terminus2__Claude-Opus-4.6", kind="atif", n_fail=16, n_pass=8),
    "vix-opus47": dict(sub="vix__claude-opus-4-7", kind="atif", n_fail=14, n_pass=6),
    "terminuskira-opus46": dict(sub="Terminus-KIRA__Claude-Opus-4.6", kind="atif", n_fail=12, n_pass=6),
}
MIN_BYTES, MAX_BYTES = 15_000, 2_000_000     # transcript size window for selection
RESULT_CAP = 600          # chars per rendered tool result
CMD_CAP = 1200            # chars per rendered command
PROMPT_CAP = 6000         # chars for the task prompt
WINDOW = 10               # W
STRETCH = 8               # R3 minimum stretch
STRETCH_LOOSE = 12        # R3 digits->N variant
HEALTHY_MIN_INDEX = 14
HEALTHY_QUIET = 16        # no wedge rule in the last N messages


# ----------------------------------------------------------------- network
def _ca():
    for k in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        if os.environ.get(k) and os.path.exists(os.environ[k]):
            return os.environ[k]
    return "/root/.ccr/ca-bundle.crt" if os.path.exists("/root/.ccr/ca-bundle.crt") else None


def _opener():
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    ph = urllib.request.ProxyHandler({"https": proxy} if proxy else {})
    ctx = ssl.create_default_context(cafile=_ca())
    return urllib.request.build_opener(ph, urllib.request.HTTPSHandler(context=ctx))


class Cache:
    def __init__(self, root):
        self.root = root
        for d in ("trees", "results", "raw", "trials"):
            os.makedirs(os.path.join(root, d), exist_ok=True)
        self.log = os.path.join(root, "downloads.jsonl")

    def p(self, *parts):
        return os.path.join(self.root, *parts)

    def account(self, what, nbytes):
        with open(self.log, "a") as f:
            f.write(json.dumps({"ts": time.time(), "what": what, "bytes": nbytes}) + "\n")

    def total_bytes(self):
        if not os.path.exists(self.log):
            return 0
        return sum(json.loads(l)["bytes"] for l in open(self.log) if l.strip())

    def get(self, url, retries=4):
        err = None
        for _ in range(retries):
            try:
                with _opener().open(url, timeout=300) as r:
                    body = r.read()
                    return body, r.headers
            except Exception as e:      # noqa: BLE001 - retry any transport error
                err = e
                time.sleep(2)
        raise err

    def tree(self, path):
        """Recursive listing of a dataset directory (paginated), cached."""
        cp = self.p("trees", path.rstrip("/").split("/")[-1] + ".json")
        if os.path.exists(cp):
            return json.load(open(cp))
        out, url = [], TREE_API + urllib.parse.quote(path) + "?recursive=true"
        while url:
            body, hdr = self.get(url)
            self.account("tree:" + path, len(body))
            out += json.loads(body)
            url = None
            for part in (hdr.get("Link") or "").split(","):
                if 'rel="next"' in part:
                    url = part.split("<")[1].split(">")[0]
        json.dump(out, open(cp, "w"))
        return out

    def fetch(self, path, dest):
        """Download one dataset file to dest (skip if present). Returns bytes."""
        if os.path.exists(dest):
            return 0
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        body, _ = self.get(RESOLVE + urllib.parse.quote(path))
        with open(dest + ".part", "wb") as f:
            f.write(body)
        os.replace(dest + ".part", dest)
        self.account(path, len(body))
        return len(body)


# -------------------------------------------------------------------- plan
def _trial_parts(path):
    """-> (job, trial) for a path under a submission dir, else None."""
    parts = path.split("/")
    return (parts[4], parts[5]) if len(parts) > 6 else None


def transcript_index(tree, kind):
    """trial -> (path, size) of the transcript to use. cc: the largest main
    session file under sessions/projects/-app/ (subagents excluded); atif:
    agent/trajectory.json."""
    idx = {}
    for x in tree:
        if x.get("type") != "file":
            continue
        p = x["path"]
        tp = _trial_parts(p)
        if not tp:
            continue
        if kind == "cc":
            ok = "/sessions/projects/-app/" in p and p.endswith(".jsonl") and "/subagents/" not in p
        else:
            ok = p.endswith("/agent/trajectory.json")
        if ok:
            cur = idx.get(tp[1])
            if cur is None or x["size"] > cur[1]:
                idx[tp[1]] = (p, x["size"])
    return idx


def load_results(cache, hk, tree):
    """All result.json of a submission -> {trial: {task, reward, exception, dur}}, cached."""
    cp = cache.p("results", hk + ".json")
    if os.path.exists(cp):
        return json.load(open(cp))
    paths = [x["path"] for x in tree if x["path"].endswith("/result.json") and _trial_parts(x["path"])
             and len(x["path"].split("/")) == 7]
    print(f"[plan] {hk}: fetching {len(paths)} result.json")
    dests = [cache.p("raw", *p.split("/")[3:]) for p in paths]
    with concurrent.futures.ThreadPoolExecutor(16) as ex:
        list(ex.map(lambda pd: cache.fetch(*pd), zip(paths, dests)))
    out = {}
    for d in dests:
        r = json.load(open(d))
        rw = ((r.get("verifier_result") or {}).get("rewards") or {}).get("reward")
        exc = r.get("exception_info") or {}
        ae = r.get("agent_execution") or {}
        dur = None
        try:
            from datetime import datetime
            f = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
            dur = (f(ae["finished_at"]) - f(ae["started_at"])).total_seconds()
        except Exception:  # noqa: BLE001
            pass
        out[r["trial_name"]] = dict(task=r["task_name"], reward=rw,
                                    exception=exc.get("exception_type") if exc else None, dur=dur)
        os.remove(d)
    json.dump(out, open(cp, "w"))
    return out


def plan(cache):
    """Pick trials: failures ranked by agent runtime (long/timeout = likely
    stuck), one per task; then passes ranked by transcript size (busy), one per
    task not already taken. Deterministic."""
    sel = []
    for hk, src in SOURCES.items():
        tree = cache.tree(SUB_ROOT + src["sub"])
        idx = transcript_index(tree, src["kind"])
        res = load_results(cache, hk, tree)
        rows = [(t, r) for t, r in res.items() if t in idx and MIN_BYTES <= idx[t][1] <= MAX_BYTES]
        fails = sorted([x for x in rows if x[1]["reward"] == 0], key=lambda x: -(x[1]["dur"] or 0))
        passes = sorted([x for x in rows if x[1]["reward"] == 1], key=lambda x: -idx[x[0]][1])
        taken, chosen = set(), []
        for pool, n in ((fails, src["n_fail"]), (passes, src["n_pass"])):
            k = 0
            for t, r in pool:
                if r["task"] in taken or k >= n:
                    continue
                taken.add(r["task"]); k += 1
                chosen.append(dict(harness=hk, kind=src["kind"], sub=src["sub"], trial=t, task=r["task"],
                                   trialid=t.split("__")[-1], reward=r["reward"], exception=r["exception"],
                                   dur=r["dur"], path=idx[t][0], size=idx[t][1]))
        print(f"[plan] {hk}: {len(res)} trials in dataset, {len(idx)} with transcripts, "
              f"chose {sum(1 for c in chosen if c['reward'] == 0)} failed + "
              f"{sum(1 for c in chosen if c['reward'] == 1)} passed")
        sel += chosen
    json.dump(sel, open(cache.p("plan.json"), "w"), indent=1)
    print(f"[plan] {len(sel)} trials, {sum(c['size'] for c in sel)/1e6:.1f} MB of transcripts -> plan.json")
    return sel


# ------------------------------------------------------------ conversion
BASH_TOOLS = {"bash", "bash_command", "shell", "run_command", "execute_command", "terminal", "run"}
# snake_case tools (vix, Terminus-KIRA) normalized to their PascalCase equivalents
TOOL_ALIAS = {"write_file": "Write", "edit_file": "Edit", "read_file": "Read",
              "image_read": "Read", "delete_file": "Delete"}
DONE_TOOLS = {"mark_task_complete", "TaskStop", "attempt_completion", "finish", "task_complete"}


def is_bash(tool):
    return (tool or "").lower() in BASH_TOOLS


def canon_tool(tool):
    return TOOL_ALIAS.get(tool, tool)


def canon_input(tool, inp):
    """Map alias arg names (path -> file_path) so the PascalCase handlers work."""
    if tool in TOOL_ALIAS and isinstance(inp, dict) and "path" in inp and "file_path" not in inp:
        inp = dict(inp); inp["file_path"] = inp.pop("path")
    return inp


def bash_cmd(inp):
    """Extract the command string from a shell tool call across harness variants."""
    for k in ("command", "keystrokes", "cmd", "input", "script"):
        if inp.get(k) is not None:
            return str(inp[k])
    return ""


def _clip(s, cap, tail=150):
    s = s if isinstance(s, str) else json.dumps(s)
    if len(s) <= cap:
        return s
    return s[:cap - tail - 5] + " ... " + s[-tail:]


def _result_text(block):
    c = block.get("content")
    if isinstance(c, list):
        c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict))
    return c or ""


def render_call(tool, inp):
    inp = inp if isinstance(inp, dict) else {}
    if is_bash(tool):
        cmd = bash_cmd(inp)
        if not cmd.strip():
            return f"(wait {inp.get('duration', '')}s)"
        return _clip(cmd, CMD_CAP)
    inp, tool = canon_input(tool, inp), canon_tool(tool)
    if tool == "Edit":
        return (f"{inp.get('file_path', '')}\n<<< {_clip(inp.get('old_string', ''), 250, 60)}\n"
                f">>> {_clip(inp.get('new_string', ''), 350, 80)}")
    if tool in ("Write", "NotebookEdit"):
        return f"{inp.get('file_path') or inp.get('notebook_path', '')}\n{_clip(inp.get('content') or inp.get('new_source', ''), 400, 80)}"
    if tool == "Read":
        extra = " ".join(f"{k}={inp[k]}" for k in ("offset", "limit") if k in inp)
        return f"{inp.get('file_path', '')} {extra}".strip()
    if tool in ("Grep", "Glob"):
        return f"{inp.get('pattern', '')} {inp.get('path', '')}".strip()
    return _clip(json.dumps(inp), 400, 80)


def convert_cc(path):
    """Claude Code session jsonl -> list of turns. A turn: {role, text, calls:[{tool,input,id}],
    results:[{text,err,id}]}. Consecutive same-role lines are merged (one model turn
    emits one line per content block)."""
    turns = []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") not in ("user", "assistant") or e.get("isSidechain") in (True, "True") or e.get("isMeta"):
            continue
        c = (e.get("message") or {}).get("content")
        blocks = [{"type": "text", "text": c}] if isinstance(c, str) else (c or [])
        if not turns or turns[-1]["role"] != e["type"]:
            turns.append(dict(role=e["type"], text=[], calls=[], results=[]))
        t = turns[-1]
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and (b.get("text") or "").strip():
                t["text"].append(b["text"].strip())
            elif b.get("type") == "tool_use":
                inp = b.get("input")
                t["calls"].append(dict(tool=b.get("name", "?"), input=inp if isinstance(inp, dict) else {"raw": str(inp)},
                                       id=b.get("id")))
            elif b.get("type") == "tool_result":
                t["results"].append(dict(text=_result_text(b)[:1500], err=bool(b.get("is_error")),
                                         id=b.get("tool_use_id")))
    for t in turns:
        t["text"] = "\n".join(t["text"])
    return turns


def convert_atif(path):
    """ATIF trajectory.json (Terminus 2 etc.) -> turns. An agent step becomes an
    assistant turn (message text + tool_calls) followed by a user turn holding
    the observation results. reasoning_content (thinking) is dropped."""
    d = json.load(open(path, encoding="utf-8", errors="replace"))
    turns = []
    for s in d.get("steps", []):
        if s.get("source") == "user":
            turns.append(dict(role="user", text=(s.get("message") or "").strip(), calls=[], results=[]))
            continue
        calls = []
        for c in s.get("tool_calls") or []:
            a = c.get("arguments")
            if isinstance(a, str):
                try:
                    a = json.loads(a)
                except ValueError:
                    try:
                        import ast
                        a = ast.literal_eval(a)
                    except Exception:  # noqa: BLE001
                        a = {"raw": a}
            calls.append(dict(tool=c.get("function_name", "?"), input=a if isinstance(a, dict) else {"raw": str(a)},
                              id=c.get("tool_call_id")))
        turns.append(dict(role="assistant", text=(s.get("message") or "").strip(), calls=calls, results=[]))
        res = [dict(text=(r.get("content") or "")[:1500], err=False, id=r.get("source_call_id"))
               for r in (s.get("observation") or {}).get("results") or []]
        if res:
            turns.append(dict(role="user", text="", calls=[], results=res))
    return turns


def convert(entry, raw):
    turns = convert_cc(raw) if entry["kind"] == "cc" else convert_atif(raw)
    return dict(meta=entry, turns=turns)


def trial_key(e):
    return f"{e['harness']}__{e['task']}__{e['trialid']}"


def fetch(cache, keep_raw=False):
    plan_ = json.load(open(cache.p("plan.json")))
    n_new, nbytes = 0, 0
    for e in plan_:
        cp = cache.p("trials", trial_key(e) + ".json")
        if os.path.exists(cp):
            continue
        raw = cache.p("raw", *e["path"].split("/")[3:])
        nbytes += cache.fetch(e["path"], raw)
        json.dump(convert(e, raw), open(cp, "w"))
        if not keep_raw:
            os.remove(raw)
        n_new += 1
        print(f"[fetch] {trial_key(e)} ({e['size']/1e3:.0f} KB)")
    print(f"[fetch] {n_new} new transcripts, {nbytes/1e6:.1f} MB this run; "
          f"{cache.total_bytes()/1e6:.1f} MB downloaded in total")


# --------------------------------------------------------------- features
_WS = re.compile(r"\s+")
_HEX = re.compile(r"\b[0-9a-f]{7,}\b")
_NUM = re.compile(r"\d+")
_PROMPT = re.compile(r"root@[0-9a-f-]+:")
ERR_RE = re.compile(r"(Error|Exception|error:|ERROR|FAILED|Failed|failed|Traceback|not found|No such file|"
                    r"Permission denied|Segmentation fault|fatal:|panic:|undefined reference|command not found|"
                    r"Killed|Timeout|timed out|AssertionError|cannot |Cannot |unexpected|invalid|Invalid|"
                    r"denied|refused|Aborted|core dumped)")
GENERIC_ERR = re.compile(r"^(Exit code \d+|Traceback \(most recent call last\):|Error|New Terminal Output:|"
                         r"Current Terminal Screen:)\s*$")
GENERIC_OK = re.compile(r"(has been updated successfully|File created successfully|File written|^\s*$)")
DONE_RE = re.compile(r"(task (is )?(now )?complete|all (the )?(tests|requirements) (now )?pass|successfully "
                     r"(implemented|completed|created|built)|implementation is complete|is now complete|"
                     r"everything (is )?(works|working)|^done\b|\bcompleted the task|has been (implemented|completed))",
                     re.I)
MODIFY_RE = re.compile(r"(^|[;&|]\s*|\n\s*)(cat\s*>|tee\b|mv\b|cp\b|mkdir\b|touch\b|sed\s+-i|patch\b|git\s+(clone|checkout|apply|am)|"
                       r"pip3?\s+install|apt(-get)?\s+install|npm\s+(i|install)|make\b|cmake\b|gcc\b|g\+\+|cc\b|clang|"
                       r"cargo\s+build|go\s+build|rustc|javac|ocamlopt|dune\s+build|opam\b|conda\s+install|"
                       r"python3?\s+\S*setup\.py|\S+\s*>>?\s*[\w/.\-]+)")
_PATH = re.compile(r"(?<![\w@:])(?:/[\w.\-+@%]+){2,}|(?<![\w/.\-])[\w\-]+(?:/[\w.\-+]+)+|(?<![\w/.\-])[\w\-]+\.(?:py|c|cc|cpp|h|hpp|js|ts|rs|go|java|sh|txt|json|yaml|yml|toml|md|tex|scm|red|R|csv|html|css|ppm|png|jpg|mp4|log|cfg|conf|ml|mli|hs|lua|rb|pl|sql|xml|ini|bib|asm|s)\b")
_HEAD_SKIP = {"cd", "sudo", "time", "timeout", "nohup", "env", "exec", "then", "do", "else", "fi", "done", "if", "for", "while", "export", "source", "."}


def norm_text(s, cap=400):
    s = _PROMPT.sub("root@H:", s)
    s = _HEX.sub("H", s)
    s = _NUM.sub("N", s)
    return _WS.sub(" ", s).strip()[:cap]


def call_norm(tool, inp):
    """Near-identical-command key."""
    if is_bash(tool):
        cmd = bash_cmd(inp)
        if not cmd.strip():
            return "wait"
        if cmd.strip() in ("C-c", "C-d", "C-z"):
            return "interrupt"
        cmd = re.sub(r"\s*2>&1\s*$", "", cmd.strip())
        return "sh|" + norm_text(cmd, 600)
    inp, tool = canon_input(tool, inp), canon_tool(tool)
    if tool == "Edit":
        return f"Edit|{inp.get('file_path')}|{norm_text(inp.get('old_string', ''), 200)}"
    if tool in ("Write", "NotebookEdit"):
        return f"{tool}|{inp.get('file_path') or inp.get('notebook_path')}|" + hashlib.md5(
            norm_text(inp.get("content") or inp.get("new_source", ""), 100000).encode()).hexdigest()[:10]
    if tool == "Read":
        return f"Read|{inp.get('file_path')}|{inp.get('offset', '')}"
    return tool + "|" + norm_text(json.dumps(inp, sort_keys=True), 300)


def call_form(tool, inp):
    """Coarse 'kind of action' key: a new form is evidence of a new approach."""
    if is_bash(tool):
        cmd = bash_cmd(inp)
        if not cmd.strip():
            return "wait"
        if cmd.strip() in ("C-c", "C-d", "C-z"):
            return "interrupt"
        heads = []
        for seg in re.split(r"&&|\|\||\||;|\n", cmd):
            toks = [t for t in seg.strip().split() if "=" not in t or t.startswith("-")]
            for t in toks:
                if t.startswith("-") or t in _HEAD_SKIP:
                    continue
                h = os.path.basename(t)
                if h and h not in heads:
                    heads.append(h)
                break
            if len(heads) >= 3:
                break
        return "sh:" + "+".join(_NUM.sub("N", h) for h in heads[:3])
    inp, tool = canon_input(tool, inp), canon_tool(tool)
    if tool in ("Edit", "Write", "Read", "NotebookEdit"):
        return f"{tool}:{inp.get('file_path') or inp.get('notebook_path')}"
    if tool == "Grep":
        return f"Grep:{norm_text(inp.get('pattern', ''), 60)}"
    return tool


def call_files(tool, inp):
    fs = set()
    for k in ("file_path", "path", "notebook_path"):
        if inp.get(k):
            fs.add(str(inp[k]))
    if is_bash(tool):
        fs.update(m.group(0) for m in _PATH.finditer(bash_cmd(inp)))
    return {f for f in fs if not f.startswith("/dev/") and not f.startswith("/proc/")}


def is_modifying(tool, inp):
    if canon_tool(tool) in ("Edit", "Write", "NotebookEdit", "Delete"):
        return True
    if is_bash(tool):
        return bool(MODIFY_RE.search(bash_cmd(inp)))
    return False


def err_key(text, is_err):
    """The last error-looking line of a result (command echo lines skipped),
    normalized. Generic lines ("Exit code 1") only when nothing better exists."""
    best, generic = None, None
    for ln in text.split("\n"):
        s = ln.strip()
        if not s or s.startswith(">") or "root@" in s:
            continue
        if GENERIC_ERR.match(s):
            generic = s
            continue
        if ERR_RE.search(s):
            best = s
    pick = best or (generic if is_err else None)
    return norm_text(pick, 160) if pick else None


def norm_out(text):
    lines = [ln for ln in text.split("\n") if ln.strip() and not GENERIC_ERR.match(ln.strip())
             and not ln.strip().startswith(">") and "root@" not in ln]
    return _WS.sub(" ", "\n".join(lines)).strip()[:500]


def featurize(turns):
    """Per turn: calls -> norm/form/files/modifying; results -> err_key/norm_out
    (exact, and digits->N); plus per-turn novelty flags."""
    seen_forms, seen_files = set(), set()
    for t in turns:
        t["new_form"] = t["new_file"] = False
        for c in t["calls"]:
            c["norm"] = call_norm(c["tool"], c["input"])
            c["form"] = call_form(c["tool"], c["input"])
            c["files"] = sorted(call_files(c["tool"], c["input"]))
            c["mod"] = is_modifying(c["tool"], c["input"])
            if c["form"] not in seen_forms:
                t["new_form"] = True
            if any(f not in seen_files for f in c["files"]):
                t["new_file"] = True
            seen_forms.add(c["form"]); seen_files.update(c["files"])
        for r in t["results"]:
            r["key"] = err_key(r["text"], r["err"])
            r["out"] = norm_out(r["text"])
            r["out_n"] = _HEX.sub("H", _NUM.sub("N", r["out"]))
            r["substantive"] = len(r["out"]) >= 20 and not GENERIC_OK.search(r["out"])
        t["ntext"] = norm_text(t["text"], 300)
    return turns


def pair_results(turns):
    """Attach each result to its call (by id, else by position)."""
    for i, t in enumerate(turns):
        if t["role"] != "user" or i == 0:
            continue
        prev = turns[i - 1]
        byid = {c.get("id"): c for c in prev["calls"] if c.get("id")}
        for k, r in enumerate(t["results"]):
            c = byid.get(r.get("id")) or (prev["calls"][k] if k < len(prev["calls"]) else None)
            r["call"] = c


# ------------------------------------------------------------------ rules
BOOKKEEPING = {"TodoWrite", "TaskOutput", "TaskCreate", "Task", "ExitPlanMode"} | DONE_TOOLS


def _bookkeeping(call):
    """No-op / progress-signalling calls that are SUPPOSED to repeat and whose
    result never carries work state - excluded from R1 so they don't fake a loop.
    Genuine poll/wait stalls are still caught by R3's all-wait test."""
    return (call["tool"] in BOOKKEEPING or call["norm"] in ("wait", "interrupt")
            or call["norm"].endswith("|{}") or not call.get("files") and call["form"] in ("wait", "interrupt")
            or call["norm"] in ("bash_command|{}", "?|{}")
            # single interactive keystrokes (pager 'q', prompt 'y'/'n') are not work
            or (call["norm"].startswith("sh|") and len(call["norm"]) <= 5))


def rule_wedge(turns, i):
    """-> (rule, evidence) if a wedge rule holds at user-message index i, else None."""
    W = turns[max(0, i - WINDOW + 1):i + 1]
    # R1 repeat-cmd
    groups = collections.defaultdict(list)
    for t in W:
        if t["role"] == "user":
            for r in t["results"]:
                if r.get("call") and not _bookkeeping(r["call"]):
                    groups[r["call"]["norm"]].append(r)
    for norm, rs in groups.items():
        if len(rs) >= 3:
            outs = collections.Counter(r["out"] for r in rs)
            if outs.most_common(1)[0][1] >= 2:
                c = rs[0]["call"]
                return "R1-repeat-cmd", (f"{len(rs)}x `{_clip(render_call(c['tool'], c['input']), 90, 20)}` in last "
                                        f"{WINDOW} msgs, output unchanged")
    texts = collections.Counter(t["ntext"] for t in W if t["role"] == "assistant" and t["ntext"])
    if texts and texts.most_common(1)[0][1] >= 3:
        return "R1-repeat-text", f"assistant said the same thing {texts.most_common(1)[0][1]}x: `{texts.most_common(1)[0][0][:80]}`"
    # R2 repeat-err
    keys = collections.Counter()
    for t in W:
        if t["role"] == "user":
            for k in {r["key"] for r in t["results"] if r["key"]}:
                keys[k] += 1
    if keys and keys.most_common(1)[0][1] >= 3:
        k, n = keys.most_common(1)[0]
        return "R2-repeat-err", f"error `{k[:90]}` in {n} of last {WINDOW} msgs"
    # R3 no-progress: walk back while no assistant turn brings anything new
    j = i
    while j >= 0 and not (turns[j]["role"] == "assistant" and (turns[j]["new_form"] or turns[j]["new_file"])):
        j -= 1
    stretch = turns[j + 1:i + 1]
    if len(stretch) >= STRETCH:
        res = [r for t in stretch if t["role"] == "user" for r in t["results"] if r["substantive"]]
        exact = collections.Counter(r["out"] for r in res)
        forms = sorted({c["form"] for t in stretch for c in t["calls"]})
        allwait = forms == ["wait"] or forms == ["interrupt", "wait"]
        if exact and exact.most_common(1)[0][1] >= (6 if allwait else 2):
            return "R3-no-progress", (f"{len(stretch)} msgs without a new command form or file "
                                      f"(forms: {', '.join(forms)[:80]}), identical output x{exact.most_common(1)[0][1]}")
        if len(stretch) >= STRETCH_LOOSE and not allwait:
            loose = collections.Counter(r["out_n"] for r in res if r.get("call") and r["call"]["form"] != "wait")
            if loose and loose.most_common(1)[0][1] >= 3:
                return "R3-no-progress", (f"{len(stretch)} msgs without a new command form or file "
                                          f"(forms: {', '.join(forms)[:80]}), output identical up to numbers x{loose.most_common(1)[0][1]}")
    return None


def rule_done_unverified(turns):
    last = turns[-1]
    if last["role"] != "assistant" or last["calls"] or not DONE_RE.search(last["text"]):
        return None
    for t in reversed(turns[:-1]):
        if t["role"] == "user" and any(r["substantive"] for r in t["results"]):
            keys = [r["key"] for r in t["results"] if r["key"] and r["substantive"]]
            if keys:
                return "R4-done-unverified", f"declared done right after `{keys[-1][:90]}`"
            return None
    return None


def rule_healthy(turns, i, wedge_at):
    if i < HEALTHY_MIN_INDEX or any(i - HEALTHY_QUIET < w <= i for w in wedge_at):
        return None
    W = turns[max(0, i - WINDOW + 1):i + 1]
    calls = [c for t in W for c in t["calls"]]
    if len(calls) < 5 or len({c["form"] for c in calls}) < 4:
        return None
    if max(collections.Counter(c["norm"] for c in calls).values()) > 1:
        return None
    keys = collections.Counter()
    for t in W:
        if t["role"] == "user":
            for k in {r["key"] for r in t["results"] if r["key"]}:
                keys[k] += 1
    if keys and max(keys.values()) >= 2:
        return None
    if sum(1 for t in W if t["role"] == "assistant" and (t["new_form"] or t["new_file"])) < 2:
        return None
    mod_ok = None
    for t in W:
        if t["role"] != "user":
            continue
        for r in t["results"]:
            c = r.get("call")
            if not c or r["err"] or r["key"]:
                continue
            if c["mod"]:
                mod_ok = mod_ok or True
            elif mod_ok:
                forms = sorted({c["form"] for c in calls})
                return "healthy", f"{len(calls)} varied calls ({len(forms)} forms), modify-then-verify, no repeats/errors"
    return None


def build(cache, out_dir, wedges_per_trial=1, max_healthy=None):
    os.makedirs(out_dir, exist_ok=True)
    for f in os.listdir(out_dir):                     # idempotent: rebuild from scratch
        if f.endswith(".jsonl") or f == "manifest.json":
            os.remove(os.path.join(out_dir, f))
    wedge_picks, healthy_cands = [], []               # collect first, then balance healthy
    for fn in sorted(os.listdir(cache.p("trials"))):
        d = json.load(open(cache.p("trials", fn)))
        e, turns = d["meta"], featurize(d["turns"])
        pair_results(turns)
        wedges, wedge_at, last_w = [], [], -100
        for i, t in enumerate(turns):
            if t["role"] != "user" or i < 5:
                continue
            w = rule_wedge(turns, i)
            if w:
                wedge_at.append(i)
                if len(wedges) < wedges_per_trial and i - last_w >= 40 and all(w[0] != x[1] for x in wedges):
                    wedges.append((i, w[0], w[1])); last_w = i
        d4 = rule_done_unverified(turns)
        if d4 and len(wedges) < wedges_per_trial + 1 and (not wedges or len(turns) - 1 - wedges[-1][0] >= 20):
            wedges.append((len(turns) - 1, d4[0], d4[1]))
        for w in wedges:
            wedge_picks.append((e, turns, "wedge") + w)
        healthy = [(i,) + rule_healthy(turns, i, wedge_at) for i in range(len(turns))
                   if turns[i]["role"] == "user" and rule_healthy(turns, i, wedge_at)]
        if healthy:
            i, _, ev = healthy[len(healthy) // 2]
            # priority: passing trials and trials with no wedge first, then longer transcripts
            prio = (0 if e["reward"] == 1 else 1, 0 if not wedges else 1, -len(turns))
            healthy_cands.append((prio, e, turns, "healthy", i, "healthy", ev))
    if max_healthy is None:                           # balance: healthy count ~ wedge count
        max_healthy = len(wedge_picks) + 6
    healthy_cands.sort(key=lambda c: c[0])
    picks = wedge_picks + [c[1:] for c in healthy_cands[:max_healthy]]

    manifest, counts, used = [], collections.Counter(), collections.Counter()
    for pick in picks:
        e, turns, label, cut, rule, ev = pick
        msgs = [render_turn(t) for t in turns[:cut + 1]]
        msgs = [m for m in msgs if m["message"]["content"].strip()]
        if len(msgs) < 6:
            continue
        base = f"{label}_tb2-{e['harness']}-{e['task']}_{e['trialid']}"
        used[base] += 1
        suffix = "" if used[base] == 1 else "b" * (used[base] - 1)
        name = base + suffix + ".jsonl"
        with open(os.path.join(out_dir, name), "w") as f:
            f.write(redact_secrets("\n".join(json.dumps(m) for m in msgs)) + "\n")
        manifest.append(dict(file=name, label=label, rule=rule, evidence=ev, harness=e["harness"],
                             task=e["task"], trial=e["trial"], cut_index=cut, n_messages=len(msgs),
                             total_messages=len(turns), reward=e["reward"], exception=e["exception"],
                             agent_seconds=e["dur"], source_path=e["path"]))
        counts[(label, e["harness"])] += 1
    json.dump(manifest, open(os.path.join(out_dir, "manifest.json"), "w"), indent=1)
    print(f"[build] {len(manifest)} moments -> {out_dir}/")
    for k in sorted(counts):
        print(f"   {k[0]:8} {k[1]:18} {counts[k]}")
    print("   wedge rules:", dict(collections.Counter(m["rule"] for m in manifest if m["label"] == "wedge")))


def render_turn(t):
    if t["role"] == "assistant":
        parts = [t["text"]] if t["text"] else []
        for c in t["calls"]:
            parts.append(f"[tool_use {c['tool']}] {render_call(c['tool'], c['input'])}")
        text = "\n".join(parts)
    else:
        parts = [_clip(t["text"], PROMPT_CAP, 400)] if t["text"] else []
        for r in t["results"]:
            parts.append(f"[tool result: {'ERROR ' if r['err'] else ''}{_clip(r['text'], RESULT_CAP)}]")
        text = "\n".join(parts)
    return {"type": t["role"], "uuid": str(uuid.uuid4()), "message": {"content": text}}


def stats(cache):
    per = collections.Counter()
    if os.path.exists(cache.log):
        for l in open(cache.log):
            r = json.loads(l)
            per[r["what"].split("/")[3] if r["what"].startswith("submissions/") else r["what"].split(":")[0]] += r["bytes"]
    print(f"downloaded {cache.total_bytes()/1e6:.1f} MB total")
    for k, v in per.most_common():
        print(f"   {v/1e6:8.1f} MB  {k}")
    print(f"cache: {len(os.listdir(cache.p('trials')))} converted trials, "
          f"raw dir {sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(cache.p('raw')) for f in fs)/1e6:.1f} MB")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["plan", "fetch", "build", "all", "stats"])
    ap.add_argument("--cache", default=os.environ.get("TB_CACHE", os.path.join(HERE, "tb_cache")))
    ap.add_argument("--out", default=os.path.join(HERE, "moments_tb"))
    ap.add_argument("--keep-raw", action="store_true")
    ap.add_argument("--wedges-per-trial", type=int, default=2)
    ap.add_argument("--max-healthy", type=int, default=None,
                    help="cap healthy moments (default: wedge count + 6, for balance)")
    a = ap.parse_args()
    cache = Cache(a.cache)
    if a.cmd in ("plan", "all"):
        plan(cache)
    if a.cmd in ("fetch", "all"):
        fetch(cache, a.keep_raw)
    if a.cmd in ("build", "all"):
        build(cache, a.out, a.wedges_per_trial, a.max_healthy)
    if a.cmd == "stats":
        stats(cache)


if __name__ == "__main__":
    main()


# --- secret redaction (GitHub push protection rejects fixture tokens that
# some TB tasks, e.g. sanitize-git-repo, deliberately contain) ---
_SECRET_RX = _re_redact.compile("|".join([
    r"hf_[A-Za-z0-9]{20,}", r"sk-[A-Za-z0-9_\-]{20,}", r"ghp_[A-Za-z0-9]{30,}",
    r"gho_[A-Za-z0-9]{30,}", r"github_pat_[A-Za-z0-9_]{20,}", r"AKIA[0-9A-Z]{16}",
    r"xox[baprs]-[A-Za-z0-9\-]{10,}", r"AIza[0-9A-Za-z_\-]{30,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"]))


def redact_secrets(text):
    return _SECRET_RX.sub("<REDACTED_SECRET>", text)
