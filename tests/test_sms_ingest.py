"""LAN ingest for the Android notify companion — no live phone."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import yaml

from arelis import sms_ingest
from arelis.contacts import Contact, match_contact_label, normalize_phone
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.sms_inbound import InboundSms, SeenMessageStore
from arelis.sms_ingest import (
    InboundIngestServer,
    RecentInboundLog,
    ensure_ingest_token,
    format_ingest_listen_urls,
    load_ingest_token,
    parse_ingest_payload,
    publish_inbound,
)
from arelis.tools.inbound_sms import InboundSmsTool


@pytest.fixture(autouse=True)
def _fresh_lan_lookup() -> Iterator[None]:
    """A stuck getaddrinfo in an earlier test must not leak into this one."""
    sms_ingest._reset_hostname_lookup()
    yield
    sms_ingest._reset_hostname_lookup()


def _book(**people: dict) -> dict[str, Contact]:
    out: dict[str, Contact] = {}
    for alias, fields in people.items():
        phone = str(fields.get("phone") or "")
        raw_aliases = fields.get("aliases") or ()
        if isinstance(raw_aliases, str):
            raw_aliases = (raw_aliases,)
        out[alias] = Contact(
            alias=alias,
            name=str(fields.get("name") or ""),
            phone=phone,
            digits=normalize_phone(phone),
            email="",
            aliases=tuple(str(a) for a in raw_aliases),
        )
    return out


def test_format_ingest_listen_urls_mentions_port() -> None:
    text = format_ingest_listen_urls(8765)
    assert ":8765" in text
    assert text.startswith("http://")


class _RouteSocket:
    """Stand-in for the UDP probe socket used by list_lan_ipv4."""

    def __init__(self, ip: str | None) -> None:
        self._ip = ip

    def connect(self, _addr: object) -> None:
        if self._ip is None:
            raise OSError("no route")

    def getsockname(self) -> tuple[str, int]:
        return (self._ip or "", 1)

    def close(self) -> None:
        return None


@pytest.mark.parametrize(
    ("hostname_ips", "route_ip", "expected"),
    [
        (
            ["10.0.0.2", "192.168.1.5", "127.0.0.1"],
            "192.168.1.5",
            ["10.0.0.2", "192.168.1.5"],
        ),
        (["10.0.0.2"], "192.168.1.9", ["192.168.1.9", "10.0.0.2"]),
        (["10.0.0.2", "10.0.0.2"], "10.1.1.1", ["10.1.1.1", "10.0.0.2"]),
        (["10.0.0.2"], "127.0.0.1", ["10.0.0.2"]),
        (None, "192.168.1.9", ["192.168.1.9"]),
        (["10.0.0.2"], None, ["10.0.0.2"]),
        (None, None, []),
        (["127.0.0.1"], "127.0.0.1", []),
    ],
)
def test_list_lan_ipv4_keeps_fast_lookup_results(
    monkeypatch: pytest.MonkeyPatch,
    hostname_ips: list[str] | None,
    route_ip: str | None,
    expected: list[str],
) -> None:
    """A fast resolver still returns the same addresses, in the same order."""

    def getaddrinfo(*_args: object, **_kwargs: object) -> list[tuple]:
        if hostname_ips is None:
            raise OSError("lookup failed")
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in hostname_ips
        ]

    monkeypatch.setattr(sms_ingest.socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(
        sms_ingest.socket,
        "socket",
        lambda *_args, **_kwargs: _RouteSocket(route_ip),
    )
    assert sms_ingest.list_lan_ipv4() == expected
    assert sms_ingest.list_lan_ipv4() == expected


def test_list_lan_ipv4_returns_when_getaddrinfo_hangs(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stuck hostname lookup must not block past a few seconds.

    macOS CI hung inside getaddrinfo on the machine hostname until the 90s
    pytest timeout killed the run. This patches that call so it waits until
    released, and requires list_lan_ipv4 to return on its own.
    """
    release = threading.Event()
    entered = threading.Event()
    finished = threading.Event()

    def hang(*_args: object, **_kwargs: object) -> list[object]:
        entered.set()
        try:
            release.wait()
            return []
        finally:
            finished.set()

    monkeypatch.setattr(sms_ingest.socket, "getaddrinfo", hang)
    started = time.monotonic()
    try:
        ips = sms_ingest.list_lan_ipv4()
        elapsed = time.monotonic() - started
        again = time.monotonic()
        ips_again = sms_ingest.list_lan_ipv4()
        again_elapsed = time.monotonic() - again
    finally:
        release.set()
    assert entered.is_set()
    # The lookup budget is 2s. 4s still fails a call that blocks until the
    # 90s pytest ceiling, which is what killed the macOS run.
    assert elapsed < 4.0, f"list_lan_ipv4 blocked for {elapsed:.1f}s"
    # A lookup that is already stuck must not cost another full wait.
    assert again_elapsed < 0.5, f"second call blocked for {again_elapsed:.1f}s"
    assert isinstance(ips, list)
    assert isinstance(ips_again, list)
    # Reap the lookup thread while the patch is still in place so the next
    # test does not inherit a stuck resolver.
    assert finished.wait(2.0)
    worker = sms_ingest._lookup_thread
    if worker is not None:
        worker.join(timeout=2.0)
        assert not worker.is_alive()
    assert not any(thread.name == "arelis-lan-lookup" for thread in threading.enumerate())


