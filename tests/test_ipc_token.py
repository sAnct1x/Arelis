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
from arelis.presence.activate import activate_existing_ui
from arelis.presence.ipc import decode_line, encode_line
from arelis.presence.ipc_client import IpcClient
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


async def test_shutdown_needs_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Quit from the tray is a real hello. A bare shutdown is not.

    Main calls the shutdown hook for a socket that never authenticated.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    token = secrets.token_urlsafe(32)
    _plant_token(token)
    stopped: list[str] = []
    running = await _start(on_shutdown=lambda reason: stopped.append(str(reason)))
    try:
        reader, writer = await _open(running.server)
        try:
            writer.write(encode_line({"op": "shutdown", "reason": "quit"}))
            await writer.drain()
            await asyncio.sleep(0.3)
            assert stopped == []
        finally:
            writer.close()
            await writer.wait_closed()

        reader, writer = await _open(running.server)
        try:
            writer.write(
                encode_line({"op": "hello", "role": "ui", "version": 1, "token": token})
            )
            await writer.drain()
            ack = decode_line(await asyncio.wait_for(reader.readline(), timeout=1.0))
            assert ack is not None and ack.get("op") == "hello_ack"
            writer.write(encode_line({"op": "shutdown", "reason": "quit"}))
            await writer.drain()
            for _ in range(20):
                if stopped:
                    break
                await asyncio.sleep(0.02)
            assert stopped == ["quit"]
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        await running.close()


async def test_ui_client_with_file_token_attaches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The ordinary case: one account, the token file, the UI attaches.

    This is the guard. A token check that refuses the real UI is worse than
    the leak it closes.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    _plant_token(secrets.token_urlsafe(32))
    core_bus = EventBus()
    ui_bus = EventBus()
    core_task = asyncio.create_task(core_bus.run())
    ui_task = asyncio.create_task(ui_bus.run())
    seen: list[Event] = []

    def capture(event: Event) -> None:
        if event.type == EventType.TOOL_CONFIRM and not (event.payload or {}).get(
            "_from_ipc"
        ):
            return
        if event.type == EventType.TOOL_CONFIRM:
            seen.append(event)

    ui_bus.subscribe(EventType.TOOL_CONFIRM, capture)
    port = _free_port()
    core = IpcServer(core_bus, host="127.0.0.1", port=port)
    await core.start()
    ui = IpcClient(ui_bus, host="127.0.0.1", port=port, reconnect_s=0.05)
    ui.start()
    try:
        for _ in range(50):
            if ui.attached:
                break
            await asyncio.sleep(0.05)
        assert ui.attached
        await core_bus.publish(
            Event(
                EventType.TOOL_CONFIRM,
                {"id": "c9", "tool": "send_email", "full_args": {"body": "ok"}},
            )
        )
        await core_bus.drain()
        for _ in range(20):
            if seen:
                break
            await asyncio.sleep(0.05)
        assert seen, "an attached UI received no confirm event"
        assert seen[0].payload.get("full_args", {}).get("body") == "ok"
    finally:
        await ui.stop()
        await core.stop()
        core_bus.stop()
        ui_bus.stop()
        for task in (core_task, ui_task):
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


async def test_activate_with_wrong_token_returns_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A second launch whose token does not match must not report success.

    Success means the running window was asked to come forward, and the
    caller then exits. A wrong True is a click that does nothing, or worse,
    a click that raises somebody else's window. Main treats any hello as
    enough.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    _plant_token(secrets.token_urlsafe(32))
    raised: list[str] = []
    running = await _start(
        seat="ui",
        on_open_ui=lambda reason: raised.append(str(reason)),
    )
    try:
        import arelis.presence.activate as activate_mod

        if hasattr(activate_mod, "read_token"):
            monkeypatch.setattr(
                activate_mod, "read_token", lambda: "not-the-session-token"
            )
        ok = await asyncio.to_thread(
            activate_existing_ui,
            {
                "presence": {
                    "ipc_host": "127.0.0.1",
                    "ipc_port": running.server.port,
                }
            },
        )
        assert ok is False
        assert raised == []
    finally:
        await running.close()


@pytest.mark.skipif(os.name == "nt", reason="mode bits are a POSIX check")
def test_token_file_is_user_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The session file is owner-read and owner-write, and nobody else.

    The directory on Windows is already per-account under LOCALAPPDATA.
    This pins the POSIX mode the writer asks for.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    from arelis.presence.ipc_token import ensure_token, token_path

    token = ensure_token(rotate=True)
    path = token_path()
    assert path.is_file()
    assert (path.stat().st_mode & 0o777) == 0o600
    assert path.read_text(encoding="ascii").strip() == token
    assert "\n" not in token
    assert len(token) >= 32


