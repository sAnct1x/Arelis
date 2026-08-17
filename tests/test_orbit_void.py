"""Orbit void skin: tokens, idle face, workbench still has Allow."""

from __future__ import annotations

import asyncio

from arelis.core.bus import EventBus
from arelis.ui.theme import COLORS, GLASS, color
from arelis.ui.void_idle import OrbitCanvas, OrbitIdle


def test_orbit_tokens() -> None:
    assert COLORS["accent"].lower() == "#ffb457"
    assert COLORS["accent2"].lower() == "#ffd9a8"
    assert int(GLASS["fill_float"]) == 255
    assert int(GLASS["fill_settings"]) == 255
    assert int(GLASS["fill_docked"]) == 0
    assert int(GLASS["fill_stage"]) == 0


def test_every_surface_is_lit_by_one_warm_source() -> None:
    """No neutral and no green anywhere on the ramp.

    This asserts the light model rather than the hexes, because the hexes are
    the thing that gets retuned. What must not change is that a surface reads as
    firelight: red above green above blue at every step, and the darker it gets
    the more saturated it is, which is what makes a shadow an ember rather than
    grey paint with a tint on it.
    """
    ramp = ("bg0", "bg1", "bg2", "dim", "text_dim", "thinking", "hint", "text")
    previous = -1.0
    for name in ramp:
        tint = color(name)
        assert tint.red() > tint.green() > tint.blue(), f"{name} is not warm"
        assert tint.hueF() * 360 < 45, f"{name} has drifted to yellow-green"
        lightness = tint.lightnessF()
        assert lightness > previous, f"{name} is not brighter than the step below"
        previous = lightness

    # Body text on the surface it is actually painted on. Below about 4:1 the
    # dim ramp stops being legible at 13px, which is the size all of it is.
    assert _contrast(color("text"), color("panel_fill")) > 7.0
    assert _contrast(color("hint"), color("panel_fill")) > 4.0
    assert _contrast(color("text_dim"), color("panel_fill")) > 2.5


