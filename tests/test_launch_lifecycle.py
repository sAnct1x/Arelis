"""Launching, closing and relaunching — the parts of it that a test can reach.

Three of the four defects behind this file are only observable as pixels or as
process counts, and are verified by hand instead
(arelis/ui/_verify_tray_restore.py for the window measurements). What is left
here is everything with a decidable answer:

  - a floating instrument is a top-level window of its own, so hiding the glass
    has to take it along or it is left orphaned on the desktop
  - a second launch has to reach the first one, which means something has to be
    listening when no core is running
  - the loop has to stop with nothing still writing to memory.db
  - the desktop shortcut must not go through a console program

The console-flash test looks like it is testing a script rather than the program.
It is: the flash is invisible in every automated check and unmissable to the
person launching, so the only durable guard is on the shape of the shortcut.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from arelis.core.bus import EventBus
from arelis.presence.ipc import open_ui_request_message
from arelis.presence.ipc_server import IpcServer

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _float(dock) -> None:
    dock.show()
    dock.setFloating(True)
    dock.show()


def test_hiding_the_glass_takes_its_floating_instruments_with_it(arelis_window) -> None:
    window = arelis_window()
    _float(window.think_dock)
    assert window.think_dock.isVisible()

    window._park_floating_docks()
    assert not window.think_dock.isVisible(), (
        "a floating dock left visible with the glass hidden is an orphan panel, "
        "which is what 'two Arelises stacked' turned out to be"
    )

    window._unpark_floating_docks()
    assert window.think_dock.isVisible()
    assert window.think_dock.isFloating()


def test_parking_leaves_docked_instruments_alone(arelis_window) -> None:
    """Only top-level docks are the problem; a docked one goes with its parent."""
    window = arelis_window()
    window.think_dock.setFloating(False)
    window.think_dock.show()
    window._park_floating_docks()
    assert not getattr(window.think_dock, "_arelis_parked", False)


def test_unparking_only_restores_what_was_parked(arelis_window) -> None:
    """Coming back with a panel the user had closed would be its own bug."""
    window = arelis_window()
    _float(window.think_dock)
    window.think_dock.hide()
    window._unpark_floating_docks()
    assert not window.think_dock.isVisible()


def test_parking_does_not_uncheck_the_view_menu(arelis_window) -> None:
    """The dock is coming back, so the menu must not record it as turned off."""
    window = arelis_window()
    _float(window.think_dock)
    window.act_thinking.setChecked(True)
    window._park_floating_docks()
    assert window.act_thinking.isChecked()


def test_minimizing_parks_them_too(arelis_window) -> None:
    """The title bar is the other way to take the glass off screen.

    The state change is delivered by hand because the offscreen platform these
    tests run on has no taskbar to minimize into and never sends one. What is
    being checked is the handler: given a minimized window and the event Qt sends
    on any real platform, the floating panels go with it.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QWindowStateChangeEvent

    window = arelis_window()
    window.show()
    _float(window.think_dock)

    window.setWindowState(Qt.WindowState.WindowMinimized)
    window.changeEvent(QWindowStateChangeEvent(Qt.WindowState.WindowNoState))
    assert not window.think_dock.isVisible()

    window.setWindowState(Qt.WindowState.WindowNoState)
    window.changeEvent(QWindowStateChangeEvent(Qt.WindowState.WindowMinimized))
    assert window.think_dock.isVisible()


def test_restore_comes_back_to_the_size_it_left_at(arelis_window, qt_app) -> None:
    """showNormal() answered 'not maximized' whatever the window had been.

    Restoring a maximized glass at its restored-down size means Windows presents
    the full-screen frame it kept and then the smaller one, which is the second
    Arelis people were seeing underneath the first.
    """
    from PySide6.QtCore import Qt

    window = arelis_window()
    window.showMaximized()
    qt_app.processEvents()
    window._remember_window_state()
    window.hide()
    window.show_from_tray()
    qt_app.processEvents()
    assert window.windowState() & Qt.WindowState.WindowMaximized


