"""Earth globe stack and Cesium bridge contract. No WebEngine required."""

from __future__ import annotations

import os
import sys

import pytest

from arelis.earth.globe_stack import (
    CESIUM_JS,
    GIBS_XYZ,
    GOOGLE_3D,
    OSM_XYZ,
    choose_stack,
)
from arelis.earth.runtime import EarthRuntime, set_earth
from arelis.ui.earth_globe_host import (
    building_rows,
    entity_rows,
    globe_http_user_agent,
    globe_line,
    globe_wants_own_process,
    parse_globe_line,
    place_rows,
    webengine_available,
)


def test_stack_picks_photoreal_then_ion_then_gibs() -> None:
    assert choose_stack(google_key="", ion_token="").kind == "gibs"
    assert choose_stack(google_key="", ion_token="token").kind == "ion"
    stack = choose_stack(google_key="maps-key", ion_token="ion")
    assert stack.kind == "photoreal"
    payload = stack.to_payload()
    assert payload["googleKey"] == "maps-key"
    assert "NASA" in payload["credits"]
    assert "Google" in payload["credits"]
    assert payload["photorealAltM"] == "8000"
    assert payload["cesiumBase"].startswith("https://cesium.com/")
    assert payload["cesiumBase"].endswith("/")
    assert "cesium.com" in CESIUM_JS
    assert "gibs.earthdata.nasa.gov" in GIBS_XYZ
    assert "tile.googleapis.com" in GOOGLE_3D
    assert "tile.openstreetmap.org" in OSM_XYZ


def test_globe_names_itself_to_osm() -> None:
    from arelis import __source_url__, __version__

    ua = globe_http_user_agent()
    assert ua.startswith(f"Arelis/{__version__}")
    assert __source_url__ in ua


def test_entity_rows_skip_people_and_carry_lla() -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.frames import lla_to_ecef
    from arelis.earth.lod import EarthView

    set_earth(None)
    earth = EarthRuntime()
    earth.active = True
    earth.layers["flights"] = True
    earth.last_view = EarthView(band="approach", lat=39.7817, lon=-89.6501)
    x, y, z = lla_to_ecef(39.7817, -89.6501, 10_000.0)
    earth.store.upsert(
        Entity(
            id="flt:1",
            cls="aircraft",
            layer="flights",
            label="TEST1",
            x=x,
            y=y,
            z=z,
            meta={"lat": 39.7817, "lon": -89.6501, "alt": 10000.0, "track_deg": 45.0},
        )
    )
    earth.store.upsert(
        Entity(
            id="p:1",
            cls="person",
            layer="people",
            label="nope",
            x=x,
            y=y,
            z=z,
            meta={"lat": 39.7817, "lon": -89.6501},
        )
    )
    set_earth(earth)
    rows = entity_rows()
    assert all(row["id"] != "p:1" for row in rows)
    hit = next(row for row in rows if row["id"] == "flt:1")
    assert hit["lat"] == 39.7817
    assert hit["lon"] == -89.6501
    assert hit["layer"] == "flights"
    assert hit["mark"] == "flights"
    assert hit["heading_deg"] == 45.0
    assert hit["freshness"] == "simulated"
    set_earth(None)


def test_entity_rows_vessel_cog_and_freshness() -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.frames import lla_to_ecef
    from arelis.earth.lod import EarthView

    set_earth(None)
    earth = EarthRuntime()
    earth.active = True
    earth.layers["vessels"] = True
    earth.last_view = EarthView(band="near", lat=39.7817, lon=-89.6501)
    x, y, z = lla_to_ecef(39.7817, -89.6501, 0.0)
    earth.store.upsert(
        Entity(
            id="ves:1",
            cls="vessel",
            layer="vessels",
            label="TESTSHIP",
            x=x,
            y=y,
            z=z,
            freshness="live",
            meta={"lat": 39.7817, "lon": -89.6501, "cog_deg": 270.0},
        )
    )
    set_earth(earth)
    rows = entity_rows()
    hit = next(row for row in rows if row["id"] == "ves:1")
    assert hit["mark"] == "vessels"
    assert hit["heading_deg"] == 270.0
    assert hit["freshness"] == "live"
    set_earth(None)


