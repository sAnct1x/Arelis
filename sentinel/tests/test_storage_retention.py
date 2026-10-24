"""Tests for storage retention, log rotation, warrant ledger compaction, and artifact pruning."""

from __future__ import annotations

import httpx
import pytest

from sentinel.bridge import SentinelBridgeServer, SentinelClient
from sentinel.castes.harvester import HarvesterCaste
from sentinel.castes.sanitizer import SanitizerCaste
from sentinel.core.hive import SwarmHive
from sentinel.core.receipts import ReceiptLedger
from sentinel.core.telemetry import TelemetryLogger
from sentinel.paths import harvest_dir, quarantine_dir


def test_telemetry_logger_rotates_and_prunes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    logger = TelemetryLogger(log_dir=tmp_path, max_file_bytes=1000, max_backups=2)

    # Write enough entries to force multiple rotations
    for i in range(120):
        logger.record(
            "INFO",
            unit_id=f"SNT-TST-{i:03d}",
            caste="test",
            phase="TEST_EVENT",
            message=f"Telemetry event payload {i} with some extra padding to cross the 1000 byte threshold rapidly",
        )

    assert logger.jsonl_path.is_file()
    assert logger.text_path.is_file()

    # Verify backup files were created
    b1_json = tmp_path / f"{logger.jsonl_path.name}.1"
    b1_txt = tmp_path / f"{logger.text_path.name}.1"
    assert b1_json.is_file() or b1_txt.is_file()

    # Test explicit prune
    res = logger.prune_disk_logs(max_bytes=500, max_backups=1)
    assert isinstance(res["rotated"], list)
    assert isinstance(res["removed_backups"], list)


def test_receipt_ledger_compacts_disk_entries(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ledger_file = tmp_path / "test_ledger.jsonl"
    ledger = ReceiptLedger(disk_path=ledger_file, max_disk_entries=20)

    for i in range(55):
        ledger.mint(
            unit_id="SNT-HRV-001",
            caste="harvester",
            kind="web",
            source=f"https://arxiv.org/abs/2501.{i:05d}",
            span=f"Abstract text for paper {i}",
            ok=True,
        )

    # Verify file was compacted and has at most 20 entries
    lines = [ln.strip() for ln in ledger_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) <= 20
    assert len(lines) > 0
    assert "Abstract text for paper 54" in lines[-1]


def test_harvester_and_sanitizer_prune_artifacts(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sentinel.paths import set_runtime_root

    set_runtime_root(tmp_path)
    try:
        h_dir = harvest_dir()
        q_dir = quarantine_dir()

        # Create dummy old harvest dossiers
        for i in range(35):
            f = h_dir / f"2026-10-16-test-harvest-{i:02d}.md"
            f.write_text(f"# Harvest Dossier {i}\n", encoding="utf-8")

        harvester = HarvesterCaste(config={"retention": {"max_harvest_dossiers": 10}})
        removed_h = harvester.prune_harvest_dossiers(max_keep=10)
        assert len(removed_h) == 25
        remaining_h = list(h_dir.glob("*.md"))
        assert len(remaining_h) == 10

        # Create dummy old quarantine reports
        for i in range(30):
            f = q_dir / f"quarantine-17922000{i:02d}-abcd1234.json"
            f.write_text(f'{{"quarantine_id": {i}}}\n', encoding="utf-8")

        sanitizer = SanitizerCaste(config={"retention": {"max_quarantine_files": 12}})
        removed_q = sanitizer.prune_quarantine_files(max_keep=12)
        assert len(removed_q) == 18
        remaining_q = list(q_dir.glob("*.json"))
        assert len(remaining_q) == 12
    finally:
        set_runtime_root(None)


@pytest.mark.asyncio
async def test_hive_prune_runtime_storage_and_overseer_api(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from sentinel.paths import set_runtime_root

    set_runtime_root(tmp_path)
    try:
        hive = SwarmHive()
        server = SentinelBridgeServer(hive, host="127.0.0.1", preferred_port=18798)
        port = await server.start()
        client = SentinelClient(host="127.0.0.1", port=port, token=server.session_token)

        try:
            # 1. Test Hive prune method directly
            summary = hive.prune_runtime_storage(max_harvests=5, max_quarantines=5)
            assert summary["ok"] is True
            assert isinstance(summary["pruned_harvests"], list)
            assert isinstance(summary["pruned_quarantines"], list)

            # 2. Test SentinelClient.prune_storage() command endpoint
            cmd_res = await client.prune_storage()
            assert cmd_res["ok"] is True
            assert "pruned_harvests" in cmd_res

            # 3. Test HTTP POST /api/overseer/prune
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}",
                headers={"X-Sentinel-Token": server.session_token},
            ) as http:
                resp = await http.post("/api/overseer/prune")
                assert resp.status_code == 200
                assert resp.json()["ok"] is True
        finally:
            await server.stop()
    finally:
        set_runtime_root(None)
