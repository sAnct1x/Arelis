"""Startup and automatic show must not steal keyboard focus."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import Qt
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
        self._force_quit = False
        self._disposed = False
        self.voice_controller = None
        self._tray_window_state = Qt.WindowState.WindowNoState
        self._pending_queue: list[Any] = []
        self._restoring_confirm_ids: set[str] = set()
        self._hidden = True
        self._visible = False
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