def test_remembering_a_state_never_remembers_minimized(arelis_window) -> None:
    """Nobody asking for the window wants it back in the taskbar."""
    from PySide6.QtCore import Qt

    window = arelis_window()
    window.setWindowState(Qt.WindowState.WindowMinimized)
    window._remember_window_state()
    assert not (window._tray_window_state & Qt.WindowState.WindowMinimized)


@pytest.mark.asyncio
async def test_a_ui_hosted_server_answers_open_ui_itself() -> None:
    """With no core there was nothing on the bridge port to hear a second launch.

    A core can only pass open_ui on to whoever is attached. A UI hosting the
    server *is* the window being asked for, so it has to act on the request.
    """
    import socket

    bus = EventBus()
    bus_task = asyncio.create_task(bus.run())
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    raised: list[str] = []
    heard = asyncio.Event()

    def _on_open_ui(reason: str) -> None:
        raised.append(reason)
        heard.set()

    server = IpcServer(bus, host="127.0.0.1", port=port, on_open_ui=_on_open_ui)
    await server.start()
    try:
        _reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        import json

        writer.write(
            (json.dumps(open_ui_request_message(reason="second_launch")) + "\n").encode()
        )
        await writer.drain()
        await asyncio.wait_for(heard.wait(), timeout=3.0)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        assert raised == ["second_launch"]
    finally:
        await server.stop()
        bus.stop()
        try:
            await asyncio.wait_for(bus_task, timeout=2)
        except Exception:
            bus_task.cancel()


def test_a_second_launch_that_reaches_the_first_one_exits_quietly(monkeypatch) -> None:
    from arelis.presence import activate
    from arelis.ui import app as app_module

    monkeypatch.setattr(activate, "activate_existing_ui", lambda _cfg: True)
    assert app_module._raise_running_instance({}) == 0


def test_a_second_launch_that_cannot_reach_the_first_one_says_so(
    monkeypatch, qt_app
) -> None:
    """The old behaviour was to exit 0 in silence, so the shortcut did nothing.

    Which is why the owner clicked it again, and again. Anything is better than
    nothing here; a held lock always means a living process, so there is never a
    case where opening a second window would have been right.
    """
    from arelis.presence import activate
    from arelis.ui import app as app_module
    from arelis.ui import dialog

    monkeypatch.setattr(activate, "activate_existing_ui", lambda _cfg: False)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    told: list[str] = []
    monkeypatch.setattr(
        dialog, "notice", lambda *a, **k: told.append(str(a[1]) if len(a) > 1 else "")
    )
    assert app_module._raise_running_instance({}) == 1
    assert told, "a launch that goes nowhere has to tell the person who launched it"


def test_the_retry_is_what_covers_an_instance_still_starting_up(monkeypatch) -> None:
    """A launch two seconds after the last can arrive before the port is bound."""
    from arelis.presence import activate
    from arelis.ui import app as app_module

    class _StillHeld:
        path = Path("unused")

        def acquire(self) -> bool:
            return False

    answers = iter([False, True])
    monkeypatch.setattr(activate, "activate_existing_ui", lambda _cfg: next(answers))
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    assert app_module._second_launch({}, _StillHeld()) == 0


def test_second_launch_opens_once_the_first_one_has_exited(monkeypatch) -> None:
    """Quit drops IPC before the lock; a shortcut in that gap must wait, not stack."""
    from arelis.presence import activate
    from arelis.ui import app as app_module

    class _ThenFree:
        path = Path("unused")
        n = 0

        def acquire(self) -> bool:
            self.n += 1
            return self.n >= 2

    monkeypatch.setattr(activate, "activate_existing_ui", lambda _cfg: False)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    assert app_module._second_launch({}, _ThenFree()) is None


def test_second_launch_that_never_hears_back_says_so(monkeypatch, qt_app) -> None:
    from arelis.presence import activate
    from arelis.ui import app as app_module
    from arelis.ui import dialog

    class _Held:
        path = Path("unused")

        def acquire(self) -> bool:
            return False

    monkeypatch.setattr(activate, "activate_existing_ui", lambda _cfg: False)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    from arelis.ui import launch as launch_module

    monkeypatch.setattr(launch_module, "_HANDOFF_MAX_TRIES", 2)
    told: list[str] = []
    monkeypatch.setattr(
        dialog, "notice", lambda *a, **k: told.append(str(a[1]) if len(a) > 1 else "")
    )
    assert app_module._second_launch({}, _Held()) == 1
    assert told


