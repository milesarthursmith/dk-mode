"""The decided shape (docs/SHAPE.md): a stateful LLM watcher.

One continuous monitor conversation per agent session. Each invocation
(same CLI contract as dk_watch: argv[1] = transcript path, DK_* env,
verdict written to $DK_MEM/.dk_active.<session> for dk_recall) feeds the
watcher only the DELTA since its last look, annotated with deterministic
signals it is free to overrule. The watcher keeps its own notes and
expectations; those, not the raw history, are its memory.

Judgement decides when to speak. Nothing mechanical gates it.

2026-09-06: what the watcher READS changed. It now sees what the agent
did, not only what it said: tool calls are rendered as short lines, tool
results head-and-tail clipped so the error at the bottom survives, the
task statement (system reminders stripped) is pinned into every look, and
the watcher's own earlier note, when it comes back inside the next user
prompt, is marked as its own so it is not read as the user speaking.
What it is ASKED FOR changed too: the fact the agent has not taken in, or
the claim the record contradicts, said the way the owner would say it.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

MEM = os.environ.get("DK_MEM", os.path.expanduser("~/.dk-mem"))
# openai = an OpenAI-format endpoint (OpenRouter by default); cli = the
# `claude` command with the login already on this machine, no key needed.
BACKEND = os.environ.get("DK_BACKEND", "openai").strip().lower()
API_URL = os.environ.get("DK_API_URL",
                         "https://openrouter.ai/api/v1/chat/completions")
KEY = os.environ.get("DK_API_KEY", "")
MODEL = os.environ.get("DK_WATCH_MODELS",
                       "claude-sonnet-5" if BACKEND == "cli"
                       else "google/gemini-2.5-flash").split(",")[0]
TIMEOUT = int(os.environ.get("DK_WATCH_TIMEOUT", "110"))
# watcher context: system + task + latest notes + last K of its own looks
KEEP_EXCHANGES = int(os.environ.get("DK_WATCHER_KEEP", "3"))
# A message is clipped head AND tail, never head only: the error is at the
# bottom of a test run, and the task text sits at the end of a 7 KB system
# reminder. These are the character budgets, not a rule about content.
MSG_HEAD = int(os.environ.get("DK_MSG_HEAD", "1800"))
MSG_TAIL = int(os.environ.get("DK_MSG_TAIL", "900"))
TASK_MAX = int(os.environ.get("DK_TASK_CHARS", "4000"))
HIST_TURN_MAX = 3500          # how much of a past look's input is kept verbatim
# Grounded interventions (SHAPE.md #4): when the watcher decides to speak
# and names a lookup, search and rewrite the alert around what was found.
# OFF unless a key is present; keep it off on benchmarks with public fixes.
EXA_KEY = os.environ.get("EXA_API_KEY", "")
EXA_URL = os.environ.get("EXA_URL", "https://api.exa.ai/search")

SYSTEM = """You are watching a coding AI work, the way its owner would if \
he were sitting behind it. You see the session in pieces, one look at a \
time. You keep notes between looks. On each look you decide whether to say \
something to the AI. On most looks you say nothing.

NOTES are your memory. Keep in them: the task and its rules, taken from \
the TASK text and never from the AI's restatement of it; what has been \
PROVEN by a tool result versus only CLAIMED by the AI; each approach tried \
and how it ended; contradictions still open (the AI says X passed, the \
record shows Y); anything that worked and was then abandoned; what the AI \
said it would do next.
EXPECTATIONS: each time the AI predicts "this will fix X", write it down. \
On the next look, check it against the record. An AI whose predictions \
keep failing has lost your trust; read its confidence accordingly.

Lines marked [sense: ...] are mechanical counts. They inform you. They \
never decide. Overrule them in either direction when the record says so.

WHEN TO SPEAK. Speak when you can name a fact the AI has not taken in, or \
a claim of its own that the record contradicts, AND the AI would do \
something different after reading it. That includes: it is doing again \
something it already tried and saw fail; it broke a rule stated in the \
task (for example it edited tests it was told not to touch); it says done \
or passing and the record does not show that; it had something working and \
walked away from it; it is solving a different problem from the one asked. \
Stay silent while real progress is being made, even messily. Stay silent \
when all you could say is what the last output already said, or what the \
AI already said it will do next. Before you speak, ask: what will the AI \
do differently after reading this? If the answer is nothing, do not speak.

NEVER: restate the last output; ask a question; encourage; praise; list \
options; explain yourself; lecture.

