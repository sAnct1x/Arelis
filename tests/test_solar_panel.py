"""Solar plate empty state and spawn chips."""

from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from arelis.physics.runtime import get_system, set_system
from arelis.ui.panels.solar import SOLAR_SPAWN, SolarPanel


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


def test_empty_solar_panel_paints(qt_app) -> None:
    set_system(None)
    panel = SolarPanel()
    panel.resize(640, 480)
    panel.show()
    qt_app.processEvents()
    assert panel.size().width() == 640
    panel.hide()


def test_solar_tools_dots_spawn_a_probe(qt_app) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip('REBOUND is not installed')
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    panel.resize(640, 480)
    panel.show()
    qt_app.processEvents()
    dots = panel._dots_rect()
    panel.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, dots.center().x(), dots.center().y(), grab=True)
    )
    assert panel._tools_open
    chips = panel._chip_rects()
    probe = next(rect for kind, rect in chips if kind == "probe")
    panel.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, probe.center().x(), probe.center().y(), grab=True)
    )
    system = get_system()
    assert system is not None
    assert any(p.kind == "probe" for p in system.nbody.particles)
    panel.hide()
    set_system(None)


def test_empty_solar_panel_opens_tools(qt_app) -> None:
    set_system(None)
    panel = SolarPanel()
    panel.resize(640, 480)
    panel.show()
    qt_app.processEvents()
    dots = panel._dots_rect()
    panel.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, dots.center().x(), dots.center().y(), grab=True)
    )
    assert panel._tools_open
    kinds = [kind for kind, _rect in panel._chip_rects()]
    assert kinds == [
        "gravity",
        "magnetic",
        "wind",
        "grid",
        "probe",
        "tracer",
        "l4",
        "impulse",
        "planet",
        "toy",
    ]
    panel.hide()


def test_open_solar_populates_then_fetches_horizons_once(
    qt_app, monkeypatch, tmp_path
) -> None:
    from arelis.physics.engine import rebound_available

    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SolarPanel, "_horizons_work", lambda self: None)
    set_system(None)
    panel = SolarPanel()
    panel.resize(640, 480)
    panel.show()
    qt_app.processEvents()
    if rebound_available():
        system = get_system()
        assert system is not None
        assert "not Horizons" in system.ic_caption()
    else:
        assert get_system() is None
    assert panel._load_pending
    panel.hide()
    set_system(None)


def test_empty_caption_hides_http_dump(qt_app) -> None:
    set_system(None)
    panel = SolarPanel()
    panel._maps_note = (
        "load needs a Sun VECTOR. Sun: Horizons returned HTTP 503.; "
        "Mercury: Horizons returned HTTP 503.; Venus: Horizons returned HTTP 400."
    )
    caption = panel._empty_caption()
    assert "busy" in caption.lower()
    assert "Mercury" not in caption
    panel.hide()


def test_horizons_fail_populates_kepler_bootstrap(
    qt_app, monkeypatch, tmp_path
) -> None:
    from arelis.physics.engine import rebound_available
    from arelis.tools.base import ToolResult

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SolarPanel, "_horizons_work", lambda self: None)
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
    panel.hide()
    set_system(None)


def test_nearest_cache_fills_the_plate_when_jpl_is_busy(
    qt_app, tmp_path, monkeypatch
) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.ic_store import save_cached
    from arelis.tools.base import ToolResult

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(SolarPanel, "_horizons_work", lambda self: None)
    save_cached("2000-01-01", sun_and_planet())
    set_system(None)
    panel = SolarPanel()
    panel._ic_date = "2000-01-02"
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
    assert system.ic_date == "2000-01-01"
    assert "cached" in system.ic_caption()
    panel.hide()
    set_system(None)


def test_epoch_scrubber_does_not_orbit(qt_app) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.evolution import GYR_MAX
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    panel.resize(640, 480)
    panel.show()
    qt_app.processEvents()
    yaw0 = panel.cam.yaw
    box = panel._epoch_rect()
    panel.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            box.right() - 2,
            box.center().y(),
            grab=True,
        )
    )
    system = get_system()
    assert system is not None
    assert system.future_gyr == pytest.approx(GYR_MAX, rel=0.05)
    assert panel._drag is None
    assert panel.cam.yaw == yaw0
    panel.hide()
    set_system(None)


