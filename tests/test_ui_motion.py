"""Chrome and chat motion.

Durations come from the shared motion tokens. The Windows animation setting,
or a quiet off switch, makes every one of these paths jump instead of animate.
Dock motion slides the widget. It does not fade it.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow, QWidget

FRAC = r"\frac{a}{b}"


def _motion():
    from arelis.ui import motion as motion_mod
    from arelis.ui import theme_tokens

    return motion_mod, theme_tokens


def _motion_on(monkeypatch) -> None:
    """Ask for motion even when this PC has window animation turned off.

    The Windows runners ship that way. An off switch later in the test still wins.
    """
    monkeypatch.delenv("ARELIS_MOTION", raising=False)
    motion_mod, _tokens = _motion()
    monkeypatch.setattr(motion_mod, "_windows_animations_enabled", lambda: True)


def _alpha_of(view, needle: str) -> int:
    found = view.document().find(needle)
    assert not found.isNull(), needle
    return found.charFormat().foreground().color().alpha()


def _running(anim) -> bool:
    return (
        anim is not None
        and anim.state() == QAbstractAnimation.State.Running
        and anim.duration() > 0
    )


def test_windows_client_area_animation_gates_motion(qt_app, monkeypatch) -> None:
    """On Windows the system animation flag is what turns motion off."""
    motion_mod, _tokens = _motion()
    monkeypatch.delenv("ARELIS_MOTION", raising=False)
    seen: dict[str, int] = {}

    def spi(action, _param, ptr, _flags):
        seen["action"] = int(action)
        ptr.contents.value = 0
        return 1

    monkeypatch.setattr(motion_mod.sys, "platform", "win32")
    monkeypatch.setattr(motion_mod, "_system_parameters_info", lambda: spi)
    from arelis.ui.glass import fade_in_widget

    widget = QWidget()
    widget.resize(40, 40)
    try:
        assert motion_mod.motion_enabled() is False
        assert seen["action"] == motion_mod.SPI_GETCLIENTAREAANIMATION
        anim = fade_in_widget(widget, 300)
        assert anim.duration() == 0
        assert widget.graphicsEffect() is None
    finally:
        widget.deleteLater()


def test_dock_slides_on_geometry_and_stays_opaque(qt_app, monkeypatch) -> None:
    """Showing a dock slides it. Opacity stays put, including a floating one."""
    _motion_on(monkeypatch)
    motion_mod, tokens = _motion()
    saved = dict(tokens.MOTION)
    from arelis.ui.window_chrome import WindowChrome

    window = QMainWindow()
    dock = QDockWidget("history", window)
    dock.setWidget(QLabel("notes"))
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    dock.setFloating(True)
    dock.resize(240, 180)
    window.resize(800, 600)
    window.show()
    dock.show()
    qt_app.processEvents()
    try:
        tokens.MOTION["base"] = 386
        tokens.MOTION["easing"] = "InOutQuad"
        before = dock.geometry()
        assert before.width() > 40
        WindowChrome._animate_dock(object(), dock, show=True)
        anim = getattr(dock, "_arelis_dock_slide", None)
        assert anim is not None
        assert bytes(anim.propertyName()) == b"geometry"
        assert anim.duration() == 386
        assert anim.easingCurve().type() == QEasingCurve.Type.InOutQuad
        assert anim.state() == QAbstractAnimation.State.Running
        assert dock.geometry() != before
        assert dock.graphicsEffect() is None
        assert dock.widget().graphicsEffect() is None
        assert abs(dock.windowOpacity() - 1.0) < 0.001
        assert not dock.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        halfway = anim.duration() // 2
        anim.setCurrentTime(halfway)
        assert dock.geometry() != before
        assert abs(dock.windowOpacity() - 1.0) < 0.001
        assert dock.graphicsEffect() is None
        anim.setCurrentTime(anim.duration())
        qt_app.processEvents()
        assert dock.geometry() == before
        assert abs(dock.windowOpacity() - 1.0) < 0.001
    finally:
        tokens.MOTION.clear()
        tokens.MOTION.update(saved)
        dock.close()
        window.close()
        del motion_mod


def test_new_chat_message_fades_and_snaps_with_the_same_gate(qt_app, monkeypatch) -> None:
    """A new line fades in. With motion off it is solid immediately."""
    _motion_on(monkeypatch)
    _motion_mod, tokens = _motion()
    saved = dict(tokens.MOTION)
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.resize(640, 480)
    try:
        tokens.MOTION["slow"] = 463
        tokens.MOTION["easing"] = "InOutQuad"
        panel.add_user("hello motion")
        anim = getattr(panel.view, "_message_fade", None)
        assert _running(anim)
        assert anim.duration() == 463
        assert anim.easingCurve().type() == QEasingCurve.Type.InOutQuad
        assert _alpha_of(panel.view, "hello") < 40
        anim.setCurrentTime(anim.duration())
        qt_app.processEvents()
        assert _alpha_of(panel.view, "hello") >= 250

        monkeypatch.setenv("ARELIS_MOTION", "0")
        panel.add_user("snap please")
        quiet = getattr(panel.view, "_message_fade", None)
        assert not _running(quiet)
        assert _alpha_of(panel.view, "snap") >= 250
        assert _alpha_of(panel.view, "hello") >= 250
    finally:
        tokens.MOTION.clear()
        tokens.MOTION.update(saved)
        panel.deleteLater()


def _math_images(document):
    out = []
    cur = QTextCursor(document)
    for pos in range(max(0, document.characterCount() - 1)):
        cur.setPosition(pos)
        cur.movePosition(
            QTextCursor.MoveOperation.NextCharacter,
            QTextCursor.MoveMode.KeepAnchor,
        )
        if cur.selectedText() != "\ufffc":
            continue
        fmt = cur.charFormat()
        if fmt.isImageFormat() and fmt.toImageFormat().name().startswith("arelis-math:"):
            out.append(fmt.toImageFormat())
    return out


def _image_alt(document) -> str:
    from PySide6.QtGui import QTextFormat

    cur = QTextCursor(document)
    for pos in range(max(0, document.characterCount() - 1)):
        cur.setPosition(pos)
        cur.movePosition(
            QTextCursor.MoveOperation.NextCharacter,
            QTextCursor.MoveMode.KeepAnchor,
        )
        fmt = cur.charFormat()
        if fmt.isImageFormat() and fmt.toImageFormat().name().startswith("arelis-math:"):
            return fmt.stringProperty(QTextFormat.Property.ImageAltText) or ""
    return ""
