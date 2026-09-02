"""The decided shape (docs/SHAPE.md): a stateful LLM watcher.

One continuous monitor conversation per agent session. Each invocation
(same CLI contract as dk_watch: argv[1] = transcript path, DK_* env,
verdict written to $DK_MEM/.dk_active.<session> for dk_recall) feeds the
watcher only the DELTA since its last look, annotated with deterministic
signals it is free to overrule. The watcher keeps its own notes and
expectations; those, not the raw history, are its memory - old exchanges
are dropped from its context once distilled (self-compaction).

Judgement decides when to speak. Nothing mechanical gates it.
"""
import json
import os
import re
import sys
import urllib.request

MEM = os.environ.get("DK_MEM", os.path.expanduser("~/.dk-mem"))
API_URL = os.environ.get("DK_API_URL",
                         "https://openrouter.ai/api/v1/chat/completions")
KEY = os.environ.get("DK_API_KEY", "")
MODEL = os.environ.get("DK_WATCH_MODELS", "google/gemini-2.5-flash").split(",")[0]
TIMEOUT = int(os.environ.get("DK_WATCH_TIMEOUT", "110"))
# watcher context: system + goal + latest notes + last K raw exchanges
KEEP_EXCHANGES = int(os.environ.get("DK_WATCHER_KEEP", "3"))
PER_MSG = 1200
# Grounded interventions (SHAPE.md #4): when the watcher decides to speak
# and names a lookup, search and rewrite the alert around what was found.
# OFF unless a key is present; keep it off on benchmarks with public fixes.
EXA_KEY = os.environ.get("EXA_API_KEY", "")
EXA_URL = os.environ.get("EXA_URL", "https://api.exa.ai/search")

SYSTEM = """You are a session watcher: an experienced engineer quietly \
observing another engineer (the agent) work, exactly as a human overseer \
would. You see the session in increments. You maintain:

NOTES - your running understanding: the goal, what the agent has tried, \
what failed, what it keeps doing, whether the work is serving the goal.
EXPECTATIONS - every time the agent claims or implies "X will happen" \
("this edit fixes the lexer tests"), record it. On your next look, check \
it. An agent whose predictions keep failing has lost credibility: judge \
its stated confidence accordingly, as a person would after the third \
"almost done".

Lines marked [sense: ...] are mechanical annotations (repeat counts, \
error streaks, score plateaus). They are senses, not verdicts - you may \
overrule them in either direction (a repeated command can be a legitimate \
sweep; a quiet stretch can be a wedge).

Speak ONLY when your accumulated understanding says the session is off \
track: circling, drifted from the goal, violating a stated constraint, \
claiming done without evidence, or persisting with an approach your notes \
show already failed. When you speak, address the agent as "you", one or \
two sentences, and cite the concrete facts from your notes (which attempt \
count, which unchanged failure, which broken prediction). Silence is the \
right answer while real progress is happening - but a wedge you can see \
in your notes and stay silent about is the one failure you are here to \
prevent.

If you decide to speak and the agent is stuck on a specific error, \
library behaviour or tool quirk that a web search would likely explain, \
set "lookup" to a short search query (the error text plus the library \
name). You will get results and a chance to rewrite your intervention \
around a concrete fact. Otherwise "lookup" is null.

Reply with JSON only:
{"notes": "...", "expectations": ["..."], "speak": "..." or null,
 "lookup": "..." or null}"""

GROUND = """Search results for your lookup are below. Rewrite your \
intervention so it leads with the most useful concrete fact from them \
(what the error usually means, the known cause, the fix pattern) and \
names the source domain in brackets. Keep it to two or three sentences, \
addressed to the agent as "you". If nothing relevant came back, keep your \
original intervention. Reply with JSON only: {"speak": "..."}"""


def exa_search(query):
    body = {"query": query[:300], "numResults": 4, "type": "auto",
            "contents": {"text": {"maxCharacters": 1200}}}
    req = urllib.request.Request(
        EXA_URL, data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "x-api-key": EXA_KEY})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    out = []
    for r in data.get("results", [])[:4]:
        out.append(f"[{r.get('url','')}]\n{(r.get('text') or '')[:1200]}")
    return "\n\n".join(out)


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def read_transcript(path):
    msgs = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if (e.get("isSidechain") or e.get("isMeta")
                        or e.get("type") not in ("user", "assistant")):
                    continue
                c = (e.get("message") or {}).get("content")
                if isinstance(c, list):
                    c = "\n".join(b.get("text", "") for b in c
                                  if isinstance(b, dict) and b.get("type") == "text")
                if isinstance(c, str) and c.strip():
                    msgs.append({"role": e["type"], "text": c.strip()})
    except OSError:
        pass
    return msgs


