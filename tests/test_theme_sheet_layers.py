"""The room sheet splits into one fixed structural layer and a colour layer.

A room switch can then leave the app-level sheet alone, which is what kept
Qt from re-matching every widget in every window on each switch.
"""

from __future__ import annotations

from arelis.ui import theme
from arelis.ui.theme_layers import COLOUR_FAMILIES, split_sheet


def _decls(layer: str) -> list[str]:
    return [d.strip().split(":", 1)[0] for body in layer.split("{")[1:] for d in body.split("}")[0].split(";") if d.strip()]


def test_structure_is_the_same_in_every_room_and_colour_holds_only_colour() -> None:
    before = theme.active_theme()
    try:
        layers = {}
        for tid in theme.THEME_IDS:
            theme.apply_theme(tid)
            layers[tid] = split_sheet(theme.stylesheet())
    finally:
        theme.apply_theme(before)
    structural = {s for s, _ in layers.values()}
    assert len(structural) == 1
    for _, colour in layers.values():
        assert colour
        assert all(p.strip().lower().startswith(COLOUR_FAMILIES) for p in _decls(colour))
    assert not any(p.strip().lower().startswith(COLOUR_FAMILIES) for p in _decls(structural.pop()))
