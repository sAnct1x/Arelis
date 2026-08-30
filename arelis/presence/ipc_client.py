"""Asyncio IPC client (UI side) — receive core events onto the local EventBus."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.identity import is_mine
from arelis.presence.ipc import (
    assert_loopback_host,
    bye_message,
    confirm_reply_message,
    decode_line,
    encode_line,
    event_from_message,
    hello_message,
    shutdown_message,
)
from arelis.presence.ports import candidates

log = logging.getLogger(__name__)

# How long a connected-but-silent peer gets to identify itself as a core. Only
# applies before the handshake; once attached, events arrive whenever they arrive
# and a quiet connection is perfectly normal.
HANDSHAKE_TIMEOUT_S = 2.0


class IpcClient:
    """Connect to a core IPC server and republish allowlisted events locally."""

    def __init__(
        self,
        bus: EventBus,
        *,
        host: str = "127.0.0.1",
        port: int = 8766,
        reconnect_s: float = 2.0,
        on_open_ui: Callable[[dict[str, Any]], None] | None = None,
        search_ports: bool = False,
    ) -> None:
        self.bus = bus
        self.host = assert_loopback_host(host)
        self.port = int(port)
        self.reconnect_s = float(reconnect_s)
        # Off by default so a caller naming an exact port gets that port. The UI
        # turns it on because its own core may have fallen forward when another
        # account had already taken the configured one.
        self.search_ports = bool(search_ports)
        self._on_open_ui = on_open_ui
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[Any] | None = None
        self._stop = asyncio.Event()
        self._attached = False
        # Counts consecutive sessions that never attached, which is also the
        # cursor into the candidate ports. Left alone after a success so a
        # dropped connection retries the port that worked before scanning again.
        self._failures = 0

    @property
    def attached(self) -> bool:
        return self._attached

    def start(self) -> asyncio.Task[Any]:
        """Run the connect/pump loop as a background task."""
        if self._task is not None and not self._task.done():
            return self._task
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="arelis-ipc-client")
        return self._task

    async def stop(self) -> None:
        self._stop.set()
        await self._close_transport()
        task = self._task
        self._task = None
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=3.0)
            except (TimeoutError, asyncio.CancelledError, Exception):
                task.cancel()

    async def send_confirm_reply(self, confirm_id: str, decision: str) -> bool:
        """Forward a human Allow/Skip to the core bus (best-effort)."""
        writer = self._writer
        if writer is None or not self._attached:
            return False
        try:
            writer.write(encode_line(confirm_reply_message(confirm_id, decision)))
            await writer.drain()
            return True
        except Exception as exc:
            log.warning("IPC confirm_reply failed: %s", exc)
            return False

    async def send_shutdown(self, *, reason: str = "quit") -> bool:
        """Ask the core process to stop (full Quit from UI tray)."""
        writer = self._writer
        if writer is None or not self._attached:
            return False
        try:
            writer.write(encode_line(shutdown_message(reason=reason)))
            await writer.drain()
            return True
        except Exception as exc:
            log.warning("IPC shutdown failed: %s", exc)
            return False

    def _port_options(self) -> list[int]:
        if not self.search_ports:
            return [self.port]
        return candidates(self.port) or [self.port]

    def _port_for_attempt(self) -> int:
        options = self._port_options()
        return options[self._failures % len(options)]

    def _keep_scanning(self) -> bool:
        """Whether another untried candidate port remains in this pass.

        A refused connection on loopback comes back immediately, so pausing
        ``reconnect_s`` between candidates would turn finding a core two ports
        along into several seconds of a UI with no live bridge and no explanation.
        Once a whole pass has failed, the cursor is back at the preferred port and
        the ordinary reconnect delay applies again.
        """
        options = self._port_options()
        return len(options) > 1 and self._failures % len(options) != 0

    async def _run(self) -> None:
        while not self._stop.is_set():
            attached_this_session = False
            try:
                attached_this_session = await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.info("IPC client session ended: %s", exc)
            self._attached = False
            if self._stop.is_set():
                break
            if not attached_this_session:
                self._failures += 1
                if self._keep_scanning():
                    continue
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.reconnect_s)
            except TimeoutError:
                pass

    async def _session(self) -> bool:
        """One connect-and-pump cycle. Returns whether it ever attached."""
        port = self._port_for_attempt()
        attached_here = False
        reader, writer = await asyncio.open_connection(self.host, port)
        self._reader = reader
        self._writer = writer
        writer.write(encode_line(hello_message(role="ui")))
        await writer.drain()
        try:
            while not self._stop.is_set():
                if attached_here:
                    line = await reader.readline()
                else:
                    # Until the ack arrives, anything at all could be on the far
                    # end. A socket that accepts the connection and then says
                    # nothing -- an unrelated service, or a half-dead core -- would
                    # otherwise hold this loop open forever, and with searching on
                    # that means never reaching the port our own core is actually
                    # listening on. A timeout here is what turns "stuck" into
                    # "next candidate".
                    line = await asyncio.wait_for(
                        reader.readline(), timeout=HANDSHAKE_TIMEOUT_S
                    )
                if not line:
                    break
                try:
                    msg = decode_line(line)
                except Exception as exc:
                    log.warning("IPC client bad line: %s", exc)
                    continue
                if msg is None:
                    continue
                op = str(msg.get("op") or "").strip()
                if op == "hello_ack":
                    if not is_mine(msg.get("instance")):
                        # Another account's core on the shared loopback
                        # interface. Attaching would republish their inbound
                        # texts and confirmation prompts onto this user's bus.
                        log.info(
                            "Core on %s:%s belongs to another account; "
                            "not attaching",
                            self.host,
                            port,
                        )
                        break
                    self._attached = True
                    attached_here = True
                    await self.bus.publish(
                        Event(
                            EventType.STATUS,
                            {
                                "message": (
                                    f"Live bridge attached to core IPC "
                                    f"{self.host}:{port}."
                                ),
                                "_from_ipc": True,
                            },
                        )
                    )
                    continue
                if op == "bye":
                    break
                if op == "event":
                    event = event_from_message(msg)
                    if event is not None:
                        await self.bus.publish(event)
                    continue
                if op == "open_ui":
                    if self._on_open_ui is not None:
                        try:
                            self._on_open_ui(msg)
                        except Exception:
                            log.exception("IPC on_open_ui callback failed")
                    continue
        finally:
            self._attached = False
            await self._close_transport()
        return attached_here

    async def _close_transport(self) -> None:
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is None:
            return
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
