"""Mailbox: ciphertext pipe, house dials out, phone calls in."""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from cryptography.exceptions import InvalidTag

from arelis.relay.config import RelaySettings, load_relay_settings
from arelis.relay.crypto import e2e_key, hkdf_sha256, open_box, seal
from arelis.relay.house import HouseTunnel
from arelis.relay.protocol import b64, decode_response, encode_request, unb64
from arelis.relay.server import run_relay


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_hkdf_matches_rfc5869_case_a1() -> None:
    ikm = bytes.fromhex("0b" * 22)
    salt = bytes.fromhex("000102030405060708090a0b0c")
    info = bytes.fromhex("f0f1f2f3f4f5f6f7f8f9")
    okm = hkdf_sha256(ikm, salt=salt, info=info, length=42)
    assert okm.hex() == (
        "3cb25f25faacd57a90434f64d0362f2a"
        "2d2d0a90cf1a5a4c5db02d56ecc4c5bf"
        "34007208d5b887185865"
    )


def test_seal_round_trip_is_bound_to_instance() -> None:
    key = e2e_key("ingest-token", "inst-1")
    blob = seal(key, b"hello", aad=b"inst-1")
    assert open_box(key, blob, aad=b"inst-1") == b"hello"
    with pytest.raises(InvalidTag):
        open_box(key, blob, aad=b"inst-2")


def test_empty_secrets_mean_lan_only(tmp_path) -> None:
    path = tmp_path / "secrets.yaml"
    path.write_text("sms: {}\n", encoding="utf-8")
    assert load_relay_settings(path) == RelaySettings(url="", token="")


def test_phone_gets_503_when_house_is_away() -> None:
    port = _free_port()
    httpd = run_relay("127.0.0.1", port, "mailbox-secret")
    try:
        resp = httpx.post(
            f"http://127.0.0.1:{port}/v1/phone/call",
            json={"instance": "inst-1", "blob": "xxxx", "stream": False},
            timeout=5,
        )
        assert resp.status_code == 503
    finally:
        httpd.shutdown()


def test_phone_reaches_local_ingest_through_the_mailbox() -> None:
    ingest_port = _free_port()

    class _Ingest(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:
            body = b'{"ok":true,"mode":"at_the_house"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    ingest = ThreadingHTTPServer(("127.0.0.1", ingest_port), _Ingest)
    threading.Thread(target=ingest.serve_forever, daemon=True).start()
    relay_port = _free_port()
    httpd = run_relay("127.0.0.1", relay_port, "mailbox-secret")
    tunnel = HouseTunnel(
        relay_url=f"http://127.0.0.1:{relay_port}",
        relay_token="mailbox-secret",
        ingest_token="ingest-token",
        local_port=ingest_port,
        instance="inst-1",
    )
    tunnel.start()
    key = e2e_key("ingest-token", "inst-1")
    aad = b"inst-1"
    blob = b64(seal(key, encode_request("GET", "/mobile/status"), aad=aad))
    try:
        deadline = time.monotonic() + 5
        resp = None
        while time.monotonic() < deadline:
            resp = httpx.post(
                f"http://127.0.0.1:{relay_port}/v1/phone/call",
                json={"instance": "inst-1", "blob": blob, "stream": False},
                timeout=8,
            )
            if resp.status_code != 503:
                break
            time.sleep(0.1)
        assert resp is not None
        assert resp.status_code == 200
        opened = open_box(key, unb64(resp.json()["blob"]), aad=aad)
        out = decode_response(opened)
        assert out["status"] == 200
        assert json.loads(out["body"].decode())["mode"] == "at_the_house"
    finally:
        tunnel.stop()
        httpd.shutdown()
        ingest.shutdown()
