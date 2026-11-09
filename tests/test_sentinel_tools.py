"""Model read tools over the Sentinel bridge: real shapes, Overseer filters, fail soft."""

from __future__ import annotations

import asyncio
import sys
import threading
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
            {
                "seq": 5,
                "iso_time": "t5",
                "level": "INFO",
                "unit_id": "TRP-07",
                "caste": "",
                "phase": "watch",
                "message": "decoy hash checked",
                "details": {},
            },
        ],
    }


def test_read_tools_mirror_live_state_and_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    """Status, list, logs and castes read the real bridge shapes.

    Logs use the Overseer console rules (threat includes ALERT and any warden
    entry; tripwire matches by caste or, with no caste, by TRP id). A down bridge or a refused
    token comes back as a failed result with the client's clean error, not
    an exception. Breaking any of those fails this test.
    """
    from arelis import sentinel_client
    from arelis.tools import sentinel_tool as st

    calls: list[str] = []
    reply: dict[str, Any] = {"value": None}
    # Delayed bridge: when set, the reply waits until a sibling task on the
    # caller's loop has run. A blocked loop never runs it; the bounded wait
    # is only a deadlock guard and is recorded as a failure.
    gate: dict[str, Any] = {"release": None, "sibling_first": []}

    def fake_command(op: str, **_kw: Any) -> dict[str, Any]:
        calls.append(op)
        if gate["release"] is not None:
            gate["sibling_first"].append(gate["release"].wait(timeout=2.0))
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

    assert log_ids() == [5, 4, 3, 2, 1]
    assert log_ids(filter="threat") == [4, 2]
    assert log_ids(filter="tripwire") == [5, 2]
    assert log_ids(filter="sanitize") == [3]
    assert log_ids(filter="harvest") == [1]
    assert log_ids(query="10.0.0.9") == [4]
    assert log_ids(limit=2) == [5, 4]
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

    reply["value"] = None

    async def gated(tool: Any) -> Any:
        release = threading.Event()
        gate["release"] = release

        async def sibling() -> None:
            release.set()

        # Tasks start in creation order: the tool reaches the bridge call
        # first, and the sibling only runs if that call yields the loop.
        result, _ = await asyncio.gather(tool.run(), sibling())
        return result

    for tool in (
        st.SentinelStatusTool(),
        st.SentinelListTool(),
        st.SentinelLogsTool(),
        st.SentinelCastesTool(),
    ):
        gate["sibling_first"].clear()
        res = asyncio.run(gated(tool))
        assert res.ok is True, tool.name
        assert gate["sibling_first"] == [True], tool.name
    gate["release"] = None


def test_sentinel_tools_are_not_registered_without_the_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Sentinel package, no Sentinel tools in the model's list."""
    from arelis.tools import sentinel_tool
    from scripts.measure_tool_schema import registry_for_profile

    names = (
        "sentinel_status",
        "sentinel_list",
        "sentinel_logs",
        "sentinel_castes",
        "sentinel_command",
        "sentinel_emp",
    )
    assert all(registry_for_profile("default").get(n) is not None for n in names)
    monkeypatch.setattr(sentinel_tool.importlib.util, "find_spec", lambda _name: None)
    reg = registry_for_profile("default")
    assert all(reg.get(n) is None for n in names)


