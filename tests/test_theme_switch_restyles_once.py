"""A room switch costs one app-wide restyle, not one per copy of the sheet."""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QEvent, QObject
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


class _StyleChanges(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.seen: Counter[int] = Counter()

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.StyleChange:
            self.seen[id(obj)] += 1
        return False


def _count(fn, widgets):
    counter = _StyleChanges()
    app = QApplication.instance()
    app.installEventFilter(counter)
    try:
        fn()
    finally:
        app.removeEventFilter(counter)
    return [counter.seen[id(x)] for x in widgets]


def test_switch_into_filament_restyles_like_one_app_sheet(arelis_window, qt_app) -> None:
    w = arelis_window({"ui": {"theme": "night", "filament_ack": True}})
    w.show()
    QTest.qWait(200)
    composer = w.conversation._composer
    widgets = [w, composer]
    switch = _count(lambda: w._choose_theme("filament", True), widgets)
    app = QApplication.instance()
    css = app.styleSheet()
    one_sheet = _count(lambda: app.setStyleSheet(css + " "), widgets)
    # A second copy of the sheet on the window doubled this. The colour layer
    # now sits on the window's children, so a switch costs at most one app
    # sheet change and still reaches the composer.
    assert all(s <= o for s, o in zip(switch, one_sheet, strict=True))
    assert switch[1] >= 1