HOW TO SAY IT. This is the owner's voice, and he is short with it.
- One or two sentences, to the AI as "you", as typed into a chat window.
- Lead with the fact from the record: what you did, how many times, what \
the output actually said, which line of the task you broke. Quote the AI's \
own words back when that is the fastest way to point at it.
- Then what to do instead, in a few words, or the one check that settles \
it. Prefer the smallest check on what is already in front of the AI (git \
diff, one failing test, a print) over fetching anything from outside; the \
record shows what its sandbox can and cannot do.
- Plain words. No "I notice", no "it seems", no "consider", no "please".
- Under 60 words. Nobody is reading the AI's replies, so never ask it to \
report, paste, or show you anything; give it the check to run.
- On your first look you have no history yet: speak only if the record \
already shows one of the reasons above.
- A note of yours reached the AI only if you see it echoed in the record \
as "[your earlier note, shown to the AI: ...]". Otherwise it was not \
delivered. Either way, never mention your notes to the AI: say the fact \
again as if for the first time.
- Everything you state must be something you saw in the record. If part \
of it is a guess, mark it "(guess)".
The owner's own words, from past sessions, so you have the register: \
"you did that already." "that's not what I asked for." "are you 100% \
sure? you didn't run it." "you said 842 passed. the harness says 785 \
failing. sort that out before you touch parse_tuple again." "bit lame, \
simplify it."

If you decide to speak and the AI is stuck on a specific error, library \
behaviour or tool quirk that a web search would likely explain, set \
"lookup" to a short search query (the error text plus the library name). \
Otherwise "lookup" is null.

