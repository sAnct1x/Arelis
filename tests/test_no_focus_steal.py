"""Startup and automatic show must not steal keyboard focus."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QSystemTrayIcon

from arelis.ui import foreground as fg
from arelis.ui.window_lifetime import WindowLifetime
from arelis.ui.window_turn import WindowTurn


class _RecorderWidget:
    """Stand-in that records show / raise_ / activateWindow / attributes."""

    def __init__(self) -> None:
        self.shows: list[bool] = []
        self.raises: list[int] = []
        self.activates: list[int] = []
        self._attrs: dict[Any, bool] = {}
        self._attr_at_show: bool | None = None
        self._window_state = Qt.WindowState.WindowMinimized
        self._states_set: list[Qt.WindowState] = []
        self._force_quit = False
        self._disposed = False
        self.voice_controller = None
        self._tray_window_state = Qt.WindowState.WindowNoState
        self._pending_queue: list[Any] = []
        self._restoring_confirm_ids: set[str] = set()
        self._hidden = True
        self._visible = False
        self.order: list[str] = []
        self.conversation = SimpleNamespace(
            confirm=SimpleNamespace(_confirm_id=""),
            ask_confirm=lambda *a, **k: None,
        )
        self.thinking = SimpleNamespace(append=lambda *a, **k: None)

    def testAttribute(self, attr: Any) -> bool:
        return bool(self._attrs.get(attr, False))

    def setAttribute(self, attr: Any, on: bool = True) -> None:
        self._attrs[attr] = bool(on)

    def show(self) -> None:
        self.order.append("show")
        self._attr_at_show = self.testAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating
        )
        self.shows.append(self._attr_at_show)
        self._hidden = False
        self._visible = True

    def raise_(self) -> None:
        self.raises.append(1)

    def activateWindow(self) -> None:
        self.activates.append(1)

    def windowState(self) -> Qt.WindowState:
        return self._window_state

    def setWindowState(self, state: Qt.WindowState) -> None:
        self.order.append("setWindowState")
        self._states_set.append(state)
        self._window_state = state

    def isVisible(self) -> bool:
        return self._visible

    def isHidden(self) -> bool:
        return self._hidden

    def _remember_window_state(self) -> None:
        state = self.windowState()
        state &= ~Qt.WindowState.WindowMinimized
        self._tray_window_state = state

    def _unpark_floating_docks(self) -> None:
        return None

    def _show_next_pending_confirm(self) -> None:
        return None

    def _set_confirm_pending(self, pending: bool) -> None:
        return None


def test_pending_confirm_while_hidden_does_not_activate(monkeypatch) -> None:
    flash_calls: list[Any] = []
    monkeypatch.setattr(
        "arelis.ui.window_turn.flash_taskbar",
        lambda w: flash_calls.append(w),
    )
    monkeypatch.setattr(
        "arelis.ui.window_lifetime.invalidate_window_surface",
        lambda w: None,
    )

    fake = _RecorderWidget()
    item = SimpleNamespace(
        id="c1",
        tool="send",
        summary="send a note",
        detail="",
        note="",
        batch_ok=False,
    )
    fake._pending_queue = [item]
    asked: list[str] = []

    def _ask(cid, tool, summary, **kwargs):
        fake.conversation.confirm._confirm_id = cid
        asked.append(cid)

    fake.conversation.ask_confirm = _ask

    # Bind the real lifetime helper onto this fake.
    fake.show_from_tray = WindowLifetime.show_from_tray.__get__(fake, type(fake))

    WindowTurn._show_next_pending_confirm(fake)  # type: ignore[arg-type]

    assert asked == ["c1"]
    assert fake.shows  # shown without activating
    assert fake.raises == []
    assert fake.activates == []
    assert flash_calls == [fake]
    assert fake._attr_at_show is True


def test_activation_reasons_gate_raise_and_activate(monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.ui.window_lifetime.invalidate_window_surface",
        lambda w: None,
    )
    monkeypatch.setattr(
        "arelis.ui.window_lifetime.flash_taskbar",
        lambda w: None,
    )
    monkeypatch.setattr(
        "arelis.ui.window_lifetime.show_without_activating",
        lambda w: w.show(),
    )

    def _fresh() -> _RecorderWidget:
        fake = _RecorderWidget()
        fake.show_from_tray = WindowLifetime.show_from_tray.__get__(fake, type(fake))
        fake._on_activation_request = WindowLifetime._on_activation_request.__get__(
            fake, type(fake)
        )
        return fake

    auto = _fresh()
    WindowLifetime._on_activation_request(auto, "tool_confirm")  # type: ignore[arg-type]
    assert auto.raises == []
    assert auto.activates == []

    for reason in ("second_instance", "core_tray", "", "tray"):
        user = _fresh()
        WindowLifetime._on_activation_request(user, reason)  # type: ignore[arg-type]
        assert user.raises == [1], reason
        assert user.activates == [1], reason

    # Tray icon Trigger / DoubleClick path (no reason arg).
    tray = _fresh()
    WindowLifetime._on_tray_activated(  # type: ignore[arg-type]
        tray, QSystemTrayIcon.ActivationReason.Trigger
    )
    assert tray.raises == [1]
    assert tray.activates == [1]

    # Tray menu Open: QAction.triggered passes a bool checked; still a user open.
    for checked in (False, True):
        menu = _fresh()
        WindowLifetime._on_activation_request(menu, checked)  # type: ignore[arg-type]
        assert menu.raises == [1]
        assert menu.activates == [1]

    # Unknown automatic reasons never take focus.
    other = _fresh()
    WindowLifetime._on_activation_request(other, "inbound_sms")  # type: ignore[arg-type]
    assert other.raises == []
    assert other.activates == []
    assert other.shows


_ACTIVATING = ("ShowWindow", "SetForegroundWindow", "BringWindowToTop", "SetWindowPlacement")


class _FakeUser32:
    """Records calls. Activating calls are recorded too (the helper swallows
    exceptions, so raising would hide them) and the tests assert none ran."""

    def __init__(self, *, zoomed: int = 0) -> None:
        self.zoomed = zoomed
        self.calls: list[tuple[Any, ...]] = []

    def __getattr__(self, name: str) -> Any:
        if name in _ACTIVATING:
            return lambda *a, **k: self.calls.append((name, *a))
        raise AttributeError(name)

    def IsZoomed(self, hwnd: Any) -> int:
        self.calls.append(("IsZoomed", hwnd))
        return self.zoomed

    def MonitorFromWindow(self, hwnd: Any, flags: Any) -> int:
        self.calls.append(("MonitorFromWindow", hwnd, flags))
        return 1

    def GetMonitorInfoW(self, hmon: Any, info_ref: Any) -> int:
        self.calls.append(("GetMonitorInfoW", hmon))
        obj = info_ref._obj
        obj.rcWork.left = 100
        obj.rcWork.top = 50
        obj.rcWork.right = 2020
        obj.rcWork.bottom = 1130
        return 1

    def GetWindowLongW(self, hwnd: Any, idx: Any) -> int:
        self.calls.append(("GetWindowLongW", hwnd, idx))
        return 0x00C00000

    def SetWindowLongW(self, hwnd: Any, idx: Any, style: Any) -> int:
        self.calls.append(("SetWindowLongW", hwnd, idx, style))
        return 0

    def SetWindowPos(
        self,
        hwnd: Any,
        insert: Any,
        x: Any,
        y: Any,
        cx: Any,
        cy: Any,
        flags: Any,
    ) -> int:
        self.calls.append(("SetWindowPos", hwnd, insert, x, y, cx, cy, flags))
        return 1


def _patch_win32_maximize(monkeypatch: Any, user32: _FakeUser32) -> None:
    monkeypatch.setattr(fg.sys, "platform", "win32")
    monkeypatch.setattr(
        QGuiApplication, "platformName", staticmethod(lambda: "windows")
    )
    monkeypatch.setattr(
        "arelis.ui.window_resize.top_level_hwnd", lambda widget: 1234
    )
    fake_windll = SimpleNamespace(user32=user32)
    monkeypatch.setattr(ctypes, "windll", fake_windll, raising=False)


def _sample_release():
    from packaging.version import Version

    from arelis.update import Release

    return Release(
        version=Version("0.2.0"),
        tag="v0.2.0",
        setup_name="Arelis-0.2.0-win64-setup.exe",
        setup_url="https://example.invalid/setup.exe",
        digest_url="https://example.invalid/setup.exe.sha256",
        size=9,
        page_url="https://example.invalid/releases",
    )


class _FakeOpenUiServer:
    async def request_open_ui(self, **kw: Any) -> int:
        return 0


async def test_allow_card_spawn_is_background(monkeypatch) -> None:
    import arelis.presence.open_ui as open_ui

    captured: list[list[str]] = []

    def fake_popen(**kwargs):
        captured.append(list(kwargs["args"]))
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr(open_ui.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(open_ui, "ui_process_appears_running", lambda *a, **k: False)

    open_ui._LAST_SPAWN_MONO = 0.0
    await open_ui.ensure_ui_open(
        _FakeOpenUiServer(), spawn_if_detached=True, reason="tool_confirm"
    )
    assert captured, "Popen was not called"
    assert "--background" in captured[0]

    captured.clear()
    open_ui._LAST_SPAWN_MONO = 0.0
    await open_ui.ensure_ui_open(_FakeOpenUiServer(), spawn_if_detached=True)
    assert captured, "Popen was not called"
    assert "--background" in captured[0]


