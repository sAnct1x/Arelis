"""World plane: mouse is the control. No camera."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from arelis.spatial.scene import WorldScene


def _mouse(kind: QEvent.Type, x: float, y: float, *, grab: bool) -> QMouseEvent:
    buttons = Qt.MouseButton.LeftButton if grab else Qt.MouseButton.NoButton
    return QMouseEvent(
        kind,
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_chooser_solar_populates_and_fetches_horizons(qt_app, monkeypatch, tmp_path) -> None:
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.ui.panels.solar import SolarPanel
    from arelis.ui.world_window import WorldWindow

    monkeypatch.setattr(
        "arelis.ui.panels.solar._horizons_fetch",
        lambda *_args, **_kwargs: None,
    )
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


