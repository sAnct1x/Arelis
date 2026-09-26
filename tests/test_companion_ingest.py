"""Companion APK / Gemma routes on the ingest server — no live phone."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import httpx
import pytest

from arelis import companion_pack
from arelis.companion_pack import ApkOffer, file_sha256, write_sidecar
from arelis.core.bus import EventBus
from arelis.sms_ingest import InboundIngestServer
from arelis.sms_pairing import issue_pair_secret


def _pair_secret(tmp_path: Path, monkeypatch) -> str:
    pair_path = tmp_path / "sms_pair.json"
    monkeypatch.setattr("arelis.sms_pairing.PAIR_PATH", pair_path)
    monkeypatch.setattr("arelis.sms_pairing.instance_id", lambda: "inst0123456789ab")
    monkeypatch.setattr("arelis.identity.instance_id", lambda: "inst0123456789ab")
    return issue_pair_secret(path=pair_path)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _serve(token: str = "test-token"):
    loop = asyncio.get_running_loop()
    bus = EventBus()
    task = asyncio.create_task(bus.run())
    port = _free_port()
    server = InboundIngestServer(
        bus, loop, token=token, host="127.0.0.1", port=port
    )
    server.start()
    return bus, task, server, f"http://127.0.0.1:{port}"


async def _stop(bus, task, server) -> None:
    server.stop()
    bus.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_health_includes_companion_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(companion_pack, "find_apk", lambda: None)
    monkeypatch.setattr(companion_pack, "find_gemma", lambda: None)
    monkeypatch.setattr(companion_pack, "expected_companion", lambda gradle=None: None)
    bus, task, server, base = await _serve()
    try:
        async with httpx.AsyncClient() as client:
            health = await client.get(f"{base}/inbound/health")
        assert health.status_code == 200
        snap = health.json()["companion"]
        assert snap["apk"] is False
        assert snap["gemma"] is False
        assert snap["arelis"]
    finally:
        await _stop(bus, task, server)


@pytest.mark.asyncio
async def test_companion_manifest_needs_auth(monkeypatch) -> None:
    monkeypatch.setattr(companion_pack, "find_apk", lambda: None)
    monkeypatch.setattr(companion_pack, "find_gemma", lambda: None)
    bus, task, server, base = await _serve()
    try:
        async with httpx.AsyncClient() as client:
            denied = await client.get(f"{base}/companion/manifest")
            assert denied.status_code == 401
            ok = await client.get(
                f"{base}/companion/manifest",
                headers={"X-Arelis-Token": "test-token"},
            )
            assert ok.status_code == 200
            assert ok.json()["ok"] is True
    finally:
        await _stop(bus, task, server)


@pytest.mark.asyncio
async def test_companion_apk_streams_with_pair_secret(
    tmp_path: Path, monkeypatch
) -> None:
    apk = tmp_path / "arelis.apk"
    apk.write_bytes(b"PK\x03\x04-fake-apk")
    offer = ApkOffer(
        path=apk,
        version_code=6,
        version_name="0.3.3",
        sha256=file_sha256(apk),
        size=apk.stat().st_size,
        signed="debug",
        source=str(apk),
    )
    write_sidecar(apk, offer)
    monkeypatch.setattr(companion_pack, "find_apk", lambda: offer)
    monkeypatch.setattr(companion_pack, "find_gemma", lambda: None)
    secret = _pair_secret(tmp_path, monkeypatch)
    bus, task, server, base = await _serve()
    try:
        async with httpx.AsyncClient() as client:
            bad = await client.get(f"{base}/companion/apk?pair=nope")
            assert bad.status_code == 401
            page = await client.get(f"{base}/companion?pair={secret}")
            assert page.status_code == 200
            assert "text/html" in page.headers["content-type"]
            assert "Download the app" in page.text
            got = await client.get(f"{base}/companion/apk?pair={secret}")
            assert got.status_code == 200
            assert got.content == apk.read_bytes()
            assert got.headers["content-disposition"].endswith('filename="Arelis-0.3.3.apk"')
    finally:
        await _stop(bus, task, server)


@pytest.mark.asyncio
async def test_companion_gemma_rejects_pair_secret(
    tmp_path: Path, monkeypatch
) -> None:
    pack = tmp_path / "gemma-4-E2B-it.litertlm"
    pack.write_bytes(b"x" * (companion_pack.GEMMA_MIN_BYTES + 1))
    from arelis.companion_pack import GemmaOffer

    offer = GemmaOffer(path=pack, size=pack.stat().st_size, sha256="ab" * 32)
    monkeypatch.setattr(companion_pack, "find_apk", lambda: None)
    monkeypatch.setattr(companion_pack, "find_gemma", lambda: offer)
    secret = _pair_secret(tmp_path, monkeypatch)
    bus, task, server, base = await _serve()
    try:
        async with httpx.AsyncClient() as client:
            denied = await client.get(f"{base}/companion/gemma?pair={secret}")
            assert denied.status_code == 401
            ok = await client.get(
                f"{base}/companion/gemma",
                headers={"X-Arelis-Token": "test-token"},
            )
            assert ok.status_code == 200
            assert ok.content == pack.read_bytes()
    finally:
        await _stop(bus, task, server)
