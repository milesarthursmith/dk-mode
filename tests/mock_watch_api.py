#!/usr/bin/env python3
"""Mock model for dk_watch.py tests. Serves a canned JSON selection in
either Anthropic or OpenAI wire format, chosen by the URL path the client
uses, so the watcher's real HTTP + parse path is exercised.

Usage: mock_watch_api.py <json-body> <portfile>
  <json-body> is the literal text the "model" returns.
"""
import http.server, json, sys

payload, portfile = sys.argv[1], sys.argv[2]

class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.path.endswith("/chat/completions"):
            body = {"choices": [{"message": {"role": "assistant", "content": payload}}]}
        else:
            body = {"content": [{"type": "text", "text": payload}]}
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
