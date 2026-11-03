"""An open plate keeps its title on the coil, and its bead keeps "<name> bead" (v11c)."""

from __future__ import annotations

from unittest.mock import Mock

from PySide6.QtCore import QPointF, QRect
from PySide6.QtWidgets import QWidget

from arelis.ui.filament_field import FilamentFloatBar


def test_open_tile_keeps_its_title_and_bead_name(qt_app) -> None:
    host = QWidget()
    host.resize(800, 600)
    field = Mock()
    field.float_points.return_value = (QPointF(100, 100), QPointF(140, 100))
    field.is_live.return_value = False
    bar = FilamentFloatBar(field, host)
    bar._place_hands = lambda rect: None
    bar.set_open("history", True)
    bar.place(QRect(0, 0, 800, 600))
    assert not bar.chips()["history"].isHidden()
    assert bar.chips()["history"].text() == "history"
    assert bar._beads["history"].accessibleName() == "history bead"
