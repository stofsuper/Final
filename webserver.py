"""
webserver.py — Lightweight HTTP keep-alive server for Wyspbytes hosting.

Wyspbytes (and similar free hosts) require an active HTTP endpoint to confirm
the process is alive, otherwise they put it to sleep after ~15 minutes of
no HTTP activity — even if the bot WebSocket is still connected.

HOW TO USE:
  Import and call start_webserver() at the top of your bot runner,
  OR run this alongside your bot process.

  In your bot.py / runner:
      from webserver import start_webserver
      start_webserver()

The server runs on port 8080 (or PORT env var) and responds to any
GET request with a 200 OK — enough to satisfy Wyspbytes' uptime checks.
"""

import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime


class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"✅ Bot alive — {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # Suppress default access logs to keep console clean
        pass


def start_webserver():
    """Start the HTTP keep-alive server in a background daemon thread."""
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[WebServer] Keep-alive server running on port {port}")
    return server