def test_mouse_drag_left_looks_left(qt_app) -> None:
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
    fx0, fy0, fz0 = panel.cam.forward()
    right0, _up0, _fwd0 = panel.cam.basis()
    panel.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 400, 200, grab=True))
    panel.mouseMoveEvent(_mouse(QEvent.Type.MouseButtonPress, 300, 200, grab=True))
    fx1, fy1, fz1 = panel.cam.forward()
    assert (
        (fx1 - fx0) * right0[0] + (fy1 - fy0) * right0[1] + (fz1 - fz0) * right0[2] < 0.0
    )
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


def test_inspect_tile_travel_warps_the_camera(qt_app) -> None:
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
    panel._inspect = "Earth"
    panel.update()
    qt_app.processEvents()
    eye0 = (panel.cam.x, panel.cam.y, panel.cam.z)
    hit = panel._inspect_travel_rect().center()
    panel.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, hit.x(), hit.y(), grab=True)
    )
    panel._finish_travel()
    system = get_system()
    assert system is not None
    earth = system.nbody.find("Earth")
    assert earth is not None
    dist = (
        (panel.cam.x - earth.x) ** 2
        + (panel.cam.y - earth.y) ** 2
        + (panel.cam.z - earth.z) ** 2
    ) ** 0.5
    assert dist >= earth.radius * 2.5
    assert (panel.cam.x, panel.cam.y, panel.cam.z) != eye0
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


def test_wasd_flies_the_camera(qt_app) -> None:
    from PySide6.QtGui import QKeyEvent

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
    press = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_W, Qt.KeyboardModifier.NoModifier
    )
    panel.keyPressEvent(press)
    assert panel._held(Qt.Key.Key_W)
    eye0 = (panel.cam.x, panel.cam.y, panel.cam.z)
    panel._fly_camera(0.5)
    assert (panel.cam.x, panel.cam.y, panel.cam.z) != eye0
    panel.hide()
    set_system(None)


def test_f_does_not_spawn_a_craft(qt_app) -> None:
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
    panel._hotkey(Qt.Key.Key_F)
    system = get_system()
    assert system is not None
    assert (panel.cam.x, panel.cam.y, panel.cam.z) == eye0
    assert system.nbody.find("craft") is None
    panel.hide()
    set_system(None)


def test_tools_tray_is_a_readable_list(qt_app) -> None:
    panel = SolarPanel()
    panel.resize(640, 480)
    panel._tools_open = True
    assert panel._tools_rect().height() > 200
    assert SOLAR_SPAWN[0][1] == "Particle"
    assert SOLAR_SPAWN[0][0] == "probe"
    assert "craft" not in {kind for kind, _label, _hint in SOLAR_SPAWN}
    assert "maps" not in {kind for kind, _label, _hint in SOLAR_SPAWN}
    panel.hide()


def test_impulse_without_inspect_does_not_kick(qt_app) -> None:
    from PySide6.QtGui import QKeyEvent

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
    earth = system.nbody.find("Earth")
    assert earth is not None
    vx0, vy0, vz0 = earth.vx, earth.vy, earth.vz
    dots = panel._dots_rect()
    panel.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, dots.center().x(), dots.center().y(), grab=True)
    )
    impulse = next(rect for kind, rect in panel._chip_rects() if kind == "impulse")
    panel.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            impulse.center().x(),
            impulse.center().y(),
            grab=True,
        )
    )
    assert panel._confirm is not None
    assert panel._confirm["kind"] == "need_inspect"
    panel.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert panel._confirm is None
    earth = system.nbody.find("Earth")
    assert earth is not None
    assert (earth.vx, earth.vy, earth.vz) == (vx0, vy0, vz0)
    assert not system.counterfactual
    panel.hide()
    set_system(None)


def test_impulse_apply_kicks_earth(qt_app) -> None:
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
    earth = system.nbody.find("Earth")
    assert earth is not None
    speed0 = (earth.vx**2 + earth.vy**2 + earth.vz**2) ** 0.5
    energy0 = system.energy0
    panel._inspect = "Earth"
    panel._open_impulse_confirm("Earth")
    assert panel._confirm is not None
    apply = panel._confirm_chip_rects()["apply"]
    panel.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            apply.center().x(),
            apply.center().y(),
            grab=True,
        )
    )
    assert panel._confirm is None
    earth = system.nbody.find("Earth")
    assert earth is not None
    speed1 = (earth.vx**2 + earth.vy**2 + earth.vz**2) ** 0.5
    assert speed1 == pytest.approx(speed0 + 100.0, rel=1e-9)
    assert system.counterfactual
    assert system.ic_caption() == "COUNTERFACTUAL"
    assert system.energy0 != energy0
    panel.hide()
    set_system(None)


