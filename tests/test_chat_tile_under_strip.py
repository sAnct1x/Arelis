"""A parked chat spot from a taller window opens below the slim strip, not behind it.

Babbage, 9434a47 at 1100x800: the chat tile's top ran up under the
"arelis · hands · 1 2 3" strip, so its top border was not visible.
"""

from PySide6.QtCore import QPoint, QRect
from PySide6.QtTest import QTest


def test_parked_chat_opens_below_the_strip(arelis_window):
    w = arelis_window({"ui": {"theme": "night", "filament_ack": True}})
    w.show()
    w.resize(1100, 800)
    QTest.qWait(200)
    w._choose_theme("filament", True)
    QTest.qWait(200)
    origin = w.mapToGlobal(QPoint(0, 0))
    w._filament_tile_pos["chat"] = (origin.x() + 420, origin.y() + 2)
    w.filament._filament_set_chat_open(True)
    QTest.qWait(1500)
    bar = w.title_bar
    strip = QRect(bar.mapToGlobal(QPoint(0, 0)), bar.size())
    assert w._filament_chat_tile.geometry().top() > strip.bottom(), (strip, w._filament_chat_tile.geometry())
