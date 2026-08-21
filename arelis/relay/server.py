"""Threading mailbox. The house dials out; the phone calls in.

No ingest token lives here. House proves operator relay_token. Payloads are
opaque blobs. If no house is holding a poll, the phone gets 503 and uses Gemma.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

log = logging.getLogger(__name__)

HOUSE_WAIT_S = 20.0
PHONE_WAIT_S = 60.0
STREAM_WAIT_S = 600.0
MAX_BLOB = 10 * 1024 * 1024


class _Call:
    def __init__(self, blob: str, stream: bool) -> None:
        self.id = uuid4().hex
        self.blob = blob
        self.stream = stream
        self.reply: queue.Queue[str | None] = queue.Queue()
        self.chunks: queue.Queue[str | None] = queue.Queue()


class _Slot:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.inflight = 0
        self.last_seen = 0.0
        self.pending: queue.Queue[_Call] = queue.Queue()
        self.calls: dict[str, _Call] = {}


class RelayState:
    def __init__(self, token: str) -> None:
        self.token = token
        self.lock = threading.Lock()
        self.slots: dict[str, _Slot] = {}

    def slot(self, instance: str) -> _Slot:
        with self.lock:
            got = self.slots.get(instance)
            if got is None:
                got = _Slot()
                self.slots[instance] = got
            return got

    def house_here(self, instance: str) -> bool:
        slot = self.slot(instance)
        with slot.lock:
            if slot.inflight > 0:
                return True
            return slot.last_seen > 0 and (time.monotonic() - slot.last_seen) < 35.0


def run_relay(host: str, port: int, token: str) -> ThreadingHTTPServer:
    if not token.strip():
        raise ValueError("relay token is empty")
    state = RelayState(token.strip())
    httpd = ThreadingHTTPServer((host, int(port)), _handler(state))
    thread = threading.Thread(
        target=httpd.serve_forever, name="arelis-relay", daemon=True
    )
    thread.start()
    httpd.relay_thread = thread  # type: ignore[attr-defined]
    log.info("Arelis mailbox on %s:%s", host, port)
    return httpd


def _handler(state: RelayState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            log.debug("relay %s - %s", self.address_string(), fmt % args)

        def _json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(max(0, length)) if length else b"{}"
            try:
                data = json.loads(raw.decode() or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}
            return data if isinstance(data, dict) else {}

        def _reply(self, code: int, obj: dict[str, Any]) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _bearer_ok(self) -> bool:
            auth = self.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                got = auth[7:].strip()
            else:
                got = (self.headers.get("X-Arelis-Relay") or "").strip()
            return bool(got) and got == state.token

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in {"/health", "/v1/health"}:
                self._reply(200, {"ok": True, "service": "arelis-relay"})
                return
            self._reply(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            data = self._json()
            if path == "/v1/house/poll":
                self._house_poll(data)
                return
            if path == "/v1/house/reply":
                self._house_reply(data)
                return
            if path == "/v1/house/chunk":
                self._house_chunk(data)
                return
            if path == "/v1/phone/call":
                self._phone_call(data)
                return
            self._reply(404, {"ok": False, "error": "not found"})

        def _house_poll(self, data: dict[str, Any]) -> None:
            if not self._bearer_ok():
                self._reply(401, {"ok": False, "error": "unauthorized"})
                return
            instance = str(data.get("instance") or "").strip()
            if not instance:
                self._reply(400, {"ok": False, "error": "instance required"})
                return
            slot = state.slot(instance)
            with slot.lock:
                slot.inflight += 1
                slot.last_seen = time.monotonic()
            try:
                try:
                    call = slot.pending.get(timeout=HOUSE_WAIT_S)
                except queue.Empty:
                    self.send_response(204)
                    self.end_headers()
                    return
                self._reply(
                    200,
                    {
                        "ok": True,
                        "call_id": call.id,
                        "blob": call.blob,
                        "stream": call.stream,
                    },
                )
            finally:
                with slot.lock:
                    slot.inflight = max(0, slot.inflight - 1)

        def _house_reply(self, data: dict[str, Any]) -> None:
            if not self._bearer_ok():
                self._reply(401, {"ok": False, "error": "unauthorized"})
                return
            call_id = str(data.get("call_id") or "").strip()
            blob = str(data.get("blob") or "")
            slot = _find_call(state, call_id)
            if slot is None:
                self._reply(404, {"ok": False, "error": "unknown call"})
                return
            call = slot.calls.get(call_id)
            if call is None:
                self._reply(404, {"ok": False, "error": "unknown call"})
                return
            call.reply.put(blob)
            self._reply(200, {"ok": True})

        def _house_chunk(self, data: dict[str, Any]) -> None:
            if not self._bearer_ok():
                self._reply(401, {"ok": False, "error": "unauthorized"})
                return
            call_id = str(data.get("call_id") or "").strip()
            blob = data.get("blob")
            slot = _find_call(state, call_id)
            if slot is None:
                self._reply(404, {"ok": False, "error": "unknown call"})
                return
            call = slot.calls.get(call_id)
            if call is None or not call.stream:
                self._reply(404, {"ok": False, "error": "unknown call"})
                return
            if blob is None or blob == "":
                call.chunks.put(None)
            else:
                call.chunks.put(str(blob))
            self._reply(200, {"ok": True})

        def _phone_call(self, data: dict[str, Any]) -> None:
            instance = str(data.get("instance") or "").strip()
            blob = str(data.get("blob") or "")
            stream = bool(data.get("stream"))
            if not instance or not blob:
                self._reply(400, {"ok": False, "error": "instance and blob required"})
                return
            if len(blob) > MAX_BLOB:
                self._reply(413, {"ok": False, "error": "too large"})
                return
            if not state.house_here(instance):
                self._reply(503, {"ok": False, "error": "house away"})
                return
            slot = state.slot(instance)
            call = _Call(blob, stream)
            with slot.lock:
                slot.calls[call.id] = call
            slot.pending.put(call)
            try:
                if stream:
                    self._pipe_stream(call)
                else:
                    try:
                        reply = call.reply.get(timeout=PHONE_WAIT_S)
                    except queue.Empty:
                        self._reply(504, {"ok": False, "error": "house timeout"})
                        return
                    if reply is None:
                        self._reply(502, {"ok": False, "error": "house failed"})
                        return
                    self._reply(200, {"ok": True, "blob": reply})
            finally:
                with slot.lock:
                    slot.calls.pop(call.id, None)

        def _pipe_stream(self, call: _Call) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            deadline = time.monotonic() + STREAM_WAIT_S
            try:
                while time.monotonic() < deadline:
                    timeout = min(30.0, deadline - time.monotonic())
                    try:
                        item = call.chunks.get(timeout=max(0.1, timeout))
                    except queue.Empty:
                        continue
                    if item is None:
                        return
                    self.wfile.write((item + "\n").encode())
                    self.wfile.flush()
            except OSError:
                return

    return Handler


def _find_call(state: RelayState, call_id: str) -> _Slot | None:
    if not call_id:
        return None
    with state.lock:
        slots = list(state.slots.values())
    for slot in slots:
        with slot.lock:
            if call_id in slot.calls:
                return slot
    return None
