"""Night room: selectable Sodium GUI theme, palette, stylesheet, fallback."""

from __future__ import annotations

from arelis.ui.theme import (
    COLORS,
    DEFAULT_THEME,
    THEME_CHOICES,
    THEME_IDS,
    active_theme,
    apply_theme,
    resolve_theme_id,
    theme_from_config,
)
from arelis.ui.theme_tokens import _PALETTES


def test_night_is_listed_among_selectable_themes() -> None:
    assert "night" in THEME_IDS
    labels = dict(THEME_CHOICES)
    assert "night" in labels
    assert labels["night"] == "night"
    assert DEFAULT_THEME == "sodium"
    assert THEME_IDS[0] == "sodium"


def test_night_loads_without_error_and_has_required_keys() -> None:
    sodium_keys = set(_PALETTES["sodium"]["colors"])
    apply_theme("night")
    assert active_theme() == "night"
    assert set(COLORS) == sodium_keys
    for key in (
        "bg0",
        "panel_fill",
        "raised",
        "text",
        "hint",
        "accent",
        "hover",
        "row_selected",
        "well",
        "edge",
    ):
        assert key in COLORS
        assert COLORS[key]
    assert COLORS["bg0"].lower() == "#060a20"
    assert COLORS["text"].lower() == "#ffffff"
    assert COLORS["accent"].lower() == "#8050b0"
    apply_theme("sodium")
    assert active_theme() == "sodium"


def test_unknown_theme_still_falls_back_to_sodium() -> None:
    assert resolve_theme_id("bogus-night-xyz") == "sodium"
    assert resolve_theme_id(None) == "sodium"
    assert resolve_theme_id("") == "sodium"
    assert theme_from_config({"ui": {"theme": "not-a-real-theme"}}) == "sodium"
    assert theme_from_config({"ui": {"theme": "night"}}) == "night"


