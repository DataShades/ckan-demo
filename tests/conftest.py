"""A fake CKAN action API."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class FakeCkan:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.calls: list[tuple[str, dict, str | None]] = []

    def handle(self, action: str, data: dict) -> tuple[int, dict]:
        if action == "user_show":
            user = self.users.get(data["id"])
            if user is None:
                return 404, {"success": False, "error": {"__type": "Not Found Error", "message": "Not found"}}
            return 200, {"success": True, "result": user}
        if action in ("user_create", "user_patch"):
            key = data.get("name") or data["id"]
            self.users[key] = {**self.users.get(key, {}), **data, "name": key}
            return 200, {"success": True, "result": self.users[key]}
        if action == "boom":
            return 409, {"success": False, "error": {"__type": "Validation Error", "name": ["Missing value"]}}
        return 200, {"success": True, "result": data}


@pytest.fixture
def ckan():
    fake = FakeCkan()

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status, body):
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            action = self.path.rsplit("/", 1)[-1]
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
            # ckanapi sends the token as X-CKAN-API-Key.
            fake.calls.append((action, data, self.headers.get("X-CKAN-API-Key")))
            self._reply(*fake.handle(action, data))

        def do_GET(self):
            # For Portal.get_json.
            fake.calls.append(("GET " + self.path, {}, self.headers.get("Authorization")))
            if self.path.startswith("/table"):
                self._reply(200, {"data": [{"id": 1}], "last_page": 1})
            else:
                self._reply(404, {"error": "no such page"})

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.url = f"http://127.0.0.1:{server.server_port}"
    yield fake
    server.shutdown()