def test_second_process_reads_not_rotates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The second seat of a session reads the token. It does not replace it.

    The glass and the core share one file. If whichever starts second
    minted a new token, the one already listening would reject the hello
    and the bridge would stay down.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    from arelis.presence.ipc_token import claim_session_token, read_token, token_path
    from arelis.presence.lock import PresenceLock, core_lock_path, ui_lock_path

    ui = PresenceLock(ui_lock_path({}))
    assert ui.acquire()
    try:
        first = claim_session_token(PresenceLock(core_lock_path({})))
        assert first
        assert read_token() == first
        written = token_path().read_bytes()

        core = PresenceLock(core_lock_path({}))
        assert core.acquire()
        try:
            second = claim_session_token(PresenceLock(ui_lock_path({})))
            assert second == first
            assert token_path().read_bytes() == written
        finally:
            core.release()
    finally:
        ui.release()


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


def test_starting_a_seat_rotates_the_session_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qt_app
) -> None:
    """run_core and run_ui are what rotate the token. The helper is not.

    The other tests call claim_session_token themselves. Deleting the call
    in presence/core.py or ui/launch.py left them green. Each seat is
    started here the way production starts it, with ingest, the tray, and
    the window faked, and the file on disk has to change.
    """
    import threading as thread_mod

    from arelis.presence import core as core_mod
    from arelis.ui import launch as launch_mod

    real_event = thread_mod.Event

    class _Event(real_event):
        def wait(self, timeout: float | None = None):
            # The core sits in stop.wait(3600) until quit. Return at once
            # so this test observes the token and lets the seat shut down.
            # Every other wait, including thread startup, stays real.
            if timeout == 3600:
                return True
            return super().wait(timeout)

    loops: list[asyncio.AbstractEventLoop] = []
    real_new_loop = core_mod.asyncio.new_event_loop

    def _capture_loop() -> asyncio.AbstractEventLoop:
        loop = real_new_loop()
        loops.append(loop)
        return loop

    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "core"))
    previous = _old_token("core")

    class _QuietInbound:
        status_messages: list[str] = []

        async def stop(self) -> None:
            return None

    async def _bus_done(self) -> None:
        # run_core stops the loop while bus.run is still blocked on the
        # queue. That pending read becomes an unraisable error once the
        # loop is closed. The token claim happens before the bus starts,
        # so this stand-in does not weaken the assertion.
        return None

    monkeypatch.setattr(thread_mod, "Event", _Event)
    monkeypatch.setattr(core_mod.asyncio, "new_event_loop", _capture_loop)
    monkeypatch.setattr(core_mod.EventBus, "run", _bus_done)
    monkeypatch.setattr(core_mod, "attach_event_audit", lambda *_a, **_k: None)
    monkeypatch.setattr(core_mod, "attach_inbound", lambda *_a, **_k: _QuietInbound())
    monkeypatch.setattr("arelis.guard.attach_watch", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "arelis.jobs.schedule.repoint_moved_tasks_on_launch", lambda: []
    )
    assert (
        core_mod.run_core(
            {"presence": {"ipc_enabled": False, "core_tray": False}}
        )
        == 0
    )
    for loop in loops:
        loop.close()
    _assert_rotated(previous)
    monkeypatch.setattr(thread_mod, "Event", real_event)

    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "glass"))
    previous = _old_token("glass")
    monkeypatch.setattr(launch_mod, "configure_native_windows", lambda: None)
    monkeypatch.setattr(launch_mod, "configure_display_scale", lambda _cfg: None)
    monkeypatch.setattr(launch_mod, "force_windows_qt_platform", lambda _env: None)
    monkeypatch.setattr("arelis.core.seat.bind_workspace", lambda _cfg: None)
    monkeypatch.setattr("arelis.ui.solar_gl.prepare_desktop_gl", lambda _env: None)
    monkeypatch.setattr("arelis.ui.solar_gl.gl_wanted", lambda: False)
    monkeypatch.setattr(launch_mod, "qt_font_directory", lambda: tmp_path)
    monkeypatch.setattr(launch_mod, "apply_theme", lambda _t: None)
    monkeypatch.setattr(launch_mod, "load_fonts", lambda: {})
    monkeypatch.setattr(launch_mod, "app_font", lambda _families: qt_app.font())
    monkeypatch.setattr(launch_mod, "stylesheet", lambda: "")
    monkeypatch.setattr(launch_mod, "theme_from_config", lambda _c: None)
    monkeypatch.setattr(launch_mod, "app_icon_path", lambda: tmp_path / "missing.ico")
    monkeypatch.setattr(
        launch_mod,
        "apply_first_run_glass",
        lambda config, config_was_given=False: None,
    )
    monkeypatch.setattr("arelis.ui.dialog.notice", lambda *_a, **_k: None)

    assert launch_mod.run_ui({"presence": {}}) == 1
    _assert_rotated(previous)
