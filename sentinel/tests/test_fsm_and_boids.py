"""Tests for SentinelUnit FSM, Dynamic Spawning/Scaling/Upgrading, 3D Boids, and EMP Kill-Switch."""

from __future__ import annotations

import asyncio

import pytest

from sentinel.castes.base import PermissionViolationError
from sentinel.core.fsm import SentinelState
from sentinel.core.hive import SwarmHive


def test_hive_spawns_initial_castes_and_scales_dynamically() -> None:
    hive = SwarmHive()
    snap = hive.world_snapshot()
    assert snap["metrics"]["total_units"] == 22
    assert snap["metrics"]["by_caste"] == {
        "harvester": 8,
        "warden": 6,
        "sanitizer": 4,
        "tripwire": 4,
    }

    # Scale Harvesters up to 12
    scale_up = hive.scale_caste("harvester", 12, tier="mk2")
    assert scale_up["count"] == 12
    assert len(scale_up["spawned"]) == 4

    # Verify newly spawned units are mk2 (10 tentacles)
    new_uid = scale_up["spawned"][0]
    assert hive.units[new_uid].tier == "mk2"
    assert hive.units[new_uid].spec.tentacles == 10

    # Upgrade entire Harvester caste to mk3 (12 tentacles)
    upgraded = hive.upgrade_caste("harvester", "mk3", version="2.0.0")
    assert len(upgraded) == 12
    assert hive.units[new_uid].spec.tentacles == 12
    assert hive.units[new_uid].version == "2.0.0"

    # Scale Harvesters down to 6
    scale_down = hive.scale_caste("harvester", 6)
    assert scale_down["count"] == 6
    assert len(scale_down["retired"]) == 6


def test_narrow_caste_capability_sandbox_enforcement() -> None:
    hive = SwarmHive()
    sanitizer = hive.registry.get("sanitizer")
    # Sanitizer is allowed 'sanitize_text', but strictly forbidden from 'fetch_url'
    sanitizer.descriptor.assert_capability("sanitize_text")
    with pytest.raises(PermissionViolationError):
        sanitizer.descriptor.assert_capability("fetch_url")


def test_3d_boids_kinematics_separation_and_orbit() -> None:
    hive = SwarmHive()
    u1 = hive.units["SNT-HRV-001"]
    u2 = hive.units["SNT-HRV-002"]
    # Place two units almost on top of each other to verify separation force pushes them apart
    u1.position = [15.0, 0.0, 0.0]
    u2.position = [15.1, 0.0, 0.0]
    initial_dist = abs(u1.position[0] - u2.position[0])

    for _ in range(15):
        hive.step_world(1.0 / 60.0)

    final_dist = (
        (u1.position[0] - u2.position[0]) ** 2
        + (u1.position[1] - u2.position[1]) ** 2
        + (u1.position[2] - u2.position[2]) ** 2
    ) ** 0.5
    assert final_dist > initial_dist


@pytest.mark.asyncio
async def test_hardware_emp_kill_switch_instant_halt_and_restore() -> None:
    hive = SwarmHive()

    # Launch a long-running task tracked by EMP
    async def _slow_task() -> None:
        await asyncio.sleep(10.0)

    t = hive.emp.track_task(asyncio.create_task(_slow_task()))
    emp_res = await hive.trigger_emp(reason="Unit Test Emergency Stop")

    assert emp_res["ok"] is True
    assert emp_res["tripped"] is True
    assert emp_res["tasks_cancelled"] >= 1
    assert emp_res["halt_latency_ms"] < 50.0
    assert t.cancelled() or t.done()
    assert all(u.state == SentinelState.EMP_DISABLED for u in hive.units.values())

    # Dispatching while EMP is tripped must refuse
    blocked = await hive.dispatch_task("warden", {"action": "patrol_scan"})
    assert blocked["ok"] is False

    # Restore swarm
    restored = await hive.restore_from_emp()
    assert restored["tripped"] is False
    assert all(u.state == SentinelState.PATROLLING for u in hive.units.values())


def test_matrix_doctrines_and_swarm_pack_encirclement() -> None:
    hive = SwarmHive()
    hrv = hive.units["SNT-HRV-001"]
    trp = hive.units["SNT-TRP-001"]
    wrd = hive.units["SNT-WRD-001"]
    san = hive.units["SNT-SAN-001"]

    assert hrv.doctrine == "HUNTER-GATHERER"
    assert trp.doctrine == "HUNTER-SEEKER"
    assert san.doctrine == "HUNTER-KILLER"

    # Recruit a 4-Sentinel Hunter-Killer Strike Pack around SNT-WRD-001
    wingmen = hive._recruit_pack(wrd, max_wingmen=3)
    assert len(wingmen) == 3
    assert wrd.pack_role == "ALPHA"
    assert wrd.pack_size == 4
    assert all(w.pack_role == "WINGMAN" and w.pack_id == wrd.pack_id for w in wingmen)

    # Transition Alpha to ENGAGED_DEFENSE on a target coordinate and step world
    wrd.transition(
        SentinelState.ENGAGED_DEFENSE,
        task="Neutralizing hostile payload",
        target_position=[20.0, 0.0, 20.0],
        laser_active=True,
        laser_kind="defense",
    )
    assert wrd.doctrine == "HUNTER-KILLER"

    hive.step_world(1.0 / 60.0)
    # Wingmen must synchronize with Alpha's engagement state, target, laser, and doctrine
    for w in wingmen:
        assert w.state == SentinelState.ENGAGED_DEFENSE
        assert w.laser_active is True
        assert w.doctrine == "HUNTER-KILLER"
        assert w.target_position == [20.0, 0.0, 20.0]

    # Release pack and verify all wingmen return to PATROLLING SOLO state
    hive._release_pack(wrd.pack_id)
    assert all(w.pack_role == "SOLO" and w.state == SentinelState.PATROLLING for w in wingmen)
