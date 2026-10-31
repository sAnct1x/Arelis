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


def test_chat_tile_steps_off_her_hub_when_the_window_shrinks(arelis_window, qt_app) -> None:
    w = arelis_window(
        {
            "ui": {
                "default_width": 1800,
                "default_height": 1100,
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
    tile = w._filament_chat_tile
    # The chat tile sits where her hub will be once the window is small.
    tile.setGeometry(QRect(hub.left(), hub.top() - 200, 320, 280))
    w.setGeometry(QRect(w.geometry().topLeft(), w.geometry().size() / 2))
    QTest.qWait(300)
    hub = QRect(stage.mapToGlobal(QPoint(0, 0)), stage.size())
    assert not tile.geometry().intersects(hub)


def test_a_chat_spot_parked_in_a_bigger_window_steps_off_her_hub(arelis_window, qt_app) -> None:
    # Babbage, 1100x800: the parked spot put the tile over her hub and 36 px
    # past the window's left edge.
    w = arelis_window(
        {
            "ui": {
                "default_width": 1100,
                "default_height": 800,
                "theme": "night",
                "filament_ack": True,
                "filament_tile_pos": {"chat": {"x": -36, "y": 300}},
            }
        }
    )
    w.show()
    w.resize(1100, 800)
    qt_app.processEvents()
    w._choose_theme("filament", True)
    w.filament._filament_set_chat_open(True)
    QTest.qWait(1500)
    stage = w.persona_stage
    hub = QRect(stage.mapToGlobal(QPoint(0, 0)), stage.size())
    tile = w._filament_chat_tile.geometry()
    assert not tile.intersects(hub)
    assert tile.left() >= w.geometry().left()
