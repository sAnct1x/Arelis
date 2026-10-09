"""Startup and automatic show must not steal keyboard focus."""

from __future__ import annotations

import ast
import ctypes
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QSystemTrayIcon, QWidget

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


def test_present_at_startup_does_not_activate(qt_app, monkeypatch) -> None:
    from arelis.ui.launch import _present_at_startup

    win32_calls: list[Any] = []
    monkeypatch.setattr(fg, "_win32_foreground", lambda w: win32_calls.append(w))

    widget = QWidget()
    try:
        attr = Qt.WidgetAttribute.WA_ShowWithoutActivating
        assert not widget.testAttribute(attr)
        raises: list[int] = []
        activates: list[int] = []
        attr_at_show: list[bool] = []
        real_show = widget.show
        real_raise = widget.raise_
        real_activate = widget.activateWindow

        def _show() -> None:
            attr_at_show.append(widget.testAttribute(attr))
            real_show()

        def _raise() -> None:
            raises.append(1)
            real_raise()

        def _activate() -> None:
            activates.append(1)
            real_activate()

        widget.show = _show  # type: ignore[method-assign]
        widget.raise_ = _raise  # type: ignore[method-assign]
        widget.activateWindow = _activate  # type: ignore[method-assign]

        _present_at_startup(widget)
        qt_app.processEvents()

        assert attr_at_show == [True]
        assert not widget.testAttribute(attr)
        assert raises == []
        assert activates == []
        assert win32_calls == []
        assert not (
            widget.windowState() & Qt.WindowState.WindowMinimized
        )
    finally:
        widget.deleteLater()


