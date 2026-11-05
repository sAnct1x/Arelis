"""Model read tools over the Sentinel bridge: real shapes, Overseer filters, fail soft."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

_SENTINEL_ROOT = Path(__file__).resolve().parents[1] / "sentinel"
if str(_SENTINEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SENTINEL_ROOT))


def _snapshot() -> dict[str, Any]:
    """Shapes from SwarmHive.world_snapshot, SentinelUnit.to_dict, TelemetryEntry."""
    return {
        "emp": {"armed": True, "tripped": True, "tripped_at": 1.0, "reason": "operator"},
        "metrics": {"total_units": 3, "max_units": 64, "by_caste": {"warden": 2, "harvester": 1}},
        "units": [
            {
                "unit_id": "WRD-01",
                "caste": "warden",
                "tier": "mk1",
                "state": "PATROLLING",
                "current_task": "watch port 8790",
                "doctrine": "HUNTER-KILLER",
                "missions_completed": 2,
            },
            {
                "unit_id": "WRD-02",
                "caste": "warden",
                "tier": "mk1",
                "state": "EMP_DISABLED",
                "current_task": "EMP HALTED (operator)",
                "doctrine": "HUNTER-KILLER",
                "missions_completed": 0,
            },
            {
                "unit_id": "HRV-01",
                "caste": "harvester",
                "tier": "mk2",
                "state": "ENGAGED_HARVEST",
                "current_task": "arxiv exoplanets",
                "doctrine": "HUNTER-GATHERER",
                "missions_completed": 5,
            },
        ],
        "telemetry_log": [
            {
                "seq": 1,
                "iso_time": "t1",
                "level": "INFO",
                "unit_id": "HRV-01",
                "caste": "harvester",
                "phase": "fetch",
                "message": "fetched arxiv page",
                "details": {},
            },
            {
                "seq": 2,
                "iso_time": "t2",
                "level": "ALERT",
                "unit_id": "TRP-01",
                "caste": "tripwire",
                "phase": "watch",
                "message": "decoy file touched",
                "details": {"path": "bait.txt"},
            },
            {
                "seq": 3,
                "iso_time": "t3",
                "level": "SANITIZE",
                "unit_id": "SAN-01",
                "caste": "sanitizer",
                "phase": "scan",
                "message": "stripped prompt injection",
                "details": {},
            },
            {
                "seq": 4,
                "iso_time": "t4",
                "level": "INFO",
                "unit_id": "WRD-01",
                "caste": "warden",
                "phase": "ban",
                "message": "peer banned",
                "details": {"ip": "10.0.0.9"},
            },
        ],
    }


def test_read_tools_mirror_live_state_and_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    """Status, list, logs and castes read the real bridge shapes.

    Logs use the Overseer console rules (threat includes ALERT and any warden
    entry; tripwire matches by caste or TRP id). A down bridge or a refused
    token comes back as a failed result with the client's clean error, not
    an exception. Breaking any of those fails this test.
    """
    from arelis import sentinel_client
    from arelis.tools import sentinel_tool as st

    calls: list[str] = []
    reply: dict[str, Any] = {"value": None}

    def fake_command(op: str, **_kw: Any) -> dict[str, Any]:
        calls.append(op)
        if reply["value"] is not None:
            return reply["value"]
        if op == "snapshot":
            return {"ok": True, "snapshot": _snapshot()}
        if op == "list_castes":
            return {
                "ok": True,
                "castes": [
                    {
                        "caste_id": "warden",
                        "single_purpose": "defend",
                        "allowed_capabilities": ["ban_peer", "observe"],
                    },
                    {
                        "caste_id": "scout",
                        "single_purpose": "map",
                        "allowed_capabilities": ["observe"],
                    },
                ],
                "counts": {"warden": 2},
            }
        raise AssertionError(op)

    monkeypatch.setattr(sentinel_client, "command", fake_command)

    def run(tool: Any, **kw: Any):
        return asyncio.run(tool.run(**kw))

    status = run(st.SentinelStatusTool())
    assert status.ok and status.data == {
        "emp_tripped": True,
        "total_units": 3,
        "by_caste": {"warden": 2, "harvester": 1},
    }
    assert "EMP stop is ON" in status.output

    listed = run(st.SentinelListTool(), caste="warden", state="patrolling")
    assert [u["unit_id"] for u in listed.data["units"]] == ["WRD-01"]
    assert [u["unit_id"] for u in run(st.SentinelListTool(), query="exoplanet").data["units"]] == [
        "HRV-01"
    ]

    def log_ids(**kw: Any) -> list[int]:
        return [e["seq"] for e in run(st.SentinelLogsTool(), **kw).data["entries"]]

    assert log_ids() == [4, 3, 2, 1]
    assert log_ids(filter="threat") == [4, 2]
    assert log_ids(filter="tripwire") == [2]
    assert log_ids(filter="sanitize") == [3]
    assert log_ids(filter="harvest") == [1]
    assert log_ids(query="10.0.0.9") == [4]
    assert log_ids(limit=2) == [4, 3]
    assert run(st.SentinelLogsTool(), filter="bogus").ok is False

    castes = run(st.SentinelCastesTool())
    assert castes.data["castes"] == [
        {
            "caste_id": "warden",
            "built_in": True,
            "purpose": "defend",
            "capabilities": ["ban_peer", "observe"],
            "units": 2,
        },
        {
            "caste_id": "scout",
            "built_in": False,
            "purpose": "map",
            "capabilities": ["observe"],
            "units": 0,
        },
    ]
    assert set(calls) == {"snapshot", "list_castes"}

    for err in (sentinel_client.OFFLINE, sentinel_client.REFUSED):
        reply["value"] = {"ok": False, "error": err}
        for tool in (
            st.SentinelStatusTool(),
            st.SentinelListTool(),
            st.SentinelLogsTool(),
            st.SentinelCastesTool(),
        ):
            res = run(tool)
            assert res.ok is False and res.output == err


def test_sentinel_tools_are_not_registered_without_the_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Sentinel package, no Sentinel tools in the model's list."""
    from arelis.tools import sentinel_tool
    from scripts.measure_tool_schema import registry_for_profile

    names = ("sentinel_status", "sentinel_list", "sentinel_logs", "sentinel_castes")
    assert all(registry_for_profile("default").get(n) is not None for n in names)
    monkeypatch.setattr(sentinel_tool.importlib.util, "find_spec", lambda _name: None)
    reg = registry_for_profile("default")
    assert all(reg.get(n) is None for n in names)
