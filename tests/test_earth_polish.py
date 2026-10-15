"""Reality plate polish: status, find, band, keys, rubric."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from arelis.earth.copy import (
    band_phrase,
    enter_note,
    live_chip_label,
    status_sentence,
)
from arelis.earth.entity import Entity
from arelis.earth.lod import EarthView
from arelis.earth.runtime import EarthRuntime, set_earth
from arelis.ui.earth_overlay import earth_chip_items


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
    assert "waiting on published feeds" in line
    assert "Click Live" not in line
    earth.store.upsert(
        Entity(
            id="icao:pub",
            cls="aircraft",
            layer="flights",
            label="PUB",
            x=0.0,
            y=0.0,
            z=0.0,
            freshness="live",
            source="OpenSky",
        )
    )
    assert "live published feeds" in status_sentence(earth)
    earth._live_busy = True
    earth.store.clear()
    assert "fetching published feeds" in status_sentence(earth)
    earth._live_busy = False
    earth.live = False
    earth.store.upsert(
        Entity(
            id="icao:pub",
            cls="aircraft",
            layer="flights",
            label="PUB",
            x=0.0,
            y=0.0,
            z=0.0,
            freshness="live",
            source="OpenSky",
        )
    )
    coast = status_sentence(earth)
    assert "coasting" in coast
    assert "Live keeps pulling" not in coast


def test_enter_note_is_human() -> None:
    assert "ECEF" not in enter_note(live=False, n=12)
    assert "simulated" in enter_note(live=False, n=12)
    assert "coast" in enter_note(live=False, n=12, snapshot=True)
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
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth.live = True
    set_earth(earth)
    assert dict(earth_chip_items("space"))["live"] == "Live on"
    assert "satellites" in items
    city = dict(earth_chip_items("city"))
    assert city["band"] == "in the city"
    assert "people" in city
    near = dict(earth_chip_items("near"))
    assert "tiles" not in near
    assert "flights" in near
    assert "satellites" in near


def test_live_chip_label() -> None:
    assert live_chip_label(on=False) == "Live off"
    assert live_chip_label(on=True) == "Live on"
    assert live_chip_label(on=True, busy=True) == "Live …"
    assert live_chip_label(on=False, busy=True) == "Live off"
    from arelis.earth.copy import loading_line, ride_hint
    from arelis.earth.lod import EarthView

    assert ride_hint("iss") == "click to ride · Esc to leave it"
    assert ride_hint("iss", riding=True) == "Esc or click empty sky to hop off"
    assert ride_hint("satellites") == ""
    earth = EarthRuntime()
    earth.last_view = EarthView("space")
    assert loading_line(earth, busy=True) == "fetching satellites"
    assert loading_line(earth, globe_ready=False) == "falling in"
    assert loading_line(earth, globe_failed=True) == "fancy map failed — NASA ball"
    from arelis.ui.panels.solar_earth import SPACE_ENTER_ALT_M, earth_enter_lla

    lat, lon, alt = earth_enter_lla(None)
    assert alt == SPACE_ENTER_ALT_M
    from arelis.earth.frames import subsolar_lla

    slat, slon = subsolar_lla()
    assert abs(lat - slat) < 0.2
    assert abs(((lon - slon + 180) % 360) - 180) < 0.2
    earth.last_view = EarthView("space", lat=40.0, lon=-83.0)
    assert earth_enter_lla(earth) == (40.0, -83.0, SPACE_ENTER_ALT_M)


