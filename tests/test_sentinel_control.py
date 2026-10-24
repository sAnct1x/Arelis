"""Command-bridge routes require the session token. EMP persists. The authority gate is live."""

from __future__ import annotations

from pathlib import Path
from typing import Any


async def test_snapshot_and_overseer_post_require_the_session_token(tmp_path: Path) -> None:
    """Most command-bridge routes used to skip the session token.

    GET /api/snapshot and Overseer POSTs (EMP, restore, scale, file read)
    answered any loopback caller. Only /api/command checked. One gate now
    covers every non-static route. Skipping that check on snapshot or on
    the POST path is a failure of this test.

    EMP used to live only in memory. trigger_emp must persist the stop flag
    so a new hive on the same data dir refuses dispatch_task and spawns
    units as EMP_DISABLED. Skipping the file write, or the constructor
    read, is a failure of this test.

    AuthorityGate used to run only in unit tests. dispatch_task, prune,
    and warden.ban_peer now go through SwarmHive._authorize_work.
    A Tier 0 observe must run. A Tier 2 delete or prune must park and
    leave the file. Commenting out evaluate_request in dispatch_task,
    or on the prune/ban branch, is a failure of this test.
    """
    import sys

    import httpx

    sentinel_root = Path(__file__).resolve().parents[1] / "sentinel"
    if str(sentinel_root) not in sys.path:
        sys.path.insert(0, str(sentinel_root))

    from sentinel.bridge.protocol import TOKEN_HEADER
    from sentinel.bridge.server import SentinelBridgeServer

    class _Hive:
        async def start_background_loops(self, *, hz: int = 60) -> None:
            return None

        async def stop_background_loops(self) -> None:
            return None

        def world_snapshot(self) -> dict[str, Any]:
            return {"units": []}

        async def set_theme(self, theme_id: str) -> dict[str, Any]:
            return {"id": theme_id}

    token = "testtoken"
    server = SentinelBridgeServer(
        _Hive(),
        host="127.0.0.1",
        preferred_port=0,
        token=token,
    )
    port = await server.start()
    try:
        url = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient() as http:
            snap_bare = await http.get(f"{url}/api/snapshot")
            assert snap_bare.status_code == 401

            post_bare = await http.post(
                f"{url}/api/overseer/theme",
                json={"theme": "night"},
            )
            assert post_bare.status_code == 401

            headers = {TOKEN_HEADER: token}
            snap_ok = await http.get(f"{url}/api/snapshot", headers=headers)
            assert snap_ok.status_code == 200
            assert "units" in snap_ok.json()

            post_ok = await http.post(
                f"{url}/api/overseer/theme",
                json={"theme": "night"},
                headers=headers,
            )
            assert post_ok.status_code == 200
    finally:
        await server.stop()

    from sentinel.castes.warden import WardenCaste
    from sentinel.core.fsm import SentinelState
    from sentinel.core.hive import SwarmHive
    from sentinel.paths import quarantine_dir, set_runtime_root

    hive_cfg = {
        "swarm": {
            "initial_pools": {
                "harvester": 1,
                "warden": 1,
                "sanitizer": 1,
                "tripwire": 1,
            },
            "auto_scale": False,
            "max_total_units": 8,
            "default_tier": "mk1",
        },
        "tripwire": {"watched_roots": []},
        "warden": {"watched_ports": []},
    }
    set_runtime_root(tmp_path)
    try:
        hive = SwarmHive(hive_cfg)
        await hive.trigger_emp(reason="persist across restart")
        restarted = SwarmHive(hive_cfg)
        blocked = await restarted.dispatch_task("warden", {"action": "patrol_scan"})
        assert blocked["ok"] is False
        assert all(u.state == SentinelState.EMP_DISABLED for u in restarted.units.values())
    finally:
        set_runtime_root(None)

    set_runtime_root(tmp_path / "gate")
    try:
        gated = SwarmHive(hive_cfg)
        observe = await gated.dispatch_task(
            "warden",
            {"action": "patrol_scan", "animate": False},
        )
        assert observe["ok"] is True

        qfile = quarantine_dir() / "quarantine-1792200001-deadbeef.json"
        qfile.parent.mkdir(parents=True, exist_ok=True)
        qfile.write_text('{"keep": true}\n', encoding="utf-8")

        parked = await gated.dispatch_task(
            "sanitizer",
            {"action": "DELETE_QUARANTINE_FILE", "path": str(qfile), "animate": False},
        )
        assert parked["ok"] is False
        assert parked.get("parked") is True
        assert qfile.is_file()

        pruned = gated.prune_runtime_storage(max_quarantines=0)
        assert pruned["ok"] is False
        assert pruned.get("parked") is True
        assert qfile.is_file()

        wrd = gated.registry.get("warden")
        assert isinstance(wrd, WardenCaste)
        ban = wrd.ban_peer("198.51.100.42", reason="control-test ban")
        assert ban.get("parked") is True
        banned, _entry = wrd.is_banned("198.51.100.42")
        assert banned is False
    finally:
        set_runtime_root(None)
