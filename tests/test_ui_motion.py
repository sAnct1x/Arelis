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


def test_widget_fade_duration_follows_the_slow_token(qt_app, monkeypatch) -> None:
    """A plate fade takes the shared slow duration, not a private number."""
    _motion_on(monkeypatch)
    motion_mod, tokens = _motion()
    from arelis.ui import theme

    saved = dict(tokens.MOTION)
    assert theme.MOTION is tokens.MOTION
    assert theme.motion_enabled is motion_mod.motion_enabled
    assert set(tokens.MOTION) >= {"fast", "base", "slow", "easing"}
    assert tokens.MOTION["fast"] < tokens.MOTION["base"] < tokens.MOTION["slow"]
    widget = QWidget()
    widget.resize(80, 40)
    try:
        tokens.MOTION["slow"] = 417
        tokens.MOTION["easing"] = "InOutQuad"
        from arelis.ui.glass import fade_in_widget

        anim = fade_in_widget(widget)
        assert anim.duration() == 417
        assert anim.state() == QAbstractAnimation.State.Running
        assert anim.easingCurve().type() == QEasingCurve.Type.InOutQuad
        effect = widget.graphicsEffect()
        assert effect is not None
        assert effect.opacity() == 0.0
        assert bytes(anim.propertyName()) == b"opacity"
    finally:
        tokens.MOTION.clear()
        tokens.MOTION.update(saved)
        widget.deleteLater()
        del qt_app, motion_mod


def test_widget_fade_snaps_when_motion_is_off(qt_app, monkeypatch) -> None:
    """An off switch skips the fade. The widget is fully there at once."""
    monkeypatch.setenv("ARELIS_MOTION", "0")
    from arelis.ui.glass import fade_in_widget

    widget = QWidget()
    widget.resize(80, 40)
    widget.show()
    qt_app.processEvents()
    try:
        anim = fade_in_widget(widget, 400)
        assert anim.duration() == 0
        assert anim.state() != QAbstractAnimation.State.Running
        assert widget.graphicsEffect() is None
    finally:
        widget.deleteLater()


def test_config_off_switch_skips_motion(qt_app, monkeypatch, tmp_path) -> None:
    """A saved off switch does the same thing as the environment one."""
    monkeypatch.delenv("ARELIS_MOTION", raising=False)
    motion_mod, _tokens = _motion()
    cfg = tmp_path / "config.local.yaml"
    cfg.write_text("ui:\n  motion: false\n", encoding="utf-8")
    monkeypatch.setattr(motion_mod, "LOCAL_CONFIG_PATH", cfg)
    from arelis.ui.glass import fade_in_widget

    widget = QWidget()
    widget.resize(40, 40)
    try:
        assert motion_mod.motion_enabled() is False
        anim = fade_in_widget(widget, 300)
        assert anim.duration() == 0
        assert widget.graphicsEffect() is None
    finally:
        widget.deleteLater()


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


def test_windows_query_treats_a_failed_call_as_on() -> None:
    """A failed system read does not freeze the interface."""
    motion_mod, _tokens = _motion()

    def spi(action, _param, ptr, _flags):
        assert int(action) == motion_mod.SPI_GETCLIENTAREAANIMATION
        ptr.contents.value = 0
        return 0

    assert motion_mod._query_client_area_animation(spi) is True

    def on(action, _param, ptr, _flags):
        assert int(action) == 0x1042
        ptr.contents.value = 1
        return 1

    assert motion_mod._query_client_area_animation(on) is True