def test_planet_apply_adds_extra(qt_app) -> None:
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
    n0 = sum(1 for p in system.nbody.particles if p.massive)
    panel._open_planet_confirm()
    apply = panel._confirm_chip_rects()["apply"]
    panel.mousePressEvent(
        _mouse(
            QEvent.Type.MouseButtonPress,
            apply.center().x(),
            apply.center().y(),
            grab=True,
        )
    )
    extra = system.nbody.find("extra")
    assert extra is not None
    assert extra.massive
    assert extra.kind == "planet"
    assert sum(1 for p in system.nbody.particles if p.massive) == n0 + 1
    assert system.counterfactual
    assert system.ic_caption() == "COUNTERFACTUAL"
    assert panel._inspect == "extra"
    panel.hide()
    set_system(None)


def test_home_returns_to_system_overview(qt_app) -> None:
    from PySide6.QtGui import QKeyEvent

    from arelis.physics.constants import AU_M
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
    earth = system.nbody.find("Earth")
    assert earth is not None
    panel._travel_to("Earth")
    panel._finish_travel()
    near = (
        (panel.cam.x - earth.x) ** 2
        + (panel.cam.y - earth.y) ** 2
        + (panel.cam.z - earth.z) ** 2
    ) ** 0.5
    assert near < 1.0e9
    panel.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Home, Qt.KeyboardModifier.NoModifier)
    )
    assert panel.cam.distance > 80.0 * AU_M
    assert panel._inspect == "Earth"
    panel.hide()
    set_system(None)


def test_right_click_travels_without_a_menu(qt_app) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent

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
    earth = system.nbody.find("Earth")
    assert earth is not None
    panel._begin_view(system)
    proj = panel._proj((earth.x, earth.y, earth.z))
    assert proj is not None
    sx, sy, _d = proj
    eye0 = (panel.cam.x, panel.cam.y, panel.cam.z)
    pos = QPoint(int(sx), int(sy))
    panel.contextMenuEvent(
        QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos, panel.mapToGlobal(pos))
    )
    panel._finish_travel()
    assert panel._inspect == "Earth"
    assert (panel.cam.x, panel.cam.y, panel.cam.z) != eye0
    panel.hide()
    set_system(None)


def test_fly_speed_cruises_away_from_bodies(qt_app) -> None:
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
    panel.cam.speed = 10.0
    assert panel._fly_speed() > 1.0e9
    panel._travel_to("Earth")
    panel._finish_travel()
    panel.cam.speed = 50.0
    assert panel._fly_speed() == pytest.approx(50.0)
    panel.hide()
    set_system(None)


def test_running_overview_waits_for_a_pixel_of_motion(qt_app) -> None:
    """Unpaused at the overview, planets move sub-pixel per frame. Do not repaint."""
    from arelis.physics.demo import circular_system
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import _IDLE_PX

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(circular_system(), tracers=0))
    panel = SolarPanel()
    panel.resize(960, 720)
    panel.show()
    qt_app.processEvents()
    system = get_system()
    assert system is not None
    system.paused = False
    panel._keys.clear()
    panel._fly_v = [0.0, 0.0, 0.0]
    panel._painted_note = panel._maps_note
    # Pinned, not assumed: either of these would satisfy the gate on its own.
    panel._help = False
    system.show_graphs = False
    panel._painted_t = system.t
    assert panel._view_dirty(system) is False
    # Calibrate off the live scene, then straddle the threshold, so this pins
    # the gate rather than the one huge jump any threshold would pass.
    panel._painted_t = system.t - 1.0
    per_second = panel._motion_px(system)
    assert per_second > 0.0
    panel._painted_t = system.t - 0.4 * _IDLE_PX / per_second
    assert panel._motion_px(system) < _IDLE_PX
    assert panel._view_dirty(system) is False
    panel._painted_t = system.t - 2.5 * _IDLE_PX / per_second
    assert panel._motion_px(system) > _IDLE_PX
    assert panel._view_dirty(system) is True
    # Sparklines carry numbers a still frame would freeze, so that fallback has
    # to fire on its own clock even when nothing moved a pixel.
    panel._painted_t = system.t - 0.4 * _IDLE_PX / per_second
    system.show_graphs = True
    panel._painted_wall = time.perf_counter() - 1.0
    assert panel._view_dirty(system) is True
    panel._painted_wall = time.perf_counter()
    assert panel._view_dirty(system) is False
    system.show_graphs = False
    system.paused = True
    panel._painted_t = system.t
    assert panel._view_dirty(system) is False
    # A real paint has to move the watermark. If it does not, the gate either
    # never fires again or fires every frame, and the unit checks above lie.
    panel._painted_t = system.t - 3600.0
    panel.update()
    qt_app.processEvents()
    assert panel._painted_t == system.t
    panel.hide()
    set_system(None)