Reply with JSON only, no prose, no code fences:
{"notes": "...", "expectations": ["..."],
 "facts": ["each fact from the record that your message rests on"],
 "speak": "..." or null, "lookup": "..." or null}"""

GROUND = """Search results for your lookup are below. Rewrite your \
message so it leads with the most useful concrete fact from them (what \
the error usually means, the known cause, the fix pattern) and names the \
source domain in brackets. Keep it to two or three sentences, to the AI \
as "you", in the same plain register. If nothing relevant came back, keep \
your original message. Reply with JSON only: {"speak": "..."}"""


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


def clip(text, head=MSG_HEAD, tail=MSG_TAIL):
    """Keep the start and the END. A head-only cut loses the traceback."""
    text = text or ""
    if len(text) <= head + tail + 40:
        return text
    return (text[:head] + f"\n[... {len(text) - head - tail} chars cut ...]\n"
            + text[-tail:])


REMINDER_RE = re.compile(r"<system-reminder>(.*?)</system-reminder>", re.S)
NOTE_RE = re.compile(r"<self-steering>(.*?)</self-steering>", re.S)


def render_user_text(text):
    """Harness text inside a user message, rendered so the watcher knows
    what it is. Its own earlier note comes back inside the next prompt
    wrapped in a hook-success reminder; without this mark the watcher reads
    itself as the user. Other reminders are boilerplate and are collapsed."""
    def one(m):
        body = m.group(1)
        if "hook success" in body and "<self-steering>" in body:
            notes = " ".join(n.group(1).strip() for n in NOTE_RE.finditer(body))
            return f"[your earlier note, shown to the AI: {notes}]"
        return "[harness reminder omitted]"
    out = REMINDER_RE.sub(one, text)
    out = re.sub(r"(\[harness reminder omitted\]\s*){2,}",
                 "[harness reminders omitted]\n", out)
    return out.strip()


def render_call(name, inp):
    inp = inp if isinstance(inp, dict) else {}
    if name == "Bash":
        return f"[ran: {clip(str(inp.get('command', '')), 700, 200)}]"
    if name == "Edit":
        return (f"[edit {inp.get('file_path', '?')}: replace "
                f"{clip(str(inp.get('old_string', '')), 350, 150)!r} WITH "
                f"{clip(str(inp.get('new_string', '')), 350, 150)!r}"
                f"{' (all occurrences)' if inp.get('replace_all') else ''}]")
    if name in ("Write", "NotebookEdit"):
        return (f"[write {inp.get('file_path', '?')}: "
                f"{clip(str(inp.get('content', inp.get('new_source', ''))), 400, 200)!r}]")
    if name == "Read":
        return f"[read {inp.get('file_path', '?')}]"
    if name in ("Grep", "Glob"):
        return f"[{name.lower()} {inp.get('pattern', '')!r} in {inp.get('path', '.')}]"
    return f"[tool {name}: {clip(json.dumps(inp), 400, 100)}]"


def read_transcript(path):
    """Claude Code jsonl -> [{"role", "text"}], tool calls and results
    rendered into the text. Bench moments whose content is already plain
    text pass through unchanged apart from the harness-noise marking."""
    msgs = []
    names = {}                                   # tool_use id -> tool name
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
                parts = []
                if isinstance(c, str):
                    parts.append(c)
                elif isinstance(c, list):
                    for b in c:
                        if not isinstance(b, dict):
                            continue
                        t = b.get("type")
                        if t == "text":
                            parts.append(b.get("text", ""))
                        elif t == "tool_use":
                            names[b.get("id")] = b.get("name", "?")
                            parts.append(render_call(b.get("name", "?"),
                                                     b.get("input")))
                        elif t == "tool_result":
                            rc = b.get("content")
                            if isinstance(rc, list):
                                rc = "\n".join(x.get("text", "") for x in rc
                                               if isinstance(x, dict))
                            tag = "ERROR " if b.get("is_error") else ""
                            parts.append(f"[result of {names.get(b.get('tool_use_id'), 'tool')}: "
                                         f"{tag}{clip(str(rc or '(no output)'))}]")
                text = "\n".join(p for p in parts if p and p.strip())
                if e["type"] == "user":
                    text = render_user_text(text)
                if text.strip():
                    msgs.append({"role": e["type"], "text": text.strip()})
    except OSError:
        pass
    return msgs


def task_text(msgs):
    """The first thing the user asked, in full, reminders stripped. Copied
    from the record every look, never from the watcher's own notes, so the
    goal cannot drift as the notes are rewritten."""
    for m in msgs:
        if m["role"] == "user":
            t = re.sub(r"\[harness reminders? omitted\]\s*", "", m["text"])
            t = re.sub(r"\[your earlier note, shown to the AI: .*?\]\s*", "", t, flags=re.S).strip()
            if t:
                return t[:TASK_MAX]
    return "(no task text found)"


def signals(msgs):
    """Deterministic senses over the WHOLE transcript. Counts survive any
    context window because they are recomputed. They inform; the watcher
    decides."""
    out = []
    seen = {}
    for m in msgs:
        if m["role"] != "assistant":
            continue
        k = re.sub(r"\s+", " ", m["text"][:120])
        seen[k] = seen.get(k, 0) + 1
    rep = {k: v for k, v in seen.items() if v >= 3}
    for k, v in sorted(rep.items(), key=lambda x: -x[1])[:3]:
        out.append(f"[sense: assistant text beginning \"{k[:70]}...\" has appeared {v} times so far]")
    pcts = [int(m.group(1)) for t in msgs
            for m in [re.search(r"\((\d+)% fixed\)", t["text"])] if m]
    if len(pcts) >= 3 and len(set(pcts[-3:])) == 1:
        out.append(f"[sense: the driver has reported {pcts[-1]}% fixed on each of the last {len(pcts) - pcts[::-1].index(pcts[-1])} checks]")
    errs = sum(1 for m in msgs[-8:] if m["role"] == "assistant"
               and re.search(r"error|failed|apolog", m["text"], re.I))
    if errs >= 4:
        out.append(f"[sense: {errs} of the last 8 assistant messages mention an error or failure]")
    return out


# Reasoning: OFF by default. The one paired run (docs/log.md 2026-09-05)
# found reasoning-on made the watcher quieter, not sharper. Open variable.
REASONING = os.environ.get("DK_REASONING", "").strip().lower()


def call_api(messages):
    body = {"model": MODEL, "max_tokens": 8000 if REASONING else 3000,
            "temperature": 0, "messages": messages}
    if REASONING:
        body["reasoning"] = {"effort": REASONING}
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode(),
        headers={"content-type": "application/json",
                 "authorization": f"Bearer {KEY}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read())
    ch = data.get("choices") or []
    return (ch[0].get("message", {}).get("content") or "") if ch else ""


def call_cli(messages):
    """DK_BACKEND=cli: the `claude` command with the login on this machine.
    The watcher's conversation is flattened into one prompt; its system
    text goes in through --append-system-prompt."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [m for m in messages if m["role"] != "system"]
    lines = []
    for m in rest[:-1]:
        who = "YOUR EARLIER LOOK" if m["role"] == "user" else "YOUR REPLY"
        lines.append(f"=== {who} ===\n{m['content']}")
    lines.append("=== THIS LOOK ===\n" + rest[-1]["content"])
    prompt = ("Do not use any tools. Answer from the text below only, "
              "with the JSON described in your instructions.\n\n"
              + "\n\n".join(lines))
    cmd = ["claude", "-p", "--model", MODEL, "--append-system-prompt", system]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                       timeout=TIMEOUT + 60)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p exit {r.returncode}: {r.stderr.strip()[:300]}")
    return r.stdout


