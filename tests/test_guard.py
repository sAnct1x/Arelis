"""House watch — inbound limits, lockout, egress budget, snapshot text."""

from __future__ import annotations

import logging

from arelis.guard import Watch


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


def test_inbound_flood_warning_logs_once_per_client_per_minute(
    caplog, monkeypatch
) -> None:
    """A retry loop must not write one warning per refused request."""
    clock = {"now": 1_000.0}
    monkeypatch.setattr("arelis.guard.watch._now", lambda: clock["now"])
    watch = Watch()
    watch.inbound_burst = 3
    watch.inbound_window_s = 10.0
    host = "192.168.1.9"
    other = "192.168.1.10"
    for _ in range(3):
        assert watch.admit_inbound(host).ok

    with caplog.at_level(logging.WARNING, logger="arelis.watch"):
        denied = [watch.admit_inbound(host) for _ in range(18)]
    assert all(not item.ok and item.reason == "rate" for item in denied)
    floods = [
        rec.getMessage()
        for rec in caplog.records
        if rec.name == "arelis.watch" and "inbound flood" in rec.getMessage()
    ]
    assert len(floods) == 1
    assert host in floods[0]
    assert "suppressed" not in floods[0]

    for _ in range(3):
        assert watch.admit_inbound(other).ok
    with caplog.at_level(logging.WARNING, logger="arelis.watch"):
        other_denied = watch.admit_inbound(other)
    assert not other_denied.ok
    assert other_denied.reason == "rate"
    floods = [
        rec.getMessage()
        for rec in caplog.records
        if rec.name == "arelis.watch" and "inbound flood" in rec.getMessage()
    ]
    assert len(floods) == 2
    assert any(other in line for line in floods)

    clock["now"] += 61.0
    caplog.clear()
    for _ in range(3):
        assert watch.admit_inbound(host).ok
    with caplog.at_level(logging.WARNING, logger="arelis.watch"):
        later = watch.admit_inbound(host)
    assert not later.ok
    assert later.reason == "rate"
    floods = [
        rec.getMessage()
        for rec in caplog.records
        if rec.name == "arelis.watch" and "inbound flood" in rec.getMessage()
    ]
    assert len(floods) == 1
    assert "17" in floods[0]
    assert "suppressed" in floods[0]


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


