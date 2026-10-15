"""The loopback bridge is not a public bulletin board.

8766 accepts any connection from the machine. Before a session token, the
server added that socket to the broadcast set on accept, so a program that
never said hello still received confirm cards (a draft mail body included)
and inbound texts, and could allow a send or shut the core down.

The token lives in the user's state directory. The user never types it.
A hello without it is refused, and nothing is forwarded until the hello
checks out.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.paths import state_dir
from arelis.presence.ipc import decode_line, encode_line
from arelis.presence.ipc_server import IpcServer


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _plant_token(token: str) -> None:
    """Write the session file the way a seat would, without importing the helper.

    The guard below has to pass on a server that does not know about tokens
    yet, so the plant is just the file both sides will read once they do.
    """
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "ipc.token"
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, token.encode("ascii"))
    finally:
        os.close(fd)


class _Running:
    def __init__(self, bus: EventBus, task: asyncio.Task[None], server: IpcServer) -> None:
        self.bus = bus
        self.task = task
        self.server = server

    async def close(self) -> None:
        await self.server.stop()
        self.bus.stop()
        self.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await self.task


async def _start(**kwargs: object) -> _Running:
    bus = EventBus()
    task = asyncio.create_task(bus.run())
    port = _free_port()
    server = IpcServer(bus, host="127.0.0.1", port=port, **kwargs)  # type: ignore[arg-type]
    await server.start()
    return _Running(bus, task, server)


async def _open(server: IpcServer) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
    # Let the accept handler reach its read, so a broadcast that happens
    # next is not lost on a client the server has not recorded yet.
    await asyncio.sleep(0.05)
    return reader, writer


async def test_hello_without_token_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A hello with no session token gets an auth error, not an ack.

    Main answers hello_ack. That ack is what used to open the rest of the
    conversation: confirms, shutdown, and the live event stream.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    _plant_token(secrets.token_urlsafe(32))
    running = await _start()
    try:
        reader, writer = await _open(running.server)
        try:
            writer.write(encode_line({"op": "hello", "role": "ui", "version": 1}))
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=1.0)
        finally:
            writer.close()
            await writer.wait_closed()
        msg = decode_line(line)
        assert msg is not None
        assert msg.get("op") == "error"
        assert msg.get("reason") == "auth"
        assert running.server.attached_clients == 0
    finally:
        await running.close()


async def test_confirm_reply_without_hello_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Allow and skip are a human decision. A stranger socket cannot cast one.

    Main publishes TOOL_CONFIRM_REPLY for a confirm_reply that arrived
    before any hello.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    token = secrets.token_urlsafe(32)
    _plant_token(token)
    replies: list[Event] = []

    def capture(event: Event) -> None:
        if event.type == EventType.TOOL_CONFIRM_REPLY:
            replies.append(event)

    running = await _start()
    running.bus.subscribe(EventType.TOOL_CONFIRM_REPLY, capture)
    try:
        _reader, writer = await _open(running.server)
        try:
            writer.write(
                encode_line({"op": "confirm_reply", "id": "c1", "decision": "allow"})
            )
            try:
                await writer.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            await asyncio.sleep(0.3)
            await running.bus.drain()
            assert replies == []
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

        # A good hello on a new socket still carries the decision. The first
        # socket was closed for speaking before it authenticated.
        reader, writer = await _open(running.server)
        try:
            writer.write(
                encode_line(
                    {"op": "hello", "role": "ui", "version": 1, "token": token}
                )
            )
            await writer.drain()
            ack = decode_line(await asyncio.wait_for(reader.readline(), timeout=1.0))
            assert ack is not None and ack.get("op") == "hello_ack"
            writer.write(
                encode_line({"op": "confirm_reply", "id": "c1", "decision": "allow"})
            )
            await writer.drain()
            for _ in range(20):
                if replies:
                    break
                await asyncio.sleep(0.02)
            await running.bus.drain()
            assert len(replies) == 1
            assert replies[0].payload.get("decision") == "allow"
            assert replies[0].payload.get("id") == "c1"
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        await running.close()


async def test_socket_that_never_said_hello_gets_no_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A connected socket is not a subscriber.

    Main forwards TOOL_CONFIRM, body and all, to every accepted socket.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    _plant_token(secrets.token_urlsafe(32))
    running = await _start()
    body = "draft the picnic list"
    try:
        reader, writer = await _open(running.server)
        try:
            await running.bus.publish(
                Event(
                    EventType.TOOL_CONFIRM,
                    {
                        "id": "c1",
                        "tool": "send_email",
                        "full_args": {"body": body},
                    },
                )
            )
            await running.bus.drain()
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=0.3)
            except TimeoutError:
                line = b""
            assert body.encode("utf-8") not in line
            assert not line.strip()
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        await running.close()


def _old_token(label: str) -> bytes:
    """A token already on disk, so a no-op startup is visible."""
    token = f"old-{label}-token-0123456789abcdef"
    _plant_token(token)
    from arelis.presence.ipc_token import token_path

    return token_path().read_bytes()


def _assert_rotated(previous: bytes) -> None:
    from arelis.presence.ipc_token import read_token, token_path

    current = token_path().read_bytes()
    assert current != previous, "seat start left the old session token in place"
    text = read_token()
    assert text is not None
    assert len(text) >= 32
    assert text.encode("ascii") == current


