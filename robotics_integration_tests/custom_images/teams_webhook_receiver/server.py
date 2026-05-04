"""Minimal HTTP server that captures Teams webhook POST requests.

Endpoints:
    POST /webhook       – Accepts an adaptive card JSON payload, stores it.
    GET  /notifications – Returns all captured payloads as a JSON array.
    GET  /health        – Returns 200 OK (used for readiness checks).
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock

_notifications: list[dict] = []
_lock = Lock()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path == "/webhook":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"raw": body.decode("utf-8", errors="replace")}

            with _lock:
                _notifications.append(payload)

            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/notifications":
            with _lock:
                data = json.dumps(_notifications)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data.encode())
        elif self.path == "/health":
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    # Suppress per-request log lines
    def log_message(self, format, *args) -> None:  # noqa: A002
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 8080), Handler)
    print("Teams webhook receiver listening on :8080", flush=True)
    server.serve_forever()
