"""Two accounts, one PC, one loopback interface: whose core is that?

Arelis has no logins. Windows separates accounts, ``%LOCALAPPDATA%`` separates
state, and the presence locks are per user, so two people signed into one PC can
each run a core. What none of that separates is the loopback interface. Both
cores want 8765 for inbound texts and 8766 for the UI bridge, and "is a core
running?" was answered by connecting and seeing a reply.

That produced three failures, and the first is the serious one:

* the second user's UI attached to the first user's core, republishing their
  inbound texts and confirmation prompts onto the second user's bus;
* the second-instance path raised the first user's window and reported success,
  so for the second user, launching Arelis did nothing at all;
* the SMS readiness chip went green off the other account's healthy ingest while
  the user's own had never bound.

The fix is two rules that these tests pin. Every loopback service says which
account it belongs to (``arelis.identity``), and every client requires a match.
Ports fall forward to the next free one (``arelis.presence.ports``) so the second
core still works, with the first user keeping the documented port.

Being another account is done two ways here, deliberately. Identity itself is
tested by changing ``ARELIS_DATA_DIR``, since to this code an account *is* a data
root. The cross-account tests instead make the running server answer with a fixed
foreign id, because identity is computed live from the environment: switching the
environment would change the server's answer along with the client's and the two
would agree again, testing nothing.

Verifying the real thing on two real Windows profiles is still outstanding, and
no test on one machine can stand in for it.
"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any

import pytest

from arelis import identity
from arelis.core.bus import EventBus
from arelis.presence.inbound_runtime import attach_inbound
from arelis.presence.ipc_client import IpcClient
from arelis.presence.ipc_server import IpcServer
from arelis.presence.lock import find_my_ingest_port, probe_ingest_health
from arelis.presence.ports import PORT_SEARCH_SPAN, candidates

# Any value that is not this machine's. Sixteen hex characters, matching the real
# shape, so nothing passes for the wrong reason.
STRANGER = "0123456789abcdef"


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


def test_two_data_roots_are_two_instances(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The identity is the account, and the account is the data root.

    Derived rather than stored, so there is no file to be missing on a read-only
    profile and no first run to seed it.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "alice"))
    alice = identity.instance_id()
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "bob"))
    bob = identity.instance_id()

    assert alice != bob
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "alice"))
    assert identity.instance_id() == alice, "identity must survive a restart"


def test_identity_is_case_insensitive_like_windows_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``C:\\Users`` and ``c:\\users`` are one account, not two."""
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "Alice"))
    upper = identity.instance_id()
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "Alice").lower())
    assert identity.instance_id() == upper


def test_an_unnamed_service_is_treated_as_someone_elses() -> None:
    """The direction to be wrong in, if we must be wrong.

    An Arelis predating this handshake sends no instance. Guessing it is ours
    reopens the cross-account leak; guessing it is not costs a second core on a
    second port. Only one of those is recoverable.
    """
    assert not identity.is_mine(None)
    assert not identity.is_mine("")
    assert not identity.is_mine("   ")
    assert not identity.is_mine(12345)
    assert identity.is_mine(identity.instance_id())


# ------------------------------------------------------------ port choice


def test_the_preferred_port_comes_first() -> None:
    """The single-user install must be untouched by any of this.

    If the first Arelis to start did not get 8765, every setup instruction and
    every already-configured phone companion would be wrong, for no benefit.
    """
    assert candidates(8765)[0] == 8765
    assert candidates(8765) == list(range(8765, 8765 + PORT_SEARCH_SPAN))


def test_port_zero_is_left_alone() -> None:
    """"Let the OS choose" cannot collide, so scanning would be nonsense.

    Without this it would expand to ports 1 to 6, which are privileged.
    """
    assert candidates(0) == [0]


def test_candidates_never_wrap_past_the_ceiling() -> None:
    """Wrapping would offer a low privileged port as the next candidate."""
    assert candidates(65534) == [65534, 65535]
    assert candidates(70000) == []


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
        assert str(runtime.ingest.port) in joined
        assert "already in use" in joined
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
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The leak, stated as the thing that must not happen.

    Another account's core is listening and this UI connects to it. Before the
    handshake it attached and began republishing that account's inbound texts and
    confirmation prompts onto this bus.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "me"))
    monkeypatch.setattr("arelis.presence.ipc_server.instance_id", lambda: STRANGER)

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


async def test_the_bridge_still_attaches_to_its_own_core(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The check must not be so strict that ordinary use breaks.

    One account, one core, one UI: the overwhelmingly common case, and the one it
    would be catastrophic to regress in the name of the rare one.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "me"))
    core_bus = EventBus()
    ui_bus = EventBus()
    core_task = asyncio.create_task(core_bus.run())
    ui_task = asyncio.create_task(ui_bus.run())
    port = _free_port()
    core = IpcServer(core_bus, host="127.0.0.1", port=port)
    await core.start()
    ui = IpcClient(ui_bus, host="127.0.0.1", port=port, reconnect_s=0.1)
    ui.start()
    try:
        for _ in range(50):
            if ui.attached:
                break
            await asyncio.sleep(0.05)
        assert ui.attached
    finally:
        await ui.stop()
        await core.stop()
        core_bus.stop()
        ui_bus.stop()
        for task in (core_task, ui_task):
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


async def test_the_core_bridge_moves_up_a_port_and_the_ui_finds_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The bind failure that used to vanish, and the search that recovers it.

    ``IpcServer.start()`` is launched as a task in ``arelis.presence.core``, so
    the second account's bind error was an unretrieved task exception: the UI
    received no core events, with nothing on screen to connect that to a port.
    The UI scans because it cannot know in advance whether its own core got the
    configured port.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "me"))
    preferred = _free_port()
    occupied = _hold(preferred)

    core_bus = EventBus()
    ui_bus = EventBus()
    core_task = asyncio.create_task(core_bus.run())
    ui_task = asyncio.create_task(ui_bus.run())
    core = IpcServer(core_bus, host="127.0.0.1", port=preferred)
    await core.start()
    assert core.port != preferred
    assert core.port in candidates(preferred)

    ui = IpcClient(
        ui_bus,
        host="127.0.0.1",
        port=preferred,
        reconnect_s=0.1,
        search_ports=True,
    )
    ui.start()
    try:
        for _ in range(60):
            if ui.attached:
                break
            await asyncio.sleep(0.05)
        assert ui.attached, "the UI never found its own core one port along"
    finally:
        await ui.stop()
        await core.stop()
        occupied.close()
        core_bus.stop()
        ui_bus.stop()
        for task in (core_task, ui_task):
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


async def test_a_client_given_one_port_does_not_wander(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Searching is opt-in, because a caller naming a port means that port.

    Otherwise a client could silently attach to a neighbouring service that had
    nothing to do with what it was asked to connect to.
    """
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "me"))
    core_bus = EventBus()
    ui_bus = EventBus()
    core_task = asyncio.create_task(core_bus.run())
    ui_task = asyncio.create_task(ui_bus.run())
    core_port = _free_port()
    core = IpcServer(core_bus, host="127.0.0.1", port=core_port)
    await core.start()

    # Ask for the port just below the real one, with searching off.
    ui = IpcClient(ui_bus, host="127.0.0.1", port=core_port - 1, reconnect_s=0.05)
    ui.start()
    try:
        for _ in range(10):
            await asyncio.sleep(0.05)
            assert not ui.attached
    finally:
        await ui.stop()
        await core.stop()
        core_bus.stop()
        ui_bus.stop()
        for task in (core_task, ui_task):
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
