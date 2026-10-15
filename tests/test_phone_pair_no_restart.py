"""Pairing a phone must start ingest in this process, without a restart.

Catches Settings → Notify → Create a pairing code writing a token and drawing
a QR while leaving /inbound/pair dark until Arelis was launched again.
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest

from arelis.core.bus import EventBus
from arelis.presence.inbound_runtime import (
    InboundRuntime,
    create_pairing_code,
    sync_ingest_listener,
)
from arelis.presence.lock import probe_ingest_health
from arelis.presence.ports import candidates
from arelis.sms_ingest import load_ingest_token


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _config(port: int, *, enabled: Any = "auto") -> dict[str, Any]:
    return {
        "tools": {
            "sms": {
                "enabled": True,
                "inbound": {
                    "enabled": True,
                    "fallback_smsgate": False,
                    "ingest": {
                        "enabled": enabled,
                        "host": "127.0.0.1",
                        "port": port,
                    },
                },
                "auto_reply": {"enabled": False},
            }
        }
    }


def _seat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secrets = tmp_path / "secrets.yaml"
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ARELIS_INGEST_TOKEN", raising=False)
    monkeypatch.setattr("arelis.sms_ingest.SECRETS_PATH", secrets)
    monkeypatch.setattr(
        "arelis.presence.inbound_runtime.load_sms_account",
        lambda: None,
    )


def _ours_listening(config: dict[str, Any]) -> list[int]:
    ingest = ((config.get("tools") or {}).get("sms") or {}).get("inbound") or {}
    preferred = int((ingest.get("ingest") or {}).get("port") or 8765)
    found: list[int] = []
    for port in candidates(preferred):
        if probe_ingest_health(port=port, mine_only=True, timeout_s=1.0):
            found.append(port)
    return found


async def _bus() -> tuple[EventBus, asyncio.Task[None]]:
    bus = EventBus()
    task = asyncio.create_task(bus.run())
    return bus, task


async def _shutdown(runtime: InboundRuntime, bus: EventBus, task: asyncio.Task[None]) -> None:
    await runtime.stop()
    bus.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_create_pairing_code_starts_listener_without_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fresh auto profile: the Settings create-code path binds ingest now."""
    _seat(monkeypatch, tmp_path)
    port = _free_port()
    config = _config(port, enabled="auto")
    bus, task = await _bus()
    runtime = InboundRuntime(owned=True)
    try:
        runtime = create_pairing_code(
            bus, asyncio.get_running_loop(), config, runtime
        )
        token = load_ingest_token()
        assert token
        assert runtime.ingest is not None
        bound = runtime.ingest.port
        async with httpx.AsyncClient() as client:
            health = await client.get(f"http://127.0.0.1:{bound}/inbound/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        assert _ours_listening(config) == [bound]
    finally:
        await _shutdown(runtime, bus, task)


async def test_enabled_false_does_not_listen_and_stop_frees_the_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Create-code with ingest off stays quiet; turning off a live listener unbinds."""
    _seat(monkeypatch, tmp_path)
    port = _free_port()
    off = _config(port, enabled=False)
    bus, task = await _bus()
    loop = asyncio.get_running_loop()
    runtime = InboundRuntime(owned=True)
    try:
        runtime = create_pairing_code(bus, loop, off, runtime)
        assert load_ingest_token()
        assert runtime.ingest is None
        assert _ours_listening(off) == []

        on = _config(port, enabled="auto")
        runtime = create_pairing_code(bus, loop, on, runtime)
        assert runtime.ingest is not None
        bound = runtime.ingest.port
        assert probe_ingest_health(port=bound, timeout_s=1.0)

        runtime = sync_ingest_listener(bus, loop, off, runtime)
        assert runtime.ingest is None
        assert not probe_ingest_health(port=bound, timeout_s=0.5)
        # Nothing accepts on the old port any more. A raw connect, not a
        # bind: on Linux the health probe leaves a TIME_WAIT on this port
        # that blocks a plain bind for about a minute even when it is free.
        with pytest.raises(ConnectionRefusedError):
            socket.create_connection(("127.0.0.1", bound), timeout=5.0).close()
    finally:
        await _shutdown(runtime, bus, task)


async def test_starting_twice_leaves_one_healthy_listener(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A second start must not bind a second port as this user."""
    _seat(monkeypatch, tmp_path)
    port = _free_port()
    config = _config(port, enabled=True)
    bus, task = await _bus()
    loop = asyncio.get_running_loop()
    runtime = InboundRuntime(owned=True)
    try:
        runtime = create_pairing_code(bus, loop, config, runtime)
        runtime = create_pairing_code(bus, loop, config, runtime)
        runtime = sync_ingest_listener(bus, loop, config, runtime)
        assert len(_ours_listening(config)) == 1
        assert runtime.ingest is not None
        assert runtime.ingest.running
    finally:
        await _shutdown(runtime, bus, task)


