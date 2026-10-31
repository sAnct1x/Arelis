"""Orbit void skin: tokens, idle face, workbench still has Allow."""

from __future__ import annotations

import asyncio

from arelis.core.bus import EventBus
from arelis.ui.idle_host import idle_eligible, sync_idle_mode
from arelis.ui.theme import BLOOM, COLORS, GLASS, HAIRLINE, PLATE, color
from arelis.ui.void_idle import OrbitCanvas


def test_every_surface_is_lit_by_one_warm_source() -> None:
    """One sodium lamp in an evening room.

    Hexes get retuned. What stays: every surface is warm (red above green
    above blue, hue under 34), the void stays low chroma so the room is an
    evening rather than chocolate, the lamp is #ff7a22, and type on the
    working plate is bright enough to read.
    """
    from arelis.ui.theme import apply_theme

    apply_theme("sodium")
    ramp = ("bg0", "bg1", "bg2", "dim", "text_dim", "thinking", "hint", "text")
    previous = -1.0
    for name in ramp:
        tint = color(name)
        assert tint.red() > tint.green() > tint.blue(), f"{name} is not warm"
        assert tint.hueF() * 360 < 32, f"{name} has drifted to yellow"
        lightness = tint.lightnessF()
        assert lightness > previous, f"{name} is not brighter than the step below"
        previous = lightness

    # Body text on the surface it is actually painted on. Below about 4.5:1 the
    # dim ramp stops being legible at 13px, which is the size all of it is.
    # Paper has to step off the amber hint, and the far wall has to step off
    # the void, or the room collapses back into one brown.
    void = color("bg0")
    assert void.red() - void.blue() <= 8
    assert _contrast(color("text"), color("panel_fill")) > 12.0
    assert _contrast(color("hint"), color("panel_fill")) > 7.0
    assert _contrast(color("dim"), color("panel_fill")) > 4.5
    assert _contrast(color("text_dim"), color("panel_fill")) > 4.5
    assert _contrast(color("text"), color("hint")) > 1.5
    assert _contrast(color("bg2"), color("bg0")) > 1.5
    # The room light has to actually read. A 40-alpha inner bloom is a stain.
    assert BLOOM["inner"][0][1][3] >= 70
    assert PLATE["seal"][:3] == (
        color("bg0").red(),
        color("bg0").green(),
        color("bg0").blue(),
    )
    assert HAIRLINE["rest"] == int(GLASS["rim_pulse_lo"])
    assert HAIRLINE["live"] >= 180
    assert int(GLASS["fill_strip"]) >= 100

    # Every named fill, rim, and type token — not just the eight-step ramp.
    # Danger is the one family allowed off-amber. Pulse min/max are alphas.
    skip = {"rim_pulse_min", "rim_pulse_max"}
    for name, raw in COLORS.items():
        if name in skip or name.startswith("danger"):
            continue
        if not raw.startswith(("#", "rgb")):
            continue
        tint = color(name)
        if tint.alpha() == 0:
            continue
        assert tint.red() > tint.green() > tint.blue(), f"{name} is not warm"
        assert tint.hueF() * 360 < 34, f"{name} has drifted off sodium amber"


