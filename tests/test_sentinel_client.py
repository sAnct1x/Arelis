"""Arelis's synchronous Sentinel bridge client: token on every call, fail soft."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


def test_every_call_sends_the_token_and_failures_come_back_as_clean_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fake bridge checks X-Sentinel-Token like the real one.

    Dropping the token from the call, letting an HTTP or decode error escape,
    or calling out when Sentinel is down fails this test.
    """
    import sys
    from pathlib import Path

    sentinel_root = Path(__file__).resolve().parents[1] / "sentinel"
    if str(sentinel_root) not in sys.path:
        sys.path.insert(0, str(sentinel_root))
    from sentinel.bridge.protocol import TOKEN_HEADER

    from arelis import sentinel_client, sentinel_control

    good = "g" * 40
    seen: list[tuple[str, str | None]] = []
    mode = {"reply": "json"}

    class _Bridge(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            token = self.headers.get(TOKEN_HEADER)
            seen.append((body["op"], token))
            if mode["reply"] == "garbage":
                status, raw = 200, b"<html>not the bridge</html>"
            elif token != good:
                status, raw = 401, json.dumps({"ok": False, "error": "Unauthorized session token"}).encode()
            else:
                status, raw = 200, json.dumps({"ok": True, "op": body["op"]}).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *_a) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), _Bridge)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    target = {"value": ("127.0.0.1", port, good)}
    monkeypatch.setattr(sentinel_control, "bridge_target", lambda: target["value"])
    try:
        assert sentinel_client.ping() == {"ok": True, "op": "ping"}
        assert sentinel_client.snapshot()["ok"] is True
        assert sentinel_client.command("list_castes")["ok"] is True
        assert seen == [("ping", good), ("snapshot", good), ("list_castes", good)]

        target["value"] = ("127.0.0.1", port, "b" * 40)
        bad = sentinel_client.ping()
        assert bad["ok"] is False and "Unauthorized" in bad["error"]

        mode["reply"] = "garbage"
        target["value"] = ("127.0.0.1", port, good)
        assert sentinel_client.ping() == {"ok": False, "error": sentinel_client.REFUSED}
    finally:
        server.shutdown()
        server.server_close()

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = s.getsockname()[1]
    target["value"] = ("127.0.0.1", closed, good)
    assert sentinel_client.ping() == {"ok": False, "error": sentinel_client.UNREACHABLE}

    seen.clear()
    target["value"] = None
    assert sentinel_client.ping() == {"ok": False, "error": sentinel_client.OFFLINE}
    assert seen == []
