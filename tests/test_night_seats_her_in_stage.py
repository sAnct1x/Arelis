"""Night seats her in the stage band: the dock stays a hidden alias and the chat ends where she begins."""

from __future__ import annotations


def test_night_hosts_her_in_the_band_not_the_dock(arelis_window, qt_app) -> None:
    w = arelis_window({"ui": {"default_width": 1200, "default_height": 800, "theme": "night"}})
    w.show()
    qt_app.processEvents()
    assert w.persona_panel.parentWidget() is w.persona_stage
    assert w.persona_stage.isVisible()
    w._sync_panel_margins()
    right = w._stage_layout.contentsMargins().right()
    assert w.conversation.geometry().right() < w.persona_stage.geometry().left()
    assert right >= w.persona_stage.width()
