"""Asyncio IPC server (core side) — fan-out allowlisted bus events to UI clients."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.identity import instance_id
from arelis.presence.ipc import (
    assert_loopback_host,
    bye_message,
    decode_line,
    encode_line,
    event_message,
    open_ui_message,
)
from arelis.presence.ports import candidates

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
        on_open_ui: Any | None = None,
    ) -> None:
        self.bus = bus
        self.host = assert_loopback_host(host)
        self.port = int(port)
        self._on_shutdown = on_shutdown
        # Set when the process hosting this server owns a window. A core can only
        # pass open_ui on to whoever is attached; a UI hosting its own server is
        # the thing being asked for and has to answer for itself.
        self._on_open_ui = on_open_ui
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
        """Bind the preferred port, or the next free one above it.

        The fall-forward matters more here than for inbound ingest. This is
        started as a bare task in ``arelis.presence.core``, so a bind failure
        used to surface as an unretrieved task exception: the second account's UI
        received no core events at all, with nothing on screen and nothing in the
        status line to connect that to a port. Loopback and discoverable by
        handshake, so moving is invisible to the user.

        Subscribing to the bus is deferred until a port is held. Subscribing
        first and then raising would leave a closed server attached to the bus,
        broadcasting to no one.
        """
        if self._server is not None:
            return
        last_error: OSError | None = None
        for candidate in candidates(self.port):
            try:
                server = await asyncio.start_server(
                    self._handle_client,
                    host=self.host,
                    port=candidate,
                )
            except OSError as exc:
                last_error = exc
                continue
            self._closed = False
            self.port = candidate
            self._server = server
            self.bus.subscribe(None, self._on_bus_event)
            log.info("Core IPC listening on %s:%s", self.host, self.port)
            try:
                from arelis.guard import Listener, get_watch

                get_watch().register_listener(
                    Listener(
                        name="ipc",
                        host=self.host,
                        port=self.port,
                        bind="loopback",
                    )
                )
            except Exception:
                log.debug("Watch did not register IPC", exc_info=True)
            return
        if last_error is not None:
            raise last_error
        raise OSError(f"{self.port} is not a port number that can be bound")

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
        try:
            from arelis.guard import get_watch

            get_watch().drop_listener("ipc")
        except Exception:
            pass
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
        # Debug, not info: a bare connection means nothing yet. The readiness probe
        # walks these ports every few seconds hunting for its ingest server, and
        # logging each one filled the log with hundreds of lines an hour that no
        # UI was ever on the other end of. The hello below is the real event.
        log.debug("IPC connection from %s", peer)
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
                    # Something that is not us. The ports either side of this one
                    # are the inbound-ingest fall-forward range, and the readiness
                    # probe walks them with an HTTP request looking for its own
                    # ingest server — so an HTTP verb arriving here is ordinary
                    # and used to produce five identical warnings per probe, one
                    # per header line. Hang up instead: whoever this is, they are
                    # not going to start speaking JSON on line six.
                    log.debug("IPC non-JSON line from %s: %s", peer, exc)
                    break
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
                                    # Named so the UI can tell this core apart
                                    # from another account's on the same
                                    # loopback interface. See arelis.identity.
                                    "instance": instance_id(),
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
                    reason = str(msg.get("reason") or "open_ui_request")
                    if callable(self._on_open_ui):
                        try:
                            self._on_open_ui(reason)
                        except Exception:
                            log.exception("IPC on_open_ui failed")
                    await self.request_open_ui(reason=reason)
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
