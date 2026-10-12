"""A launch the user did not start must not take the Windows foreground.

``_launched_in_background`` is the one flag (``--background``: login, tray,
updater, and the no-activate test path). With it set, startup must not call
raise_ / activateWindow / setFocus / SetForegroundWindow / AllowSetForegroundWindow,
and every SetWindowPos includes SWP_NOACTIVATE. A Start-menu launch leaves the
flag clear and may still focus the composer. A second shortcut click is the
user asking, so it may still raise.
"""

from __future__ import annotations

import ctypes
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from arelis.ui import foreground as fg
from arelis.ui import window_resize as wr
from arelis.ui.window_lifetime import WindowLifetime

_SWP_NOACTIVATE = 0x0010


class _QuietWindow:
    """Records the calls that steal the foreground on Windows."""

    def __init__(self, *, quiet: bool, state: Qt.WindowState) -> None:
        self._launched_in_background = quiet
        self._state = state
        self._attrs: dict[Any, bool] = {}
        self._flags = Qt.WindowType.Window
        self.calls: list[tuple[Any, ...]] = []

    def window(self) -> _QuietWindow:
        return self

    def windowState(self) -> Qt.WindowState:
        return self._state

    def setWindowState(self, state: Qt.WindowState) -> None:
        self.calls.append(("setWindowState", state))
        self._state = state

    def testAttribute(self, attr: Any) -> bool:
        return bool(self._attrs.get(attr, False))

    def setAttribute(self, attr: Any, on: bool = True) -> None:
        self._attrs[attr] = bool(on)

    def windowFlags(self) -> Qt.WindowType:
        return self._flags

    def setWindowFlag(self, flag: Qt.WindowType, on: bool = True) -> None:
        self.calls.append(("setWindowFlag", flag, bool(on)))
        if on:
            self._flags |= flag
        else:
            self._flags &= ~flag

    def show(self) -> None:
        self.calls.append(("show", self._flags, self._state))

    def raise_(self) -> None:
        self.calls.append(("raise_",))

    def activateWindow(self) -> None:
        self.calls.append(("activateWindow",))

    def isVisible(self) -> bool:
        return False

    def isHidden(self) -> bool:
        return True


class _User32:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def LockSetForegroundWindow(self, flags: int) -> int:
        self.calls.append(("LockSetForegroundWindow", int(flags)))
        return 1

    def AllowSetForegroundWindow(self, pid: int) -> int:
        self.calls.append(("AllowSetForegroundWindow", int(pid)))
        return 1

    def SetForegroundWindow(self, hwnd: int) -> int:
        self.calls.append(("SetForegroundWindow", int(hwnd)))
        return 1

    def BringWindowToTop(self, hwnd: int) -> int:
        self.calls.append(("BringWindowToTop", int(hwnd)))
        return 1

    def ShowWindow(self, hwnd: int, cmd: int) -> int:
        self.calls.append(("ShowWindow", int(hwnd), int(cmd)))
        return 1

    def SetWindowPos(
        self, hwnd: Any, insert: Any, x: Any, y: Any, cx: Any, cy: Any, flags: Any
    ) -> int:
        self.calls.append(("SetWindowPos", hwnd, insert, x, y, cx, cy, int(flags)))
        return 1

    def GetWindowLongW(self, hwnd: Any, idx: Any) -> int:
        self.calls.append(("GetWindowLongW", hwnd, idx))
        return 0

    def SetWindowLongW(self, hwnd: Any, idx: Any, style: Any) -> int:
        self.calls.append(("SetWindowLongW", hwnd, idx, style))
        return 0

    def IsZoomed(self, hwnd: Any) -> int:
        return 0

    def MonitorFromWindow(self, hwnd: Any, flags: Any) -> int:
        return 1

    def GetMonitorInfoW(self, hmon: Any, info_ref: Any) -> int:
        obj = info_ref._obj
        obj.rcWork.left = 0
        obj.rcWork.top = 0
        obj.rcWork.right = 800
        obj.rcWork.bottom = 600
        return 1

    def GetWindowRect(self, hwnd: Any, rc: Any) -> int:
        return 0


def _names(calls: list[tuple[Any, ...]]) -> list[str]:
    return [c[0] for c in calls]


