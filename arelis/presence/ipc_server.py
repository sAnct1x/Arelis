"""Asyncio IPC server (core side) — fan-out allowlisted bus events to UI clients."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.presence.ipc import (
    assert_loopback_host,
    bye_message,
    decode_line,
    encode_line,
    event_message,
    open_ui_message,
)

log = logging.getLogger(__name__)


class IpcServer:
    """Loopback JSON-lines server attached to a core EventBus."""

    def __init__(
        self,
        bus: EventBus,
        *,
        host: str = "127.0.0.1",
        port: int = 8766,
        on_shutdown: Any | None = None,
    ) -> None:
        self.bus = bus
        self.host = assert_loopback_host(host)
        self.port = int(port)
        self._on_shutdown = on_shutdown
        self._server: asyncio.Server | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._attached = 0
        self._closed = False

    @property
    def attached_clients(self) -> int:
        return self._attached

    async def request_open_ui(self, **payload: Any) -> int:
        """Broadcast open_ui to attached UIs. Returns attached client count."""
        if self._closed or not self._clients:
            return 0
        await self._broadcast(open_ui_message(**payload))
        return self._attached

    async def start(self) -> None:
        if self._server is not None:
            return
        self._closed = False
        self.bus.subscribe(None, self._on_bus_event)
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.host,
            port=self.port,
        )
        log.info("Core IPC listening on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        self._closed = True
        for writer in list(self._clients):
            try:
                writer.write(encode_line(bye_message()))
                await writer.drain()
            except Exception:
                pass
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()
        self._attached = 0
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            log.info("Core IPC stopped")

    async def _on_bus_event(self, event: Event) -> None:
        if self._closed:
            return
        msg = event_message(event)
        if msg is None:
            return
        await self._broadcast(msg)

    async def _broadcast(self, msg: dict[str, Any]) -> None:
        dead: list[asyncio.StreamWriter] = []
        payload = encode_line(msg)
        for writer in list(self._clients):
            try:
                writer.write(payload)
                await writer.drain()
            except Exception:
                dead.append(writer)
        for writer in dead:
            self._drop_client(writer)

    def _drop_client(self, writer: asyncio.StreamWriter) -> None:
        if writer in self._clients:
            self._clients.discard(writer)
            self._attached = max(0, self._attached - 1)
        try:
            writer.close()
        except Exception:
            pass

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        log.info("IPC client connected from %s", peer)
        self._clients.add(writer)
        greeted = False
        try:
            while not self._closed:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = decode_line(line)
                except Exception as exc:
                    log.warning("IPC bad line from %s: %s", peer, exc)
                    continue
                if msg is None:
                    continue
                op = str(msg.get("op") or "").strip()
                if op == "hello":
                    if not greeted:
                        greeted = True
                        self._attached += 1
                        log.info(
                            "IPC UI attached (role=%s version=%s); clients=%s",
                            msg.get("role"),
                            msg.get("version"),
                            self._attached,
                        )
                        writer.write(
                            encode_line(
                                {
                                    "op": "hello_ack",
                                    "role": "core",
                                    "version": int(msg.get("version") or 1),
                                }
                            )
                        )
                        await writer.drain()
                    continue
                if op == "bye":
                    break
                if op == "confirm_reply":
                    confirm_id = str(msg.get("id") or "").strip()
                    decision = str(msg.get("decision") or "").strip().lower()
                    if confirm_id and decision:
                        await self.bus.publish(
                            Event(
                                EventType.TOOL_CONFIRM_REPLY,
                                {
                                    "id": confirm_id,
                                    "decision": decision,
                                    "_from_ipc": True,
                                },
                            )
                        )
                    continue
                if op == "open_ui_request":
                    await self.request_open_ui(
                        reason=str(msg.get("reason") or "open_ui_request")
                    )
                    continue
                if op == "shutdown":
                    reason = str(msg.get("reason") or "quit")
                    log.info("IPC shutdown requested (%s) from %s", reason, peer)
                    if callable(self._on_shutdown):
                        try:
                            self._on_shutdown(reason)
                        except Exception:
                            log.exception("IPC on_shutdown failed")
                    continue
                log.debug("IPC ignored op=%s from %s", op, peer)
        finally:
            self._drop_client(writer)
            log.info("IPC client disconnected from %s", peer)
