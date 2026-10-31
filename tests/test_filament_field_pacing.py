"""The filament field slows its own repaint when a paint is expensive, so her frames keep the UI thread."""

from __future__ import annotations

from arelis.ui.filament_field import FilamentField


def test_field_interval_follows_paint_cost() -> None:
    field = FilamentField()
    assert field.atmosphere_ms() == 33
    for _ in range(40):
        field.note_paint_ms(25.0)
    assert 70 <= field.atmosphere_ms() <= 100
    for _ in range(40):
        field.note_paint_ms(200.0)
    assert field.atmosphere_ms() == 100
    for _ in range(60):
        field.note_paint_ms(2.0)
    assert field.atmosphere_ms() == 33