def _contrast(a, b) -> float:
    def channel(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    def luminance(c) -> float:
        r, g, bl = (channel(x) for x in (c.redF(), c.greenF(), c.blueF()))
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl

    lo, hi = sorted((luminance(a), luminance(b)))
    return (hi + 0.05) / (lo + 0.05)


def test_orbit_idle_widget(qt_app) -> None:
    idle = OrbitIdle()
    idle.set_sessions([("s1", "Morning brief"), ("s2", "Reply to Robin")])
    idle.set_readout(ollama="ok", listening="off")
    idle.show()
    qt_app.processEvents()
    assert idle.listen_word.text()
    idle.set_animating(True)
    idle.set_animating(False)
    idle.deleteLater()


def test_app_icon_paint_is_orbit_amber(qt_app) -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "generate_app_icon.py"
    spec = importlib.util.spec_from_file_location("generate_app_icon", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    image = mod._paint(64)
    center = image.pixelColor(32, 32)
    # Core / bloom is warm amber, not the old teal/sky interferometer.
    assert center.red() > center.blue()
    assert center.red() > 80
    tile = image.pixelColor(8, 8)
    assert tile.red() >= tile.blue()


def test_parked_orbit_canvas(qt_app) -> None:
    canvas = OrbitCanvas(size=72, dim=0.42)
    assert canvas.width() == 72
    assert canvas.height() == 72
    canvas.set_animating(True)
    canvas.set_animating(False)
    canvas.deleteLater()


def test_cold_start_is_orbit_idle(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window._reset_layout()
        assert window._idle_eligible()
        assert window.conversation._idle_mode
        assert not window.chat.empty.isHidden()
        assert not window.chat.has_messages
        assert window.chat.empty.idle_placeholder.text() == "what are we working on"
        assert window.conversation.input.placeholderText() == ""
        assert window.conversation.input.parent() is window.chat.empty.prompt_host
        assert window.conversation.role.isHidden()
        window.history_dock.show()
        window._sync_idle_mode()
        assert window.conversation._idle_mode
        assert window.conversation.input.parent() is window.chat.empty.prompt_host
        window.conversation.conversation_btn.setChecked(True)
        window._sync_idle_mode()
        assert window._idle_eligible()
        assert window.conversation._idle_mode
        assert window.conversation.conversation_btn.isChecked()
        assert window.conversation.input.parent() is window.chat.empty.prompt_host
        window.conversation.conversation_btn.setChecked(False)
        window.conversation.input.setText("hello")
        window._sync_idle_mode()
        assert window._idle_eligible()
        assert window.conversation._idle_mode
        assert window.conversation.input.parent() is window.chat.empty.prompt_host
        assert window.conversation._parked_orbit.isHidden()
        window.chat.add_user("hello")
        window._sync_idle_mode()
        assert not window._idle_eligible()
        assert not window.conversation._idle_mode
        assert window.conversation.input.parent() is window.conversation._composer
        assert not window.conversation._parked_orbit.isHidden()
        window.chat.clear()
        window.conversation.input.clear()
        window._sync_idle_mode()
        assert window.conversation._idle_mode
        assert not window.chat.empty.isHidden()
        assert window.conversation.input.parent() is window.chat.empty.prompt_host
        assert window.conversation._parked_orbit.isHidden()
    finally:
        window.hide()
        window.loop.close()


def test_idle_prompt_grows_then_wraps(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window._reset_layout()
        phrase = "hello, how are you tonight"
        window.conversation.input.setText(phrase)
        window.conversation._fit_idle_prompt()
        assert window.conversation.input.text() == phrase
        assert window.conversation.input.parent() is window.chat.empty.prompt_host
        fm = window.conversation.input.fontMetrics()
        assert window.conversation.input.width() >= fm.horizontalAdvance(phrase)
        assert window.chat.empty.listen_word.isHidden()
        assert window.chat.empty.idle_hairline.width() >= fm.horizontalAdvance(phrase)
        window.conversation.input.setText("hello, " * 48)
        window.conversation._fit_idle_prompt()
        assert window.conversation.input.width() <= 720
        assert window.conversation.input.height() > 36
        assert "hello," in window.conversation.input.text()
    finally:
        window.hide()
        window.loop.close()


def _orbit_center_in_window(window) -> tuple[int, int]:
    orbit = window.chat.empty.orbit
    pt = orbit.mapTo(window, orbit.rect().center())
    return pt.x(), pt.y()


def test_idle_orbit_stays_on_window_bloom(qt_app) -> None:
    """History/Thinking overlay the void; they must not shove the idle face."""
    from arelis.ui.app import ArelisWindow, BusBridge
    from arelis.ui.stage import BLOOM_X

    window = ArelisWindow(
        {
            "ui": {"default_width": 1440, "default_height": 900},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window.show()
        window.resize(1440, 900)
        window._reset_layout()
        qt_app.processEvents()
        window.chat.empty._layout_idle()
        bloom_x = int(window.width() * BLOOM_X)
        x0, _y0 = _orbit_center_in_window(window)
        assert abs(x0 - bloom_x) < 36

        window.history_dock.show()
        window._sync_idle_mode()
        qt_app.processEvents()
        window.chat.empty._layout_idle()
        x_hist, _ = _orbit_center_in_window(window)
        assert abs(x_hist - x0) < 24
        assert abs(x_hist - bloom_x) < 36

        window.think_dock.show()
        window._sync_idle_mode()
        qt_app.processEvents()
        window.chat.empty._layout_idle()
        x_both, _ = _orbit_center_in_window(window)
        assert abs(x_both - bloom_x) < 36
        assert window.conversation.input.parent() is window.chat.empty.prompt_host
    finally:
        window.hide()
        window.loop.close()


def test_side_chrome_does_not_shift_orbit(qt_app) -> None:
    idle = OrbitIdle()
    idle.resize(900, 640)
    idle.show()
    qt_app.processEvents()
    idle.set_sessions([("s1", "Morning brief"), ("s2", "Reply to Robin")])
    idle.set_side_chrome(ghosts=True, readout=True)
    qt_app.processEvents()
    idle._layout_idle()
    x0 = idle.orbit.mapTo(idle, idle.orbit.rect().center()).x()
    idle.set_side_chrome(ghosts=False, readout=False)
    qt_app.processEvents()
    idle._layout_idle()
    x1 = idle.orbit.mapTo(idle, idle.orbit.rect().center()).x()
    assert abs(x0 - x1) < 8
    assert abs(x0 - idle.width() // 2) < 24
    idle.deleteLater()


def test_idle_ghosts_are_not_clipped(qt_app) -> None:
    from PySide6.QtWidgets import QLabel

    idle = OrbitIdle()
    idle.resize(1100, 720)
    idle.show()
    qt_app.processEvents()
    long_title = "hello, how are you today? and then a longer wrap so the title needs two lines"
    idle.set_sessions(
        [
            ("s1", long_title),
            ("s2", "Morning brief"),
            ("s3", "Reply to Robin"),
        ]
    )
    idle.set_side_chrome(ghosts=True, readout=True)
    qt_app.processEvents()
    idle._layout_idle()
    ghosts = idle._ghosts
    assert ghosts.isVisible()
    assert idle.rect().contains(ghosts.geometry())
    layout = ghosts.layout()
    assert layout is not None
    assert layout.count() == 3
    for i in range(3):
        row = layout.itemAt(i).widget()
        assert row is not None
        assert ghosts.rect().contains(row.geometry())
        title = row.findChild(QLabel, "VoidGhostValue")
        assert title is not None
        assert row.rect().contains(title.geometry())
        wrapped = title.heightForWidth(title.width())
        assert title.height() >= wrapped - 1
        assert title.height() >= title.fontMetrics().height()
    idle.deleteLater()


def test_a_latched_voice_mode_does_not_push_the_ghosts_off(qt_app) -> None:
    """The mode line lives in the centre column, so its width is the column's
    width. A long one moved the column out far enough that _layout_idle found no
    room for the session ghosts and hid them."""
    idle = OrbitIdle()
    idle.resize(1100, 720)
    idle.show()
    qt_app.processEvents()
    idle.set_sessions([("s1", "Morning brief"), ("s2", "Reply to Robin")])
    idle.set_side_chrome(ghosts=True, readout=True)
    qt_app.processEvents()
    for mode in ("off", "conversation", "dictate", "wake", "ack"):
        idle.set_voice_mode(mode)
        idle._layout_idle()
        assert idle._ghosts.isVisible(), f"{mode} hid the session ghosts"
        assert idle._readout.isVisible(), f"{mode} hid the readout"
        assert idle.listen_word.width() <= 300
    idle.deleteLater()


def test_idle_prompt_centers_on_orbit(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 1100, "default_height": 720},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window.show()
        window.resize(1100, 720)
        window._reset_layout()
        qt_app.processEvents()
        window.conversation._fit_idle_prompt()
        idle = window.chat.empty
        host = idle.prompt_host
        line = idle.idle_hairline
        placeholder = idle.idle_placeholder
        fm = placeholder.fontMetrics()
        ph_w = fm.horizontalAdvance(placeholder.text())
        assert placeholder.isVisible()
        assert host.width() <= ph_w + 40
        assert host.width() >= ph_w
        assert abs(line.width() - host.width()) <= 2
        orbit_cx = idle.orbit.mapTo(idle, idle.orbit.rect().center()).x()
        host_cx = host.mapTo(idle, host.rect().center()).x()
        line_cx = line.mapTo(idle, line.rect().center()).x()
        ph_cx = placeholder.mapTo(idle, placeholder.rect().center()).x()
        assert abs(orbit_cx - host_cx) < 8
        assert abs(host_cx - line_cx) < 8
        assert abs(host_cx - ph_cx) < 8
    finally:
        window.hide()
        window.loop.close()


def test_allow_still_opens_on_workbench(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    try:
        stage.set_idle_mode(False)
        stage.ask_confirm("c1", "workspace", "write file")
        assert stage.confirm_open()
        assert not stage.confirm.isHidden()
        stage.dismiss_confirm()
        assert not stage.confirm_open()
        assert stage.confirm.isHidden()
    finally:
        stage.deleteLater()


def test_drive_strip_pause_go(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    try:
        stage.set_idle_mode(False)
        assert stage.drive.isHidden()
        stage.set_drive(True, "about to click e3…")
        assert not stage.drive.isHidden()
        assert "e3" in stage.drive.status.text()
        paused: list[str] = []
        stage.pause_requested.connect(lambda: paused.append("pause"))
        stage.resume_requested.connect(lambda: paused.append("go"))
        stage.drive.pause_btn.click()
        assert stage.drive.is_paused()
        assert "paused" in stage.drive.status.text()
        assert stage.drive.pause_btn.text() == "go"
        stage.drive.pause_btn.click()
        assert not stage.drive.is_paused()
        assert paused == ["pause", "go"]
        stage.set_drive(False)
        assert stage.drive.isHidden()
        assert not stage.drive.is_paused()
        stage.set_drive_your_turn("your turn — captcha")
        assert not stage.drive.isHidden()
        assert stage.drive.is_paused()
        assert "captcha" in stage.drive.status.text()
        assert stage.drive.pause_btn.text() == "go"
    finally:
        stage.deleteLater()
