"""Glass inbound: a sibling window is not a core, and attach has a way home."""

from __future__ import annotations

import asyncio
import socket
from types import SimpleNamespace

import pytest

from arelis.presence.glass_inbound import (
    ATTACH_GRACE_S,
    TAKEOVER_HOLD_S,
    should_take_ingest,
    watch_orphan_ingest,
)
from arelis.presence.lock import (
    PresenceLock,
    core_lock_path,
    external_core_available,
    find_my_ingest_port,
)


def _sms_config(port: int, *, lock_path: str) -> dict:
    return {
        "presence": {"lock_path": lock_path},
        "tools": {
            "sms": {
                "enabled": True,
                "inbound": {
                    "enabled": True,
                    "fallback_smsgate": False,
                    "ingest": {"enabled": True, "host": "127.0.0.1", "port": port},
                },
                "auto_reply": {"enabled": False},
            }
        },
    }


def test_should_take_ingest_table() -> None:
    base = dict(
        attached=False,
        already_own=False,
        core_lock=False,
        our_ingest_up=False,
        attached_once=False,
        waited_s=0.0,
        core_absent_s=0.0,
        grace_s=5.0,
        hold_s=8.0,
    )
    assert not should_take_ingest(**{**base, "waited_s": 4.9})
    assert should_take_ingest(**{**base, "waited_s": 5.0})
    assert not should_take_ingest(**{**base, "waited_s": 99.0, "core_lock": True})
    assert not should_take_ingest(**{**base, "waited_s": 99.0, "attached": True})
    assert not should_take_ingest(**{**base, "waited_s": 99.0, "already_own": True})
    assert not should_take_ingest(**{**base, "waited_s": 99.0, "our_ingest_up": True})
    # Bridge was live; core lock gone — wait the hold, then take.
    dropped = {**base, "attached_once": True, "waited_s": 99.0, "core_absent_s": 7.9}
    assert not should_take_ingest(**dropped)
    assert should_take_ingest(**{**dropped, "core_absent_s": 8.0})
    assert ATTACH_GRACE_S == 5.0
    assert TAKEOVER_HOLD_S == 8.0


async def test_watch_claims_after_grace() -> None:
    claimed = {"n": 0}

    async def claim() -> bool:
        claimed["n"] += 1
        return True

    stop = asyncio.Event()
    task = asyncio.create_task(
        watch_orphan_ingest(
            is_attached=lambda: False,
            already_own=lambda: False,
            core_lock=lambda: False,
            our_ingest_up=lambda: False,
            claim=claim,
            stop=stop,
            grace_s=0.05,
            hold_s=8.0,
            tick_s=0.02,
        )
    )
    for _ in range(20):
        if claimed["n"]:
            break
        await asyncio.sleep(0.02)
    stop.set()
    await task
    assert claimed["n"] == 1


async def test_watch_does_not_claim_while_core_lock_held() -> None:
    claimed = {"n": 0}

    async def claim() -> bool:
        claimed["n"] += 1
        return True

    stop = asyncio.Event()
    task = asyncio.create_task(
        watch_orphan_ingest(
            is_attached=lambda: False,
            already_own=lambda: False,
            core_lock=lambda: True,
            our_ingest_up=lambda: False,
            claim=claim,
            stop=stop,
            grace_s=0.02,
            hold_s=0.02,
            tick_s=0.01,
        )
    )
    await asyncio.sleep(0.08)
    stop.set()
    await task
    assert claimed["n"] == 0


def test_external_core_available_is_the_lock_not_ingest(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A sibling glass on :8765 must not look like ``--core``."""
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "seat"))
    lock_path = tmp_path / "arelis-core.lock"
    config = {"presence": {"lock_path": str(lock_path)}}
    assert not external_core_available(config)

    lock = PresenceLock(core_lock_path(config))
    assert lock.acquire()
    try:
        assert external_core_available(config)
    finally:
        lock.release()
    assert not external_core_available(config)


async def test_sibling_ingest_does_not_count_as_core(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "seat"))
    monkeypatch.setenv("ARELIS_INGEST_TOKEN", "test-token-xyz")
    from arelis.core.bus import EventBus
    from arelis.presence.inbound_runtime import attach_inbound
    from arelis.presence.ports import candidates

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])

    lock_path = tmp_path / "arelis-core.lock"
    config = _sms_config(port, lock_path=str(lock_path))
    bus = EventBus()
    loop = asyncio.get_running_loop()
    bus_task = asyncio.create_task(bus.run())
    runtime = attach_inbound(bus, loop, config, owned=True)
    try:
        assert runtime.ingest is not None
        assert find_my_ingest_port(config) in {port, *candidates(port)[1:]}
        assert not external_core_available(config), (
            "sibling ingest was treated as a detached core"
        )
    finally:
        await runtime.stop()
        bus.stop()
        bus_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bus_task


async def test_claim_skips_when_already_owning() -> None:
    from arelis.presence.glass_inbound import claim_orphan_ingest

    window = SimpleNamespace(
        inbound_runtime=SimpleNamespace(owned=True, ingest=object()),
    )
    bus = SimpleNamespace(publish=lambda *_a, **_k: None)
    assert not await claim_orphan_ingest(
        window, bus, asyncio.get_running_loop(), {}, hint="stay"
    )
