#!/usr/bin/env python3
"""Local stand-in for an OpenAI-compatible server (Ollama / LM Studio /
llama.cpp), used by run_dk_tests.sh to exercise DK_BACKEND=openai without a
local model installed.

Usage: mock_openai_api.py <markdown-file> <portfile> [delay-seconds]
"""
import http.server
import json
import sys
import time

md_path, portfile = sys.argv[1], sys.argv[2]
delay = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("content-length", 0)))
        # A real OpenAI-compatible server rejects a body without "messages".
        try:
            req = json.loads(raw or b"{}")
        except ValueError:
            req = {}
        if "messages" not in req:
            self.send_response(400); self.end_headers(); return
        if delay:
            time.sleep(delay)
        with open(md_path, encoding="utf-8") as f:
            body = json.dumps({
                "choices": [{"message": {"role": "assistant", "content": f.read()}}]
            }).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
with open(portfile, "w") as f:
    f.write(str(server.server_address[1]))
server.serve_forever()