def _contrast(a, b) -> float:
    def channel(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    def luminance(c) -> float:
        r, g, bl = (channel(x) for x in (c.redF(), c.greenF(), c.blueF()))
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl

    lo, hi = sorted((luminance(a), luminance(b)))
    return (hi + 0.05) / (lo + 0.05)


def test_social_preview_is_sodium_orbit(qt_app) -> None:
    from pathlib import Path

    from PySide6.QtGui import QImage

    committed = Path(__file__).resolve().parents[1] / "docs" / "social-preview.png"
    assert committed.is_file()
    image = QImage(str(committed))
    assert image.width() == 1280
    assert image.height() == 640
    center = image.pixelColor(image.width() // 2, image.height() // 2)
    assert center.red() > center.blue()
    assert center.red() > center.green()
    assert center.hue() < 34


def test_cold_start_is_orbit_idle(qt_app) -> None:
    from PySide6.QtWidgets import QLabel

    from arelis.ui.app import ArelisWindow, BusBridge
    from arelis.ui.void_idle import FIRST_RUN_ASKS, TOOLS_CHIP_TITLE

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600, "theme": "sodium"},
            "router": {"default_role": "fast"},
            "voice": {"enabled": False},
        },
        BusBridge(),
        asyncio.new_event_loop(),
        EventBus(),
    )
    try:
        window._reset_layout()
        assert idle_eligible(window)
        assert window.conversation._idle_mode
        assert not window.chat.empty.isHidden()
        assert not window.chat.has_messages
        assert window.chat.empty.idle_placeholder.text() == "what are we working on"
        assert window.chat.empty.listen_word.isHidden()
        assert window.conversation.input.placeholderText() == ""
        ghost_text = [
            w.text() for w in window.chat.empty._ghosts.findChildren(QLabel)
        ]
        assert "TOOLS" in ghost_text
        assert TOOLS_CHIP_TITLE in ghost_text
        assert any(ask in ghost_text for ask in FIRST_RUN_ASKS)
        assert window.conversation.input.parent() is window.chat.empty.prompt_host
        assert window.conversation.role.isHidden()
        window.history_dock.show()
        sync_idle_mode(window)
        assert window.conversation._idle_mode
        assert window.conversation.input.parent() is window.chat.empty.prompt_host
        assert window.chat.empty._want_ghosts is False
        window.conversation.conversation_btn.setChecked(True)
        sync_idle_mode(window)
        assert idle_eligible(window)
        assert window.conversation._idle_mode
        assert window.conversation.conversation_btn.isChecked()
        assert window.conversation.input.parent() is window.chat.empty.prompt_host
        window.conversation.conversation_btn.setChecked(False)
        window.conversation.input.setText("hello")
        sync_idle_mode(window)
        assert idle_eligible(window)
        assert window.conversation._idle_mode
        assert window.conversation.input.parent() is window.chat.empty.prompt_host
        assert window.conversation._parked_orbit.isHidden()
        window.chat.add_user("hello")
        sync_idle_mode(window)
        assert not idle_eligible(window)
        assert not window.conversation._idle_mode
        assert window.conversation.input.parent() is window.conversation._composer
        assert window.conversation._parked_orbit.isHidden()
        window.chat.clear()
        window.conversation.input.clear()
        sync_idle_mode(window)
        assert window.conversation._idle_mode
        assert not window.chat.empty.isHidden()
        assert window.conversation.input.parent() is window.chat.empty.prompt_host
        assert window.conversation._parked_orbit.isHidden()
    finally:
        window.hide()
        window.loop.close()


def test_idle_keeps_one_orbit_when_docks_open(arelis_window) -> None:
    """A fade pixmap plus the live face is the two-orbit screenshot."""

    window = arelis_window()
    window._reset_layout()
    window.history_dock.show()
    window.camera_dock.show()
    sync_idle_mode(window)
    assert window.conversation.graphicsEffect() is None
    assert window.chat.empty.graphicsEffect() is None
    assert not window.chat.empty.isHidden()
    assert window.chat.view.isHidden()
    assert window.conversation._parked_orbit.isHidden()
    visible = [c for c in window.findChildren(OrbitCanvas) if not c.isHidden()]
    assert visible == [window.chat.empty.orbit]


def test_idle_prompt_grows_then_wraps(qt_app) -> None:
    from arelis.ui.app import ArelisWindow, BusBridge

    window = ArelisWindow(
        {
            "ui": {"default_width": 800, "default_height": 600, "theme": "sodium"},
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
        sentence = (
            "I want you to deeply research what JWST has discovered about "
            "the planet K2-12B's atmosphere. I want this research to be "
            "properly formatted"
        )
        window.conversation.input.setText(sentence)
        window.conversation._fit_idle_prompt()
        bar = window.conversation.input.verticalScrollBar()
        assert bar.maximum() == 0
        assert bar.value() == 0
        assert window.conversation.input.height() > 36
    finally:
        window.hide()
        window.loop.close()


def _orbit_center_in_window(window) -> tuple[int, int]:
    orbit = window.chat.empty.orbit
    pt = orbit.mapTo(window, orbit.rect().center())
    return pt.x(), pt.y()


def test_idle_orbit_takes_each_room_accent(qt_app) -> None:
    """Amber aether on sodium, her own violet on night, one painter for both."""
    from PySide6.QtGui import QImage, QPainter

    from arelis.ui.theme import apply_theme
    from arelis.ui.void_idle import AETHER, paint_aether_orbit

    frames = {}
    for room in ("sodium", "night"):
        apply_theme(room)
        image = QImage(220, 220, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paint_aether_orbit(painter, 110.0, 110.0, angle=90.0)
        painter.end()
        frames[room] = image.pixelColor(110 + 58, 106)
    apply_theme("sodium")
    amber, violet = frames["sodium"], frames["night"]
    assert amber.alpha() > 60 and violet.alpha() > 60
    assert amber.red() > amber.green() > amber.blue()
    assert violet.blue() > violet.red() > violet.green()
    assert abs(violet.hsvHue() - _hue(AETHER["violet"])) <= 12


def _hue(rgb: tuple[int, int, int]) -> int:
    from PySide6.QtGui import QColor

    return QColor(*rgb).hsvHue()
