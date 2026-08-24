"""World plane: mouse is the control. No camera."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

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
