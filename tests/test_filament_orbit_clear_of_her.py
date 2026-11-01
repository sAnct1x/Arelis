"""Filament: the orbit, the ask and reality sit on the desk left of her band, so a click on her
centre reaches the stage, as in Night and Sodium."""

from __future__ import annotations


def test_orbit_settles_left_of_her_and_her_centre_is_the_stage(arelis_window, qt_app) -> None:
    w = arelis_window({"ui": {"default_width": 1600, "default_height": 900, "theme": "filament"}})
    w.show()
    qt_app.processEvents()
    stage = w.persona_stage
    band_left = stage.parentWidget().mapTo(w, stage.geometry().topLeft()).x()
    field = w._filament
    cx, _cy, rx, _ry = field.ellipse(w.rect(), settled=True)
    assert cx + rx < band_left
    assert field.prompt_point(w.rect()).x() < band_left
    assert field.bead_point("reality", w.rect()).x() < band_left
    hit = w.childAt(stage.mapTo(w, stage.rect().center()))
    assert hit is not None and not w.conversation.isAncestorOf(hit) and hit is not w.conversation