def test_overlay_reuses_roster_chrome_and_inspect_work(qt_app) -> None:
    """Label placement probes six spots per body; none of it may rebuild a HUD."""
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
    panel._set_inspect("Earth")
    names = panel._roster_names(system)
    boxes = panel._chrome_rects()
    lines = panel._inspect_lines(system)
    assert lines
    for _ in range(40):
        assert panel._roster_names(system) is names
        assert panel._chrome_rects() is boxes
        assert panel._inspect_lines(system) is lines
        panel._chrome_covers(200, 200)
    panel._set_inspect("Mars")
    assert panel._roster_names(system) is names
    assert panel._chrome_rects() is not boxes
    fresh = panel._inspect_lines(system)
    assert fresh is not lines
    # Identity alone would pass on a cache keyed on the wrong thing.
    assert any("Mars" in line for line in fresh)
    assert not any("Mars" in line for line in lines)
    panel.hide()
    set_system(None)


def test_label_dodging_stops_rebuilding_the_inspect_hud(qt_app) -> None:
    """The count is the fix. Six candidate spots per body used to rebuild a HUD."""
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
    system.paused = True
    panel._set_inspect("Earth")
    panel.update()
    qt_app.processEvents()
    asked: list[str] = []
    real = system.hud_for_name

    def counted(name: str):
        asked.append(name)
        return real(name)

    system.hud_for_name = counted
    panel._inspect_key = None
    panel._chrome_key = None
    panel.update()
    qt_app.processEvents()
    assert asked, "the paint never built the inspect tile at all"
    assert len(asked) <= 2, f"inspect HUD rebuilt {len(asked)} times in one paint"
    panel.hide()
    set_system(None)


def test_albedo_sample_blends_neighbours(qt_app) -> None:
    import numpy as np

    from arelis.ui.panels.solar import _sample_albedo

    tex = np.zeros((2, 2, 3), dtype=np.uint8)
    tex[0, 0] = (0, 0, 0)
    tex[0, 1] = (255, 0, 0)
    tex[1, 0] = (0, 255, 0)
    tex[1, 1] = (0, 0, 255)
    lon = np.array([[0.0]])
    lat = np.array([[0.0]])
    samp = _sample_albedo(tex, lon, lat)
    assert samp.shape == (1, 1, 3)
    red, green, blue = samp[0, 0]
    assert red == pytest.approx(127.5, abs=1.0)
    assert green == pytest.approx(0.0, abs=1.0)
    assert blue == pytest.approx(127.5, abs=1.0)


def test_on_globe_hides_labels_on_the_inspected_disc(qt_app) -> None:
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
    panel._cover = (100.0, 100.0, 40.0)
    assert panel._on_globe(100.0, 100.0) is True
    assert panel._on_globe(130.0, 100.0) is True
    assert panel._on_globe(200.0, 100.0) is False
    panel._cover = (320.0, 240.0, 80.0)
    assert panel._close_globe() is True
    panel.hide()
    set_system(None)


def test_close_inspect_field_is_not_zero_au(qt_app) -> None:
    from arelis.physics.constants import AU_M
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import _fmt_m

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    panel.resize(640, 480)
    panel.show()
    qt_app.processEvents()
    system = get_system()
    assert system is not None
    panel._travel_to("Earth")
    panel._finish_travel()
    field = panel._look_field_m(system)
    assert field < 0.05 * AU_M
    assert "AU" not in _fmt_m(field)
    panel.hide()
    set_system(None)