def test_reset_clears_a_stuck_hostname_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hung resolver hides hostname addresses until the lookup state is reset.

    That is what macOS CI did: an earlier real getaddrinfo never returned, and
    every later call reused that thread. Resetting starts a new lookup, so
    these tests do not depend on order.
    """
    release = threading.Event()
    entered = threading.Event()

    def hang(*_args: object, **_kwargs: object) -> list[object]:
        entered.set()
        release.wait()
        return []

    def hostname_only(*_args: object, **_kwargs: object) -> list[tuple]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.2", 0))]

    monkeypatch.setattr(sms_ingest.socket, "getaddrinfo", hang)
    monkeypatch.setattr(
        sms_ingest.socket,
        "socket",
        lambda *_args, **_kwargs: _RouteSocket("192.168.1.9"),
    )
    stuck: threading.Thread | None = None
    try:
        assert sms_ingest.list_lan_ipv4() == ["192.168.1.9"]
        assert entered.is_set()
        monkeypatch.setattr(sms_ingest.socket, "getaddrinfo", hostname_only)
        assert sms_ingest.list_lan_ipv4() == ["192.168.1.9"]
        stuck = sms_ingest._lookup_thread
        sms_ingest._reset_hostname_lookup()
        assert sms_ingest.list_lan_ipv4() == ["192.168.1.9", "10.0.0.2"]
    finally:
        release.set()
        if stuck is not None:
            stuck.join(timeout=2.0)


def test_released_hang_leaves_no_lookup_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """After a stuck lookup is released, its thread is gone.

    The resolver runs on a daemon thread the process cannot kill. This test
    holds getaddrinfo, lets the call return on the budget, then releases it.
    Nothing named arelis-lan-lookup should still be alive.
    """
    release = threading.Event()
    entered = threading.Event()

    def hang(*_args: object, **_kwargs: object) -> list[object]:
        entered.set()
        release.wait()
        return []

    monkeypatch.setattr(sms_ingest.socket, "getaddrinfo", hang)
    monkeypatch.setattr(
        sms_ingest.socket,
        "socket",
        lambda *_args, **_kwargs: _RouteSocket("192.168.1.9"),
    )
    try:
        assert sms_ingest.list_lan_ipv4() == ["192.168.1.9"]
        assert entered.wait(1.0)
    finally:
        release.set()
    worker = sms_ingest._lookup_thread
    assert worker is not None
    assert worker.name == "arelis-lan-lookup"
    worker.join(timeout=2.0)
    assert not worker.is_alive()
    assert not any(thread.name == "arelis-lan-lookup" for thread in threading.enumerate())


def test_load_ingest_token(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "secrets.yaml"
    path.write_text(
        yaml.safe_dump({"sms": {"ingest_token": "secret-token"}}),
        encoding="utf-8",
    )
    monkeypatch.delenv("ARELIS_INGEST_TOKEN", raising=False)
    assert load_ingest_token(path) == "secret-token"
    monkeypatch.setenv("ARELIS_INGEST_TOKEN", "from-env")
    assert load_ingest_token(path) == "from-env"


def test_ensure_ingest_token_mints_once(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "secrets.yaml"
    path.write_text(yaml.safe_dump({"email": {"address": "me@x.com"}}), encoding="utf-8")
    monkeypatch.delenv("ARELIS_INGEST_TOKEN", raising=False)
    first = ensure_ingest_token(path=path)
    second = ensure_ingest_token(path=path)
    assert first
    assert first == second
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["sms"]["ingest_token"] == first
    assert raw["email"]["address"] == "me@x.com"


def test_match_contact_label_strips_emoji() -> None:
    book = _book(
        wife={
            "name": "Robin Hale",
            "phone": "+15551112222",
            "aliases": ("robbie",),
        }
    )
    assert match_contact_label("My Wife 💋", book) is book["wife"]
    assert match_contact_label("Robin Hale", book) is book["wife"]


def test_parse_ingest_resolves_name() -> None:
    book = _book(wife={"name": "Robin Hale", "phone": "5551112222"})
    msg = parse_ingest_payload(
        {"id": "n1", "from": "My Wife", "body": "I love you too"},
        contacts=book,
    )
    assert msg is not None
    assert msg.contact_name == "Robin Hale"
    assert msg.body == "I love you too"


def test_parse_ingest_photo_bytes(tmp_path: Path, monkeypatch) -> None:
    """Companion JPEG extras become a file, not a blank bubble."""
    import base64

    from arelis import sms_media

    monkeypatch.setattr(sms_media, "media_dir", lambda: tmp_path)
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6360000002000100ffff03000006000557bf0000000049454e44ae426082"
    )
    book = _book(wife={"name": "Robin", "phone": "555-0100"})
    msg = parse_ingest_payload(
        {
            "id": "pic1",
            "from": "Robin",
            "body": "Photo",
            "image_jpeg": base64.b64encode(png).decode("ascii"),
        },
        contacts=book,
    )
    assert msg is not None
    assert msg.media_kind == "image"
    assert msg.media_path
    assert Path(msg.media_path).is_file()


async def test_publish_swallows_stale_companion_dump(tmp_path: Path) -> None:
    bus = EventBus()
    received: list[dict] = []

    async def capture(event) -> None:
        if event.type == EventType.SMS_RECEIVED:
            received.append(dict(event.payload))

    bus.subscribe(EventType.SMS_RECEIVED, capture)
    task = asyncio.create_task(bus.run())
    seen = SeenMessageStore(tmp_path / "seen.json")
    old = InboundSms(
        id="old-sync",
        sender="+15550100",
        body="from last month",
        time="2020-01-01T00:00:00Z",
    )
    assert await publish_inbound(bus, old, seen=seen) is False
    await asyncio.sleep(0.05)
    assert received == []
    assert seen.has("old-sync")
    bus.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_publish_dedupes_same_body_different_ids(tmp_path: Path) -> None:
    """Ticker and body POSTs with the same text must not ring twice."""
    bus = EventBus()
    received: list[dict] = []

    async def capture(event) -> None:
        if event.type == EventType.SMS_RECEIVED:
            received.append(dict(event.payload))

    bus.subscribe(EventType.SMS_RECEIVED, capture)
    task = asyncio.create_task(bus.run())
    seen = SeenMessageStore(tmp_path / "seen.json")
    book = _book(wife={"name": "Robin", "phone": "555-0100"})
    first = parse_ingest_payload(
        {"id": "tick1", "from": "Robin", "body": "dedupe-fixture-body"},
        contacts=book,
    )
    second = parse_ingest_payload(
        {"id": "tick2", "from": "Robin", "body": "dedupe-fixture-body"},
        contacts=book,
    )
    assert first is not None and second is not None
    assert await publish_inbound(bus, first, seen=seen) is True
    assert await publish_inbound(bus, second, seen=seen) is False
    await asyncio.sleep(0.05)
    assert len(received) == 1
    bus.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_publish_dedupes(tmp_path: Path) -> None:
    bus = EventBus()
    received: list[dict] = []

    async def capture(event) -> None:
        if event.type == EventType.SMS_RECEIVED:
            received.append(dict(event.payload))

    bus.subscribe(EventType.SMS_RECEIVED, capture)
    task = asyncio.create_task(bus.run())
    seen = SeenMessageStore(tmp_path / "seen.json")
    book = _book(wife={"name": "Robin", "phone": "5551112222"})
    msg = parse_ingest_payload(
        {"id": "dup1", "from": "Robin", "body": "hi"},
        contacts=book,
    )
    assert msg is not None
    assert await publish_inbound(bus, msg, seen=seen) is True
    assert await publish_inbound(bus, msg, seen=seen) is False
    await asyncio.sleep(0.05)
    assert len(received) == 1
    bus.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_ingest_http_server(tmp_path: Path) -> None:
    bus = EventBus()
    received: list[dict] = []

    async def capture(event) -> None:
        if event.type == EventType.SMS_RECEIVED:
            received.append(dict(event.payload))

    bus.subscribe(EventType.SMS_RECEIVED, capture)
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(bus.run())
    seen = SeenMessageStore(tmp_path / "seen.json")
    # Asked for rather than hard-coded. The fixed 18765 is the port the phone
    # talks to, which means a test using it fails whenever a real Arelis is
    # running on the machine, and on Linux it also collided with its own
    # previous run: a listening socket sits in TIME_WAIT after close, and
    # rebinding it without SO_REUSEADDR is refused.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    base = f"http://127.0.0.1:{port}"
    server = InboundIngestServer(
        bus,
        loop,
        token="test-token",
        host="127.0.0.1",
        port=port,
        seen=seen,
    )
    server.start()
    try:
        async with httpx.AsyncClient() as client:
            health = await client.get(f"{base}/inbound/health")
            assert health.status_code == 200
            assert health.json()["ok"] is True
            assert health.json()["port"] == port
            assert health.json()["instance"]
            bad = await client.get(f"{base}/inbound/ping")
            assert bad.status_code == 401
            ping = await client.get(
                f"{base}/inbound/ping",
                headers={"X-Arelis-Token": "test-token"},
            )
            assert ping.status_code == 200
            assert ping.json()["ok"] is True

            post = await client.post(
                f"{base}/inbound/sms",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "id": "notif:abc",
                    "from": "Piper",
                    "body": "G",
                    "source": "notification",
                },
            )
            assert post.status_code == 200
            assert post.json()["published"] is True
        await asyncio.sleep(0.05)
        assert len(received) == 1
        assert received[0]["body"] == "G"
        assert received[0]["source"] == "notification"
    finally:
        server.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_token_ok_falls_back_to_memory_when_disk_read_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A secrets.yaml read that throws must still honor the in-memory token."""
    bus = EventBus()
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(bus.run())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = InboundIngestServer(
        bus,
        loop,
        token="memory-token",
        host="127.0.0.1",
        port=port,
        seen=SeenMessageStore(tmp_path / "seen.json"),
    )
    server.start()

    def _boom() -> str | None:
        raise OSError("pairing code file unreadable")

    monkeypatch.setattr("arelis.sms_ingest.load_ingest_token", _boom)
    try:
        async with httpx.AsyncClient() as client:
            ping = await client.get(
                f"http://127.0.0.1:{port}/inbound/ping",
                headers={"X-Arelis-Token": "memory-token"},
            )
        assert ping.status_code == 200
        assert ping.json()["ok"] is True
    finally:
        server.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_inbound_sms_tool_lists_recent() -> None:
    log = RecentInboundLog(limit=5)
    from arelis.sms_inbound import InboundSms

    log.record(
        InboundSms(
            id="1",
            sender="+1",
            body="hello",
            time="t",
            contact_name="Robin",
        ),
        source="notification",
    )
    # Swap process log for the tool call.
    import arelis.sms_ingest as mod
    import arelis.tools.inbound_sms as tool_mod

    old = mod.RECENT_INBOUND
    mod.RECENT_INBOUND = log
    tool_mod.RECENT_INBOUND = log
    try:
        result = await InboundSmsTool().run(limit=5)
        assert result.ok
        assert "Robin" in result.output
        assert result.data["count"] == 1
    finally:
        mod.RECENT_INBOUND = old
        tool_mod.RECENT_INBOUND = old