def test_quiet_show_makes_no_activate_calls(monkeypatch) -> None:
    """Background flag: show does not raise, activate, or grant foreground."""
    user32 = _User32()
    monkeypatch.setattr(fg.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32), raising=False)
    monkeypatch.setattr(fg, "_win32_maximize_inactive", lambda w: None)

    window = _QuietWindow(quiet=True, state=Qt.WindowState.WindowNoState)
    fg.show_without_activating(window)

    assert "raise_" not in _names(window.calls)
    assert "activateWindow" not in _names(window.calls)
    assert "AllowSetForegroundWindow" not in _names(user32.calls)
    assert "SetForegroundWindow" not in _names(user32.calls)
    assert "BringWindowToTop" not in _names(user32.calls)
    show = next(c for c in window.calls if c[0] == "show")
    assert show[1] & Qt.WindowType.WindowDoesNotAcceptFocus
    assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is False


def test_quiet_maximized_show_is_not_sw_maximize(monkeypatch) -> None:
    """Qt's SW_SHOWMAXIMIZED activates. Quiet show must not hand it that state."""
    maxed: list[Any] = []
    monkeypatch.setattr(fg, "_win32_maximize_inactive", lambda w: maxed.append(w))

    window = _QuietWindow(
        quiet=True,
        state=Qt.WindowState.WindowMinimized | Qt.WindowState.WindowMaximized,
    )
    from arelis.ui.launch import _present_at_startup

    _present_at_startup(window)
    show = next(c for c in window.calls if c[0] == "show")
    assert not (show[2] & Qt.WindowState.WindowMaximized)
    assert maxed == []
    states = [c[1] for c in window.calls if c[0] == "setWindowState"]
    assert states
    assert all(not (s & Qt.WindowState.WindowMaximized) for s in states)
    assert "activateWindow" not in _names(window.calls)
    assert "raise_" not in _names(window.calls)


def test_quiet_late_show_does_not_run_focus(monkeypatch) -> None:
    """The 80ms composer focus must not run at all on a quiet launch."""
    from arelis.ui.window_build import WindowBuild

    calls: list[str] = []
    window = _QuietWindow(quiet=True, state=Qt.WindowState.WindowNoState)
    window.conversation = SimpleNamespace(focus_input=lambda: calls.append("focus"))
    WindowBuild._focus_composer_after_show(window)  # type: ignore[arg-type]
    assert calls == []

    user = _QuietWindow(quiet=False, state=Qt.WindowState.WindowNoState)
    user.conversation = SimpleNamespace(focus_input=lambda: calls.append("focus"))
    WindowBuild._focus_composer_after_show(user)  # type: ignore[arg-type]
    assert calls == ["focus"]


def test_quiet_late_focus_does_not_call_set_focus(qt_app, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    from arelis.ui.panels.conversation import ConversationStage

    monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: None))
    calls: list[Any] = []

    class _Input:
        def setFocus(self, *args: Any) -> None:
            calls.append(("setFocus", args))

        def inherits(self, _name: str) -> bool:
            return False

        def ensureCursorVisible(self) -> None:
            calls.append(("caret",))

        def window(self) -> Any:
            return host

    host = SimpleNamespace(_launched_in_background=True)
    conv = SimpleNamespace(input=_Input(), window=lambda: host, _filament_desk=False)
    ConversationStage.focus_input(conv)  # type: ignore[arg-type]
    ConversationStage.restore_composer_caret(conv)  # type: ignore[arg-type]
    assert not any(c[0] == "setFocus" for c in calls)


def test_user_launch_still_focuses_the_composer(qt_app, monkeypatch) -> None:
    from PySide6.QtWidgets import QApplication

    from arelis.ui.panels.conversation import ConversationStage

    monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: None))

    calls: list[str] = []

    class _Input:
        def setFocus(self, *_args: Any) -> None:
            calls.append("setFocus")

        def inherits(self, _name: str) -> bool:
            return False

        def window(self) -> Any:
            return host

    host = SimpleNamespace(_launched_in_background=False)
    conv = SimpleNamespace(input=_Input(), window=lambda: host)
    ConversationStage.focus_input(conv)  # type: ignore[arg-type]
    assert calls == ["setFocus"]


