"""Tests for Caste 02 (WardenSentinel) and Caste 04 (TripwireSentinel)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.core.hive import SwarmHive
from sentinel.safety.network import is_blocked_url


def test_warden_ssrf_and_loopback_url_blocking() -> None:
    assert is_blocked_url("http://127.0.0.1:11434/api/tags") is not None
    assert is_blocked_url("http://localhost:8765/ingest") is not None
    assert is_blocked_url("http://169.254.169.254/latest/meta-data/") is not None
    assert is_blocked_url("http://192.168.1.1/admin") is not None
    assert is_blocked_url("file:///C:/Windows/System32/cmd.exe") is not None
    assert is_blocked_url("https://export.arxiv.org/api/query") is None


def test_warden_sliding_window_flood_and_auth_lockout(tmp_path: Path) -> None:
    hive = SwarmHive()
    warden = hive.registry.get("warden")
    warden._banlist_path = tmp_path / "banned_peers.json"  # type: ignore[attr-defined]
    warden._banned_peers.clear()  # type: ignore[attr-defined]

    # Test auth failure lockout
    for _ in range(warden.auth_fail_limit - 1):  # type: ignore[attr-defined]
        res = warden.note_auth_fail("10.20.30.40")  # type: ignore[attr-defined]
        assert res["locked"] is False

    lock_res = warden.note_auth_fail("10.20.30.40")  # type: ignore[attr-defined]
    assert lock_res["locked"] is True
    assert lock_res["permanently_banned"] is True

    # Subsequent inbound request from locked IP must be refused
    admit = warden.admit_inbound("10.20.30.40")  # type: ignore[attr-defined]
    assert admit["ok"] is False
    assert admit["reason"] == "locked"

    # Even after active lockout window expires, non-loopback brute-force IP remains permanently blacklisted
    warden._locked_until.clear()  # type: ignore[attr-defined]
    admit_after = warden.admit_inbound("10.20.30.40")  # type: ignore[attr-defined]
    assert admit_after["ok"] is False
    assert admit_after["reason"] == "permanent_blacklist"

    # Unbanning removes peer from blacklist
    assert warden.unban_peer("10.20.30.40") is True  # type: ignore[attr-defined]
    assert warden.admit_inbound("10.20.30.40")["ok"] is True  # type: ignore[attr-defined]



@pytest.mark.asyncio
async def test_warden_socket_patrol_and_threat_interception() -> None:
    hive = SwarmHive()
    scan = await hive.dispatch_task("warden", {"action": "patrol_scan", "animate": False})
    assert scan["ok"] is True
    assert len(scan["snapshot"]["bastions"]) == 4

    # Block an SSRF egress attempt via Warden
    blocked = await hive.dispatch_task(
        "warden",
        {"action": "verify_egress", "url": "http://127.0.0.1:11434", "animate": False},
    )
    assert blocked["ok"] is True
    assert blocked["neutralized"] is False
    assert blocked["allowed"] is False


@pytest.mark.asyncio
async def test_tripwire_merkle_baseline_and_tamper_detection(tmp_path: Path) -> None:
    hive = SwarmHive()
    protected_dir = tmp_path / "vault"
    protected_dir.mkdir()
    secret_file = protected_dir / "config.yaml"
    secret_file.write_text("mode: safe\n", encoding="utf-8")

    # Register baseline via TripwireSentinel
    reg = await hive.dispatch_task(
        "tripwire",
        {"action": "register", "path": str(protected_dir), "label": "TestVault", "animate": False},
    )
    assert reg["ok"] is True
    assert reg["file_count"] == 1

    # Verify intact before modification
    check_ok = await hive.dispatch_task("tripwire", {"action": "verify", "animate": False})
    assert check_ok["intact"] is True

    # Tamper with the file
    secret_file.write_text("mode: compromised\n", encoding="utf-8")

    # Tripwire must detect the exact modified file, Merkle root mismatch, and unified line-by-line diff
    check_tampered = await hive.dispatch_task("tripwire", {"action": "verify", "animate": False})
    assert check_tampered["intact"] is False
    vault_report = next(r for r in check_tampered["roots"] if r["label"] == "TestVault")
    assert vault_report["intact"] is False
    assert "config.yaml" in vault_report["modified"]
    diff_lines = "\n".join(vault_report["diffs"]["config.yaml"])
    assert "-mode: safe" in diff_lines
    assert "+mode: compromised" in diff_lines


def test_warden_ip_scope_and_firewall_rule_builder() -> None:
    from sentinel.castes.warden import build_windows_firewall_block_cmd, classify_ip_scope

    assert classify_ip_scope("127.0.0.1") == "loopback"
    assert classify_ip_scope("::1") == "loopback"
    assert classify_ip_scope("192.168.1.42") == "lan"
    assert classify_ip_scope("10.0.0.5") == "lan"
    assert classify_ip_scope("185.220.101.44") == "wan"
    cmd = build_windows_firewall_block_cmd("185.220.101.44")
    assert "netsh advfirewall firewall add rule" in cmd
    assert "remoteip=185.220.101.44" in cmd


def test_tripwire_refuses_runtime_restoration_and_protects_roots(tmp_path: Path) -> None:
    from sentinel.castes.tripwire import TripwireCaste

    trp = TripwireCaste()
    # Create test directory to verify legacy heal_root request is explicitly rejected
    heal_dir = tmp_path / "Arelis_Sentinel_Test"
    heal_dir.mkdir()
    cfg_file = heal_dir / "settings.yaml"
    cfg_file.write_text("allow_exec: false\n", encoding="utf-8")

    trp.register_watch_root(heal_dir, label="HealRoot", mode="auto_heal")
    cfg_file.write_text("allow_exec: true\n", encoding="utf-8")
    v1 = trp.verify_all()
    assert v1["intact"] is False

    heal_res = trp.heal_root(heal_dir)
    assert heal_res["ok"] is False
    assert "disabled" in heal_res["error"]
    assert cfg_file.read_text(encoding="utf-8") == "allow_exec: true\n"
    assert trp.verify_all()["intact"] is False

    # Verify readonly_strict refuses to write
    ro_dir = tmp_path / "Arelis_ReadOnly"
    ro_dir.mkdir()
    ro_file = ro_dir / "core.py"
    ro_file.write_text("x = 1\n", encoding="utf-8")
    trp.register_watch_root(ro_dir, label="ArelisCore", mode="readonly_strict")
    ro_file.write_text("x = 2\n", encoding="utf-8")
    refused = trp.heal_root(ro_dir)
    assert refused["ok"] is False
    assert ro_file.read_text(encoding="utf-8") == "x = 2\n"
