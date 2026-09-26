"""Clicking a tile behind another app must raise it, same as the glass."""

from __future__ import annotations

import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QWidget


def test_seal_marks_the_plate_for_click_to_front(qt_app) -> None:
    from arelis.ui.foreground import accepts_click_to_front
    from arelis.ui.glass import seal_tool_window

    plate = QWidget()
    try:
        assert not accepts_click_to_front(plate)
        seal_tool_window(plate)
        assert accepts_click_to_front(plate)
    finally:
        plate.deleteLater()


def test_claim_foreground_raises_owner_when_another_app_is_front(
    qt_app, monkeypatch
) -> None:
    from arelis.ui import foreground as fg

    monkeypatch.setattr(fg, "process_owns_foreground", lambda: False)
    owner = QWidget()
    tile = QWidget(owner)
    tile.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.Window)
    owner_raises: list[int] = []
    owner_raise = owner.raise_

    def _owner_raise() -> None:
        owner_raises.append(1)
        owner_raise()

    owner.raise_ = _owner_raise  # type: ignore[method-assign]
    try:
        owner.show()
        tile.show()
        qt_app.processEvents()
        fg.claim_foreground(tile)
        qt_app.processEvents()
        assert owner_raises
    finally:
        tile.deleteLater()
        owner.deleteLater()


def test_claim_foreground_does_not_bury_tile_under_owner(qt_app, monkeypatch) -> None:
    """A maximized glass used to climb over the inbox when we were already front."""
    from arelis.ui import foreground as fg

    monkeypatch.setattr(fg, "process_owns_foreground", lambda: True)
    owner = QWidget()
    tile = QWidget(owner)
    tile.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.Window)
    owner_raises: list[int] = []
    tile_raises: list[int] = []
    owner_raise = owner.raise_
    tile_raise = tile.raise_

    def _owner_raise() -> None:
        owner_raises.append(1)
        owner_raise()

    def _tile_raise() -> None:
        tile_raises.append(1)
        tile_raise()

    owner.raise_ = _owner_raise  # type: ignore[method-assign]
    tile.raise_ = _tile_raise  # type: ignore[method-assign]
    try:
        owner.show()
        tile.show()
        qt_app.processEvents()
        fg.claim_foreground(tile)
        qt_app.processEvents()
        assert owner_raises == []
        assert tile_raises
    finally:
        tile.deleteLater()
        owner.deleteLater()


def test_claim_foreground_raises_the_tile(qt_app) -> None:
    from arelis.ui.foreground import claim_foreground

    back = QWidget()
    front = QWidget()
    try:
        back.setWindowTitle("back")
        front.setWindowTitle("front")
        back.resize(200, 160)
        front.resize(200, 160)
        back.show()
        front.show()
        front.raise_()
        front.activateWindow()
        qt_app.processEvents()
        claimed: list[QWidget] = []
        original = back.activateWindow

        def _activate() -> None:
            claimed.append(back)
            original()

        back.activateWindow = _activate  # type: ignore[method-assign]
        claim_foreground(back)
        qt_app.processEvents()
        assert claimed == [back]
    finally:
        back.deleteLater()
        front.deleteLater()


def test_click_on_tile_child_claims_when_another_app_is_in_front(
    qt_app, monkeypatch
) -> None:
    from arelis.ui import foreground as fg
    from arelis.ui.glass import seal_tool_window

    monkeypatch.setattr(fg, "process_owns_foreground", lambda: False)
    claimed: list[QWidget] = []
    monkeypatch.setattr(fg, "claim_foreground", lambda w: claimed.append(w))

    plate = QWidget()
    child = QLabel("body", plate)
    try:
        seal_tool_window(plate)
        plate.resize(240, 180)
        child.resize(80, 24)
        plate.show()
        qt_app.processEvents()
        QTest.mouseClick(child, Qt.MouseButton.LeftButton)
        qt_app.processEvents()
        assert claimed
        assert all(widget is plate for widget in claimed)
    finally:
        plate.deleteLater()


def test_click_skips_when_the_tile_is_already_front(qt_app, monkeypatch) -> None:
    from arelis.ui import foreground as fg
    from arelis.ui.glass import seal_tool_window

    monkeypatch.setattr(fg, "process_owns_foreground", lambda: True)
    claimed: list[QWidget] = []
    monkeypatch.setattr(fg, "claim_foreground", lambda w: claimed.append(w))

    plate = QWidget()
    try:
        seal_tool_window(plate)
        plate.show()
        plate.activateWindow()
        qt_app.processEvents()
        if not plate.isActiveWindow():
            pytest.skip("offscreen platform did not activate the plate")
        QTest.mouseClick(plate, Qt.MouseButton.LeftButton)
        qt_app.processEvents()
        assert claimed == []
    finally:
        plate.deleteLater()


def test_arelis_tiles_accept_click_to_front(arelis_window) -> None:
    from arelis.ui.foreground import accepts_click_to_front

    win = arelis_window()
    tiles = [
        win,
        win.calendar_window,
        win.notify_inbox,
        win.contacts_inbox,
        win._filament_chat_tile,
    ]
    for tile in tiles:
        assert accepts_click_to_front(tile), tile.objectName()


def test_floating_dock_accepts_click_to_front(arelis_window) -> None:
    from arelis.ui.dock_surface import apply_dock_chrome
    from arelis.ui.foreground import accepts_click_to_front

    win = arelis_window()
    dock = win.think_dock
    dock.setFloating(True)
    apply_dock_chrome(dock, True)
    dock.show()
    assert accepts_click_to_front(dock)


@pytest.mark.skipif(sys.platform != "win32", reason="WM_MOUSEACTIVATE is Windows")
def test_mouseactivate_claims_a_tile_behind_another_app(qt_app, monkeypatch) -> None:
    from ctypes import addressof, wintypes

    from arelis.ui import foreground as fg
    from arelis.ui.window_resize import MA_ACTIVATE, WM_MOUSEACTIVATE, handle_native_resize

    monkeypatch.setattr(fg, "process_owns_foreground", lambda: False)
    claimed: list[QWidget] = []
    monkeypatch.setattr(fg, "claim_foreground", lambda w: claimed.append(w))

    msg = wintypes.MSG()
    msg.message = WM_MOUSEACTIVATE
    widget = QWidget()
    try:
        assert handle_native_resize(widget, b"windows_generic_MSG", addressof(msg)) == (
            True,
            MA_ACTIVATE,
        )
        assert claimed == [widget]
    finally:
        widget.deleteLater()