def test_activation_is_ignored_while_quitting(arelis_window) -> None:
    """Raising a dying window is how a tray-quit relaunch stacked two glasses."""
    window = arelis_window()
    window.hide()
    window._force_quit = True
    window._on_activation_request()
    window.show_from_tray()
    assert window.isHidden()


def test_a_pending_card_does_not_raise_the_glass_while_quitting(arelis_window) -> None:
    """Stop-on-quit used to schedule the next Allow card, which called show."""
    from arelis.presence.pending_confirms import PendingConfirm

    window = arelis_window()
    window.hide()
    window._force_quit = True
    window._pending_queue = [
        PendingConfirm(id="c1", tool="send_sms", summary="text wife", args={})
    ]
    window._show_next_pending_confirm()
    assert window.isHidden()
    assert not window.conversation.confirm._confirm_id


def test_quit_from_tray_forces_quit_before_it_touches_the_turn(
    arelis_window, monkeypatch
) -> None:
    """A dead loop or a next-card timer used to raise the glass and block Quit."""
    from PySide6.QtWidgets import QApplication

    window = arelis_window()
    window.hide()
    seen: list[tuple] = []

    def cancel(*, schedule_next: bool) -> None:
        seen.append(("cancel", window._force_quit, schedule_next))

    def close() -> None:
        seen.append(("close", window._force_quit))

    quits: list[int] = []
    app = QApplication.instance()
    assert app is not None
    monkeypatch.setattr(window, "_cancel_turn", cancel)
    monkeypatch.setattr(window, "close", close)
    monkeypatch.setattr(app, "quit", lambda: quits.append(1))

    window.quit_from_tray()
    assert seen == [("cancel", True, False), ("close", True)]
    assert quits == [1]

    window.quit_from_tray()
    assert seen == [("cancel", True, False), ("close", True)]
    assert quits == [1, 1]


def test_later_is_dropped_while_quitting(arelis_window, qt_app) -> None:
    window = arelis_window()
    window._force_quit = True
    called: list[int] = []
    window._later(0, lambda: called.append(1))
    qt_app.processEvents()
    assert called == []


def test_draining_the_loop_cancels_what_is_still_running() -> None:
    from arelis.ui.app import _drain_event_loop

    loop = asyncio.new_event_loop()
    try:

        async def forever() -> None:
            await asyncio.sleep(3600)

        task = loop.create_task(forever())
        loop.run_until_complete(_drain_event_loop(loop, budget_s=2.0))
        assert task.done()
        assert task.cancelled()
    finally:
        loop.close()


def test_draining_the_loop_waits_for_writes_that_are_already_in_a_thread() -> None:
    """The corruption risk, and the reason cancelling tasks is not sufficient.

    MemoryIndexer does its writing in asyncio.to_thread. Cancelling the task
    abandons the await and leaves the worker thread mid-statement in memory.db,
    which is the state the process used to exit in.
    """
    from arelis.ui.app import _drain_event_loop

    loop = asyncio.new_event_loop()
    finished: list[str] = []

    def slow_write() -> None:
        time.sleep(0.3)
        finished.append("written")

    try:

        async def start_write() -> None:
            # Deliberately not awaited: the point is a write still running when
            # the loop is asked to stop.
            loop.run_in_executor(None, slow_write)
            await asyncio.sleep(0)

        loop.run_until_complete(start_write())
        assert not finished
        loop.run_until_complete(_drain_event_loop(loop, budget_s=3.0))
        assert finished == ["written"]
    finally:
        loop.close()


