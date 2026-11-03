"""An open plate hides its title button: the bead must carry the tile's name for UIA."""

from __future__ import annotations

from unittest.mock import Mock

from PySide6.QtWidgets import QWidget

from arelis.ui.filament_field import FilamentFloatBar


def test_open_tile_stays_named_by_its_bead(qt_app) -> None:
    host = QWidget()
    bar = FilamentFloatBar(Mock(), host)
    bead = bar._beads["history"]
    bar.set_open("history", True)
    assert bead.accessibleName() == "history"
    bar.set_open("history", False)
    assert bead.accessibleName() == "history bead"
