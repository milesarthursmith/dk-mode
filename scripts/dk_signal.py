#!/usr/bin/env python3
"""dk_signal.py - record a steering event from something other than a human.

The capture hook mines conversations. This is the other door: any process
that STEERS an agent can report it directly, which is the honest way to
catch machine-sourced steering rather than guessing at it with regex.

Anything that tells an agent it got something wrong is a steering event:
  - an adversarial verifier / judge returning FIX or KILL
  - a review subagent rejecting a diff
  - a ship gate, a failing test suite, a lint rule that keeps tripping
  - a human-written script noticing the agent did the thing it shouldn't

Use it from a hook, a CI step, a skill, or another agent:

  dk_signal.py --kind verdict --source my-verifier \\
      --text "FIX: heading promises a calculator the page does not contain" \\
      --context "shipped page /heating-costs with an empty section"

Only --text is required. Entries land in the same dk.jsonl the capture hook
writes, under the same lock, and flow through the same consolidation - so a
verifier's repeated complaint becomes a standing rule exactly like a
human's repeated correction does. Deduplicated on content, so a gate that
fires the same complaint twice in one run records it once.

Exits 0 even when it does nothing (not installed here, lock busy): a
telemetry call must never fail the pipeline it is reporting from.
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def find_root(start):
    d = start
    for _ in range(8):
        if os.path.isdir(os.path.join(d, ".claude")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.getcwd()


def main():
    ap = argparse.ArgumentParser(add_help=True, description=__doc__.splitlines()[0])
    ap.add_argument("--text", required=True,
                    help="what the steering said - the verbatim complaint")
    ap.add_argument("--kind", default="verdict",
                    help="verdict | test-failure | review | gate (free-form)")
    ap.add_argument("--source", default="verifier",
                    help="who steered: ci, code-review, <verifier or agent name>...")
    ap.add_argument("--context", default="",
                    help="what the agent had just done")
    ap.add_argument("--target", default="",
                    help="optional file/slug/PR the steering was about")
    args = ap.parse_args()

    root = os.environ.get("CLAUDE_PROJECT_DIR") or find_root(SCRIPT_DIR)
    mem = os.path.join(root, ".claude", "memory")
    raw = os.path.join(mem, "dk.jsonl")
    lock = os.path.join(mem, ".dk.lock")
    if not os.path.isdir(mem):
        return 0                      # dk-mode not installed here: no-op

    text = args.text.strip()
    if not text:
        return 0
    # Content-addressed id: the same verdict reported twice is one event.
    uid = "sig-" + hashlib.sha256(
        f"{args.source}|{args.kind}|{args.target}|{text}".encode()
    ).hexdigest()[:16]

    try:
        with open(raw, encoding="utf-8", errors="replace") as f:
            if uid in f.read():
                return 0
    except OSError:
        pass

    entry = {
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "session": os.environ.get("CLAUDE_SESSION_ID", "")[:8],
        "uuid": uid,
        "source": args.source,
        "kind": args.kind,
        "signal": args.kind,
        "text": text[:600],
        "assistant_context": args.context[:500],
        "target": args.target,
        "cwd": os.getcwd(),
    }

    acquired = False
    for _ in range(20):
        try:
            os.mkdir(lock)
            acquired = True
            break
        except FileExistsError:
            try:
                if time.time() - os.stat(lock).st_mtime > 30:
                    os.rmdir(lock)
                    continue
            except OSError:
                pass
            time.sleep(0.25)
        except OSError:
            return 0
    if not acquired:
        return 0                      # busy: dropping one signal is fine
    try:
        with open(raw, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        with open(os.path.join(mem, "log.md"), "a", encoding="utf-8") as f:
            f.write(f'{datetime.date.today().isoformat()} | dk-signal | '
                    f'{args.source}/{args.kind}: {text[:60]}\n')
    except OSError:
        pass
    finally:
        try:
            os.rmdir(lock)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
