"""Reality plate polish: status, find, band, keys, rubric."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from arelis.earth.copy import (
    band_phrase,
    coach_line,
    deaf_line,
    enter_note,
    inspect_kind_line,
    live_chip_label,
    status_sentence,
)
from arelis.earth.frames import lla_to_ecef
from arelis.earth.goto import suggest
from arelis.earth.key_paste import missing_picture_keys, save_earth_key
from arelis.earth.lod import EarthView, LookBBox
from arelis.earth.polish_score import CHECKS, score
from arelis.earth.runtime import EarthRuntime, set_earth
from arelis.spatial.verbs import classify_physics_act
from arelis.ui.earth_chrome import MARK_HINTS
from arelis.ui.earth_overlay import earth_chip_items, inspect_caption


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth.look import forget

    set_earth(None)
    forget()
    monkeypatch.setattr(
        "arelis.earth.runtime.EarthRuntime._merge_local",
        lambda self: None,
    )
    yield
    forget()
    set_earth(None)


def _mouse(kind, x: float, y: float):
    pos = QPointF(x, y)
    return QMouseEvent(
        kind,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def test_status_is_a_sentence_without_ecef() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    line = status_sentence(earth)
    assert "Watching Earth" in line
    assert "simulated" in line
    assert "Click Live" in line
    assert "ECEF" not in line
    assert "ecef" not in line
    earth.last_view = EarthView("city", lat=35.6, lon=139.7)
    earth.live = True
    line = status_sentence(earth)
    assert "in the city" in line
    assert "live published feeds" in line
    assert "Click Live" not in line


def test_enter_note_is_human() -> None:
    assert "ECEF" not in enter_note(live=False, n=12)
    assert "simulated" in enter_note(live=False, n=12)
    assert "live published" in enter_note(live=True, n=12)
    earth = EarthRuntime()
    note = earth.enter(unix=1.0)
    assert "Watching Earth" in note
    assert "ECEF" not in note
    assert "ECEF" not in earth.status_line()


def test_band_phrase_is_distance_not_a_toggle() -> None:
    assert band_phrase("space") == "from space"
    assert band_phrase("city") == "in the city"
    items = dict(earth_chip_items("space"))
    assert items["band"] == "from space"
    assert items["live"] == "Live off"
    assert "satellites" in items
    city = dict(earth_chip_items("city"))
    assert city["band"] == "in the city"
    assert "people" in city


def test_live_chip_label() -> None:
    assert live_chip_label(on=False) == "Live off"
    assert live_chip_label(on=True) == "Live on"
    assert live_chip_label(on=True, busy=True) == "Live …"


def test_coach_and_deaf_copy() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    assert "Click Live" in (coach_line(earth) or "")
    earth.live = True
    earth.last_view = EarthView(
        "near",
        lat=0.0,
        lon=-150.0,
        bbox=LookBBox(-5, -155, 5, -145),
    )
    for layer in list(earth.layers):
        earth.layers[layer] = False
    assert deaf_line(earth) is not None
    assert "deaf" in (deaf_line(earth) or "").lower() or "hole" in (
        deaf_line(earth) or ""
    ).lower()


def test_find_matches_tokyo_and_iss() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    cities = suggest("tokyo", earth)
    assert any(h.name == "Tokyo" and h.kind == "city" for h in cities)
    tok = suggest("tok", earth)
    assert tok and tok[0].name == "Tokyo"
    iss = suggest("iss", earth)
    assert iss
    home = suggest("home", earth)
    assert isinstance(home, list)


def test_key_paste_writes_without_echo(tmp_path: Path) -> None:
    dest = tmp_path / "secrets.yaml"
    dest.write_text("earth:\n  other: keep\n", encoding="utf-8")
    assert save_earth_key("google_maps_key", "secret-value-xyz", path=dest)
    text = dest.read_text(encoding="utf-8")
    assert "google_maps_key" in text
    assert "secret-value-xyz" in text
    assert "other: keep" in text
    assert not save_earth_key("not_a_field", "x", path=dest)
    missing = missing_picture_keys()
    assert all(len(row) == 3 for row in missing)


def test_inspect_caption_is_english() -> None:
    from arelis.earth.entity import Entity

    pos = lla_to_ecef(51.5, -0.12, 10_000.0)
    text = inspect_caption(
        Entity(
            id="icao:abc",
            cls="aircraft",
            layer="flights",
            label="BAW1",
            x=pos[0],
            y=pos[1],
            z=pos[2],
            vx=100.0,
            source="OpenSky Network",
            freshness="dead-reckoned",
        )
    )
    assert "flight ·" in text
    assert "dead-reckoned" in text
    assert "OpenSky Network" in text
    assert inspect_kind_line("vessels", "simulated") == "ship · drawn, not a live feed"


def test_mark_hints_and_closed_verbs() -> None:
    names = " ".join(f"{k} {h}" for k, h in MARK_HINTS)
    assert "plane" in names
    assert "ship" in names
    assert "ISS" in names
    assert classify_physics_act("enter Earth").verb == "enter_earth"
    assert classify_physics_act("leave Earth").verb == "leave_earth"


def test_plate_find_and_live_click(qt_app, monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.ui.earth_find import apply_goto, open_find, type_find
    from arelis.ui.panels.solar import KEY_HINT_EARTH, SolarPanel

    monkeypatch.setattr("arelis.earth.runtime.EarthRuntime._merge_live", lambda self: None)
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SolarPanel()
    panel.resize(960, 720)
    panel._hud_bottom = 80
    hits, box = panel._earth_chip_layout()
    kinds = [kind for kind, _rect in hits]
    assert kinds[0] == "band"
    assert "live" in kinds
    assert "people" in kinds
    assert not box.isEmpty()
    panel._toggle_earth_chip("band")
    assert earth.live is False
    live_rect = next(rect for kind, rect in hits if kind == "live")
    panel.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, live_rect.center().x(), live_rect.center().y())
    )
    assert earth.live is True
    open_find(panel)
    type_find(panel, "Tokyo")
    assert any(h.name == "Tokyo" for h in panel._earth_find_hits)
    assert apply_goto(panel)
    assert panel._place is not None
    assert panel._place["name"] == "Tokyo"
    slash = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Slash, Qt.KeyboardModifier.NoModifier, "/"
    )
    panel._earth_find_on = False
    assert panel._earth_key_event(slash) is True
    assert panel._earth_find_on is True
    assert "/ find" in KEY_HINT_EARTH
    panel.hide()


def test_polish_rubric_is_complete() -> None:
    passed = {c.id for c in CHECKS}
    scores = score(passed)
    assert scores["intuitiveness"] == 10.0
    assert scores["visual"] == 10.0
    assert scores["friendly"] == 10.0
    assert {c.axis for c in CHECKS} == {"intuitiveness", "visual", "friendly"}
