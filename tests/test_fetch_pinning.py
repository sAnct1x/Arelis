"""The fetch connects to the IP the check already accepted.

On main the check says the name is public, then the connect asks DNS again.
The second answer is 127.0.0.1 and the local server is hit. These tests fail
there.
"""

from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from arelis.tools.fetch import guarded_get

# A public address the policy allows. Documentation ranges are private here,
# so they would be blocked before any connect and the test would pass for
# the wrong reason.
_PUBLIC = "1.1.1.1"


def _addr(ip: str, port: int) -> list[tuple]:
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))]


async def test_guarded_get_connects_to_checked_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """DNS that flips to loopback after the check must not be what we dial."""
    hits = 0

    async def _accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal hits
        hits += 1
        try:
            await reader.read(64)
        except Exception:
            pass
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

    server = await asyncio.start_server(_accept, "127.0.0.1", 0)
    sockets = server.sockets or []
    port = sockets[0].getsockname()[1]
    calls = {"n": 0}
    previous = socket.getaddrinfo

    def _fake(host: object, port_arg: object, *args: object, **kwargs: object) -> list:
        name = host.decode() if isinstance(host, bytes) else str(host)
        if name == "rebind.example":
            calls["n"] += 1
            ip = _PUBLIC if calls["n"] == 1 else "127.0.0.1"
            return _addr(ip, int(port_arg or 0))
        return previous(host, port_arg, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", _fake)
    try:
        async with httpx.AsyncClient(timeout=1.0, trust_env=False) as client:
            try:
                await guarded_get(client, f"http://rebind.example:{port}/secret")
            except Exception:
                pass
        await asyncio.sleep(0.05)
        assert hits == 0
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port),
            timeout=2,
        )
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)
        assert hits == 1
    finally:
        server.close()
        await server.wait_closed()


async def test_pinned_request_keeps_the_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    """The TCP target is the checked IP. Host and SNI stay the name."""
    seen: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="ok")

    def _fake(host: object, port_arg: object, *args: object, **kwargs: object) -> list:
        del host, args, kwargs
        return _addr(_PUBLIC, int(port_arg or 443))

    monkeypatch.setattr(socket, "getaddrinfo", _fake)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler),
        timeout=1.0,
        trust_env=False,
    ) as client:
        response = await guarded_get(client, "https://name.example/a")
    assert response.status_code == 200
    sent = seen[0]
    assert sent.url.host == _PUBLIC
    assert sent.headers["host"] == "name.example"
    assert sent.extensions.get("sni_hostname") == "name.example"


async def test_redirect_hop_is_pinned_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each hop is checked and pinned. A relative redirect keeps the name."""
    seen: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})
        return httpx.Response(200, text="landed")

    def _fake(host: object, port_arg: object, *args: object, **kwargs: object) -> list:
        del host, args, kwargs
        return _addr(_PUBLIC, int(port_arg or 443))

    monkeypatch.setattr(socket, "getaddrinfo", _fake)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_handler),
        timeout=1.0,
        trust_env=False,
    ) as client:
        response = await guarded_get(client, "https://name.example/a")
    assert response.status_code == 200
    assert [item.url.host for item in seen] == [_PUBLIC, _PUBLIC]
    assert [item.headers["host"] for item in seen] == ["name.example", "name.example"]
    assert seen[1].url.path == "/b"
    assert seen[1].extensions.get("sni_hostname") == "name.example"