def signals(msgs):
    """Deterministic senses over the WHOLE transcript - repeat counts and
    plateaus survive any context window because they are recomputed."""
    out = []
    # repeated near-identical assistant messages (first 120 chars)
    seen = {}
    for m in msgs:
        if m["role"] != "assistant":
            continue
        k = re.sub(r"\s+", " ", m["text"][:120])
        seen[k] = seen.get(k, 0) + 1
    rep = {k: v for k, v in seen.items() if v >= 3}
    for k, v in sorted(rep.items(), key=lambda x: -x[1])[:3]:
        out.append(f"[sense: assistant repeated near-identical message x{v}: \"{k[:70]}...\"]")
    # driver-reported score plateau
    pcts = [int(m.group(1)) for t in msgs
            for m in [re.search(r"\((\d+)% fixed\)", t["text"])] if m]
    if len(pcts) >= 3 and len(set(pcts[-3:])) == 1:
        out.append(f"[sense: reported progress flat at {pcts[-1]}% for {len(pcts) - pcts[::-1].index(pcts[-1])} checks]")
    # error mentions streak in recent assistant messages
    errs = sum(1 for m in msgs[-8:] if m["role"] == "assistant"
               and re.search(r"error|failed|apolog", m["text"], re.I))
    if errs >= 4:
        out.append(f"[sense: {errs} of last 8 assistant messages mention errors/failures]")
    return out


def call_model(messages):
    body = {"model": MODEL, "max_tokens": 2000, "temperature": 0,
            "messages": messages}
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode(),
        headers={"content-type": "application/json",
                 "authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read())
    ch = data.get("choices") or []
    return (ch[0].get("message", {}).get("content") or "") if ch else ""


def main():
    transcript = sys.argv[1]
    session = os.environ.get("DK_SESSION", "session")[:16]
    os.makedirs(MEM, exist_ok=True)
    state_p = os.path.join(MEM, f".watcher_state.{session}")
    convo_p = os.path.join(MEM, f".watcher_convo.{session}")
    state = _load(state_p, {"seen": 0, "notes": "", "expectations": []})
    convo = _load(convo_p, [])

    msgs = read_transcript(transcript)
    delta = msgs[state["seen"]:]
    if not delta:
        return 0
    lines = [f"[{m['role']}] {m['text'][:PER_MSG]}" for m in delta]
    lines += signals(msgs)
    turn = ("Your notes so far:\n" + (state["notes"] or "(first look)")
            + "\nYour open expectations:\n"
            + ("\n".join("- " + e for e in state["expectations"]) or "(none)")
            + "\n\nNew activity since your last look:\n" + "\n\n".join(lines)
            + "\n\nUpdate notes and expectations; decide whether to speak.")

    # context = system + last K exchanges of the watcher's own conversation
    history = convo[-2 * KEEP_EXCHANGES:]
    messages = ([{"role": "system", "content": SYSTEM}] + history
                + [{"role": "user", "content": turn}])
    try:
        raw = call_model(messages)
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0), strict=False) if m else {}
    except Exception as e:
        with open(os.path.join(MEM, "watcher.log"), "a") as f:
            f.write(f"FAILED: {type(e).__name__}: {e}\n")
        return 0

    state["seen"] = len(msgs)
    state["notes"] = str(data.get("notes", state["notes"]))[:3000]
    exp = data.get("expectations")
    if isinstance(exp, list):
        state["expectations"] = [str(x)[:200] for x in exp][:10]
    _save(state_p, state)
    convo += [{"role": "user", "content": turn},
              {"role": "assistant", "content": raw[:4000]}]
    _save(convo_p, convo[-2 * KEEP_EXCHANGES:])

    speak = data.get("speak")
    lookup = data.get("lookup")
    grounded = False
    if isinstance(speak, str) and speak.strip() and EXA_KEY \
            and isinstance(lookup, str) and lookup.strip():
        try:
            found = exa_search(lookup)
            if found:
                raw2 = call_model(messages + [
                    {"role": "assistant", "content": raw[:4000]},
                    {"role": "user", "content": GROUND + "\n\n" + found}])
                m2 = re.search(r"\{.*\}", raw2, re.S)
                d2 = json.loads(m2.group(0), strict=False) if m2 else {}
                if isinstance(d2.get("speak"), str) and d2["speak"].strip():
                    speak, grounded = d2["speak"], True
        except Exception as e:
            with open(os.path.join(MEM, "watcher.log"), "a") as f:
                f.write(f"lookup failed: {type(e).__name__}: {e}\n")
    active = os.path.join(MEM, f".dk_active.{session}")
    if isinstance(speak, str) and speak.strip():
        with open(active, "w") as f:
            f.write(f"<self-steering>\n{speak.strip()[:600]}\n</self-steering>\n")
    else:
        open(active, "w").close()      # fresh-and-empty: nothing to say
    with open(os.path.join(MEM, "watcher.log"), "a") as f:
        f.write(f"ok: spoke={bool(speak)} grounded={grounded} "
                f"seen={state['seen']} exp={len(state['expectations'])}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
