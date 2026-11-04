"""A switch into Filament gives her stage one region, not one per chrome step.

Babbage, 9434a47 trace: the hub took 273x546, 275x550, 300x600, 313x626 over
170 ms while the title bar slimmed and the bars hid, and Chromium dropped every
frame meanwhile (633-683 ms stall). The switch now settles the layout first.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


class _Geo(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.seen = []

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.Resize:
            self.seen.append(obj.size())
        return False


def test_switch_into_filament_places_her_stage_once(arelis_window) -> None:
    w = arelis_window(
        {"ui": {"theme": "night", "filament_ack": True, "default_width": 1600, "default_height": 1000}}
    )
    w.show()
    QTest.qWait(300)
    face = w._sync_filament_face

    def pumping_face():  # native tile windows pump messages mid-switch on Windows
        QApplication.processEvents()
        face()

    w._sync_filament_face = pumping_face
    geo = _Geo()
    w.persona_stage.installEventFilter(geo)
    w._choose_theme("filament", True)
    QTest.qWait(500)
    assert len(geo.seen) == 1, geo.seen
