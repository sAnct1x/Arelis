"""Idle and away rest close the instruments but never hide her."""

from __future__ import annotations

from arelis.ui.idle_host import enter_away_rest, return_to_idle


def test_idle_and_away_rest_leave_her_visible(arelis_window, qt_app) -> None:
    w = arelis_window({"ui": {"default_width": 1200, "default_height": 800, "theme": "night"}})
    w.show()
    w.history_dock.show()
    qt_app.processEvents()
    return_to_idle(w)
    assert w.persona_panel.isVisible()
    assert w.history_dock.isHidden()
    w.history_dock.show()
    w._away_rest = True
    enter_away_rest(w)
    assert w._away_resting
    assert w.persona_panel.isVisible()
    assert w.history_dock.isHidden()
