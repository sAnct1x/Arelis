"""Tests for TelemetryLogger (disk JSONL + text logging) and SimulationDirector scenarios."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sentinel.core.hive import SwarmHive
from sentinel.core.simulator import SCENARIO_CATALOG
from sentinel.core.telemetry import TelemetryLogger


def test_telemetry_logger_writes_disk_and_ring(tmp_path: Path) -> None:
    logger = TelemetryLogger(log_dir=tmp_path)
    entry = logger.record(
        "WARDEN",
        unit_id="SNT-WRD-001",
        caste="warden",
        phase="PERIMETER_BLOCK",
        message="Blocked inbound brute-force probe on :8765",
        details={"client_ip": "192.168.1.240", "port": 8765},
    )
    assert entry.seq == 1
    assert entry.level == "WARDEN"
    assert len(logger.recent(10)) >= 1
    assert logger.jsonl_path.is_file()
    assert logger.text_path.is_file()
    assert "192.168.1.240" in logger.jsonl_path.read_text(encoding="utf-8")
    assert "SNT-WRD-001" in logger.text_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_simulation_director_scenarios_and_world_snapshot() -> None:
    hive = SwarmHive()
    snap0 = hive.world_snapshot()
    assert "telemetry_log" in snap0
    assert "scenarios" in snap0
    assert len(snap0["scenarios"]) == len(SCENARIO_CATALOG)

    # Verify real host hardware/network/disk telemetry is populated
    ht = snap0.get("host_telemetry") or {}
    assert ht.get("ram_total_gb", 0) > 0
    assert ht.get("merkle_files_hashed", 0) > 0
    assert isinstance(ht.get("merkle_roots"), dict)

    # Verify both real Bastion socket nodes and real BLAKE2b Merkle Anchor nodes exist in 3D space
    node_ids = {n["node_id"] for n in snap0["nodes"]}
    assert "bastion-port-8790" in node_ids
    assert "merkle-root-1" in node_ids

    # Trigger a scenario and verify active banner / FX / telemetry emission
    res = await hive.simulator.run_scenario("injection_attack")
    assert res["ok"] is False
    assert "Scripted" in res["error"]

    await asyncio.sleep(0.15)
    snap1 = hive.world_snapshot()
    assert len(snap1["telemetry_log"]) == len(snap0["telemetry_log"])
    assert len(snap1["fx_events"]) == 0
    assert snap1["active_banner"] is None
    await hive.trigger_emp("Test cleanup halt")
