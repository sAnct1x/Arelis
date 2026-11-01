"""Quick 3D in Night and Sodium: her view is the stage's base layer, so the look's haze has no band edge (a box)."""

from __future__ import annotations


def test_in_night_under_quick3d_her_view_fills_the_stage(arelis_window, qt_app, monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", "qq3d")
    w = arelis_window({"ui": {"default_width": 1600, "default_height": 900, "theme": "night"}})
    w.show()
    qt_app.processEvents()
    stage = w.persona_stage
    assert stage.geometry() == stage.parentWidget().rect()
    assert stage.zone().left() > stage.parentWidget().width() // 2
