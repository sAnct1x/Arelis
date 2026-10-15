"""Solar plate empty state and spawn chips."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from arelis.physics.runtime import get_system, set_system
from arelis.ui.panels.solar import SolarPanel


@pytest.fixture(autouse=True)
def _reset_solar_system():
    """The live system is process-global. A missed teardown flakes later tests."""
    set_system(None)
    yield
    set_system(None)


def _mouse(kind: QEvent.Type, x: float, y: float, *, grab: bool) -> QMouseEvent:
    buttons = Qt.MouseButton.LeftButton if grab else Qt.MouseButton.NoButton
    pos = QPointF(x, y)
    return QMouseEvent(
        kind,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_horizons_fail_populates_kepler_bootstrap(
    qt_app, monkeypatch, tmp_path
) -> None:
    from arelis.physics.engine import rebound_available
    from arelis.tools.base import ToolResult

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "arelis.ui.panels.solar._horizons_fetch",
        lambda *_args, **_kwargs: None,
    )
    set_system(None)
    panel = SolarPanel()
    panel._load_pending = False
    panel._load_result = ToolResult(
        ok=False,
        output="JPL Horizons is busy.",
        data={"fail_class": "fail:horizons"},
    )
    panel._ingest_background()
    system = get_system()
    assert system is not None
    assert system.nbody.find("Sun") is not None
    assert system.nbody.find("Earth") is not None
    assert "not Horizons" in system.ic_caption()
    assert not panel._load_pending
    assert "busy" in (panel._maps_note or "").lower()
    panel.hide()
    set_system(None)


def test_overview_shows_and_picks_neptune(qt_app) -> None:
    from arelis.physics.constants import AU_M
    from arelis.physics.demo import circular_system
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(circular_system(), tracers=0))
    panel = SolarPanel()
    panel.resize(960, 720)
    panel.show()
    qt_app.processEvents()
    system = get_system()
    assert system is not None
    assert panel.cam.distance > 80.0 * AU_M
    panel._begin_view(system)
    neptune = system.nbody.find("Neptune")
    assert neptune is not None
    proj = panel._proj((neptune.x, neptune.y, neptune.z))
    assert proj is not None
    sx, sy, depth = proj
    assert 0.0 <= sx < panel.width()
    assert 0.0 <= sy < panel.height()
    view = next(b for b in system.views() if b.name == "Neptune")
    assert panel._screen_radius(view, depth) >= 5.0
    panel.update()
    qt_app.processEvents()
    assert panel._body_at(sx, sy) == "Neptune"
    for name in ("Saturn", "Uranus", "Neptune"):
        body = system.nbody.find(name)
        assert body is not None
        hit = panel._proj((body.x, body.y, body.z))
        assert hit is not None, name
        assert 0.0 <= hit[0] < panel.width(), name
        assert 0.0 <= hit[1] < panel.height(), name
    assert not panel._help
    # Overview HUD is a plate, not the globe. Keys chrome grew with Earth;
    # 100px was a screenshot of an older strip and failed at 112 on the same
    # 720px panel. Keep it in the top quarter.
    assert panel._hud_bottom < panel.height() // 4
    panel.hide()
    set_system(None)


def test_click_inspects_without_traveling(qt_app) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    panel.resize(640, 480)
    panel.show()
    qt_app.processEvents()
    eye0 = (panel.cam.x, panel.cam.y, panel.cam.z)
    system = get_system()
    assert system is not None
    panel._begin_view(system)
    earth = system.nbody.find("Earth")
    assert earth is not None
    proj = panel._proj((earth.x, earth.y, earth.z))
    assert proj is not None
    sx, sy, _d = proj
    panel.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, sx, sy, grab=True))
    panel.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, sx, sy, grab=False))
    assert panel._inspect == "Earth"
    assert (panel.cam.x, panel.cam.y, panel.cam.z) == eye0
    panel._travel_to("Earth")
    panel._finish_travel()
    dist = ((panel.cam.x - earth.x) ** 2 + (panel.cam.y - earth.y) ** 2 + (panel.cam.z - earth.z) ** 2) ** 0.5
    assert dist >= earth.radius * 2.5
    panel.hide()
    set_system(None)


def test_second_click_on_a_body_travels(qt_app) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    panel.resize(640, 480)
    panel.show()
    qt_app.processEvents()
    system = get_system()
    assert system is not None
    panel._begin_view(system)
    earth = system.nbody.find("Earth")
    assert earth is not None
    proj = panel._proj((earth.x, earth.y, earth.z))
    assert proj is not None
    sx, sy, _d = proj
    eye0 = (panel.cam.x, panel.cam.y, panel.cam.z)
    panel.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, sx, sy, grab=True))
    panel.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, sx, sy, grab=False))
    assert panel._inspect == "Earth"
    assert (panel.cam.x, panel.cam.y, panel.cam.z) == eye0
    panel._inspect_at(sx, sy)
    panel._finish_travel()
    assert (panel.cam.x, panel.cam.y, panel.cam.z) != eye0
    assert panel._earth_at_door is True
    assert not panel._inspect_enter_rect().isEmpty()
    panel.hide()
    set_system(None)


def test_wheel_dollies_along_look(qt_app) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QWheelEvent

    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    panel.resize(640, 480)
    panel.show()
    qt_app.processEvents()
    eye0 = (panel.cam.x, panel.cam.y, panel.cam.z)
    speed0 = panel.cam.speed
    pos = QPointF(panel.width() * 0.55, panel.height() * 0.45)
    event = QWheelEvent(
        pos,
        pos,
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    panel.wheelEvent(event)
    assert (panel.cam.x, panel.cam.y, panel.cam.z) != eye0
    assert panel.cam.speed == speed0
    panel.hide()
    set_system(None)