def test_entity_lla_orbital_uses_geodetic_not_sphere() -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.frames import ecef_to_geodetic, ecef_to_lla, lla_to_ecef
    from arelis.earth.lod import entity_lla

    x, y, z = lla_to_ecef(51.6, -0.1, 408_000.0)
    sat = Entity(
        id="sat:tle",
        cls="satellite",
        layer="satellites",
        label="TLE",
        x=x,
        y=y,
        z=z,
        freshness="live",
    )
    pair = entity_lla(sat)
    assert pair is not None
    geo = ecef_to_geodetic(x, y, z)
    sphere = ecef_to_lla(x, y, z)
    assert pair[0] == pytest.approx(geo[0], abs=1e-6)
    assert pair[1] == pytest.approx(geo[1], abs=1e-6)
    assert abs(pair[0] - sphere[0]) > 0.05


def test_photoreal_miss_does_not_fail_the_host(qt_app, monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.ui.earth_globe_host.webengine_available", lambda: False
    )
    from arelis.ui.earth_globe_host import EarthGlobeHost

    host = EarthGlobeHost()
    host.failed = False
    host._on_failed("photoreal")
    assert host.failed is False
    host._on_failed("cesium")
    assert host.failed is True
    host.hide()


def test_solar_gl_releases_the_context_before_cesium(qt_app) -> None:
    from arelis.ui.solar_gl import SolarSpaceView

    view = SolarSpaceView.__new__(SolarSpaceView)
    view._ctx = None
    SolarSpaceView.release_current(view)
    hits: list[int] = []

    class _Ctx:
        def doneCurrent(self) -> None:
            hits.append(1)

    view._ctx = _Ctx()
    SolarSpaceView.release_current(view)
    assert hits == [1]


def test_solar_gl_park_skips_make_current(qt_app) -> None:
    from PySide6.QtGui import QImage

    from arelis.ui.solar_gl import SolarSpaceView

    view = SolarSpaceView.__new__(SolarSpaceView)
    view.gl_ok = True
    view._surface = object()
    view._parked = False
    view._frame = QImage(2, 2, QImage.Format.Format_RGB32)
    view._frame_key = None
    hits: list[str] = []

    class _Ctx:
        def doneCurrent(self) -> None:
            hits.append("done")

        def makeCurrent(self, _surface) -> bool:
            hits.append("make")
            return True

    view._ctx = _Ctx()
    SolarSpaceView.park(view)
    assert "done" in hits
    assert view._parked
    assert view._ctx is None
    assert view.gl_ok is False
    hits.clear()
    out = SolarSpaceView.render(view, 8, 8, stars_only=True)
    assert out is view._frame
    assert "make" not in hits
    SolarSpaceView.unpark(view)
    assert view._parked is False


def test_pytest_does_not_forbid_cesium(qt_app) -> None:
    from arelis.ui.panels.solar import SolarPanel

    panel = SolarPanel()
    panel._cesium_off = False
    if webengine_available():
        assert panel._cesium_forbidden() is False
        assert panel._skip_cesium() is False
    else:
        assert panel._cesium_forbidden() is True


