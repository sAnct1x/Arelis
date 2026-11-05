"""Bounded hive alert policy: retask only, no firewall or model loop."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from sentinel.castes.tripwire import TripwireCaste
from sentinel.castes.warden import WardenCaste
from sentinel.core.alert_policy import AlertPolicy, POLICY_ACTIONS
from sentinel.core.hive import SwarmHive


def test_protection_copy_does_not_claim_a_firewall() -> None:
    root = Path(__file__).resolve().parents[1]
    js = (root / "sentinel/ui/overseer/telemetry_ws.js").read_text(encoding="utf-8")
    warden = (root / "sentinel/castes/warden.py").read_text(encoding="utf-8")
    assert "Banned IPs" not in js
    assert "Firewall Warden" not in warden
    assert "listed peers (records only)" in js
    assert "Socket and admission Warden" in warden
    assert "peers listed (not OS-blocked)" in warden
    assert "listed_peer" in warden


class _Gate:
    def __init__(self) -> None:
        self.current = 0
        self.max = 0
        self.starts = 0

    def enter(self) -> None:
        self.starts += 1
        self.current += 1
        if self.current > self.max:
            self.max = self.current

    def leave(self) -> None:
        self.current -= 1


async def _wait_until(pred, *, timeout: float = 4.0, label: str = "condition") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"timed out waiting for {label}")


@pytest.mark.asyncio
async def test_alert_policy_retasks_on_host_signals_and_stays_bounded(
    tmp_path: Path,
) -> None:
    """Quiet, benign write, cooldown A,B,A, pressure, exclusive host work, EMP, errors."""
    policy = AlertPolicy(cooldown_s=60.0, max_cooldown_entries=8)
    now = 5_000.0
    assert policy.should_act("flood", "A", now=now) is True
    policy.mark_seen("flood", "A", now=now)
    assert policy.should_act("flood", "B", now=now + 1) is True
    policy.mark_seen("flood", "B", now=now + 1)
    assert policy.should_act("flood", "A", now=now + 2) is False
    assert policy.should_act("not-a-signal", "A", now=now + 2) is False
    assert policy.should_act("flood", "A", now=now + 61) is True

    press = AlertPolicy(cooldown_s=60.0, max_cooldown_entries=8)
    acted = 0
    for i in range(40):
        sig = f"peer-{i}"
        if press.should_act("flood", sig, now=now + 10):
            press.mark_seen("flood", sig, now=now + 10)
            acted += 1
    assert acted == 8
    assert press.cooldown_size == 8
    assert press.should_act("flood", "peer-99", now=now + 11) is False
    assert press.should_act("flood", "peer-0", now=now + 11) is False
    assert press.should_act("flood", "peer-0", now=now + 70) is True

    tight = AlertPolicy(max_history=3)
    for i in range(8):
        tight.record({"i": i})
    assert [e["i"] for e in tight.history] == [5, 6, 7]

    hive = SwarmHive()
    wrd = hive.registry.get("warden")
    trp = hive.registry.get("tripwire")
    assert isinstance(wrd, WardenCaste)
    assert isinstance(trp, TripwireCaste)

    watch = tmp_path / "watched"
    watch.mkdir()
    watched_file = watch / "note.txt"
    watched_file.write_text("alpha\n", encoding="utf-8")
    trp.register_watch_root(watch, label="policy-watch")

    hive.deception.audit_canary_integrity = lambda: []  # type: ignore[method-assign]

    mode = {"flood": False, "block_dispatch_scan": False, "block_obs": False}
    dispatch_blocked = threading.Event()
    release_dispatch = threading.Event()
    obs_blocked = threading.Event()
    release_obs = threading.Event()
    scanners = _Gate()
    dispatches = _Gate()

    def quiet_snap(*, flood: bool) -> dict:
        flood_peers = (
            [{"remote_ip": "203.0.113.9", "connections": 24}] if flood else []
        )
        return {
            "bastions": [],
            "new_listening_ports": [],
            "flood_peers": flood_peers,
            "total_listening_tcp": 0,
            "total_established_tcp": 0,
            "wan_peers_count": 0,
            "lan_peers_count": 0,
            "loopback_peers_count": 0,
            "remote_peers_sample": [],
            "inbound_non_loopback_hits": [],
            "locked_clients": [],
            "locked_count": 0,
            "banned_peers_count": 0,
            "banned_peers": [],
            "pinned_egress_hosts_count": 0,
            "alerts": [],
        }

    def fake_scan_sockets() -> dict:
        scanners.enter()
        try:
            if mode["block_dispatch_scan"] and hive.alert_policy.dispatch_in_flight():
                dispatch_blocked.set()
                release_dispatch.wait(timeout=5)
            if mode["block_obs"] and hive.alert_policy.scan_in_flight() and not hive.alert_policy.dispatch_in_flight():
                obs_blocked.set()
                release_obs.wait(timeout=5)
            return quiet_snap(flood=mode["flood"])
        finally:
            scanners.leave()

    orig_verify = trp.verify_all

    def fake_verify_all() -> dict:
        scanners.enter()
        try:
            return orig_verify()
        finally:
            scanners.leave()

    wrd.scan_sockets = fake_scan_sockets  # type: ignore[method-assign]
    trp.verify_all = fake_verify_all  # type: ignore[method-assign]

    orig_dispatch = hive.dispatch_task

    async def counted_dispatch(
        caste: str, payload: dict, *, unit_id: str | None = None
    ) -> dict:
        dispatches.enter()
        try:
            return await orig_dispatch(caste, payload, unit_id=unit_id)
        finally:
            dispatches.leave()

    hive.dispatch_task = counted_dispatch  # type: ignore[method-assign]

    quiet = await hive.apply_alert_signals([])
    assert quiet["acted"] is False
    unknown = await hive.apply_alert_signals([("not-a-signal", "x")])
    assert unknown["acted"] is False

    first = await hive.apply_alert_signals([("flood", "10.1.0.1:9")])
    assert first["acted"] is True
    assert first["action"] == "patrol_scan"
    second = await hive.apply_alert_signals([("flood", "10.1.0.2:9")])
    assert second["acted"] is True
    again = await hive.apply_alert_signals([("flood", "10.1.0.1:9")])
    assert again["acted"] is False

    async def boom(caste: str, payload: dict, *, unit_id: str | None = None) -> dict:
        raise RuntimeError("handler failed")

    hive.dispatch_task = boom  # type: ignore[method-assign]
    err = await hive.apply_alert_signals([("exposure", ":65501 (bound)")])
    assert err["reason"] == "error" and err["ok"] is False
    assert hive.alert_policy.dispatch_in_flight() is False
    hive.dispatch_task = counted_dispatch  # type: ignore[method-assign]

    hive._telemetry_interval_s = 0.05
    await hive.start_background_loops(hz=10)
    assert hive._telemetry_task is not None
    assert hive._telemetry_task in hive.emp._active_tasks

    try:
        hist = len(hive.alert_policy.history)
        await _wait_until(lambda: scanners.starts >= 1, label="first observation or dispatch scan")
        await asyncio.sleep(0.15)
        assert len(hive.alert_policy.history) == hist

        watched_file.write_text("alpha\nbeta\n", encoding="utf-8")
        await _wait_until(
            lambda: any(
                e.get("kind") == "merkle" and e.get("acted") for e in hive.alert_policy.history
            ),
            label="merkle retask after benign write",
        )
        assert "beta" in watched_file.read_text(encoding="utf-8")
        merkle_ev = next(
            e for e in hive.alert_policy.history if e.get("kind") == "merkle" and e.get("acted")
        )
        assert merkle_ev.get("action") == "verify"
        assert merkle_ev.get("caste") == "tripwire"
        assert "heal" not in str(merkle_ev.get("action"))

        mode["flood"] = True
        mode["block_dispatch_scan"] = True
        await _wait_until(dispatch_blocked.is_set, label="dispatch scan blocked")
        starts_while_held = scanners.starts
        await asyncio.sleep(0.2)
        assert hive.alert_policy.dispatch_in_flight() is True
        assert hive.alert_policy.scan_in_flight() is False
        assert hive.alert_policy.begin_scan() is False
        assert scanners.starts == starts_while_held
        assert scanners.max == 1
        assert dispatches.max == 1
        mode["block_dispatch_scan"] = False
        release_dispatch.set()
        await _wait_until(
            lambda: hive.alert_policy.dispatch_in_flight() is False
            and hive.alert_policy.scan_in_flight() is False,
            label="dispatch slot cleared",
        )

        mode["flood"] = False
        mode["block_obs"] = True
        await _wait_until(obs_blocked.is_set, label="observation scan blocked")
        obs_starts = scanners.starts
        assert hive.alert_policy.scan_in_flight() is True
        assert hive.alert_policy.dispatch_in_flight() is False
        assert hive.alert_policy.begin_scan() is False
        assert hive.alert_policy.begin_dispatch() is False
        busy = await hive.apply_alert_signals([("exposure", ":1 (held-scan)")])
        assert busy.get("reason") == "dispatch_busy" and busy.get("acted") is False
        hive._telemetry_task.cancel()
        await asyncio.sleep(0.1)
        assert obs_blocked.is_set()
        assert scanners.starts == obs_starts
        assert hive.alert_policy.scan_in_flight() is True
        mode["block_obs"] = False
        release_obs.set()
        await _wait_until(
            lambda: hive.alert_policy.scan_in_flight() is False, label="worker released scan slot"
        )

        await hive.stop_background_loops()
        hive._telemetry_interval_s = 0.05
        await hive.start_background_loops(hz=10)
        assert hive._telemetry_task is not None
        assert hive._telemetry_task in hive.emp._active_tasks

        late: list[str] = []
        entered = asyncio.Event()
        orig_exec = wrd.execute

        async def slow_execute(unit, payload, **kwargs):
            entered.set()
            await asyncio.sleep(30)
            late.append("late-handler-mutation")
            return await orig_exec(unit, payload, **kwargs)

        wrd.execute = slow_execute  # type: ignore[method-assign]
        mode["flood"] = True
        await _wait_until(entered.is_set, label="EMP-target dispatch entered")
        await hive.emp.trigger_emp(hive.units, reason="test halt")
        await asyncio.sleep(0.05)
        assert late == []
        assert hive.emp.is_tripped
        assert hive._telemetry_task.done()
        blocked = await hive.apply_alert_signals([("new_ports", ":9999")])
        assert blocked["reason"] == "emp" and blocked["acted"] is False
    finally:
        release_dispatch.set()
        release_obs.set()
        mode["block_dispatch_scan"] = False
        mode["block_obs"] = False
        await hive.stop_background_loops()


    assert POLICY_ACTIONS["exposure"][1]["action"] == "patrol_scan"
    assert POLICY_ACTIONS["canary"][1]["action"] == "verify"
    assert scanners.max == 1
    assert dispatches.max == 1
