"""The orbit ticks at 60 Hz, but never faster than filament_render's worker paints a
frame: a worker painting nonstop would hog the GIL from the GUI thread."""

from __future__ import annotations

import time

from arelis.ui.filament_field import FilamentField


def test_tick_backs_off_to_the_workers_own_paint_cost(qt_app, monkeypatch) -> None:
    from PySide6.QtCore import QRect

    from arelis.ui.filament_render import FieldRenderer

    field = FilamentField()
    assert field.atmosphere_ms() == 16

    def slow_paint(self, painter, rect) -> None:  # 40 ms of worker CPU
        end = time.thread_time() + 0.04
        while time.thread_time() < end:
            pass

    monkeypatch.setattr(FilamentField, "_paint", slow_paint)
    render = FieldRenderer(field)
    try:
        render.request(QRect(0, 0, 320, 180), 1.0)
        deadline = time.monotonic() + 5
        while render.frame() is None and time.monotonic() < deadline:
            qt_app.processEvents()
            time.sleep(0.005)
        assert render.frame() is not None
        assert field.atmosphere_ms() >= 39
        field.set_load("camera")
        assert field.atmosphere_ms() == 50
    finally:
        render.stop()
