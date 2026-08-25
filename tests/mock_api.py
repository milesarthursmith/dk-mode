#!/usr/bin/env python3
"""Local stand-in for the Anthropic API, used only by run_remember_tests.sh.

Serves every POST with a canned Anthropic-shaped response whose text is the
given markdown file, so remember_consolidate.py's real HTTP path is exercised
end to end with no network and no key spend.

Usage: mock_api.py <markdown-file> <portfile> [delay-seconds]
Binds 127.0.0.1 on a free port and writes the port number to <portfile>.
"""
import http.server
import json
import sys
import time

md_path, portfile = sys.argv[1], sys.argv[2]
delay = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        if delay:
            time.sleep(delay)
        with open(md_path, encoding="utf-8") as f:
            body = json.dumps(
                {"content": [{"type": "text", "text": f.read()}]}).encode("utf-8")
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
