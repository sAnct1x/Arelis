"""Something else is on the port: whose core just answered?

8765 and 8766 are fixed numbers on an interface every program on the machine
shares, so something else answering there is ordinary. A development server, a
second Arelis run from another checkout, a stale process from before a crash, or
another Windows account's core -- all the same to a caller that decided "a core is
running" from the fact that a socket accepted the connection.

Three failures came out of trusting that, and they read as unrelated bugs:

* the UI bridge attached to whatever answered and republished its traffic onto
  this bus;
* the second-instance path handed its request to a stranger and reported success,
  so launching Arelis did nothing and no window appeared;
* the SMS readiness chip went green off somebody else's health endpoint while
  this user's own ingest had never bound.

Two rules fix it and these tests pin them. Every loopback service says which copy
of Arelis it belongs to (``arelis.identity``), and every client requires a match.
Ports fall forward to the next free one (``arelis.presence.ports``), so a second
core still works while the first keeps the documented port.

Being a different copy is arranged two ways here, deliberately. Identity itself is
tested by changing ``ARELIS_DATA_DIR``, since a data root is exactly what
distinguishes one copy from another. The tests about *refusing* a stranger instead
make the running server answer with a fixed foreign id, because identity is
computed live from the environment: switching the environment would move the
server's answer along with the client's and the two would agree again, testing
nothing.

The sharpest case is two Windows accounts signed into one PC, where the traffic
being republished belongs to another person rather than to a stray socket. It is
uncommon, it is not the reason any of this exists, and it is the one case a test on
a single machine cannot really stand in for -- ``ARELIS_DATA_DIR`` reproduces the
resolution rules, not fast user switching.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from pathlib import Path
from typing import Any

import pytest

from arelis.core.bus import EventBus
from arelis.presence.inbound_runtime import attach_inbound
from arelis.presence.ipc_client import IpcClient
from arelis.presence.ipc_server import IpcServer
from arelis.presence.lock import find_my_ingest_port, probe_ingest_health
from arelis.presence.ports import candidates

# Any value that is not this machine's. Sixteen hex characters, matching the real
# shape, so nothing passes for the wrong reason.
STRANGER = "0123456789abcdef"


@pytest.fixture
def ipc_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """One account's data root, with the session token the bridge requires.

    The UI client and the second-instance path read this file when they
    connect. Without it the server closes the hello, and every test below
    that expects a live bridge would fail for that reason instead of the
    one it names.
    """
    root = tmp_path / "me"
    monkeypatch.setenv("ARELIS_DATA_DIR", str(root))
    from arelis.presence.ipc_token import ensure_token

    ensure_token(rotate=True)
    return root


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _hold(port: int) -> socket.socket:
    """Occupy a port the way another account's Arelis would."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", port))
    sock.listen(1)
    return sock


def _echo_requests(stop: threading.Event) -> tuple[socket.socket, threading.Thread]:
    """Listen and write each request back.

    A loopback socket connected to itself does this: the bytes just sent are
    the bytes read next. The health probe has to treat that as silence.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(0.2)

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _addr = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(1.0)
                data = b""
                try:
                    while b"\r\n\r\n" not in data and len(data) < 8192:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    if data:
                        conn.sendall(data)
                except OSError:
                    pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return srv, thread


def _sms_config(port: int) -> dict[str, Any]:
    return {
        "tools": {
            "sms": {
                "enabled": True,
                "inbound": {
                    "enabled": True,
                    "fallback_smsgate": False,
                    "ingest": {"enabled": True, "host": "127.0.0.1", "port": port},
                },
                "auto_reply": {"enabled": False},
            }
        }
    }


# --------------------------------------------------------------- who am I


# ------------------------------------------------------------ port choice


# ------------------------------------------------- inbound ingest, port taken


async def test_ingest_falls_forward_when_the_port_is_taken(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The second account's inbound must work, and be told where it landed.

    Before this, ``attach_inbound`` caught the bind error and emitted a status
    line containing a WinError number. Inbound was simply dead for the second
    user and the only clue was a code.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "bob"))
    monkeypatch.setenv("ARELIS_INGEST_TOKEN", "test-token-xyz")
    preferred = _free_port()
    occupied = _hold(preferred)

    bus = EventBus()
    loop = asyncio.get_running_loop()
    bus_task = asyncio.create_task(bus.run())
    runtime = attach_inbound(bus, loop, _sms_config(preferred), owned=True)
    try:
        assert runtime.ingest is not None, "ingest gave up instead of moving"
        assert runtime.ingest.port != preferred
        assert runtime.ingest.port in candidates(preferred)
        assert runtime.ingest.running
        # The user has to learn that the URL already in their phone is stale.
        joined = " ".join(runtime.status_messages)
        assert "Phone notifications moved to a new spot" in joined
        assert str(preferred) not in joined
        assert str(runtime.ingest.port) not in joined
    finally:
        await runtime.stop()
        occupied.close()
        bus.stop()
        bus_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bus_task


async def test_health_names_the_owner_and_probes_can_require_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``mine_only`` is what makes scanning for a core safe.

    One live server, asked twice: once while it answers as us and once while it
    answers as another account. The plain probe must keep saying "something is
    serving here", because callers like the hardware harness and the Settings
    test button are asking literally that.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "alice"))
    monkeypatch.setenv("ARELIS_INGEST_TOKEN", "test-token-xyz")
    port = _free_port()

    bus = EventBus()
    loop = asyncio.get_running_loop()
    bus_task = asyncio.create_task(bus.run())
    config = _sms_config(port)
    runtime = attach_inbound(bus, loop, config, owned=True)
    try:
        assert runtime.ingest is not None
        assert probe_ingest_health(port=port, timeout_s=2.0)
        assert probe_ingest_health(port=port, timeout_s=2.0, mine_only=True)
        assert find_my_ingest_port(config) == port

        monkeypatch.setattr("arelis.sms_ingest.instance_id", lambda: STRANGER)
        assert probe_ingest_health(port=port, timeout_s=2.0), (
            "something is still serving, and the plain probe must still say so"
        )
        assert not probe_ingest_health(port=port, timeout_s=2.0, mine_only=True)
        assert find_my_ingest_port(config) is None, (
            "another account's ingest was accepted as this user's own"
        )
    finally:
        await runtime.stop()
        bus.stop()
        bus_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await bus_task


# ------------------------------------------------------ the UI/core bridge


async def test_the_bridge_refuses_another_accounts_core(
    monkeypatch: pytest.MonkeyPatch, ipc_home: Path
) -> None:
    """The leak, stated as the thing that must not happen.

    Some other Arelis is listening and this UI connects to it. Before the
    handshake it attached and began republishing that copy's inbound texts and
    confirmation prompts onto this bus -- noise at best, and somebody else's
    messages when the other copy belongs to another person.
    """
    monkeypatch.setattr("arelis.presence.ipc_server.instance_id", lambda: STRANGER)
    assert ipc_home.is_dir()

    their_bus = EventBus()
    their_task = asyncio.create_task(their_bus.run())
    port = _free_port()
    their_core = IpcServer(their_bus, host="127.0.0.1", port=port)
    await their_core.start()

    my_bus = EventBus()
    my_task = asyncio.create_task(my_bus.run())
    my_ui = IpcClient(my_bus, host="127.0.0.1", port=port, reconnect_s=0.05)
    my_ui.start()
    try:
        for _ in range(20):
            await asyncio.sleep(0.05)
            assert not my_ui.attached, "attached to another account's core"
    finally:
        await my_ui.stop()
        await their_core.stop()
        their_bus.stop()
        my_bus.stop()
        for task in (their_task, my_task):
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


