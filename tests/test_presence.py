"""Presence P1: core lock, inbound runtime, health probe — no live phone."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from arelis.core.bus import EventBus
from arelis.presence.inbound_runtime import InboundRuntime, attach_inbound
from arelis.presence.lock import (
    PresenceLock,
    external_core_available,
    lock_held_by_other,
    probe_ingest_health,
    ui_lock_path,
)
from arelis.presence.open_ui import ui_process_appears_running
from arelis.sms_ingest import load_ingest_token


def test_presence_lock_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "arelis-core.lock"
    first = PresenceLock(path)
    second = PresenceLock(path)
    assert first.acquire()
    assert first.held
    assert not second.acquire()
    assert lock_held_by_other(path)
    first.release()
    assert not lock_held_by_other(path)
    assert second.acquire()
    second.release()


def test_ui_lock_path_and_detect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {"presence": {"ui_lock_path": str(tmp_path / "arelis-ui.lock")}}
    path = ui_lock_path(cfg)
    assert path.name == "arelis-ui.lock"
    lock = PresenceLock(path)
    assert lock.acquire()
    assert ui_process_appears_running(cfg)
    lock.release()
    assert not ui_process_appears_running(cfg)


def test_probe_ingest_health_false_when_nothing_listens() -> None:
    assert probe_ingest_health(port=59999, timeout_s=0.2) is False


@pytest.mark.asyncio
async def test_attach_inbound_starts_health_without_ui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("sms:\n  ingest_token: test-token-xyz\n", encoding="utf-8")
    monkeypatch.setenv("ARELIS_INGEST_TOKEN", "test-token-xyz")
    assert load_ingest_token(secrets) == "test-token-xyz"

    bus = EventBus()
    loop = asyncio.get_running_loop()
    bus_task = asyncio.create_task(bus.run())
    config = {
        "tools": {
            "sms": {
                "enabled": True,
                "inbound": {
                    "enabled": True,
                    "fallback_smsgate": False,
                    "ingest": {"enabled": True, "host": "127.0.0.1", "port": 18765},
                },
                "auto_reply": {"enabled": False},
            }
        }
    }
    # load_sms_account may return None — fine; auto_reply still starts.
    runtime = attach_inbound(
        bus,
        loop,
        config,
        owned=True,
        stay_open_hint="core is running",
    )
    try:
        assert runtime.owned
        assert runtime.ingest is not None
        assert runtime.ingest.running
        assert any("Inbound notify ready" in m for m in runtime.status_messages)
        assert probe_ingest_health(port=18765, timeout_s=1.0)
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://127.0.0.1:18765/inbound/health")
            assert resp.status_code == 200
            assert resp.json().get("ok") is True
        assert external_core_available(
            {
                "presence": {"lock_path": str(tmp_path / "unused.lock")},
                "tools": {"sms": {"inbound": {"ingest": {"port": 18765}}}},
            }
        )
    finally:
        await runtime.stop()
        assert runtime.ingest is None
        bus.stop()
        bus_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bus_task


def test_inbound_runtime_stop_noop_when_not_owned() -> None:
    runtime = InboundRuntime(owned=False)

    async def _run() -> None:
        await runtime.stop()

    asyncio.run(_run())


def test_core_flag_in_help() -> None:
    from arelis.main import main
    from arelis.presence.core import run_core

    assert callable(run_core)
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