def test_gpu_env_does_not_forbid_cesium(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arelis.ui.panels.solar import SolarPanel

    monkeypatch.setattr("arelis.ui.solar_gl.gl_wanted", lambda: True)
    monkeypatch.setattr(
        "arelis.ui.earth_globe_host.webengine_available", lambda: True
    )
    panel = SolarPanel()
    panel._gl = None
    panel._cesium_off = False
    assert panel._skip_cesium() is False
    assert panel._cesium_forbidden() is False


def test_enter_earth_parks_solar_gl_for_cesium(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Destroy the offscreen context, then schedule Cesium — under pytest too."""
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QImage

    from arelis.ui.panels.solar import SolarPanel

    panel = SolarPanel()
    monkeypatch.setattr(
        "arelis.ui.earth_globe_host.webengine_available", lambda: True
    )
    monkeypatch.setattr(QTimer, "singleShot", lambda *_a, **_k: None)
    calls: list[str] = []

    class FakeGL:
        gl_ok = True
        _parked = False

        def park(self) -> None:
            calls.append("park")
            self._parked = True

        def render(self, *_a, **_k):
            calls.append("render")
            img = QImage(4, 4, QImage.Format.Format_RGB32)
            img.fill(0)
            return img

    panel._gl = FakeGL()
    panel._cesium_off = False
    panel._enter_earth_globe()
    assert "park" in calls
    assert "render" not in calls
    assert panel._cesium_off is False
    assert panel._globe_host is None
    assert panel._cesium_forbidden() is False


def test_leave_earth_drops_webengine(qt_app) -> None:
    from arelis.ui.panels.solar import SolarPanel

    panel = SolarPanel()
    retired: list[str] = []

    class _Widget:
        def hide(self) -> None:
            retired.append("hide")

        def deleteLater(self) -> None:
            retired.append("delete")

    class Host(_Widget):
        def __init__(self) -> None:
            self._view = _Widget()

        def shutdown(self) -> None:
            retired.append("shutdown")

    class FakeGL:
        _parked = True

        def unpark(self) -> None:
            retired.append("unpark")
            self._parked = False

    panel._globe_host = Host()
    panel._earth_hud = _Widget()
    panel._gl = FakeGL()
    panel._leave_earth_globe()
    assert panel._globe_host is None
    assert panel._earth_hud is None
    assert retired.count("delete") >= 2
    assert "shutdown" in retired
    assert "unpark" in retired


def test_hiding_solar_drops_cesium(qt_app) -> None:
    from arelis.ui.panels.solar import SolarPanel

    panel = SolarPanel()
    retired: list[str] = []

    class Host:
        def hide(self) -> None:
            retired.append("hide")

        def deleteLater(self) -> None:
            retired.append("delete")

        def shutdown(self) -> None:
            retired.append("shutdown")

        _view = None

    panel._globe_host = Host()
    from PySide6.QtGui import QHideEvent

    panel.hideEvent(QHideEvent())
    assert panel._globe_host is None
    assert "shutdown" in retired
    from arelis.earth.runtime import EarthRuntime, get_earth, set_earth

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel2 = SolarPanel()
    panel2.hideEvent(QHideEvent())
    zone = get_earth()
    assert zone is None or zone.active is False
    set_earth(None)


def test_cesium_off_blocks_late_mount_even_without_gl(qt_app) -> None:
    from arelis.ui.panels.solar import SolarPanel

    panel = SolarPanel()
    panel._gl = None
    panel._cesium_off = True
    assert panel._skip_cesium() is True
    panel._mount_earth_globe()
    assert panel._globe_host is None
    panel._park_space_for_earth()
    assert panel._globe_host is None


def test_gpu_travel_parks_then_mounts_cesium(qt_app) -> None:
    """Enter Earth parks solar GL, then mounts Cesium under pytest."""
    from arelis.earth.runtime import get_earth, set_earth
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import SolarPanel

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_earth(None)
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    panel.resize(640, 480)
    calls: list[str] = []

    class FakeGL:
        gl_ok = True
        _parked = False

        def park(self) -> None:
            calls.append("park")
            self._parked = True

        def unpark(self) -> None:
            calls.append("unpark")
            self._parked = False

        def render(self, *_a, **_k):
            from PySide6.QtGui import QImage

            img = QImage(4, 4, QImage.Format.Format_RGB32)
            img.fill(0)
            return img

    panel._gl = FakeGL()
    panel._travel_to("Earth")
    panel._finish_travel()
    zone = get_earth()
    assert zone is None or zone.active is False
    panel._enter_earth_zone()
    zone = get_earth()
    assert zone is not None and zone.active
    assert panel._cesium_off is False
    assert "park" in calls
    assert panel._globe_host is None
    panel._mount_earth_globe()
    if webengine_available():
        assert panel._globe_host is not None
        assert panel._globe_host.failed is False
    else:
        assert panel._globe_host is None
    panel._leave_earth_zone()
    assert zone.active is False
    assert panel._globe_host is None
    assert "unpark" in calls
    panel._enter_earth_zone()
    again = get_earth()
    assert again is not None and again.active
    assert panel._cesium_off is False
    panel._mount_earth_globe()
    if webengine_available():
        assert panel._globe_host is not None
    panel.hide()
    panel._leave_earth_zone()
    set_system(None)
    set_earth(None)


def test_earth_hud_is_the_same_sodium_chrome(qt_app) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    from arelis.ui.earth_globe_host import EarthHudGlass

    panel = QWidget()
    panel.resize(640, 480)
    hud = EarthHudGlass(panel)
    assert not hud.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    flags = hud.windowFlags()
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    hud.hide()
    panel.hide()


@pytest.mark.timeout(20)
@pytest.mark.skipif(
    sys.platform != "win32" and not os.environ.get("ARELIS_GLOBE_HOST_TEST"),
    reason="EarthGlobeHost can hang headless Linux past pytest-timeout's thread method",
)
def test_pytest_constructs_webengine_host(qt_app) -> None:
    if not webengine_available():
        pytest.skip("Qt WebEngine is not installed")
    from PySide6.QtCore import Qt

    from arelis.ui.earth_globe_host import EarthGlobeHost

    host = EarthGlobeHost()
    assert host.failed is False
    assert host._view is not None
    assert not host.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert host.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    host.hide()
    host.deleteLater()
    qt_app.processEvents()


def test_earth_zone_paint_does_not_touch_solar_gl(qt_app) -> None:
    from PySide6.QtGui import QImage

    from arelis.ui.panels.solar import SolarPanel

    panel = SolarPanel()
    calls: list[str] = []

    class FakeGL:
        gl_ok = True
        _parked = False

        def render(self, *_a, **_k):
            calls.append("render")
            img = QImage(4, 4, QImage.Format.Format_RGB32)
            img.fill(0)
            return img

        def park(self) -> None:
            calls.append("park")
            self._parked = True

        def unpark(self) -> None:
            calls.append("unpark")
            self._parked = False

        def release_current(self) -> None:
            calls.append("release")

    class FakeHost:
        failed = False

        def isVisible(self) -> bool:
            return True

        def setGeometry(self, _rect) -> None:
            return None

        def hide(self) -> None:
            return None

    panel._gl = FakeGL()
    panel.resize(64, 64)
    panel._park_space_for_earth()
    assert "park" in calls
    assert "render" not in calls
    panel._globe_host = FakeHost()
    panel.paintEvent(None)
    assert "render" not in calls
    panel._leave_earth_globe()
    assert "unpark" in calls


def test_building_rows_need_city_and_the_chip(tmp_path) -> None:
    from arelis.earth.buildings import _cache_dir_for_tests
    from arelis.earth.lod import EarthView

    _cache_dir_for_tests(tmp_path)
    key = "39.78_-89.65"
    (tmp_path / f"{key}.json").write_text(
        '{"unix": 1, "rings": [[[39.78, -89.65], [39.781, -89.650], [39.7817, -89.6501]]]}',
        encoding="utf-8",
    )
    earth = EarthRuntime()
    earth.active = True
    earth.buildings = True
    earth.last_view = EarthView(band="space", lat=39.7817, lon=-89.6501)
    set_earth(earth)
    assert building_rows() == []
    earth.last_view = EarthView(band="city", lat=39.7817, lon=-89.6501)
    earth.buildings = False
    assert building_rows() == []
    earth.buildings = True
    rows = building_rows()
    assert len(rows) == 1
    assert rows[0][0] == [39.78, -89.65]
    set_earth(None)
    from arelis.paths import state_dir

    _cache_dir_for_tests(state_dir() / "earth" / "buildings")


def test_chromium_disables_gpu_when_a_share_context_exists(monkeypatch) -> None:
    from arelis.ui.earth_globe_host import prepare_chromium_for_shared_gl

    monkeypatch.setattr(
        "PySide6.QtGui.QOpenGLContext.globalShareContext", lambda: object()
    )
    env: dict[str, str] = {}
    flags = prepare_chromium_for_shared_gl(env)
    assert "--disable-gpu" in flags
    assert env["QTWEBENGINE_CHROMIUM_FLAGS"] == flags
    already = {"QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu --foo"}
    assert prepare_chromium_for_shared_gl(already) == "--disable-gpu --foo"
    parked: dict[str, str] = {}
    assert prepare_chromium_for_shared_gl(parked, share_live=False) == ""
    assert "QTWEBENGINE_CHROMIUM_FLAGS" not in parked


def test_chromium_keeps_gpu_without_a_share_context(monkeypatch) -> None:
    from arelis.ui.earth_globe_host import prepare_chromium_for_shared_gl

    monkeypatch.setattr(
        "PySide6.QtGui.QOpenGLContext.globalShareContext", lambda: None
    )
    env: dict[str, str] = {}
    assert prepare_chromium_for_shared_gl(env) == ""
    assert "QTWEBENGINE_CHROMIUM_FLAGS" not in env


def test_inspecting_mercury_leaves_earth(qt_app) -> None:
    from arelis.earth.runtime import EarthRuntime, get_earth, set_earth
    from arelis.ui.panels.solar import SolarPanel

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SolarPanel()
    panel._set_inspect("Mercury")
    zone = get_earth()
    assert zone is None or zone.active is False
    assert panel._inspect == "Mercury"
    set_earth(None)


def test_show_event_does_not_remount_cesium(qt_app, monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth.runtime import EarthRuntime, set_earth
    from arelis.ui.panels.solar import SolarPanel

    calls: list[str] = []
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SolarPanel()
    monkeypatch.setattr(panel, "_enter_earth_globe", lambda: calls.append("enter"))
    from PySide6.QtGui import QShowEvent

    panel._globe_host = None
    panel.showEvent(QShowEvent())
    assert calls == []
    set_earth(None)


def test_find_field_is_capped() -> None:
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QApplication

    from arelis.ui.earth_find import _FIELD_MAX_W, layout_find

    app = QApplication.instance()
    fm = QFontMetrics(app.font()) if app is not None else QFontMetrics(QApplication([]).font())
    _box, field, _rows = layout_find(fm, 10, 40, 1600, open_=False, hits=[])
    assert field.width() == _FIELD_MAX_W
    assert field.width() <= 380


def test_place_rows_space_is_empty() -> None:
    assert place_rows("space", 0.0, 0.0) == []
    near = place_rows("approach", 0.0, 0.0)
    assert isinstance(near, list)
    assert len(near) <= 8
    assert webengine_available() in {True, False}


def test_hud_glass_does_not_forward_events() -> None:
    from arelis.ui.earth_globe_host import GLOBE_DIR

    host = (GLOBE_DIR.parent / "earth_globe_host.py").read_text(encoding="utf-8")
    proc = (GLOBE_DIR.parent / "earth_globe_proc.py").read_text(encoding="utf-8")
    js = (GLOBE_DIR / "bridge.js").read_text(encoding="utf-8")
    html = (GLOBE_DIR / "index.html").read_text(encoding="utf-8")
    assert "GlobeKeyHose" in host
    assert "deliver_globe_key" in host
    assert "skyBox" in js
    assert "if (viewer.scene.skyBox)" in js
    assert "baseLayer: false" in js
    assert "CESIUM_BASE_URL" in js
    assert "billboard" in js
    assert "PinBuilder" not in js
    assert js.count("billboard") > js.count("point:")
    assert "marksJson" in js
    assert "marksJson" in host
    assert "push_marks" in host
    assert 'bridge.failed("photoreal")' not in js
    assert "prepare_chromium_for_shared_gl" in host
    assert "disable-gpu" in host
    assert "globe_wants_own_process" in host
    assert "earth_globe_proc" in host
    assert "buildingsJson" in host
    assert "nudgeJson" in host
    assert "lookJson" in host
    assert "aimJson" in host
    assert "push_look" in host
    assert "push_aim" in host
    assert "enableRotate = true" in js
    assert "skyBox.show = true" in js
    assert "skyBox.show = false" not in js
    assert "saneLla" in js
    assert "function clampMarkAlt" in js
    assert "function saneMarkLla" in js
    assert "saneMarkLla(row.lat" in js
    assert 'code === "KeyW"' in js
    assert 'ev.key === "ArrowLeft"' in js
    assert "function applyLook" in js
    assert "function lookTarget" in js
    assert "window.setInterval(stepKeys" not in js
    assert "2_400_000" not in (
        GLOBE_DIR.parent / "earth_chrome.py"
    ).read_text(encoding="utf-8")
    assert "showErrorPanel" in js
    assert "recoverRender" in js
    assert "setBuildings" in js
    assert "bldg:" in js
    assert "background: #040508" in html
    assert "background: transparent" not in html
    assert "makeViewer(false)" in js
    assert "makeViewer(true)" not in js
    assert "Cesium.Color.TRANSPARENT" not in js
    assert "dressLighting" in js
    assert "nightFadeOutDistance" in js
    assert "photorealAltM = 8000" in js
    assert "photorealAltM || 80000" not in js
    assert "function flySeconds" in js
    assert "function flyTo" in js
    assert "emitCamera(true)" in js
    assert "moveEnd.addEventListener" in js
    assert "function hoseKey" in js
    assert "keyStruck" in js
    assert "function pickedMarkId" in js
    assert "LEFT_DOUBLE_CLICK" in js
    assert "minimumZoomDistance = 200" in js
    assert "function labelDepth" in js
    assert "POSITIVE_INFINITY" not in js.split("function labelDepth")[1].split("function lookHit")[0]
    assert "function wantLabel" in js
    assert "findOpen" in js
    assert "lastEmit = 0" in js
    assert "keyStruck" in host
    assert "push_find" in host
    assert "hostKey" in host
    assert 'op == "find"' in proc
    assert 'op == "look"' in proc
    assert 'op == "aim"' in proc
    assert "hostKey.connect" in proc
    stack = (GLOBE_DIR.parent.parent / "earth" / "globe_stack.py").read_text(
        encoding="utf-8"
    )
    blob = html + js + stack
    for banned in ("NOFORN", "KH11", "Gods Eye", "TOP SECRET"):
        assert banned not in blob


def test_globe_wants_own_process_when_gpu_solar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARELIS_EARTH_GLOBE_CHILD", raising=False)
    monkeypatch.delenv("ARELIS_EARTH_GLOBE_OOP", raising=False)
    monkeypatch.setattr("arelis.ui.solar_gl.gl_wanted", lambda: True)
    monkeypatch.setattr(
        "arelis.ui.earth_globe_host.share_group_live", lambda: False
    )
    assert globe_wants_own_process() is True
    monkeypatch.setenv("ARELIS_EARTH_GLOBE_CHILD", "1")
    assert globe_wants_own_process() is False


def test_globe_stays_in_process_without_gpu_or_share(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARELIS_EARTH_GLOBE_CHILD", raising=False)
    monkeypatch.delenv("ARELIS_EARTH_GLOBE_OOP", raising=False)
    monkeypatch.setattr("arelis.ui.solar_gl.gl_wanted", lambda: False)
    monkeypatch.setattr(
        "arelis.ui.earth_globe_host.share_group_live", lambda: False
    )
    assert globe_wants_own_process() is False


def test_globe_line_roundtrip() -> None:
    raw = globe_line({"event": "hwnd", "hwnd": 42})
    assert raw.endswith(b"\n")
    msg = parse_globe_line(raw)
    assert msg == {"event": "hwnd", "hwnd": 42}
    assert parse_globe_line(b"") is None
    assert parse_globe_line(b"not-json") is None


def test_earth_plate_uses_main_app_ghost_rule() -> None:
    """winId() on a child HWND and a leftover FBO are the offset ghost."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "arelis" / "ui"
    host = (root / "earth_globe_host.py").read_text(encoding="utf-8")
    earth = (root / "panels" / "solar_earth.py").read_text(encoding="utf-8")
    solar = (root / "panels" / "solar.py").read_text(encoding="utf-8")
    stack = host.split("def stack_chrome_over_globe", 1)[1].split("class GlobeBridge", 1)[0]
    assert "hud.winId" not in stack
    assert "view.winId" not in stack
    assert "SetWindowPos" not in stack
    assert "raise_()" in stack
    assert "mapToGlobal" in stack
    assert "def seal_globe_plate" in host
    assert "WA_TranslucentBackground, False" in host
    assert "WA_OpaquePaintEvent, True" in host
    assert "_stars_hold" not in earth
    assert "_stars_hold" not in solar
    live = solar.split("if self._earth_globe_live()", 1)[1].split("painter = QPainter(self)", 2)[1]
    assert "fillRect" in live
    assert "drawImage" not in live.split("return", 1)[0]


def test_launch_does_not_import_webengine() -> None:
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1] / "arelis" / "ui" / "launch.py"
    ).read_text(encoding="utf-8")
    assert "from PySide6.QtWebEngineWidgets import QWebEngineView" not in text
    assert "AA_ShareOpenGLContexts" not in text
    assert "earth_globe_proc" in (
        Path(__file__).resolve().parents[1]
        / "arelis"
        / "ui"
        / "earth_globe_proc.py"
    ).read_text(encoding="utf-8")
