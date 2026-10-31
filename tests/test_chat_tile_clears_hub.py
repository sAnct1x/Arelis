"""Opening chat in filament places its tile beside her hub, never over it."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect
from PySide6.QtTest import QTest


def test_chat_tile_opens_clear_of_her_hub(arelis_window, qt_app) -> None:
    w = arelis_window(
        {
            "ui": {
                "default_width": 900,
                "default_height": 650,
                "theme": "night",
                "filament_ack": True,
            }
        }
    )
    w.show()
    qt_app.processEvents()
    w._choose_theme("filament", True)
    w.filament._filament_set_chat_open(True)
    QTest.qWait(1500)
    stage = w.persona_stage
    hub = QRect(stage.mapToGlobal(QPoint(0, 0)), stage.size())
    assert stage.isVisible() and hub.width() > 0
    assert not w._filament_chat_tile.geometry().intersects(hub)


def test_her_panel_fits_a_small_hub(arelis_window, qt_app) -> None:
    w = arelis_window(
        {
            "ui": {
                "default_width": 900,
                "default_height": 650,
                "theme": "night",
                "filament_ack": True,
            }
        }
    )
    w.show()
    qt_app.processEvents()
    w._choose_theme("filament", True)
    qt_app.processEvents()
    stage = w.persona_stage
    assert stage.width() < 220  # a hub smaller than the old dock floor
    assert w.persona_panel.geometry() == stage.rect()
