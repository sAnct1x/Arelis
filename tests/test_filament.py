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


def test_leaving_filament_times_each_step_of_the_relayout(arelis_window, qt_app, caplog) -> None:
    """The Atria line splits the leave relayout so its 370 ms has an owner."""
    import logging

    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    window.show()
    apply_window_theme(window, "filament", persist=False)
    window.act_contacts.trigger()
    qt_app.processEvents()
    with caplog.at_level(logging.INFO, logger="arelis.ui.timing"):
        apply_window_theme(window, "night", persist=False)
        qt_app.processEvents()
    line = next(r.getMessage() for r in caplog.records if "theme to=night" in r.getMessage())
    steps = ("leave_hide", "leave_unlock", "leave_chrome", "leave_docks", "leave_geometry")
    assert all(f" {step}=" in line for step in steps), line


def test_filament_menu_offers_the_language_actions(arelis_window) -> None:
    """Filament has no View menu, so its own menu is the only way to switch language."""
    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    window.show()
    apply_window_theme(window, "filament", persist=False)
    menu = window.filament._build_filament_menu()
    subs = {a.menu().title(): a.menu() for a in menu.actions() if a.menu() is not None}
    assert "Language" in subs
    assert subs["Language"].actions() == list(window._lang_actions.values())


def test_filament_days_tile_keeps_its_bar_buttons_readable(arelis_window, qt_app) -> None:
    """At 360 px the calendar bar was squeezed into empty pills; it wraps instead."""
    from PySide6.QtWidgets import QPushButton

    from arelis.ui.settings_host import apply_window_theme

    window = arelis_window()
    window.show()
    apply_window_theme(window, "filament", persist=False)
    window.act_calendar.trigger()
    from arelis.ui.filament_tile import DEFAULT_SIZES
    from arelis.ui.panels.calendar import CalendarMonthView

    cal = window.calendar_window
    cal.resize(*DEFAULT_SIZES["days"])
    for _ in range(5):
        qt_app.processEvents()
    assert cal.width() < 500
    # The wrapped bar costs rows: the tile grows so the month grid keeps its pre-wrap
    # 184 px (183 after other tests; 112 at the old 340 px height).
    assert cal.findChild(CalendarMonthView).height() >= 180
    buttons = [
        b
        for b in cal.findChildren(QPushButton)
        if b.isVisible() and b.objectName() == "InstrumentAction"
    ]
    assert len(buttons) >= 10
    for button in buttons:
        assert button.width() >= button.sizeHint().width(), button.text()
        assert button.mapTo(cal, button.rect().topRight()).x() < cal.width(), button.text()