def test_command_and_emp_send_the_right_ops_and_refuse_bad_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sentinel_command (deploy, stop, retask, mission) and sentinel_emp.

    Each action sends its bridge op with checked arguments. Count is 1..50,
    unknown castes, arguments from another action and unsupported or
    unlisted capabilities are refused before any control op. Every supported
    capability maps to the verb its handler branches on. Mission returns an
    accepted reference, never a finished result. There is no restore tool,
    EMP never waits on a card while command keeps the normal write card, and
    every bridge call leaves the caller's loop free.
    """
    from arelis import sentinel_client
    from arelis.tools import policy
    from arelis.tools import sentinel_tool as st

    castes = [
        {
            "caste_id": "harvester",
            "allowed_capabilities": [
                "fetch_url",
                "query_arxiv",
                "query_horizons",
                "query_wikipedia",
                "write_harvest_report",
            ],
        },
        {
            "caste_id": "warden",
            "allowed_capabilities": [
                "scan_sockets",
                "admit_inbound",
                "note_auth_fail",
                "verify_egress",
                "intercept_threat",
                "ban_peer",
            ],
        },
        {
            "caste_id": "tripwire",
            "allowed_capabilities": [
                "build_baseline",
                "verify_integrity",
                "register_watch_root",
                "heal_root",
            ],
        },
        {
            "caste_id": "sanitizer",
            "allowed_capabilities": [
                "sanitize_text",
                "sanitize_html",
                "verify_binary",
                "inspect_archive",
                "quarantine_payload",
                "immunize_hash",
            ],
        },
        {"caste_id": "scout", "allowed_capabilities": ["query_arxiv"]},
        {
            "caste_id": "stalker",
            "allowed_capabilities": [
                "process:list",
                "process:inspect_pid",
                "process:detect_rogue",
                "process:audit_memory",
            ],
        },
    ]
    sent: list[tuple[str, dict[str, Any]]] = []
    gate: dict[str, Any] = {"release": None, "sibling_first": []}

    def fake_command(op: str, **kw: Any) -> dict[str, Any]:
        if gate["release"] is not None:
            gate["sibling_first"].append(gate["release"].wait(timeout=2.0))
        sent.append((op, kw))
        if op == "list_castes":
            return {"ok": True, "castes": castes}
        if op == "spawn_units":
            return {
                "ok": True,
                "spawned": [{"unit_id": f"W{i}"} for i in range(min(kw["count"], 2))],
            }
        if op == "retire_unit":
            return {"ok": kw["unit_id"] == "W0", "retired": kw["unit_id"] == "W0"}
        if op == "dispatch_task":
            return {"ok": True, "result": {"ok": True}}
        if op == "start_harvest_mission":
            return {"ok": True, "mission_ref": "REQ-0001", "status": "running", "accepted": True}
        return {"ok": True}

    monkeypatch.setattr(sentinel_client, "command", fake_command)
    cmd = st.SentinelCommandTool()

    def run(tool: Any, **kw: Any):
        sent.clear()
        return asyncio.run(tool.run(**kw))

    def control_ops() -> list[str]:
        return [op for op, _ in sent if op != "list_castes"]

    res = run(cmd, action="deploy", caste="Warden", count=2)
    assert res.ok and sent[-1] == ("spawn_units", {"caste": "warden", "count": 2})
    assert run(cmd, action="deploy", caste="warden", count=3).output.endswith("unit limit.")
    for bad in (
        {"caste": "warden", "count": 51},
        {"caste": "warden", "count": 0},
        {"caste": "warden", "count": True},
        {"caste": "ghost"},
        {"caste": "warden", "question": "x"},
    ):
        assert run(cmd, action="deploy", **bad).ok is False and control_ops() == []
    assert run(cmd, action="launch").ok is False and sent == []

    assert run(cmd, action="stop", unit_id="W0").ok and sent == [("retire_unit", {"unit_id": "W0"})]
    assert run(cmd, action="stop", unit_id="W9").ok is False
    assert run(cmd, action="stop", caste="warden").ok
    assert sent[-1] == ("scale_caste", {"caste": "warden", "target_count": 0})
    assert run(cmd, action="stop").ok is False and sent == []
    assert run(cmd, action="stop", unit_id="W0", caste="warden").ok is False and sent == []

    expected = {
        ("harvester", "fetch_url", "https://example.org"): {
            "action": "url",
            "url": "https://example.org",
        },
        ("harvester", "query_arxiv", "q"): {"action": "arxiv", "query": "q"},
        ("harvester", "query_horizons", "Mars"): {"action": "horizons", "target": "Mars"},
        ("harvester", "query_wikipedia", "q"): {"action": "wikipedia", "query": "q"},
        ("warden", "scan_sockets", ""): {"action": "patrol_scan"},
        ("warden", "verify_egress", "https://example.org"): {
            "action": "verify_egress",
            "url": "https://example.org",
        },
        ("warden", "intercept_threat", "10.0.0.9"): {
            "action": "intercept",
            "source_ip": "10.0.0.9",
        },
        ("tripwire", "register_watch_root", "C:/x"): {"action": "register", "path": "C:/x"},
        ("tripwire", "verify_integrity", ""): {"action": "verify"},
        ("sanitizer", "sanitize_text", "hi"): {
            "capability": "sanitize_text",
            "is_html": False,
            "text": "hi",
        },
        ("sanitizer", "sanitize_html", "<b>"): {
            "capability": "sanitize_html",
            "is_html": True,
            "text": "<b>",
        },
        ("sanitizer", "inspect_archive", "zz"): {"capability": "inspect_archive", "data": "zz"},
        ("stalker", "process:list", ""): {"capability": "process:list"},
        ("stalker", "process:inspect_pid", "4242"): {
            "capability": "process:inspect_pid",
            "pid": "4242",
        },
        ("stalker", "process:detect_rogue", ""): {"capability": "process:detect_rogue"},
        ("stalker", "process:audit_memory", ""): {"capability": "process:audit_memory"},
    }
    assert set(st.RETASK_MAP) == {(c, k) for c, k, _ in expected}
    for (caste, cap, target), payload in expected.items():
        res = run(cmd, action="retask", caste=caste, capability=cap, target=target)
        assert res.ok, (caste, cap, res.output)
        assert sent[-1] == ("dispatch_task", {"caste": caste, "payload": payload}), (caste, cap)

    for caste, cap, kw in (
        ("harvester", "write_harvest_report", {}),  # listed, no handler branch
        ("warden", "ban_peer", {"target": "1.2.3.4"}),
        ("sanitizer", "verify_binary", {"target": "x"}),
        ("tripwire", "heal_root", {}),
        ("warden", "query_arxiv", {"target": "q"}),  # another caste's capability
        ("scout", "query_arxiv", {"target": "q"}),  # listed but no mapping for a custom caste
        ("harvester", "query_arxiv", {}),  # target required
        ("warden", "scan_sockets", {"target": "x"}),  # takes no target
        ("harvester", "query_arxiv", {"target": "q", "payload": {"method": "POST"}}),
        ("harvester", "query_arxiv", {"target": "q", "payload": {"action": "url"}}),
        ("stalker", "process:kill", {}),
        ("stalker", "process:list", {"target": "1"}),
        ("stalker", "process:inspect_pid", {}),
        ("stalker", "process:list", {"payload": {"method": "POST"}}),
    ):
        res = run(cmd, action="retask", caste=caste, capability=cap, **kw)
        assert res.ok is False and "dispatch_task" not in control_ops(), (caste, cap)
    castes[1]["allowed_capabilities"].remove("intercept_threat")  # caste narrowed
    res = run(
        cmd, action="retask", caste="warden", capability="intercept_threat", target="10.0.0.9"
    )
    assert res.ok is False and "dispatch_task" not in control_ops()
    res = run(
        cmd,
        action="retask",
        caste="harvester",
        capability="query_arxiv",
        target="q",
        payload={"max_results": 3},
    )
    assert sent[-1][1]["payload"] == {"action": "arxiv", "query": "q", "max_results": 3}
    res = run(
        cmd,
        action="retask",
        caste="stalker",
        capability="process:list",
        payload={"limit": 5},
    )
    assert res.ok and sent[-1] == (
        "dispatch_task",
        {"caste": "stalker", "payload": {"limit": 5, "capability": "process:list"}},
    )
    res = run(cmd, action="deploy", caste="stalker", count=1)
    assert res.ok and sent[-1] == ("spawn_units", {"caste": "stalker", "count": 1})

    res = run(cmd, action="mission", question="exoplanet transits")
    assert res.ok and res.data["mission_ref"] == "REQ-0001" and "not finished" in res.output
    assert sent == [
        (
            "start_harvest_mission",
            {
                "question": "exoplanet transits",
                "targets": [
                    {"action": "arxiv", "query": "exoplanet transits", "max_results": 4},
                    {"action": "wikipedia", "query": "exoplanet transits"},
                ],
            },
        )
    ]

    assert run(st.SentinelEmpTool()).ok and sent == [
        ("emp_halt", {"reason": "Arelis emergency stop"})
    ]
    assert policy.confirm_toggle("sentinel_emp", {}, risk="write") == "none"
    assert policy.confirm_toggle("sentinel_command", {"action": "stop"}, risk="write") == "writes"
    assert not any("restore" in t.name for t in st.sentinel_tools())

    # Real registry risk (write) through needs_confirm. This records current
    # card and voice behavior; it does not endorse leaving voice unasked
    # commands free. ask_is_grant still skips the ordinary write card when
    # the user's ask named the tool, and does not skip it when the switch
    # is off.
    from arelis.tools.base import ToolRegistry
    from arelis.tools.policy import confirm_mode, set_confirm_mode

    reg = ToolRegistry()
    for tool in st.sentinel_tools():
        if tool.name in {"sentinel_command", "sentinel_emp"}:
            reg.register(tool)
    assert reg.get("sentinel_command").risk == "write"
    assert reg.get("sentinel_emp").risk == "write"
    args = {"action": "deploy", "caste": "warden", "count": 1}
    previous = confirm_mode()
    try:
        set_confirm_mode("card")
        assert reg.needs_confirm("sentinel_command", args, asked=False) is True
        assert reg.needs_confirm("sentinel_command", args, asked=True, ask_is_grant=True) is False
        assert reg.needs_confirm("sentinel_command", args, asked=True, ask_is_grant=False) is True
        assert reg.needs_confirm("sentinel_emp", {}, asked=False) is False
        assert reg.needs_confirm("sentinel_emp", {}, asked=True) is False
        set_confirm_mode("voice")
        assert reg.needs_confirm("sentinel_command", args, asked=False) is False
        assert reg.needs_confirm("sentinel_command", args, asked=True) is False
        assert reg.needs_confirm("sentinel_emp", {}, asked=False) is False
        assert reg.needs_confirm("sentinel_emp", {}, asked=True) is False
    finally:
        set_confirm_mode(previous)

    async def gated(tool: Any, **kw: Any) -> Any:
        release = threading.Event()
        gate["release"] = release

        async def sibling() -> None:
            release.set()

        result, _ = await asyncio.gather(tool.run(**kw), sibling())
        return result

    for tool, kw in (
        (cmd, {"action": "deploy", "caste": "warden"}),
        (cmd, {"action": "stop", "unit_id": "W0"}),
        (cmd, {"action": "retask", "caste": "warden", "capability": "scan_sockets"}),
        (cmd, {"action": "mission", "question": "q"}),
        (st.SentinelEmpTool(), {}),
    ):
        gate["sibling_first"].clear()
        assert asyncio.run(gated(tool, **kw)).ok is True, kw
        assert gate["sibling_first"] and all(gate["sibling_first"]), kw
    gate["release"] = None


def test_start_harvest_mission_answers_at_once_and_records_the_outcome() -> None:
    """The bridge starts the real harvest swarm in the background.

    It refuses under EMP, answers before the mission ends, tracks the task
    for EMP cancellation, and records done or failed (with the reason) in
    mission_status and the telemetry log.
    """
    from types import SimpleNamespace

    from sentinel.bridge.server import SentinelBridgeServer

    async def scenario() -> None:
        release = asyncio.Event()
        outcomes: list[dict[str, Any]] = [
            {"ok": True, "mission_id": "MSN-0007"},
            {"ok": False, "parked": True, "error": "queued for operator sign-off"},
        ]
        tracked: list[asyncio.Task[Any]] = []
        logged: list[tuple[str, str]] = []

        async def swarm(question: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
            await release.wait()
            return outcomes.pop(0)

        def track(t: asyncio.Task[Any]) -> asyncio.Task[Any]:
            tracked.append(t)
            return t

        hive = SimpleNamespace(
            emp=SimpleNamespace(is_tripped=False, track_task=track),
            dispatch_harvest_swarm=swarm,
            telemetry=SimpleNamespace(
                record=lambda level, **kw: logged.append((level, kw["message"]))
            ),
        )
        server = SentinelBridgeServer(hive, token="t" * 40)
        targets = [{"action": "arxiv", "query": "q"}]
        ok, data, _ = server._start_harvest_mission({"question": "q", "targets": targets})
        assert ok and data == {"mission_ref": "REQ-0001", "status": "running", "accepted": True}
        assert server._missions["REQ-0001"]["status"] == "running" and len(tracked) == 1
        server._start_harvest_mission({"question": "q2", "targets": targets})
        release.set()
        await asyncio.gather(*tracked)
        await asyncio.sleep(0)
        assert server._missions["REQ-0001"]["status"] == "done"
        assert server._missions["REQ-0001"]["mission_id"] == "MSN-0007"
        assert server._missions["REQ-0002"]["status"] == "failed"
        assert "sign-off" in server._missions["REQ-0002"]["error"]
        assert [lvl for lvl, _ in logged] == ["HARVEST", "ALERT"]

        release.clear()
        outcomes.append({"ok": True})
        server._start_harvest_mission({"question": "q3", "targets": targets})
        tracked[-1].cancel()
        await asyncio.gather(*tracked, return_exceptions=True)
        await asyncio.sleep(0)
        rec3 = server._missions["REQ-0003"]
        assert rec3["status"] == "failed" and rec3["question"] == "q3"
        assert rec3["error"] == "cancelled" and "finished_at" in rec3

        hive.emp.is_tripped = True
        before = len(tracked)
        ok, _, err = server._start_harvest_mission({"question": "q", "targets": targets})
        assert ok is False and "EMP" in err and len(tracked) == before

        # Admission, target cap, recovery and bounded history (same test).
        from sentinel.bridge.server import (
            MAX_IN_FLIGHT_MISSIONS,
            MAX_MISSION_HISTORY,
            MAX_MISSION_TARGETS,
        )

        release2 = asyncio.Event()
        tracked2: list[asyncio.Task[Any]] = []
        results2: list[dict[str, Any]] = []

        async def swarm2(question: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
            await release2.wait()
            return results2.pop(0) if results2 else {"ok": True}

        def track2(t: asyncio.Task[Any]) -> asyncio.Task[Any]:
            tracked2.append(t)
            return t

        hive2 = SimpleNamespace(
            emp=SimpleNamespace(is_tripped=False, track_task=track2),
            dispatch_harvest_swarm=swarm2,
            telemetry=SimpleNamespace(record=lambda level, **kw: None),
        )
        server2 = SentinelBridgeServer(hive2, token="t" * 40)
        before_n, before_t = len(server2._missions), len(tracked2)
        for bad in (
            {"question": "q", "targets": 3},
            {"question": "q", "targets": ["x"]},
            {"question": "q", "targets": [{}] * (MAX_MISSION_TARGETS + 1)},
            {"question": "q", "targets": []},
        ):
            ok, _, err = server2._start_harvest_mission(bad)
            assert ok is False and err
        assert len(server2._missions) == before_n and len(tracked2) == before_t
        assert server2._mission_seq == 0

        accepted = 0
        refused = 0
        for i in range(100):
            ok, _, _ = server2._start_harvest_mission({"question": f"held-{i}", "targets": targets})
            if ok:
                accepted += 1
            else:
                refused += 1
        assert accepted == MAX_IN_FLIGHT_MISSIONS and refused == 100 - MAX_IN_FLIGHT_MISSIONS
        assert len(tracked2) == MAX_IN_FLIGHT_MISSIONS
        assert server2._running_mission_count() == MAX_IN_FLIGHT_MISSIONS
        assert len(server2._missions) == MAX_IN_FLIGHT_MISSIONS

        results2.extend({"ok": True} for _ in range(MAX_IN_FLIGHT_MISSIONS))
        release2.set()
        await asyncio.gather(*tracked2)
        await asyncio.sleep(0)
        assert server2._running_mission_count() == 0

        # Recovery after success.
        release2.clear()
        ok, _, _ = server2._start_harvest_mission({"question": "after-ok", "targets": targets})
        assert ok is True
        results2.append({"ok": True})
        release2.set()
        await asyncio.gather(*tracked2)
        await asyncio.sleep(0)
        assert server2._running_mission_count() == 0

        # Recovery after failure.
        release2.clear()
        ok, _, _ = server2._start_harvest_mission({"question": "after-fail", "targets": targets})
        assert ok is True
        results2.append({"ok": False, "error": "queued for operator sign-off"})
        release2.set()
        await asyncio.gather(*tracked2)
        await asyncio.sleep(0)
        assert server2._running_mission_count() == 0
        assert any(
            rec.get("error") and "sign-off" in rec["error"] for rec in server2._missions.values()
        )

        # Recovery after EMP-style cancellation.
        release2.clear()
        ok, _, _ = server2._start_harvest_mission({"question": "after-emp", "targets": targets})
        assert ok is True
        tracked2[-1].cancel()
        await asyncio.gather(*tracked2, return_exceptions=True)
        await asyncio.sleep(0)
        assert server2._running_mission_count() == 0
        ok, _, _ = server2._start_harvest_mission({"question": "after-cancel", "targets": targets})
        assert ok is True
        tracked2[-1].cancel()
        await asyncio.gather(*tracked2, return_exceptions=True)
        await asyncio.sleep(0)

        # History pressure: keep one active, finish more than the cap.
        release2.clear()
        ok, data, _ = server2._start_harvest_mission(
            {"question": "keep-active", "targets": targets}
        )
        assert ok is True
        active_ref = data["mission_ref"]
        immediate: list[asyncio.Task[Any]] = []

        async def swarm_now(question: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
            return {"ok": True}

        def track_now(t: asyncio.Task[Any]) -> asyncio.Task[Any]:
            immediate.append(t)
            return t

        hive2.dispatch_harvest_swarm = swarm_now
        hive2.emp.track_task = track_now
        for i in range(MAX_MISSION_HISTORY + 20):
            ok, _, _ = server2._start_harvest_mission(
                {"question": f"flood-{i}", "targets": targets}
            )
            assert ok is True
            await asyncio.gather(*immediate)
            immediate.clear()
        await asyncio.sleep(0)
        finished = [rec for rec in server2._missions.values() if rec.get("status") != "running"]
        running = [rec for rec in server2._missions.values() if rec.get("status") == "running"]
        assert len(finished) == MAX_MISSION_HISTORY
        assert len(running) == 1 and active_ref in server2._missions
        assert server2._missions[active_ref]["status"] == "running"

        # TTL drops old finished rows but still keeps the active one.
        old_finished = [
            ref for ref, rec in server2._missions.items() if rec.get("status") != "running"
        ]
        for ref in old_finished:
            server2._missions[ref]["finished_at"] = 1.0
        server2._prune_mission_history()
        assert active_ref in server2._missions
        assert server2._missions[active_ref]["status"] == "running"
        assert server2._running_mission_count() == 1
        assert all(rec.get("status") == "running" for rec in server2._missions.values())

        tracked2[-1].cancel()
        await asyncio.gather(*tracked2, return_exceptions=True)

    asyncio.run(scenario())
