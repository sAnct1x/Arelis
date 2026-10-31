"""Filament presence keeps her on screen as a floating tile."""

from __future__ import annotations


def test_presence_mode_leaves_the_persona_dock_visible(arelis_window, qt_app) -> None:
    w = arelis_window({"ui": {"default_width": 960, "default_height": 720, "theme": "filament"}})
    w.show()
    qt_app.processEvents()
    assert w._filament_parked is not None
    assert w.persona_dock.isVisible()
    assert w.persona_dock.isFloating()
