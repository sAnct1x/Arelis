"""Asyncio IPC client (UI side) — receive core events onto the local EventBus."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.presence.ipc import (
    assert_loopback_host,
    bye_message,
    confirm_reply_message,
    decode_line,
    encode_line,
    event_from_message,
    hello_message,
    open_ui_request_message,
    shutdown_message,
)

log = logging.getLogger(__name__)


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
    ) -> None:
        self.bus = bus
        self.host = assert_loopback_host(host)
        self.port = int(port)
        self.reconnect_s = float(reconnect_s)
        self._on_open_ui = on_open_ui
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[Any] | None = None
        self._stop = asyncio.Event()
        self._attached = False

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

    async def send_open_ui_request(self, **payload: Any) -> bool:
        """Ask core to rebroadcast open_ui (second-instance activate)."""
        writer = self._writer
        if writer is None or not self._attached:
            return False
        try:
            writer.write(encode_line(open_ui_request_message(**payload)))
            await writer.drain()
            return True
        except Exception as exc:
            log.warning("IPC open_ui_request failed: %s", exc)
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

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.info("IPC client session ended: %s", exc)
            self._attached = False
            if self._stop.is_set():
                break
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.reconnect_s)
            except TimeoutError:
                pass

    async def _session(self) -> None:
        reader, writer = await asyncio.open_connection(self.host, self.port)
        self._reader = reader
        self._writer = writer
        writer.write(encode_line(hello_message(role="ui")))
        await writer.drain()
        try:
            while not self._stop.is_set():
                line = await reader.readline()
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
                    self._attached = True
                    await self.bus.publish(
                        Event(
                            EventType.STATUS,
                            {
                                "message": (
                                    f"Live bridge attached to core IPC "
                                    f"{self.host}:{self.port}."
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
