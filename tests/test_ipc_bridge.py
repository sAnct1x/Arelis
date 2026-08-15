"""Core↔UI JSON-lines IPC — loopback only, offline (no phone / no Qt)."""

from __future__ import annotations

import asyncio
import socket

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.presence.ipc import (
    assert_loopback_host,
    event_message,
    hello_message,
    open_ui_message,
    shutdown_message,
)
from arelis.presence.ipc_client import IpcClient
from arelis.presence.ipc_server import IpcServer
from arelis.presence.open_ui import ensure_ui_open


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_assert_loopback_rejects_lan() -> None:
    with pytest.raises(ValueError):
        assert_loopback_host("0.0.0.0")
    with pytest.raises(ValueError):
        assert_loopback_host("192.168.1.10")
    assert assert_loopback_host("127.0.0.1") == "127.0.0.1"
    assert assert_loopback_host("localhost") == "127.0.0.1"


def test_event_message_skips_non_forward_and_echo() -> None:
    assert (
        event_message(Event(EventType.ASSISTANT_DELTA, {"text": "x"})) is None
    )
    assert (
        event_message(
            Event(EventType.SMS_RECEIVED, {"body": "hi", "_from_ipc": True})
        )
        is None
    )
    msg = event_message(Event(EventType.SMS_RECEIVED, {"body": "hi"}, id="abc"))
    assert msg is not None
    assert msg["op"] == "event"
    assert msg["type"] == "sms_received"
    assert hello_message()["op"] == "hello"
    assert open_ui_message(reason="tool_confirm")["op"] == "open_ui"


@pytest.mark.asyncio
async def test_open_ui_broadcast_invokes_callback() -> None:
    core_bus = EventBus()
    ui_bus = EventBus()
    core_task = asyncio.create_task(core_bus.run())
    ui_task = asyncio.create_task(ui_bus.run())
    opened: list[dict] = []

    port = _free_loopback_port()
    server = IpcServer(core_bus, host="127.0.0.1", port=port)
    await server.start()
    client = IpcClient(
        ui_bus,
        host="127.0.0.1",
        port=port,
        reconnect_s=0.2,
        on_open_ui=lambda msg: opened.append(dict(msg)),
    )
    client.start()
    try:
        for _ in range(50):
            if client.attached:
                break
            await asyncio.sleep(0.05)
        assert client.attached
        n = await server.request_open_ui(reason="test")
        assert n >= 1
        for _ in range(50):
            if opened:
                break
            await asyncio.sleep(0.05)
        assert opened
        assert opened[0]["op"] == "open_ui"
        assert opened[0].get("reason") == "test"

        # Detached path: no spawn in unit test.
        lonely = EventBus()
        lonely_server = IpcServer(lonely, host="127.0.0.1", port=_free_loopback_port())
        await lonely_server.start()
        result = await ensure_ui_open(lonely_server, spawn_if_detached=False)
        assert result["attached"] == 0
        assert result["spawned"] is False
        await lonely_server.stop()

        # Shutdown callback from attached client.
        stopped: list[str] = []
        core_bus2 = EventBus()
        ui_bus2 = EventBus()
        t1 = asyncio.create_task(core_bus2.run())
        t2 = asyncio.create_task(ui_bus2.run())
        port2 = _free_loopback_port()
        server2 = IpcServer(
            core_bus2,
            host="127.0.0.1",
            port=port2,
            on_shutdown=lambda reason: stopped.append(str(reason)),
        )
        await server2.start()
        client2 = IpcClient(ui_bus2, host="127.0.0.1", port=port2, reconnect_s=0.2)
        client2.start()
        for _ in range(50):
            if client2.attached:
                break
            await asyncio.sleep(0.05)
        assert client2.attached
        assert await client2.send_shutdown(reason="test_quit")
        for _ in range(50):
            if stopped:
                break
            await asyncio.sleep(0.05)
        assert stopped == ["test_quit"]
        assert shutdown_message()["op"] == "shutdown"
        await client2.stop()
        await server2.stop()
        core_bus2.stop()
        ui_bus2.stop()
        t1.cancel()
        t2.cancel()
        await asyncio.gather(t1, t2, return_exceptions=True)
    finally:
        await client.stop()
        await server.stop()
        core_bus.stop()
        ui_bus.stop()
        core_task.cancel()
        ui_task.cancel()
        await asyncio.gather(core_task, ui_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_live_bridge_sms_and_confirm_reply() -> None:
    core_bus = EventBus()
    ui_bus = EventBus()
    core_task = asyncio.create_task(core_bus.run())
    ui_task = asyncio.create_task(ui_bus.run())

    seen: list[Event] = []
    replies: list[Event] = []

    async def ui_capture(event: Event) -> None:
        if event.type in {
            EventType.SMS_RECEIVED,
            EventType.TOOL_CONFIRM,
            EventType.STATUS,
        }:
            seen.append(event)

    async def core_capture(event: Event) -> None:
        if event.type == EventType.TOOL_CONFIRM_REPLY:
            replies.append(event)

    ui_bus.subscribe(None, ui_capture)
    core_bus.subscribe(None, core_capture)

    port = _free_loopback_port()
    server = IpcServer(core_bus, host="127.0.0.1", port=port)
    await server.start()
    client = IpcClient(ui_bus, host="127.0.0.1", port=port, reconnect_s=0.2)
    client.start()

    try:
        # Wait for hello_ack → attached
        for _ in range(50):
            if client.attached:
                break
            await asyncio.sleep(0.05)
        assert client.attached, "UI client never attached to core IPC"

        await core_bus.publish(
            Event(
                EventType.SMS_RECEIVED,
                {"from": "+15551212", "body": "bridge test", "id": "m1"},
            )
        )
        await core_bus.publish(
            Event(
                EventType.TOOL_CONFIRM,
                {
                    "id": "c1",
                    "tool": "send_sms",
                    "summary": "send_sms(to=+1…)",
                },
            )
        )

        for _ in range(50):
            types = {e.type for e in seen}
            if EventType.SMS_RECEIVED in types and EventType.TOOL_CONFIRM in types:
                break
            await asyncio.sleep(0.05)

        types = {e.type for e in seen}
        assert EventType.SMS_RECEIVED in types
        assert EventType.TOOL_CONFIRM in types
        sms = next(e for e in seen if e.type == EventType.SMS_RECEIVED)
        assert sms.payload.get("body") == "bridge test"
        assert sms.payload.get("_from_ipc") is True

        ok = await client.send_confirm_reply("c1", "skip")
        assert ok
        for _ in range(50):
            if replies:
                break
            await asyncio.sleep(0.05)
        assert replies
        assert replies[0].payload.get("id") == "c1"
        assert replies[0].payload.get("decision") == "skip"
    finally:
        await client.stop()
        await server.stop()
        core_bus.stop()
        ui_bus.stop()
        # EventBus.run blocks on queue.get() even after stop(); cancel tasks.
        core_task.cancel()
        ui_task.cancel()
        await asyncio.gather(core_task, ui_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_server_refuses_non_loopback_host() -> None:
    bus = EventBus()
    with pytest.raises(ValueError):
        IpcServer(bus, host="0.0.0.0", port=18767)
