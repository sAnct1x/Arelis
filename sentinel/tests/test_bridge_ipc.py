"""Tests for Sentinel Loopback Bridge Server, Token Auth, and Sovereign Client."""

from __future__ import annotations

import httpx
import pytest

from sentinel.bridge import SentinelBridgeServer, SentinelClient, assert_loopback_host
from sentinel.core.hive import SwarmHive


def test_bridge_refuses_non_loopback_binding() -> None:
    assert assert_loopback_host("127.0.0.1") == "127.0.0.1"
    assert assert_loopback_host("localhost") == "127.0.0.1"
    with pytest.raises(ValueError):
        assert_loopback_host("0.0.0.0")
    with pytest.raises(ValueError):
        assert_loopback_host("192.168.1.50")


@pytest.mark.asyncio
async def test_bridge_server_and_sovereign_client_end_to_end() -> None:
    hive = SwarmHive()
    server = SentinelBridgeServer(hive, host="127.0.0.1", preferred_port=18790)
    port = await server.start()
    try:
        client = SentinelClient(host="127.0.0.1", port=port, token=server.session_token)

        # 1. Ping
        ping = await client.ping()
        assert ping["ok"] is True
        assert ping["pong"] is True

        # 2. Unauthenticated command must return 401
        bad_client = SentinelClient(host="127.0.0.1", port=port, token="invalid-token")
        unauth = await bad_client.ping()
        assert unauth["ok"] is False

        # 3. Theme switch (sodium -> filament -> night -> matrix)
        for t_name in ("filament", "night", "matrix", "sodium"):
            t_res = await client.set_theme(t_name)
            assert t_res["ok"] is True
            assert t_res["theme"]["id"] == t_name

        # 4. Spawn & Upgrade units via client
        sp = await client.spawn_units("harvester", count=2, tier="mk2")
        assert sp["ok"] is True
        assert len(sp["spawned"]) == 2

        # 5. Verify 3D Overseer static HTML is served on /overseer
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"http://127.0.0.1:{port}/overseer")
            assert resp.status_code == 200
            assert "SENTINEL — Arelis 3D Swarm Overseer" in resp.text

        # 6. EMP Halt & Restore via client
        emp = await client.emp_halt(reason="Bridge Test Halt")
        assert emp["ok"] is True
        assert emp["emp"]["tripped"] is True

        rest = await client.emp_restore()
        assert rest["ok"] is True
        assert rest["emp"]["tripped"] is False
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_overseer_qol_endpoints_and_preference_persistence(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from sentinel.config import load_config, save_local_preferences

    pref_file = tmp_path / "config.local.yaml"
    save_local_preferences(
        theme="matrix",
        camera_mode="chase",
        default_tier="mk3",
        override_path=pref_file,
    )
    merged = load_config(override_path=pref_file)
    assert merged["ui"]["theme"] == "matrix"
    assert merged["ui"]["camera_mode"] == "chase"
    assert merged["swarm"]["default_tier"] == "mk3"

    hive = SwarmHive()
    warrant = hive.ledger.mint(
        unit_id="SNT-HRV-001",
        caste="harvester",
        kind="web",
        source="https://arxiv.org/abs/2501.00001",
        span="Verified exoplanet transmission spectroscopy abstract.",
        ok=True,
    )

    server = SentinelBridgeServer(hive, host="127.0.0.1", preferred_port=18792)
    port = await server.start()
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as http:
            # 1. Scale caste (+1 / -1)
            r_scale = await http.post("/api/overseer/scale", json={"caste": "harvester", "delta": 1})
            assert r_scale.status_code == 200
            assert r_scale.json()["ok"] is True

            # 2. Upgrade swarm unit tier to MK3 (12 tentacles)
            r_up = await http.post("/api/overseer/upgrade", json={"tier": "mk3", "caste": "all"})
            assert r_up.status_code == 200
            up_data = r_up.json()
            assert up_data["ok"] is True
            assert up_data["tier"] == "mk3"
            assert up_data["tentacles"] == 12

            # 3. Verify retired self-heal route returns explicit refusal
            r_heal = await http.post("/api/overseer/heal", json={})
            assert r_heal.status_code == 200
            assert r_heal.json()["ok"] is False

            # 4. Read full Warrant Receipt via /api/overseer/file
            r_file = await http.get(
                "/api/overseer/file",
                params={"kind": "receipt", "name": warrant.receipt_id},
            )
            assert r_file.status_code == 200
            f_data = r_file.json()
            assert f_data["ok"] is True
            assert warrant.receipt_id in f_data["title"]
            assert "exoplanet transmission spectroscopy" in f_data["content"]

            # 5. Hunter-Killer Active Neutralization & Unban via /api/overseer/neutralize & /api/overseer/unban
            wrd = hive.registry.get("warden")
            san = hive.registry.get("sanitizer")
            wrd._banlist_path = tmp_path / "banned_peers.json"  # type: ignore[attr-defined]
            wrd._banned_peers.clear()  # type: ignore[attr-defined]
            san._immunized_path = tmp_path / "immunized_hashes.json"  # type: ignore[attr-defined]
            san._immunized_hashes.clear()  # type: ignore[attr-defined]

            r_neut = await http.post(
                "/api/overseer/neutralize",
                json={
                    "ip": "198.51.100.77",
                    "sha256": "b" * 64,
                    "reason": "Test Hunter-Killer Strike",
                },
            )
            assert r_neut.status_code == 400
            neut_data = r_neut.json()
            assert neut_data["ok"] is False
            assert wrd.banned_count == 0
            assert san.immunized_count == 0

            r_unban = await http.post("/api/overseer/unban", json={"ip": "198.51.100.77"})
            assert r_unban.status_code == 200
            assert r_unban.json()["unbanned"] is False

            # 6. Cross-Site WebSocket/HTTP Hijacking (CSWSH) / Evil Origin must be blocked (403)
            r_cswsh = await http.post(
                "/api/overseer/heal",
                headers={"Origin": "https://evil-attacker.example.com"},
                json={},
            )
            assert r_cswsh.status_code == 403
            assert "Cross-Origin browser attack blocked" in r_cswsh.json()["error"]
    finally:
        await server.stop()