def test_second_instance_still_raises_and_clears_quiet(monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.ui.window_lifetime.invalidate_window_surface",
        lambda w: None,
    )
    monkeypatch.setattr("arelis.ui.window_lifetime.flash_taskbar", lambda w: None)

    window = _QuietWindow(quiet=True, state=Qt.WindowState.WindowNoState)
    window._force_quit = False
    window._disposed = False
    window.voice_controller = None
    window._tray_window_state = Qt.WindowState.WindowNoState
    window.show_from_tray = WindowLifetime.show_from_tray.__get__(window, type(window))
    window._on_activation_request = WindowLifetime._on_activation_request.__get__(
        window, type(window)
    )
    window._remember_window_state = lambda: None
    window._unpark_floating_docks = lambda: None
    window._show_next_pending_confirm = lambda: None

    WindowLifetime._on_activation_request(window, "second_instance")  # type: ignore[arg-type]
    assert ("raise_",) in window.calls
    assert ("activateWindow",) in window.calls
    assert window._launched_in_background is False


def test_quiet_setwindowpos_always_noactivate(monkeypatch) -> None:
    user32 = _User32()
    monkeypatch.setattr(wr.sys, "platform", "win32")
    monkeypatch.setattr(fg.sys, "platform", "win32")
    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32), raising=False)
    monkeypatch.setattr(wr, "top_level_hwnd", lambda widget: 4242)

    wr.enable_win32_resize_frame(object())
    wr._set_hwnd_rect(4242, QRect(10, 20, 30, 40), 1.0)
    fg._win32_maximize_inactive(SimpleNamespace())

    poses = [c for c in user32.calls if c[0] == "SetWindowPos"]
    assert len(poses) >= 2
    for call in poses:
        assert call[-1] & _SWP_NOACTIVATE, f"SetWindowPos flags {call[-1]:#x} lack SWP_NOACTIVATE"
    assert "SetForegroundWindow" not in _names(user32.calls)
    assert "AllowSetForegroundWindow" not in _names(user32.calls)


def test_real_quiet_widget_show_does_not_activate(qt_app, monkeypatch) -> None:
    user32 = _User32()
    monkeypatch.setattr(fg.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32), raising=False)

    widget = QWidget()
    try:
        widget._launched_in_background = True
        activates: list[str] = []
        widget.activateWindow = lambda: activates.append("activate")  # type: ignore[method-assign]
        widget.raise_ = lambda: activates.append("raise")  # type: ignore[method-assign]
        fg.show_without_activating(widget)
        qt_app.processEvents()
        assert activates == []
        assert widget.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
        assert "AllowSetForegroundWindow" not in _names(user32.calls)
        assert "SetForegroundWindow" not in _names(user32.calls)
    finally:
        widget.deleteLater()
        qt_app.processEvents()


def test_quiet_unpark_shows_docks_without_raising(monkeypatch) -> None:
    """Parked docks come back with a quiet glass, but raise_() would steal."""
    monkeypatch.setattr(
        "arelis.ui.window_lifetime.invalidate_window_surface",
        lambda w: None,
    )
    window = _QuietWindow(quiet=True, state=Qt.WindowState.WindowNoState)
    dock = _QuietWindow(quiet=False, state=Qt.WindowState.WindowNoState)
    dock._arelis_parked = True
    window.think_dock = dock
    window.work_dock = dock
    window.history_dock = dock
    window.camera_dock = dock
    WindowLifetime._unpark_floating_docks(window)  # type: ignore[arg-type]
    assert "show" in _names(dock.calls)
    assert "raise_" not in _names(dock.calls)


def test_user_show_still_accepts_focus(monkeypatch) -> None:
    """A normal launch is allowed to take focus, so it must not set NOACTIVATE."""
    monkeypatch.setattr(fg, "_win32_maximize_inactive", lambda w: None)
    window = _QuietWindow(quiet=False, state=Qt.WindowState.WindowNoState)
    fg.show_without_activating(window)
    show = next(c for c in window.calls if c[0] == "show")
    assert not (show[1] & Qt.WindowType.WindowDoesNotAcceptFocus)


def test_confirm_card_does_not_focus_allow_when_quiet(qt_app) -> None:
    from arelis.ui.panels.confirm import ConfirmCard

    calls: list[str] = []
    host = QWidget()
    host._launched_in_background = True
    card = ConfirmCard(host)
    try:
        card.allow_btn.setFocus = lambda *a, **k: calls.append("setFocus")  # type: ignore[method-assign]
        card.ask("c1", "send", "send a note")
        assert calls == []
    finally:
        card.deleteLater()
        host.deleteLater()
        qt_app.processEvents()
