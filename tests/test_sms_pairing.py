"""QR pairing tickets and companion radio credentials."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import yaml

from arelis.qr import qr_has_finders, qr_modules
from arelis.sms_android import load_sms_account
from arelis.sms_pairing import (
    apply_pair,
    issue_pair_secret,
    make_ticket,
    parse_listen_url,
)


def test_qr_finders_for_pairing_text() -> None:
    modules = qr_modules("A1|abcdef0123456789|token-token-token|pairsecret|http://192.168.1.10:8765")
    assert qr_has_finders(modules)
    assert len(modules) == len(modules[0])
    assert len(modules) >= 21 + 8


def test_parse_listen_url_requires_port() -> None:
    assert parse_listen_url("http://192.168.1.10:8080") == "http://192.168.1.10:8080"
    assert parse_listen_url("http://192.168.1.10") is None
    assert parse_listen_url("ftp://192.168.1.10:8080") is None


def test_load_sms_account_companion_without_smsgate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARELIS_SMSGATE_PASSWORD", raising=False)
    path = tmp_path / "secrets.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "sms": {
                    "ingest_token": "tok",
                    "companion": {
                        "base_url": "http://192.168.1.20:8080",
                        "device_key": "k",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    account = load_sms_account(path)
    assert account is not None
    assert account.via == "companion"


def test_apply_pair_rejects_stale_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("arelis.sms_pairing.instance_id", lambda: "inst0123456789ab")
    pair_path = tmp_path / "pair.json"
    issue_pair_secret(path=pair_path)
    code, _body = apply_pair(
        {
            "instance": "inst0123456789ab",
            "pair": "not-the-secret",
            "listen_url": "http://192.168.1.20:8080",
            "device_key": "k",
        },
        secrets_path=tmp_path / "secrets.yaml",
        pair_path=pair_path,
    )
    assert code == 403


def test_make_ticket_reuses_unexpired_secret(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("arelis.sms_pairing.instance_id", lambda: "inst0123456789ab")
    monkeypatch.setattr("arelis.sms_pairing.PAIR_PATH", tmp_path / "pair.json")
    monkeypatch.setattr(
        "arelis.sms_pairing.pairing_urls",
        lambda port: (f"http://192.168.1.10:{port}",),
    )
    monkeypatch.setattr(
        "arelis.relay.config.load_relay_settings",
        lambda path=None: type("S", (), {"url": "", "token": ""})(),
    )
    first = make_ticket("ingest-token", 8765, rotate=True)
    reused = make_ticket("ingest-token", 8765, rotate=False)
    assert reused.pair == first.pair
    rotated = make_ticket("ingest-token", 8765, rotate=True)
    assert rotated.pair != first.pair


def test_companion_keeps_smsgate_inbox_poll(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ARELIS_SMSGATE_PASSWORD", raising=False)
    path = tmp_path / "secrets.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "sms": {
                    "inbox_base_url": "http://192.168.1.9:8080",
                    "inbox_username": "local",
                    "inbox_password": "lpass",
                    "companion": {
                        "base_url": "http://192.168.1.20:8080",
                        "device_key": "k",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    account = load_sms_account(path)
    assert account is not None
    assert account.via == "companion"
    assert account.supports_inbox_poll()
    assert account.inbox_url == "http://192.168.1.9:8080/inbox"


async def test_ingest_pair_http(tmp_path: Path, monkeypatch) -> None:
    import asyncio
    import socket

    from arelis.core.bus import EventBus
    from arelis.sms_inbound import SeenMessageStore
    from arelis.sms_ingest import InboundIngestServer

    monkeypatch.setattr("arelis.sms_pairing.instance_id", lambda: "inst0123456789ab")
    secrets = tmp_path / "secrets.yaml"
    pair_path = tmp_path / "pair.json"
    monkeypatch.setattr("arelis.sms_pairing.SECRETS_PATH", secrets)
    monkeypatch.setattr("arelis.sms_pairing.PAIR_PATH", pair_path)
    secret = issue_pair_secret(path=pair_path)

    bus = EventBus()
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(bus.run())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = InboundIngestServer(
        bus,
        loop,
        token="test-token",
        host="127.0.0.1",
        port=port,
        seen=SeenMessageStore(tmp_path / "seen.json"),
    )
    server.start()
    try:
        async with httpx.AsyncClient() as client:
            health = await client.get(f"http://127.0.0.1:{port}/inbound/health")
            assert health.status_code == 200
            denied = await client.post(
                f"http://127.0.0.1:{port}/inbound/pair",
                json={},
            )
            assert denied.status_code == 401
            ok = await client.post(
                f"http://127.0.0.1:{port}/inbound/pair",
                headers={"X-Arelis-Token": "test-token"},
                json={
                    "instance": "inst0123456789ab",
                    "pair": secret,
                    "listen_url": "http://192.168.1.20:8080",
                    "device_key": "phone-key",
                },
            )
            assert ok.status_code == 200
            assert ok.json()["ok"] is True
        account = load_sms_account(secrets)
        assert account is not None
        assert account.via == "companion"
    finally:
        server.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
