"""Headless Arelis core: inbound ingest without the glass UI.

Voice/wake stay off here (see presence design). Confirm cards for auto-reply
still publish on the bus; without a UI they wait until persistence / tray.
Nothing is sent silently.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import threading
from typing import Any

from arelis.core.bus import EventBus
from arelis.core.event_audit import attach_event_audit
from arelis.core.events import Event, EventType
from arelis.presence.inbound_runtime import attach_inbound
from arelis.presence.ipc_server import IpcServer
from arelis.presence.lock import PresenceLock, core_lock_path
from arelis.presence.open_ui import ensure_ui_open
from arelis.presence.pending_confirms import (
    PendingConfirmStore,
    pending_confirms_path,
    pending_from_event_payload,
)
from arelis.presence.tray import CoreTray

log = logging.getLogger(__name__)


def run_core(config: dict[str, Any]) -> int:
    """Run until SIGINT/SIGTERM/tray Quit/IPC shutdown. Returns exit code."""
    lock = PresenceLock(core_lock_path(config))
    if not lock.acquire():
        log.error(
            "Another Arelis core already holds %s — not starting a second ingest.",
            lock.path,
        )
        return 2

    store = PendingConfirmStore(pending_confirms_path(config))
    ipc_holder: dict[str, IpcServer | None] = {"server": None}
    stop = threading.Event()

    async def _on_bus(event: Event) -> None:
        payload = event.payload or {}
        if event.type == EventType.STATUS:
            log.info("%s", payload.get("message") or "")
            return
        if event.type == EventType.SMS_RECEIVED:
            who = payload.get("contact_name") or payload.get("contact_alias") or payload.get(
                "from"
            )
            body = str(payload.get("body") or "")
            preview = body if len(body) <= 80 else body[:79] + "…"
            log.info("Inbound SMS from %s: %s", who, preview)
            ipc = ipc_holder["server"]
            if ipc is None or ipc.attached_clients < 1:
                await bus.publish(
                    Event(
                        EventType.STATUS,
                        {
                            "message": (
                                f"Inbound SMS from {who} while no glass UI is attached "
                                f"— open Arelis to see it in chat "
                                f"(preview: {preview})"
                            )
                        },
                    )
                )
            return
        if event.type == EventType.TOOL_CONFIRM:
            item = pending_from_event_payload(payload)
            if item is not None:
                store.upsert(item)
            log.info(
                "Confirm needed (%s): %s — open Arelis to allow/skip (no silent send).",
                payload.get("tool"),
                payload.get("summary"),
            )
            result = await ensure_ui_open(
                ipc_holder["server"],
                spawn_if_detached=True,
                config=config,
                reason="tool_confirm",
                confirm_id=str(payload.get("id") or ""),
            )
            if result.get("attached"):
                log.info("open_ui broadcast to %s attached client(s).", result["attached"])
            elif result.get("spawned"):
                log.info("Spawned UI for confirm (pid=%s).", result.get("pid"))
            elif result.get("ui_lock"):
                log.info("UI already running (lock held); confirm parked — open from tray.")
            else:
                log.info("No UI attached; confirm parked on disk.")
            return
        if event.type == EventType.TOOL_CONFIRM_REPLY:
            log.info(
                "Confirm reply id=%s decision=%s tool=%s",
                payload.get("id"),
                payload.get("decision"),
                payload.get("tool"),
            )
            return
        if event.type == EventType.TOOL_RESULT:
            log.info(
                "Tool result %s ok=%s",
                payload.get("tool"),
                payload.get("ok"),
            )
            return
        if event.type == EventType.ERROR:
            log.error(
                "Error scope=%s: %s",
                payload.get("scope") or "turn",
                payload.get("message") or "",
            )

    bus = EventBus()
    bus.subscribe(None, _on_bus)
    attach_event_audit(bus, config)

    presence_cfg = config.get("presence") or {}
    ipc_enabled = bool(presence_cfg.get("ipc_enabled", True))
    ipc_host = str(presence_cfg.get("ipc_host") or "127.0.0.1")
    ipc_port = int(presence_cfg.get("ipc_port") or 8766)
    core_tray_enabled = bool(presence_cfg.get("core_tray", True))

    def _request_stop(*_args: Any) -> None:
        stop.set()

    ipc_server: IpcServer | None = None
    if ipc_enabled:
        try:
            ipc_server = IpcServer(
                bus,
                host=ipc_host,
                port=ipc_port,
                on_shutdown=_request_stop,
            )
        except ValueError as exc:
            log.error("Core IPC disabled: %s", exc)
            ipc_server = None
    ipc_holder["server"] = ipc_server

    loop = asyncio.new_event_loop()

    def loop_thread() -> None:
        asyncio.set_event_loop(loop)
        bus_task = loop.create_task(bus.run())
        loop.bus_task = bus_task  # type: ignore[attr-defined]
        if ipc_server is not None:
            ipc_task = loop.create_task(ipc_server.start())
            loop.ipc_task = ipc_task  # type: ignore[attr-defined]
        loop.run_forever()

    thread = threading.Thread(target=loop_thread, name="arelis-core-asyncio", daemon=True)
    thread.start()

    runtime = attach_inbound(
        bus,
        loop,
        config,
        owned=True,
        stay_open_hint="core is running",
        headless=True,
    )
    for message in runtime.status_messages:
        asyncio.run_coroutine_threadsafe(
            bus.publish(Event(EventType.STATUS, {"message": message})),
            loop,
        )
    if ipc_server is not None:
        asyncio.run_coroutine_threadsafe(
            bus.publish(
                Event(
                    EventType.STATUS,
                    {
                        "message": (
                            f"Core IPC ready on {ipc_host}:{ipc_port} "
                            "(UI may attach for live SMS/confirm events)."
                        )
                    },
                )
            ),
            loop,
        )

    def _tray_open_ui() -> None:
        async def _go() -> None:
            await ensure_ui_open(
                ipc_holder["server"],
                spawn_if_detached=True,
                config=config,
                reason="core_tray",
            )

        asyncio.run_coroutine_threadsafe(_go(), loop)

    tray: CoreTray | None = None
    if core_tray_enabled:
        tray = CoreTray(on_open_ui=_tray_open_ui, on_quit=_request_stop)
        tray.start()

    prev_int = signal.signal(signal.SIGINT, _request_stop)
    prev_term = signal.signal(signal.SIGTERM, _request_stop)
    log.info("Arelis core running (tray Quit / Ctrl+C / SIGTERM to stop).")
    try:
        while not stop.wait(timeout=3600):
            pass
    finally:
        signal.signal(signal.SIGINT, prev_int)
        signal.signal(signal.SIGTERM, prev_term)

    if tray is not None:
        tray.stop()

    async def shutdown() -> None:
        if ipc_server is not None:
            await ipc_server.stop()
        await runtime.stop()
        bus.stop()

    fut = asyncio.run_coroutine_threadsafe(shutdown(), loop)
    try:
        fut.result(timeout=10)
    except Exception:
        log.exception("Core shutdown failed")
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    lock.release()
    log.info("Arelis core stopped.")
    return 0
