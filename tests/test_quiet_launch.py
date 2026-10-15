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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from arelis.ui import foreground as fg

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
