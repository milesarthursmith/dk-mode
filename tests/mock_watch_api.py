#!/usr/bin/env python3
"""Mock model for dk_watch.py tests. Serves a canned JSON selection in
either Anthropic or OpenAI wire format, chosen by the URL path the client
uses, so the watcher's real HTTP + parse path is exercised.

Usage: mock_watch_api.py <json-body> <portfile>
  <json-body> is the literal text the "model" returns.
"""
import http.server, json, re, sys

payload, portfile = sys.argv[1], sys.argv[2]

# "ALL_USER" is not a canned string but an instruction to this mock: read the
# prompt actually sent, and select every [user] id it contains. That makes the
# mock able to prove what the model WAS and WAS NOT shown - a canned reply
# cannot, because it is written without seeing the prompt.
ID_RE = re.compile(r"\[(user|assistant) id=([^\]]+)\]")


def reply_for(body):
    if payload != "ALL_USER":
        return payload
    convo = body.split("=== RECENT CONVERSATION ===", 1)[-1]
    ids = [m.group(2) for m in ID_RE.finditer(convo) if m.group(1) == "user"]
    return json.dumps({"active": [], "alert": "MOCK-LIVE-ALERT",
                       "steering": [{"id": i, "source": "human",
                                     "kind": "correction"} for i in ids]})

class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        sent = self.rfile.read(int(self.headers.get("content-length", 0)))
        out = reply_for(sent.decode("utf-8", "replace"))
        if self.path.endswith("/chat/completions"):
            body = {"choices": [{"message": {"role": "assistant", "content": out}}]}
        else:
            body = {"content": [{"type": "text", "text": out}]}
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def log_message(self, *a): pass

s = http.server.HTTPServer(("127.0.0.1", 0), H)
open(portfile, "w").write(str(s.server_address[1]))
s.serve_forever()