def test_inspect_tile_is_wide_enough_for_albedo(qt_app) -> None:
    panel = SolarPanel()
    panel.resize(960, 720)
    panel._inspect = "Earth"
    box = panel._inspect_rect()
    assert box.width() >= 440
    panel.hide()


def test_roster_nests_moons_under_planets(qt_app) -> None:
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
    names = panel._roster_names(system)
    assert names.index("Moon") == names.index("Earth") + 1
    assert names.index("Phobos") == names.index("Mars") + 1
    j = names.index("Jupiter")
    assert names[j + 1 : j + 5] == ["Io", "Europa", "Ganymede", "Callisto"]
    panel.hide()
    set_system(None)


def test_inspect_card_is_always_expanded(qt_app) -> None:
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
    panel._set_inspect("Earth")
    lines = panel._inspect_lines(system)
    blob = " ".join(lines)
    assert "GM" in blob
    assert "Hill" in blob
    assert "camera warp" in blob.lower()
    assert panel._inspect_rect().width() >= 440
    assert panel._inspect_travel_rect().width() > 200
    panel._set_inspect("Ceres")
    rock = " ".join(panel._inspect_lines(system))
    assert "potato" in rock
    panel.hide()
    set_system(None)


def test_overlay_tray_toggles_without_closing(qt_app) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    panel.resize(640, 480)
    panel._tools_open = True
    system = get_system()
    assert system is not None
    assert panel._toggle_overlay("gravity") is True
    assert system.overlay.show_gravity is True
    assert panel._toggle_overlay("magnetic") is True
    assert system.overlay.show_magnetic is True
    assert panel._toggle_overlay("wind") is True
    assert system.overlay.show_wind is True
    assert panel._toggle_overlay("grid") is True
    assert system.overlay.show_grid is True
    assert panel._toggle_overlay("probe") is False
    kinds = [kind for kind, _rect in panel._chip_rects()]
    assert kinds[:4] == ["gravity", "magnetic", "wind", "grid"]
    mag0 = system.overlay.show_magnetic
    chord = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_M,
        Qt.KeyboardModifier.ControlModifier,
    )
    panel.keyPressEvent(chord)
    assert system.overlay.show_magnetic is mag0
    panel.hide()
    set_system(None)


def test_help_hotkeys_name_every_live_key() -> None:
    from arelis.ui.panels.solar import HELP_HOTKEYS, KEY_HINT, KEY_LEGEND, KEY_STRIP

    blob = " ".join(HELP_HOTKEYS)
    for token in (
        "WASD",
        "L Lagrange",
        "T trails",
        "` graphs",
        "G gravity",
        "M magnetic",
        "P wind",
        "; grid",
        "[ ]",
        "No F",
        "Spoken flags match",
    ):
        assert token in blob, token
    assert "chase" not in blob.lower()
    strip = " ".join(f"{k} {h}" for k, h in KEY_STRIP)
    assert "WASD" in strip and "H" in strip
    assert "WASD fly" in KEY_HINT
    assert "Space pause" in KEY_HINT
    legend = " ".join(f"{k} {h}" for _title, rows in KEY_LEGEND for k, h in rows)
    assert "Lagrange" in legend
    assert "magnetic" in legend
    assert "this plate" in legend


def test_key_strip_click_toggles_help(qt_app) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import KEY_HINT

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    panel.resize(960, 720)
    panel.show()
    qt_app.processEvents()
    assert not panel._help
    hit = panel._keys_toggle
    assert not hit.isEmpty()
    assert hit.width() < 80
    panel.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, hit.center().x(), hit.center().y(), grab=True)
    )
    assert panel._help
    lines = panel._hud_status_lines(get_system())
    assert any("clock paused" in line for line in lines)
    assert not any(line.startswith("paused") for line in lines)
    assert KEY_HINT
    panel.hide()
    set_system(None)


