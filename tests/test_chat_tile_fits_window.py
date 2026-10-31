"""At 1100x800 the Filament chat tile we place stays inside the window."""

from PySide6.QtCore import QPoint, QRect
from PySide6.QtTest import QTest


def test_chat_tile_fits_window(arelis_window):
    w = arelis_window({"ui": {"theme": "night", "filament_ack": True}})
    w.show()
    w.resize(1100, 800)
    QTest.qWait(200)
    w._choose_theme("filament", True)
    QTest.qWait(200)
    w.filament._filament_set_chat_open(True)
    QTest.qWait(1500)
    frame = QRect(w.mapToGlobal(QPoint(0, 0)), w.size())
    tile = w._filament_chat_tile.geometry()
    assert frame.contains(tile), (frame, tile)
    assert tile.top() >= frame.top() + w.title_bar.height()
    stage = w.persona_stage
    assert not tile.intersects(QRect(stage.mapToGlobal(QPoint(0, 0)), stage.size()))
