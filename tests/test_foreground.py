"""Clicking a tile behind another app must raise it, same as the glass."""

from __future__ import annotations

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


