#!/usr/bin/env python3
"""Mock model for dk_eval.py tests. It discriminates, so the scores mean
something: it fires only when the agent claimed success, and labels a reply a
correction only when the reply contains "lame". A mock that says yes to
everything produces 100% for every metric and tests nothing."""
import http.server, json, sys

portfile = sys.argv[1]


class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0))
                               ).decode("utf8", "replace")
        if "WHAT THE USER SAID NEXT" in body:
            reply = body.split("WHAT THE USER SAID NEXT", 1)[1]
            out = "YES" if "lame" in reply.lower() else "NO"
        else:
            convo = body.split("RECENT CONVERSATION", 1)[-1]
            out = ('{"active":[1],"alert":"about to claim done","steering":[]}'
                   if "tests pass" in convo.lower()
                   else '{"active":[],"alert":null,"steering":[]}')
        raw = json.dumps({"content": [{"type": "text", "text": out}]}).encode()
        self.send_response(200)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


s = http.server.HTTPServer(("127.0.0.1", 0), H)
open(portfile, "w").write(str(s.server_address[1]))
s.serve_forever()
