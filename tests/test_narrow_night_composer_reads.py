"""Narrow Night window: the composer input keeps room for its placeholder.

Babbage, 1100x800 with history open, mid-turn: the input was 22 px wide and the
placeholder read "m". The band now gives way to the composer row's minimum.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest


def test_composer_input_fits_its_placeholder_at_1100x800(arelis_window, qt_app) -> None:
    w = arelis_window(
        {
            "ui": {
                "theme": "night",
                "filament_ack": True,
                "default_width": 1100,
                "default_height": 800,
            }
        }
    )
    w.show()
    w.resize(1100, 800)
    w.history_dock.show()
    w.resizeDocks([w.history_dock], [400], Qt.Orientation.Horizontal)
    QTest.qWait(200)
    conv = w.conversation
    conv.chat._ensure_view()
    conv.set_busy(True)
    conv.set_idle_mode(False)
    for btn in (conv.mic_btn, conv.conversation_btn):
        btn.show()
    QTest.qWait(300)
    text = conv.input.fontMetrics().horizontalAdvance("message Arelis…")
    assert conv.input.isVisible()
    assert conv.input.width() >= text
    assert conv._composer.width() >= conv._composer.minimumSizeHint().width()
    chat_right = conv.mapTo(w, QPoint(conv.width(), 0)).x()
    band_left = w.persona_stage.mapTo(w, QPoint(0, 0)).x()
    assert chat_right <= band_left