def test_draining_the_loop_gives_up_rather_than_hanging() -> None:
    """A shutdown that never finishes is worse than one that logs a warning.

    A bare `except Exception` wrapped around an await is enough to swallow the
    cancellation, and there is code like that in most programs. The first version
    of the drain used asyncio.wait_for, which cancels what it is waiting on and
    then waits for the cancellation to land — so against a task like this one the
    ceiling was not a ceiling, and quit would never have returned at all.
    """
    from arelis.ui.app import _drain_event_loop

    loop = asyncio.new_event_loop()
    let_go = {"yes": False}

    async def stubborn() -> None:
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                if let_go["yes"]:
                    raise
                continue

    try:
        task = loop.create_task(stubborn())
        started = time.monotonic()
        loop.run_until_complete(_drain_event_loop(loop, budget_s=0.2))
        assert time.monotonic() - started < 5.0, "the drain has to be bounded"
        assert not task.done(), "this task cannot be stopped, which is the point"
    finally:
        # Left running, it would print "Task was destroyed but it is pending" from
        # this test — the exact warning the rest of this work exists to remove.
        let_go["yes"] = True
        task.cancel()
        try:
            loop.run_until_complete(asyncio.wait([task], timeout=2))
        except Exception:
            pass
        loop.close()


def test_the_desktop_shortcut_does_not_go_through_a_console_program() -> None:
    """-WindowStyle Hidden allocates a console and then hides it.

    Which is a black rectangle blinking on screen on every single launch. The
    only fix is to stop involving a console program at all, and the only place
    that can be asserted is the installer that writes the shortcut.
    """
    script = (_SCRIPTS / "install_desktop_shortcut.ps1").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    assert "powershell.exe" not in body.lower()
    assert "-WindowStyle Hidden" not in body
    assert "pythonw.exe" in body
    assert "-m arelis --solar-gl" in body
    assert '$Arguments = "-m arelis"' in body


def test_a_checkout_cannot_overwrite_the_installed_shortcut() -> None:
    """Both copies wanted the name `Arelis.lnk`, and only one of them should have it.

    Running the installer from a checkout to fix the console flash would have
    repointed the everyday shortcut at the working tree. That is not a crash: the
    two copies keep separate data roots, so it presents as an Arelis that opens
    one morning with none of your history in it.
    """
    script = (_SCRIPTS / "install_desktop_shortcut.ps1").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    assert '"Arelis (dev).lnk"' in body
    assert 'Join-Path $Root "pyproject.toml"' in body
    assert 'Join-Path $Root "tests"' in body
    assert '(Join-Path $Desktop "Arelis.lnk")' not in body, (
        "an unconditional Arelis.lnk is the hijack this guards against"
    )


def test_the_shortcut_does_not_ask_for_a_minimized_window() -> None:
    """WindowStyle 7 was aimed at PowerShell's console; there is no console now."""
    script = (_SCRIPTS / "install_desktop_shortcut.ps1").read_text(encoding="utf-8")
    body = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    assert "$shortcut.WindowStyle = 1" in body


@pytest.mark.skipif(
    __import__("sys").platform != "win32", reason="the correction is Windows-only"
)
@pytest.mark.parametrize("stray", ["offscreen", "minimal", "vnc", "OFFSCREEN"])
def test_a_stray_qt_platform_cannot_leave_the_app_with_no_window(stray: str) -> None:
    """run_ui.ps1 used to clear this; a shortcut aimed at pythonw.exe cannot.

    offscreen is the value that actually gets set by accident, but minimal and
    vnc fail the same silent way: a process that is running and invisible.
    """
    from arelis.ui.app import force_windows_qt_platform

    env = {"QT_QPA_PLATFORM": stray}
    force_windows_qt_platform(env)
    assert env["QT_QPA_PLATFORM"] == "windows"


@pytest.mark.skipif(
    __import__("sys").platform != "win32", reason="the correction is Windows-only"
)
def test_headless_checks_can_still_ask_for_offscreen() -> None:
    from arelis.ui.app import force_windows_qt_platform

    env = {"QT_QPA_PLATFORM": "offscreen", "ARELIS_ALLOW_OFFSCREEN": "1"}
    force_windows_qt_platform(env)
    assert env["QT_QPA_PLATFORM"] == "offscreen"