def test_inspect_names_iau_w_and_keeps_asteroid_potato(qt_app) -> None:
    from arelis.physics.demo import circular_system
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(circular_system(), tracers=0))
    panel = SolarPanel()
    panel.resize(960, 720)
    system = get_system()
    assert system is not None
    panel._set_inspect("Mars")
    mars = " ".join(panel._inspect_lines(system))
    assert "IAU W" in mars
    assert "body-fixed" in mars.lower()
    panel._set_inspect("Ceres")
    rock = " ".join(panel._inspect_lines(system))
    assert "potato" in rock
    assert "IAU W" not in rock
    system.overlay.show_magnetic = True
    panel._set_inspect("Jupiter")
    giant = " ".join(panel._inspect_lines(system))
    assert "Earth Shue" in giant
    system.overlay.show_wind = True
    panel._set_inspect("Earth")
    earth = " ".join(panel._inspect_lines(system)).lower()
    assert "parker" in earth
    assert "not mhd" in earth
    assert "not enlil" in earth
    panel._set_inspect("Sun")
    star = " ".join(panel._inspect_lines(system)).lower()
    assert "dipole" in star
    assert "not sdo" in star
    assert "not mhd" in star
    panel.hide()
    set_system(None)


def test_help_plate_is_keys_not_a_lecture(qt_app) -> None:
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
    assert not hasattr(panel, "_hud_lecture")
    panel._help = True
    panel.update()
    qt_app.processEvents()
    assert panel._hud_bottom < 360
    panel.hide()
    set_system(None)


def test_hud_and_inspect_do_not_overlap(qt_app) -> None:
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
    panel._set_inspect("Earth")
    for help_on in (False, True):
        panel._help = help_on
        panel.update()
        qt_app.processEvents()
        hud = panel._hud_plate_rect()
        inspect = panel._inspect_rect()
        roster = panel._roster_rect()
        assert not hud.intersects(inspect), help_on
        assert hud.right() <= inspect.left() - 8, help_on
        if not roster.isEmpty():
            assert roster.top() >= hud.bottom() + 8, (
                help_on,
                roster.top(),
                hud.bottom(),
            )
            assert not roster.intersects(hud), help_on
            assert not roster.intersects(inspect), help_on
            assert roster.bottom() <= panel._speed_rect().y() - 16, help_on
    panel.hide()
    set_system(None)


def test_roster_hides_moons_until_parent_is_inspect(qt_app) -> None:
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
    panel._set_inspect("Sun")
    vis = panel._roster_visible(system)
    assert "Earth" in vis
    assert "Moon" not in vis
    panel._set_inspect("Earth")
    vis = panel._roster_visible(system)
    assert "Moon" in vis
    assert vis.index("Moon") == vis.index("Earth") + 1
    panel.hide()
    set_system(None)


def test_solar_markers_use_drawn_marks_not_rgb_dots() -> None:
    from pathlib import Path

    paint = Path("arelis/ui/panels/solar_paint.py").read_text(encoding="utf-8")
    roster = Path("arelis/ui/panels/solar.py").read_text(encoding="utf-8")
    assert "QColor(180, 255, 200)" not in paint
    assert "QColor(180, 220, 255)" not in paint
    assert "180, 255, 200" not in paint
    assert "180, 220, 255" not in paint
    assert "ink_for_kind" in paint
    assert "paint_mark(" in paint
    assert "paint_mark(" in roster
    start = paint.index("def paint_free_markers(")
    nxt = paint.find("\ndef ", start + 1)
    end = len(paint) if nxt < 0 else nxt
    assert "paint_mark(" in paint[start:end]
    start = paint.index("def paint_lagrange(")
    end = paint.index("\ndef ", start + 1)
    assert "paint_mark(" in paint[start:end]


def test_solar_panel_paints_kind_marks(qt_app) -> None:
    from arelis.physics.demo import circular_system
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem
    from arelis.ui.earth_marks import mark_digest

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(circular_system(), tracers=0))
    panel = SolarPanel()
    panel.resize(960, 720)
    panel.show()
    qt_app.processEvents()
    panel._set_inspect("Earth")
    panel.update()
    qt_app.processEvents()
    grab = panel.grab()
    assert not grab.isNull()
    assert mark_digest("planet") != mark_digest("star")
    assert mark_digest("probe") != mark_digest("lagrange")
    panel.hide()
    set_system(None)


def test_spawn_lagrange_offscreen_grab_is_not_null(qt_app) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    panel.resize(960, 720)
    system = get_system()
    assert system is not None
    system.spawn_lagrange("L4")
    grab = panel.grab()
    assert not grab.isNull()
    panel.hide()
    set_system(None)
