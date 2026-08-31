"""House watch — inbound limits, lockout, egress budget, snapshot text."""

from __future__ import annotations

import pytest

from arelis.guard import Listener, Watch, attach_watch, get_watch, reset_watch
from arelis.tools.watch import WatchTool


def test_inbound_rate_limit_trips_then_cools() -> None:
    watch = Watch()
    watch.inbound_burst = 3
    watch.inbound_window_s = 60
    assert watch.admit_inbound("192.168.1.9").ok
    assert watch.admit_inbound("192.168.1.9").ok
    assert watch.admit_inbound("192.168.1.9").ok
    denied = watch.admit_inbound("192.168.1.9")
    assert not denied.ok
    assert denied.reason == "rate"
    assert watch.admit_inbound("192.168.1.10").ok


def test_bad_tokens_lock_the_client() -> None:
    watch = Watch()
    watch.auth_fail_limit = 3
    watch.auth_lock_s = 120
    assert watch.note_auth_fail("10.0.0.4").ok
    assert watch.note_auth_fail("10.0.0.4").ok
    locked = watch.note_auth_fail("10.0.0.4")
    assert not locked.ok
    assert locked.reason == "locked"
    denied = watch.admit_inbound("10.0.0.4")
    assert not denied.ok
    assert denied.reason == "locked"
    watch.note_auth_ok("10.0.0.4")
    assert watch.admit_inbound("10.0.0.4").ok


def test_loopback_and_lan_are_not_egress() -> None:
    watch = Watch()
    watch.egress_burst = 1
    assert watch.allow_egress("127.0.0.1")
    assert watch.allow_egress("localhost")
    assert watch.allow_egress("192.168.1.20")
    assert watch.allow_egress("api.opensky-network.org")
    assert not watch.allow_egress("api.opensky-network.org")
    assert not watch.egress_open()
    snap = watch.snapshot()
    assert snap.egress_muted
    assert snap.level == "warn"
    assert "muted" in snap.detail.lower()


def test_per_host_burst_mutes_one_catalog() -> None:
    watch = Watch()
    watch.per_host_burst = 2
    watch.egress_burst = 100
    assert watch.allow_egress("earthquake.usgs.gov")
    assert watch.allow_egress("earthquake.usgs.gov")
    assert not watch.allow_egress("earthquake.usgs.gov")


def test_snapshot_lists_bound_listeners() -> None:
    watch = Watch()
    watch.register_listener(
        Listener(name="ingest", host="0.0.0.0", port=8765, bind="lan")
    )
    watch.register_listener(
        Listener(name="ipc", host="127.0.0.1", port=8766, bind="loopback")
    )
    text = watch.snapshot().as_text()
    assert "ingest" in text and ":8765" in text
    assert "ipc" in text and "loopback" in text
    assert "Quiet" in watch.snapshot().detail


def test_disabled_watch_admits_everything() -> None:
    watch = Watch()
    watch.enabled = False
    watch.inbound_burst = 1
    watch.egress_burst = 1
    assert watch.admit_inbound("1.2.3.4").ok
    assert watch.admit_inbound("1.2.3.4").ok
    assert watch.allow_egress("example.com")
    assert watch.allow_egress("example.com")
    assert watch.snapshot().level == "off"


@pytest.mark.asyncio
async def test_watch_tool_reports_the_snapshot() -> None:
    reset_watch()
    get_watch().register_listener(
        Listener(name="ingest", host="0.0.0.0", port=8765, bind="lan")
    )
    result = await WatchTool().run()
    assert result.ok
    assert "Watch:" in result.output
    assert "ingest" in result.output


def test_attach_watch_reads_config() -> None:
    from arelis.core.bus import EventBus

    reset_watch()
    bus = EventBus()
    watch = attach_watch(
        bus, {"agent": {"watch": {"enabled": True, "inbound_burst": 7}}}
    )
    assert watch.enabled
    assert watch.inbound_burst == 7
