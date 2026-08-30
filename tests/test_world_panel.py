"""World plane: mouse is the control. No camera."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from arelis.spatial.scene import WorldScene
from arelis.ui.panels.world import WorldPanel


def _mouse(kind: QEvent.Type, x: float, y: float, *, grab: bool) -> QMouseEvent:
    buttons = Qt.MouseButton.LeftButton if grab else Qt.MouseButton.NoButton
    return QMouseEvent(
        kind,
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_mouse_drags_the_disc(qt_app) -> None:
    scene = WorldScene()
    panel = WorldPanel(scene)
    panel.resize(400, 400)
    panel.show()
    qt_app.processEvents()
    cx, cy = panel._to_px(scene.disc.x, scene.disc.y)
    panel.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, cx, cy, grab=True))
    assert scene.disc.attached
    nx, ny = panel._to_px(0.72, 0.28)
    panel.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, nx, ny, grab=True))
    assert scene.disc.x > 0.6
    panel.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, nx, ny, grab=False))
    assert not scene.disc.attached
    panel.close()


def test_left_click_targets_the_disc(qt_app) -> None:
    scene = WorldScene()
    panel = WorldPanel(scene)
    panel.resize(400, 400)
    panel.show()
    qt_app.processEvents()
    cx, cy = panel._to_px(scene.disc.x, scene.disc.y)
    panel.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, cx, cy, grab=True))
    assert scene.selected is scene.disc
    panel.close()


def test_tools_dots_spawn_a_triangle(qt_app) -> None:
    scene = WorldScene()
    panel = WorldPanel(scene)
    panel.resize(400, 400)
    panel.show()
    qt_app.processEvents()
    dots = panel._dots_rect()
    panel.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, dots.center().x(), dots.center().y(), grab=True)
    )
    assert panel._tools_open
    chips = panel._chip_rects()
    kind, rect = chips[0]
    assert kind == "triangle"
    panel.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, rect.center().x(), rect.center().y(), grab=True)
    )
    assert any(body.kind == "triangle" for body in scene.bodies)
    panel.close()


def test_right_click_opens_the_sheet(qt_app) -> None:
    scene = WorldScene()
    panel = WorldPanel(scene)
    panel.resize(400, 400)
    panel.show()
    qt_app.processEvents()
    cx, cy = panel._to_px(scene.disc.x, scene.disc.y)
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(cx, cy),
        Qt.MouseButton.RightButton,
        Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.mousePressEvent(event)
    assert scene.selected is scene.disc
    assert panel._sheet_open
    panel.close()


def test_sheet_toggles_axes(qt_app) -> None:
    scene = WorldScene()
    panel = WorldPanel(scene)
    panel.resize(400, 400)
    panel.show()
    qt_app.processEvents()
    cx, cy = panel._to_px(scene.disc.x, scene.disc.y)
    panel.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(cx, cy),
            Qt.MouseButton.RightButton,
            Qt.MouseButton.RightButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )
    assert panel._sheet_open
    assert not scene.disc.axes_on
    hit = panel._axes_rect().center()
    panel.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, hit.x(), hit.y(), grab=True))
    assert scene.disc.axes_on
    panel.close()


def test_world_window_opens_on_the_chooser(qt_app) -> None:
    from arelis.physics.runtime import set_system
    from arelis.ui.world_window import WorldWindow

    set_system(None)
    window = WorldWindow(WorldScene())
    window.show()
    qt_app.processEvents()
    window.show_chooser()
    assert window.stack.currentWidget() is window.chooser
    assert window.heading.text() == "Reality"
    window.enter_hands()
    assert window.stack.currentWidget() is window.panel
    assert window.heading.text() == "hands"
    window.hide()


def test_chooser_solar_populates_and_fetches_horizons(qt_app, monkeypatch, tmp_path) -> None:
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.ui.panels.solar import SolarPanel
    from arelis.ui.world_window import WorldWindow

    monkeypatch.setattr(SolarPanel, "_horizons_work", lambda self: None)
    monkeypatch.setattr(SolarPanel, "_try_nearest_cache", lambda self: False)
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    set_system(None)
    window = WorldWindow(WorldScene())
    window.show()
    qt_app.processEvents()
    window.enter_solar()
    if rebound_available():
        system = get_system()
        assert system is not None
        assert "not Horizons" in system.ic_caption()
    else:
        assert get_system() is None
    assert window.solar._load_pending
    assert window.stack.currentWidget() is window.solar
    assert window.heading.text() == "solar system"
    window.hide()
    set_system(None)


def test_roster_click_inspects_and_enter_warps(qt_app) -> None:
    from arelis.physics.demo import circular_system
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import SolarPanel

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(circular_system(), tracers=0))
    panel = SolarPanel()
    panel.resize(640, 480)
    panel.show()
    qt_app.processEvents()
    panel._hud_bottom = 24
    system = get_system()
    assert system is not None
    names = panel._roster_names(system)
    assert names[0] == "Sun"
    assert "Earth" in names
    vis = panel._roster_visible(system)
    assert "Earth" in vis
    i = vis.index("Earth")
    row = panel._roster_row_rect(i)
    panel.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, row.left() + 20, row.center().y(), grab=True)
    )
    assert panel._inspect == "Earth"
    eye0 = (panel.cam.x, panel.cam.y, panel.cam.z)
    row = panel._roster_row_rect(i)
    panel.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, row.right() - 10, row.center().y(), grab=True)
    )
    assert (panel.cam.x, panel.cam.y, panel.cam.z) == eye0
    assert panel._inspect == "Earth"
    panel._inspect = "Sun"
    panel._cycle_inspect(1)
    assert panel._inspect == "Mercury"
    last = names[-1]
    panel._set_inspect(last)
    assert last in panel._roster_visible(system)
    eye1 = (panel.cam.x, panel.cam.y, panel.cam.z)
    panel.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    )
    panel._finish_travel()
    assert (panel.cam.x, panel.cam.y, panel.cam.z) != eye1
    panel.hide()
    set_system(None)


def test_world_window_has_no_choose_button(qt_app) -> None:
    from PySide6.QtWidgets import QToolButton

    from arelis.ui.world_window import WorldWindow

    window = WorldWindow(WorldScene())
    window.show()
    qt_app.processEvents()
    assert window.findChild(QToolButton, "RoomWorldButton") is None
    window.hide()


def test_esc_opens_pause_menu(qt_app, monkeypatch, tmp_path) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.world_window import WorldWindow

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    window = WorldWindow(WorldScene())
    window.show()
    qt_app.processEvents()
    window.enter_solar()
    from PySide6.QtGui import QKeyEvent

    esc = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    window.solar.keyPressEvent(esc)
    assert window.pause.isVisible()
    assert window.stack.currentWidget() is window.solar
    assert window.solar.menu_up
    system = get_system()
    assert system is not None
    assert system.paused is True
    window.pause.keyPressEvent(esc)
    assert not window.pause.isVisible()
    assert not window.solar.menu_up
    window.solar.keyPressEvent(esc)
    window.pause.exit_btn.click()
    qt_app.processEvents()
    assert window.stack.currentWidget() is window.chooser
    assert not window.pause.isVisible()
    window.hide()
    set_system(None)


def test_leaving_the_solar_lab_writes_a_receipt(qt_app, monkeypatch, tmp_path) -> None:
    import json

    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.world_window import WorldWindow

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0, ic_date="2000-01-01"))
    window = WorldWindow(WorldScene())
    window.show()
    qt_app.processEvents()
    window.enter_solar()
    root = tmp_path / "outputs" / "physics" / "solar"
    assert not root.exists() or not any(root.iterdir())
    window.show_chooser()
    written = list(root.iterdir())
    assert len(written) == 1
    manifest = json.loads((written[0] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["trigger"] == "leave"
    assert manifest["camera"] is not None
    window.show_chooser()
    assert len(list(root.iterdir())) == 1
    window.enter_solar()
    window.enter_hands()
    assert len(list(root.iterdir())) == 2
    window.hide()
    assert len(list(root.iterdir())) == 2
    set_system(None)


def test_spoken_lab_verbs_skip_the_chooser(arelis_window, qt_app, monkeypatch, tmp_path) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import SolarPanel

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    monkeypatch.setattr(SolarPanel, "_horizons_work", lambda self: None)
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    window = arelis_window()
    window.conversation.room.set_room("physics", name="Reality")
    try:
        assert window._try_physics_verb("open Reality") is True
        assert not window.world_window.isHidden()
        assert window._try_physics_verb("open the solar lab") is True
        assert window.world_window.solar_active()
        assert window._try_physics_verb("take me to Earth") is True
        system = get_system()
        assert system is not None
        assert system.pending_travel == "Earth"
        assert window._try_physics_verb("show the magnetosphere") is True
        assert system.overlay.show_magnetic is True
        assert window._try_physics_verb("hide the orbits") is True
        assert system.show_osculating is False
        system.pending_travel = None
        assert window._try_physics_verb("look at Earth") is True
        assert system.pending_inspect == "Earth"
        assert system.pending_travel is None
        assert window._try_physics_verb("open the toy area") is True
        assert window.world_window.hands_active()
        assert window._try_physics_verb("increase speed") is True
        assert window._try_physics_verb("close the solar lab") is True
        assert window.world_window.isHidden()
    finally:
        window.world_window.hide()
        set_system(None)