def call_model(messages):
    return call_cli(messages) if BACKEND == "cli" else call_api(messages)


def parse_json(raw):
    """Strict: a reply without a JSON object is a FAILURE, never a silence."""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("no JSON object in reply")
    return json.loads(m.group(0), strict=False)


def log(msg):
    with open(os.path.join(MEM, "watcher.log"), "a") as f:
        f.write(msg.rstrip("\n") + "\n")


def main():
    transcript = sys.argv[1]
    # dk_capture.sh exports DK_SESSION_ID; the bench sets DK_SESSION. Both.
    session = (os.environ.get("DK_SESSION_ID") or os.environ.get("DK_SESSION")
               or "session")[:16]
    os.makedirs(MEM, exist_ok=True)
    state_p = os.path.join(MEM, f".watcher_state.{session}")
    convo_p = os.path.join(MEM, f".watcher_convo.{session}")
    active = os.path.join(MEM, f".dk_active.{session}")
    state = _load(state_p, {"seen": 0, "notes": "", "expectations": []})
    convo = _load(convo_p, [])

    msgs = read_transcript(transcript)
    if state["seen"] > len(msgs):            # file rewritten or compacted
        log(f"seen={state['seen']} > {len(msgs)} messages; re-reading from 0")
        state["seen"] = 0
    delta = msgs[state["seen"]:]
    if not delta:
        open(active, "w").close()             # nothing new: no stale verdict
        return 0
    lines = [f"[{m['role']}] {clip(m['text'])}" for m in delta]
    lines += signals(msgs)
    turn = ("=== TASK (the user's first message, verbatim) ===\n"
            + task_text(msgs)
            + "\n\n=== YOUR NOTES SO FAR ===\n" + (state["notes"] or "(first look)")
            + "\n\n=== YOUR OPEN EXPECTATIONS ===\n"
            + ("\n".join("- " + e for e in state["expectations"]) or "(none)")
            + f"\n\n=== NEW ACTIVITY SINCE YOUR LAST LOOK (messages {state['seen'] + 1}-{len(msgs)}) ===\n"
            + "\n\n".join(lines)
            + "\n\nUpdate notes and expectations; decide whether to speak.")

    history = convo[-2 * KEEP_EXCHANGES:]
    messages = ([{"role": "system", "content": SYSTEM}] + history
                + [{"role": "user", "content": turn}])
    try:
        raw = call_model(messages)
        data = parse_json(raw)
    except Exception as e:
        log(f"FAILED: {type(e).__name__}: {str(e)[:300]}")
        open(active, "w").close()             # a failed look says nothing
        return 0                              # and seen does not advance

    state["seen"] = len(msgs)
    notes = data.get("notes")
    state["notes"] = (notes if isinstance(notes, str) else state["notes"])[:4000]
    exp = data.get("expectations")
    if isinstance(exp, list):
        state["expectations"] = [str(x)[:200] for x in exp][:10]
    _save(state_p, state)
    convo += [{"role": "user", "content": clip(turn, HIST_TURN_MAX, 600)},
              {"role": "assistant", "content": raw[:3000]}]
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
                    {"role": "assistant", "content": raw[:3000]},
                    {"role": "user", "content": GROUND + "\n\n" + found}])
                d2 = parse_json(raw2)
                if isinstance(d2.get("speak"), str) and d2["speak"].strip():
                    speak, grounded = d2["speak"], True
        except Exception as e:
            log(f"lookup failed: {type(e).__name__}: {e}")
    if isinstance(speak, str) and speak.strip():
        with open(active, "w") as f:
            f.write(f"<self-steering>\n{speak.strip()[:900]}\n</self-steering>\n")
    else:
        open(active, "w").close()      # fresh-and-empty: nothing to say
    facts = data.get("facts") if isinstance(data.get("facts"), list) else []
    log(f"ok: spoke={bool(speak)} grounded={grounded} seen={state['seen']} "
        f"exp={len(state['expectations'])} facts={len(facts)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