def test_caption_fade_uses_the_fast_token_and_snaps_when_off(qt_app, monkeypatch) -> None:
    """Window buttons ease in with the shared fast duration, or appear at once."""
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QHBoxLayout

    from arelis.ui import caption_fade as fade_mod
    from arelis.ui.caption_fade import CaptionTool, watch_caption

    _motion_on(monkeypatch)
    motion_mod, tokens = _motion()
    saved_tokens = dict(tokens.MOTION)
    cursor = {"at": QPoint(-4000, -4000)}
    original = fade_mod.QCursor.pos
    fade_mod.QCursor.pos = staticmethod(lambda: cursor["at"])
    host = QWidget()
    btn = CaptionTool()
    btn.setFixedSize(28, 28)
    lay = QHBoxLayout(host)
    lay.addWidget(btn)
    host.resize(200, 48)
    try:
        tokens.MOTION["fast"] = 319
        tokens.MOTION["easing"] = "InOutQuad"
        hover = watch_caption(host, btn)
        host.show()
        qt_app.processEvents()
        cursor["at"] = btn.mapToGlobal(btn.rect().center())
        hover.sync()
        assert hover.anim.duration() == 319
        assert hover.anim.easingCurve().type() == QEasingCurve.Type.InOutQuad
        assert hover.anim.state() == QAbstractAnimation.State.Running
        assert hover.opacity < 0.5

        monkeypatch.setenv("ARELIS_MOTION", "0")
        hover.sync()
        assert hover.opacity == 1.0
        assert hover.anim.state() != QAbstractAnimation.State.Running
        assert motion_mod.motion_enabled() is False
    finally:
        fade_mod.QCursor.pos = original
        tokens.MOTION.clear()
        tokens.MOTION.update(saved_tokens)
        host.close()


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


def test_dock_hide_slides_then_closes_and_snaps_when_off(qt_app, monkeypatch) -> None:
    """Hiding a dock slides away, unless motion is off, in which case it is gone."""
    _motion_on(monkeypatch)
    _motion_mod, tokens = _motion()
    saved = dict(tokens.MOTION)
    from arelis.ui.window_chrome import WindowChrome

    dock = QDockWidget()
    dock.setWidget(QLabel("files"))
    dock.resize(220, 160)
    dock.show()
    qt_app.processEvents()
    try:
        tokens.MOTION["base"] = 360
        WindowChrome._animate_dock(object(), dock, show=False)
        anim = getattr(dock, "_arelis_dock_slide", None)
        assert anim is not None
        assert bytes(anim.propertyName()) == b"geometry"
        assert not dock.isHidden()
        assert abs(dock.windowOpacity() - 1.0) < 0.001
        anim.setCurrentTime(anim.duration())
        qt_app.processEvents()
        assert dock.isHidden()

        dock.show()
        qt_app.processEvents()
        monkeypatch.setenv("ARELIS_MOTION", "off")
        WindowChrome._animate_dock(object(), dock, show=False)
        assert dock.isHidden()
        leftover = getattr(dock, "_arelis_dock_slide", None)
        assert leftover is None or not _running(leftover)
        assert dock.graphicsEffect() is None
    finally:
        tokens.MOTION.clear()
        tokens.MOTION.update(saved)
        dock.close()


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


def test_finished_answer_fades_without_losing_math_or_find(qt_app, monkeypatch) -> None:
    """The finished answer fades. A formula and find still work on that line."""
    _motion_on(monkeypatch)
    _motion_mod, tokens = _motion()
    saved = dict(tokens.MOTION)
    from arelis.ui.chat_find import ChatFindBar
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.resize(640, 480)
    try:
        tokens.MOTION["slow"] = 440
        panel.begin_assistant()
        panel.append_delta("See the ratio")
        assert getattr(panel.view, "_message_fade", None) is None or not _running(
            panel.view._message_fade
        )
        panel.finish_assistant(f"See ${FRAC}$ now.")
        anim = getattr(panel.view, "_message_fade", None)
        assert _running(anim)
        assert anim.duration() == 440
        text = panel.view.toPlainText()
        assert "\\frac" not in text
        assert "now" in text
        assert _alpha_of(panel.view, "now") < 40
        imgs = _math_images(panel.view.document())
        assert len(imgs) == 1
        assert imgs[0].name().startswith("arelis-math:")
        bar = ChatFindBar(panel.view, panel)
        assert bar.find("now") is True
        assert panel.view.textCursor().selectedText() == "now"
        anim.setCurrentTime(anim.duration())
        qt_app.processEvents()
        assert _alpha_of(panel.view, "now") >= 250
        imgs = _math_images(panel.view.document())
        assert len(imgs) == 1
        assert _image_alt(panel.view.document()) == FRAC
        assert bar.find(FRAC) is True
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
