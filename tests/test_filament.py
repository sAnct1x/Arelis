"""Filament room: palette, field, voice grant. Sodium stays the default."""

from __future__ import annotations

from arelis.tools.policy import (
    confirm_mode,
)
from arelis.ui.theme import COLORS, THEME_IDS, active_theme, apply_theme, color


def test_tile_opacity_clamps_and_loads() -> None:
    from arelis.ui.filament_tile import (
        clamp_opacity,
        load_opacities,
        load_tile_origins,
        load_tile_sizes,
    )

    assert clamp_opacity(0.01) == 0.15
    assert clamp_opacity(2.0) == 1.0
    assert clamp_opacity(0.8) == 0.8
    loaded = load_opacities({"ui": {"filament_opacity": {"history": 0.4, "bad": "x"}}})
    assert loaded["history"] == 0.4
    assert "bad" not in loaded
    sizes = load_tile_sizes(
        {"ui": {"filament_tile_size": {"history": {"w": 280, "h": 220}, "bad": 1}}}
    )
    assert sizes["history"] == (280, 220)
    assert "bad" not in sizes
    origins = load_tile_origins(
        {
            "ui": {
                "filament_tile_pos": {
                    "history": {"x": -2560, "y": 80},
                    "chat": {"x": 140, "y": 90},
                    "bad": 1,
                }
            }
        }
    )
    assert origins["history"] == (-2560, 80)
    assert origins["chat"] == (140, 90)
    assert "bad" not in origins


def test_filament_is_a_theme() -> None:
    assert "sodium" in THEME_IDS
    assert "filament" in THEME_IDS
    apply_theme("filament")
    assert active_theme() == "filament"
    from arelis.ui.aether_look import aether_rgb

    assert COLORS["accent"].lower() == "#{:02x}{:02x}{:02x}".format(*aether_rgb()["lilac"])
    assert confirm_mode() == "voice"
    apply_theme("sodium")
    assert active_theme() == "sodium"
    assert COLORS["accent"].lower() == "#ff7a22"
    hue = color("accent").hueF() * 360
    assert 18 <= hue <= 28
    assert confirm_mode() == "card"


def test_filament_confirm_arms_without_a_card(arelis_window) -> None:
    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    apply_window_theme(window, "filament", persist=False)
    try:
        stage = window.conversation
        stage.ask_confirm(
            "c1",
            "workspace",
            "workspace()",
            headline="delete note.txt",
            batch_ok=True,
            persist_ok=True,
            persist_label="don't ask again about files",
        )
        assert stage.confirm_open()
        assert stage.confirm.isHidden()
        assert not stage.confirm.allow_always.isVisible()
        assert not stage.confirm.allow_turn.isVisible()
        assert stage.confirm.allow_always.isChecked() is False
        decided: list[tuple[str, bool]] = []
        stage.confirm.decided.connect(
            lambda _id, decision, batch: decided.append((decision, batch))
        )
        stage.input.setText("yes")
        stage._submit()
        assert decided == [("allow", False)]
        assert not stage.confirm_open()
    finally:
        apply_window_theme(window, "sodium", persist=False)




def test_leaving_filament_hides_unkept_tiles_before_unlocking_them(arelis_window, qt_app) -> None:
    """A tile Sodium will not keep is hidden before it is relaid out or re-opacified."""
    from PySide6.QtCore import QEvent, QObject

    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    window.show()
    apply_window_theme(window, "filament", persist=False)
    window.act_calendar.trigger()
    qt_app.processEvents()
    cal = window.calendar_window
    assert cal.isVisible()

    class _Resized(QObject):
        seen = 0

        def eventFilter(self, obj, event):  # type: ignore[override]
            if event.type() == QEvent.Type.Resize and obj.isWidgetType() and obj.isVisible():
                if obj is cal or cal.isAncestorOf(obj):
                    self.seen += 1
            return False

    spy = _Resized()
    qt_app.installEventFilter(spy)
    try:
        apply_window_theme(window, "sodium", persist=False)
    finally:
        qt_app.removeEventFilter(spy)
    assert cal.isHidden()
    assert spy.seen == 0
