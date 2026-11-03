"""Glass inbound: a sibling window is not a core, and attach has a way home."""

from __future__ import annotations

import asyncio
import socket

import pytest

from arelis.presence.glass_inbound import (
    ATTACH_GRACE_S,
    TAKEOVER_HOLD_S,
    should_take_ingest,
    watch_orphan_ingest,
)
from arelis.presence.lock import (
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




def test_launch_ingest_scan_runs_off_the_ui_thread(monkeypatch) -> None:
    """#520h: the 'is our ingest up?' urllib scan froze the window 5 s at launch."""
    import threading

    from arelis.presence import glass_inbound
    from arelis.presence.inbound_runtime import InboundRuntime

    release = threading.Event()
    seen: dict[str, object] = {}

    def slow_attach(*_a, **_k):
        seen["thread"] = threading.current_thread()
        release.wait(5)
        return InboundRuntime(owned=True)

    monkeypatch.setattr(glass_inbound, "attach_inbound", slow_attach)
    monkeypatch.setattr("arelis.ui.mobile_host.bind_mobile_hub", lambda _w: None)
    queued: list = []

    class Window:
        _disposed = False
        inbound_runtime = None

        class _ui_call:  # noqa: N801  (the window's Signal(object))
            emit = staticmethod(queued.append)

    window = Window()
    from arelis.ui import launch

    worker = launch.install_owned_inbound_off_ui(window, object(), None, {}, hint="")
    assert window.inbound_runtime is None  # returned while the scan still blocks
    release.set()
    worker.join(5)
    assert seen["thread"] is not threading.main_thread()
    assert len(queued) == 1
    queued[0]()  # the UI thread's turn
    assert window.inbound_runtime is not None and window.inbound_runtime.owned
