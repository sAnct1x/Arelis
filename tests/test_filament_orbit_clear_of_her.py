"""Filament: the orbit and reality sit on the desk left of her figure, so a click on her centre
reaches the stage, as in Night and Sodium; the ask ('say "hey arelis"') sits in the top right."""

from __future__ import annotations


def test_orbit_settles_left_of_her_and_her_centre_is_the_stage(arelis_window, qt_app) -> None:
    w = arelis_window({"ui": {"default_width": 1600, "default_height": 900, "theme": "filament"}})
    w.show()
    qt_app.processEvents()
    stage = w.persona_stage
    band_left = stage.parentWidget().mapTo(w, stage.zone().topLeft()).x()
    field = w._filament
    cx, _cy, rx, _ry = field.ellipse(w.rect(), settled=True)
    assert cx + rx < band_left
    ask = field.prompt_point(w.rect())
    assert ask.x() > w.width() * 0.75 and ask.y() < w.height() * 0.15  # the top right corner
    assert field.bead_point("reality", w.rect()).x() < band_left
    hit = w.childAt(w._filament.hub.toPoint())
    assert hit is not None and not w.conversation.isAncestorOf(hit) and hit is not w.conversation


def test_the_ask_at_the_top_right_is_really_on_screen(arelis_window, qt_app) -> None:
    from PySide6.QtCore import QPoint

    from arelis.ui.void_idle import OrbitIdle

    w = arelis_window({"ui": {"default_width": 1600, "default_height": 900, "theme": "filament"}})
    w.show()
    qt_app.processEvents()
    ask = next(v for v in w.findChildren(OrbitIdle) if v.isVisible()).listen_word
    # Not clipped by the chat column it was built in: it shows, and a click there reaches it.
    assert not ask.visibleRegion().isEmpty()
    assert w.childAt(ask.mapTo(w, ask.rect().center())) is ask
    assert ask.mapTo(w, QPoint(0, 0)).x() > w.width() * 0.6
