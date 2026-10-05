"""Pairing a phone must start ingest in this process, without a restart.

Catches Settings → Notify → Create a pairing code writing a token and drawing
a QR while leaving /inbound/pair dark until Arelis was launched again.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest

from arelis.core.bus import EventBus
from arelis.presence.inbound_runtime import (
    InboundRuntime,
    attach_inbound,
    create_pairing_code,
    ingest_enabled_mode,
    sync_ingest_listener,
)
from arelis.presence.lock import probe_ingest_health
from arelis.presence.ports import candidates
from arelis.presence.readiness import ChipLevel, _sms_chip
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


async def test_regenerating_a_code_invalidates_the_old_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A second Create a pairing code refuses the old token and keeps one listener."""
    _seat(monkeypatch, tmp_path)
    port = _free_port()
    config = _config(port, enabled="auto")
    bus, task = await _bus()
    runtime = InboundRuntime(owned=True)
    loop = asyncio.get_running_loop()
    try:
        runtime = create_pairing_code(bus, loop, config, runtime)
        old = load_ingest_token()
        bound = runtime.ingest.port
        runtime = create_pairing_code(bus, loop, config, runtime)
        new = load_ingest_token()
        assert old and new and old != new
        assert runtime.ingest is not None
        assert runtime.ingest.running
        assert _ours_listening(config) == [bound]
        async with httpx.AsyncClient() as client:
            denied = await client.get(
                f"http://127.0.0.1:{bound}/inbound/ping",
                headers={"X-Arelis-Token": old},
            )
            ok = await client.get(
                f"http://127.0.0.1:{bound}/inbound/ping",
                headers={"X-Arelis-Token": new},
            )
        assert denied.status_code == 401
        assert ok.status_code == 200
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
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", bound))
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


async def test_quoted_false_and_off_do_not_listen_even_with_a_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Quoted YAML strings are not booleans; they must not open the phone door."""
    _seat(monkeypatch, tmp_path)
    monkeypatch.setenv("ARELIS_INGEST_TOKEN", "quoted-off-token")
    bus, task = await _bus()
    loop = asyncio.get_running_loop()
    runtimes: list[InboundRuntime] = []
    try:
        for value in ("false", "off", "yes-please"):
            port = _free_port()
            config = _config(port, enabled=value)
            runtime = attach_inbound(bus, loop, config, owned=True)
            runtimes.append(runtime)
            assert runtime.ingest is None, value
            assert _ours_listening(config) == []
    finally:
        for runtime in runtimes:
            await runtime.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_ingest_enabled_mode_logs_unrecognized_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    assert ingest_enabled_mode(True) == "on"
    assert ingest_enabled_mode(False) == "off"
    assert ingest_enabled_mode("auto") == "auto"
    assert ingest_enabled_mode("false") == "off"
    assert ingest_enabled_mode("off") == "off"
    ingest_enabled_mode("false")
    ingest_enabled_mode("mystery")
    ingest_enabled_mode("mystery")
    lines = [r.message for r in caplog.records if "ingest.enabled" in r.message]
    assert len(lines) >= 1
    assert sum(1 for line in lines if "mystery" in line) == 1


def test_sms_chip_uses_plain_phone_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "arelis.presence.readiness.load_sms_account",
        lambda: object(),
    )
    off = _sms_chip(_config(8765, enabled=False))
    assert off.status is ChipLevel.OFF
    assert off.detail == "Phone notifications are off."
    assert _sms_chip(
        {"tools": {"sms": {"enabled": False}}}
    ).detail == "Phone notifications are off."
    assert _sms_chip(
        {"tools": {"sms": {"enabled": True, "inbound": {"enabled": False}}}}
    ).detail == "Phone notifications are off."

    monkeypatch.setattr(
        "arelis.presence.readiness.find_my_ingest_port",
        lambda _config: 8765,
    )
    ok = _sms_chip(_config(8765, enabled="auto"))
    assert ok.status is ChipLevel.OK
    assert ok.detail == "Phone notifications are running."

    monkeypatch.setattr(
        "arelis.presence.readiness.find_my_ingest_port",
        lambda _config: 8766,
    )
    taken_ok = _sms_chip(_config(8765, enabled=True))
    assert taken_ok.detail == "Phone notifications are running."

    monkeypatch.setattr(
        "arelis.presence.readiness.find_my_ingest_port",
        lambda _config: None,
    )
    monkeypatch.setattr(
        "arelis.presence.readiness.probe_ingest_health",
        lambda **_k: True,
    )
    warn_taken = _sms_chip(_config(8765, enabled=True))
    assert warn_taken.status is ChipLevel.WARN
    assert warn_taken.detail == (
        "Another Arelis on this PC is using the phone connection."
    )

    monkeypatch.setattr(
        "arelis.presence.readiness.probe_ingest_health",
        lambda **_k: False,
    )
    warn_down = _sms_chip(_config(8765, enabled=True))
    assert warn_down.detail == (
        "Phone notifications aren't running. Restart Arelis to try again."
    )
    assert "—" not in warn_down.detail
    monkeypatch.setattr(
        "arelis.presence.readiness.load_sms_account",
        lambda: None,
    )
    assert _sms_chip(_config(8765, enabled="auto")).detail == "Phone not paired."


async def test_settings_create_token_starts_health_on_loopback(
    qt_app, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Offscreen Settings path: the same slot the button calls must bind ingest."""
    os_env_port = _free_port()
    _seat(monkeypatch, tmp_path)
    from PySide6.QtWidgets import QWidget

    from arelis.ui.settings_dialog import SettingsDialog

    config = _config(os_env_port, enabled="auto")
    config["voice"] = {}
    config["presence"] = {}
    config["workspace"] = {
        "named_roots": [{"name": "arelis", "path": str(tmp_path), "read_only": False}]
    }
    bus, task = await _bus()
    host = QWidget()
    host.bus = bus
    host.loop = asyncio.get_running_loop()
    host.config = config
    host.inbound_runtime = InboundRuntime(owned=True)
    host.sms_ingest = None
    dlg = SettingsDialog(config, parent=host, list_models=lambda: [])
    try:
        dlg._create_ingest_token()
        runtime = host.inbound_runtime
        assert runtime.ingest is not None
        bound = runtime.ingest.port
        async with httpx.AsyncClient() as client:
            health = await client.get(f"http://127.0.0.1:{bound}/inbound/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        assert "restart" not in dlg.pair_status.text().lower()
    finally:
        dlg.close()
        host.deleteLater()
        await _shutdown(host.inbound_runtime, bus, task)
