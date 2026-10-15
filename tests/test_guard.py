"""House watch — inbound limits, lockout, egress budget, snapshot text."""

from __future__ import annotations

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


