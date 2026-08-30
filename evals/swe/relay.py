"""Monitor egress relay for network-isolated swebench sandboxes.

The testbed container runs on an internal-only network (the agent must
not reach GitHub - the fix commits for every instance are public). This
relay is the one hole: it accepts plain HTTP from the internal network
and re-originates the request to openrouter.ai over TLS, so dk_watch can
call its monitor model and nothing else changes. Runs in a sidecar with
egress; stdlib only.
"""
import http.server
import json
import os
import urllib.error
import urllib.request

UPSTREAM = "https://openrouter.ai"
HOP = {"host", "connection", "content-length", "accept-encoding"}


class Relay(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in HOP}
        req = urllib.request.Request(UPSTREAM + self.path, data=body,
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=110) as resp:
                data = resp.read()
                code = resp.status
        except urllib.error.HTTPError as e:
            data, code = e.read(), e.code
        except Exception as e:
            data = json.dumps({"error": f"relay: {type(e).__name__}: {e}"
                               }).encode()
            code = 502
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    port = int(os.environ.get("RELAY_PORT", "8080"))
    http.server.ThreadingHTTPServer(("0.0.0.0", port), Relay).serve_forever()