def test_run_ui_has_no_activating_startup_calls() -> None:
    src = (Path(__file__).resolve().parents[1] / "arelis" / "ui" / "launch.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    run_ui = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "run_ui":
            run_ui = node
            break
    assert run_ui is not None, "run_ui not found in launch.py"
    banned = {"activateWindow", "raise_", "SetForegroundWindow"}
    hits: list[str] = []
    for node in ast.walk(run_ui):
        if isinstance(node, ast.Attribute) and node.attr in banned:
            hits.append(node.attr)
        if isinstance(node, ast.Name) and node.id in banned:
            hits.append(node.id)
    assert hits == [], f"run_ui still activates at startup: {hits}"


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


def test_claim_foreground_still_activates(qt_app, monkeypatch) -> None:
    win32_calls: list[Any] = []
    monkeypatch.setattr(fg, "_win32_foreground", lambda w: win32_calls.append(w))
    monkeypatch.setattr(fg, "process_owns_foreground", lambda: True)

    widget = QWidget()
    try:
        activates: list[int] = []
        raises: list[int] = []
        real_activate = widget.activateWindow
        real_raise = widget.raise_

        def _activate() -> None:
            activates.append(1)
            real_activate()

        def _raise() -> None:
            raises.append(1)
            real_raise()

        widget.activateWindow = _activate  # type: ignore[method-assign]
        widget.raise_ = _raise  # type: ignore[method-assign]
        widget.show()
        qt_app.processEvents()
        fg.claim_foreground(widget)
        qt_app.processEvents()
        assert raises
        assert activates
        assert win32_calls == [widget]
    finally:
        widget.deleteLater()


def test_present_at_startup_unminimizes_before_show_keeps_maximized() -> None:
    from arelis.ui.launch import _present_at_startup

    fake = _RecorderWidget()
    fake._window_state = (
        Qt.WindowState.WindowMinimized | Qt.WindowState.WindowMaximized
    )
    _present_at_startup(fake)
    assert fake.order[:2] == ["setWindowState", "show"]
    assert fake._states_set
    state = fake._states_set[0]
    assert not (state & Qt.WindowState.WindowMinimized)
    assert state & Qt.WindowState.WindowMaximized


def test_present_at_startup_maximizes_inactive_after_show(monkeypatch) -> None:
    from arelis.ui.launch import _present_at_startup

    max_calls: list[str] = []

    def _max(widget: Any) -> None:
        max_calls.append("max")
        widget.order.append("max")

    monkeypatch.setattr(fg, "_win32_maximize_inactive", _max)

    maximized = _RecorderWidget()
    maximized._window_state = Qt.WindowState.WindowMaximized
    _present_at_startup(maximized)
    assert max_calls == ["max"]
    assert maximized.order == ["setWindowState", "show", "max"]

    normal = _RecorderWidget()
    normal._window_state = Qt.WindowState.WindowNoState
    _present_at_startup(normal)
    assert max_calls == ["max"]
    assert "max" not in normal.order


def test_show_from_tray_maximizes_inactive_when_not_activating(monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.ui.window_lifetime.invalidate_window_surface",
        lambda w: None,
    )
    max_calls: list[Any] = []

    def _max(widget: Any) -> None:
        max_calls.append(widget)
        widget.order.append("max")

    monkeypatch.setattr(fg, "_win32_maximize_inactive", _max)

    fake = _RecorderWidget()
    fake._tray_window_state = Qt.WindowState.WindowMaximized
    fake.show_from_tray = WindowLifetime.show_from_tray.__get__(fake, type(fake))
    WindowLifetime.show_from_tray(fake, activate=False)  # type: ignore[arg-type]
    assert max_calls == [fake]
    show_at = fake.order.index("show")
    assert fake.order[show_at + 1] == "max"

    other = _RecorderWidget()
    other._tray_window_state = Qt.WindowState.WindowNoState
    other.show_from_tray = WindowLifetime.show_from_tray.__get__(other, type(other))
    WindowLifetime.show_from_tray(other, activate=False)  # type: ignore[arg-type]
    assert max_calls == [fake]


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


def test_win32_maximize_inactive_sets_style_then_noactivate_pos(monkeypatch) -> None:
    user32 = _FakeUser32(zoomed=0)
    _patch_win32_maximize(monkeypatch, user32)
    fg._win32_maximize_inactive(object())
    names = [c[0] for c in user32.calls]
    assert names.index("SetWindowLongW") < names.index("SetWindowPos")
    long_call = next(c for c in user32.calls if c[0] == "SetWindowLongW")
    assert long_call[3] & 0x01000000
    pos = next(c for c in user32.calls if c[0] == "SetWindowPos")
    assert pos[1] == 1234
    assert pos[3] == 100
    assert pos[4] == 50
    assert pos[5] == 1920
    assert pos[6] == 1080
    flags = pos[7]
    assert flags & 0x0010  # SWP_NOACTIVATE
    assert flags & 0x0004  # SWP_NOZORDER
    assert not set(names) & set(_ACTIVATING)


def test_win32_maximize_inactive_skips_when_already_zoomed(monkeypatch) -> None:
    user32 = _FakeUser32(zoomed=1)
    _patch_win32_maximize(monkeypatch, user32)
    fg._win32_maximize_inactive(object())
    assert user32.calls == [("IsZoomed", 1234)]


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


def test_update_offer_waits_when_another_app_is_front(qt_app, monkeypatch) -> None:
    from arelis.ui.update_prompt import UpdatePrompt

    confirms: list[int] = []
    flashes: list[Any] = []
    monkeypatch.setattr(
        "arelis.ui.update_prompt.confirm",
        lambda *a, **k: confirms.append(1) or False,
    )
    monkeypatch.setattr(
        "arelis.ui.update_prompt.process_owns_foreground",
        lambda: False,
        raising=False,
    )
    monkeypatch.setattr(
        "arelis.ui.foreground.process_owns_foreground",
        lambda: False,
    )
    monkeypatch.setattr(
        "arelis.ui.update_prompt.flash_taskbar",
        lambda w: flashes.append(w),
        raising=False,
    )
    monkeypatch.setattr(
        "arelis.ui.foreground.flash_taskbar",
        lambda w: flashes.append(w),
    )

    window = QWidget()
    try:
        prompt = UpdatePrompt(window)
        prompt._offer(_sample_release())
        assert confirms == []
        assert len(flashes) == 1
    finally:
        window.deleteLater()


def test_update_offer_waits_after_background_launch(qt_app, monkeypatch) -> None:
    from arelis.ui.update_prompt import UpdatePrompt

    confirms: list[int] = []
    monkeypatch.setattr(
        "arelis.ui.update_prompt.confirm",
        lambda *a, **k: confirms.append(1) or False,
    )
    monkeypatch.setattr(
        "arelis.ui.foreground.process_owns_foreground",
        lambda: True,
    )
    monkeypatch.setattr(
        "arelis.ui.update_prompt.process_owns_foreground",
        lambda: True,
        raising=False,
    )
    monkeypatch.setattr(
        "arelis.ui.foreground.flash_taskbar",
        lambda w: None,
    )
    monkeypatch.setattr(
        "arelis.ui.update_prompt.flash_taskbar",
        lambda w: None,
        raising=False,
    )

    window = QWidget()
    try:
        window._launched_in_background = True
        prompt = UpdatePrompt(window)
        prompt._offer(_sample_release())
        assert confirms == []
    finally:
        window.deleteLater()


def test_held_update_offer_shows_when_user_brings_arelis_front(qt_app, monkeypatch) -> None:
    from arelis.ui.update_prompt import UpdatePrompt

    monkeypatch.setattr("arelis.ui.update_prompt.sys.platform", "win32")
    confirms: list[int] = []
    monkeypatch.setattr(
        "arelis.ui.update_prompt.confirm",
        lambda *a, **k: confirms.append(1) or False,
    )
    monkeypatch.setattr(
        "arelis.ui.foreground.process_owns_foreground",
        lambda: False,
    )
    monkeypatch.setattr(
        "arelis.ui.update_prompt.process_owns_foreground",
        lambda: False,
        raising=False,
    )
    monkeypatch.setattr(
        "arelis.ui.foreground.flash_taskbar",
        lambda w: None,
    )
    monkeypatch.setattr(
        "arelis.ui.update_prompt.flash_taskbar",
        lambda w: None,
        raising=False,
    )

    window = QWidget()
    try:
        prompt = UpdatePrompt(window)
        prompt._offer(_sample_release())
        assert confirms == []

        QGuiApplication.instance().applicationStateChanged.emit(  # type: ignore[union-attr]
            Qt.ApplicationState.ApplicationActive
        )
        qt_app.processEvents()
        assert confirms == [1]

        QGuiApplication.instance().applicationStateChanged.emit(  # type: ignore[union-attr]
            Qt.ApplicationState.ApplicationActive
        )
        qt_app.processEvents()
        assert confirms == [1]
    finally:
        window.deleteLater()


def test_update_offer_shows_when_arelis_is_front(qt_app, monkeypatch) -> None:
    from arelis.ui.update_prompt import UpdatePrompt

    monkeypatch.setattr("arelis.ui.update_prompt.sys.platform", "win32")
    confirms: list[int] = []
    monkeypatch.setattr(
        "arelis.ui.update_prompt.confirm",
        lambda *a, **k: confirms.append(1) or False,
    )
    monkeypatch.setattr(
        "arelis.ui.foreground.process_owns_foreground",
        lambda: True,
    )
    monkeypatch.setattr(
        "arelis.ui.update_prompt.process_owns_foreground",
        lambda: True,
        raising=False,
    )

    window = QWidget()
    try:
        prompt = UpdatePrompt(window)
        prompt._offer(_sample_release())
        assert confirms == [1]
    finally:
        window.deleteLater()


def test_ipc_open_ui_without_reason_is_quiet(monkeypatch) -> None:
    from arelis.ui.launch import _open_ui_reason
    from arelis.ui.window_lifetime import USER_OPEN_REASONS

    assert _open_ui_reason({}) not in USER_OPEN_REASONS
    assert _open_ui_reason(None) not in USER_OPEN_REASONS

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

    for msg in ({}, None):
        fake = _RecorderWidget()
        fake.show_from_tray = WindowLifetime.show_from_tray.__get__(fake, type(fake))
        fake._on_activation_request = WindowLifetime._on_activation_request.__get__(
            fake, type(fake)
        )
        WindowLifetime._on_activation_request(fake, _open_ui_reason(msg))  # type: ignore[arg-type]
        assert fake.raises == []
        assert fake.activates == []


def test_core_spawned_ui_is_background(monkeypatch) -> None:
    import arelis.presence.open_ui as open_ui

    captured: list[list[str]] = []

    def fake_popen(**kwargs):
        captured.append(list(kwargs["args"]))
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr(open_ui.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(open_ui, "ui_process_appears_running", lambda *a, **k: False)
    open_ui._LAST_SPAWN_MONO = 0.0

    pid = open_ui.spawn_ui_subprocess()
    assert pid == 4242
    assert captured, "Popen was not called"
    assert "--background" in captured[0]


class _FakeOpenUiServer:
    async def request_open_ui(self, **kw: Any) -> int:
        return 0


async def test_core_tray_open_spawns_without_background(monkeypatch) -> None:
    import arelis.presence.open_ui as open_ui

    captured: list[list[str]] = []

    def fake_popen(**kwargs):
        captured.append(list(kwargs["args"]))
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr(open_ui.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(open_ui, "ui_process_appears_running", lambda *a, **k: False)
    open_ui._LAST_SPAWN_MONO = 0.0

    result = await open_ui.ensure_ui_open(
        _FakeOpenUiServer(), spawn_if_detached=True, reason="core_tray"
    )
    assert result.get("spawned") is True
    assert captured, "Popen was not called"
    assert "--background" not in captured[0]


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


def test_spawn_user_reasons_match_window_lifetime() -> None:
    from arelis.presence.open_ui import _USER_OPEN_REASONS
    from arelis.ui.window_lifetime import USER_OPEN_REASONS

    assert _USER_OPEN_REASONS | {""} == USER_OPEN_REASONS


def test_background_flag_clears_on_first_activation(qt_app) -> None:
    from arelis.ui.launch import _mark_launch

    window = QWidget()
    try:
        _mark_launch(window, True)
        assert window._launched_in_background is True
        QGuiApplication.instance().applicationStateChanged.emit(  # type: ignore[union-attr]
            Qt.ApplicationState.ApplicationInactive
        )
        qt_app.processEvents()
        assert window._launched_in_background is True
        QGuiApplication.instance().applicationStateChanged.emit(  # type: ignore[union-attr]
            Qt.ApplicationState.ApplicationActive
        )
        qt_app.processEvents()
        assert window._launched_in_background is False
        QGuiApplication.instance().applicationStateChanged.emit(  # type: ignore[union-attr]
            Qt.ApplicationState.ApplicationActive
        )
        qt_app.processEvents()
        assert window._launched_in_background is False

        other = QWidget()
        try:
            _mark_launch(other, False)
            assert other._launched_in_background is False
        finally:
            other.deleteLater()
    finally:
        window.deleteLater()


def test_offer_shows_after_user_has_used_a_background_window(qt_app, monkeypatch) -> None:
    from arelis.ui.launch import _mark_launch
    from arelis.ui.update_prompt import UpdatePrompt

    monkeypatch.setattr("arelis.ui.update_prompt.sys.platform", "win32")
    confirms: list[int] = []
    monkeypatch.setattr(
        "arelis.ui.update_prompt.confirm",
        lambda *a, **k: confirms.append(1) or False,
    )
    monkeypatch.setattr(
        "arelis.ui.foreground.process_owns_foreground",
        lambda: True,
    )
    monkeypatch.setattr(
        "arelis.ui.update_prompt.process_owns_foreground",
        lambda: True,
        raising=False,
    )
    monkeypatch.setattr(
        "arelis.ui.foreground.flash_taskbar",
        lambda w: None,
    )
    monkeypatch.setattr(
        "arelis.ui.update_prompt.flash_taskbar",
        lambda w: None,
        raising=False,
    )

    window = QWidget()
    try:
        _mark_launch(window, True)
        QGuiApplication.instance().applicationStateChanged.emit(  # type: ignore[union-attr]
            Qt.ApplicationState.ApplicationActive
        )
        qt_app.processEvents()
        prompt = UpdatePrompt(window)
        prompt._offer(_sample_release())
        assert confirms == [1]
    finally:
        window.deleteLater()


def test_run_ui_wires_launch_flag_and_core_reason(qt_app) -> None:
    import inspect

    from arelis.ui.launch import _core_open_ui_handler, run_ui
    from arelis.ui.window_lifetime import USER_OPEN_REASONS

    tree = ast.parse(inspect.getsource(run_ui))
    mark_ok = False
    handler_ok = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = ""
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name == "_mark_launch" and len(node.args) >= 2:
            second = node.args[1]
            if isinstance(second, ast.Name) and second.id == "background":
                mark_ok = True
        if name == "IpcClient":
            for kw in node.keywords:
                if kw.arg != "on_open_ui":
                    continue
                val = kw.value
                if (
                    isinstance(val, ast.Call)
                    and isinstance(val.func, ast.Name)
                    and val.func.id == "_core_open_ui_handler"
                    and val.args
                    and isinstance(val.args[0], ast.Name)
                    and val.args[0].id == "window"
                ):
                    handler_ok = True
    assert mark_ok, "run_ui must pass the background parameter to _mark_launch"
    assert handler_ok, "run_ui must wire on_open_ui through _core_open_ui_handler"

    reasons: list[object] = []
    window = QWidget()
    try:
        window._on_activation_request = lambda r: reasons.append(r)  # type: ignore[method-assign]
        handler = _core_open_ui_handler(window)
        handler({})
        qt_app.processEvents()
        assert reasons and reasons[-1] not in USER_OPEN_REASONS
        handler({"reason": "core_tray"})
        qt_app.processEvents()
        assert reasons[-1] == "core_tray"
    finally:
        window.deleteLater()
