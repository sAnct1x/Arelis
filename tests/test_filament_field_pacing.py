"""The field timer is fixed per desk load: a slow paint no longer stretches the orbit."""

from __future__ import annotations

from arelis.ui.filament_field import FilamentField


def test_field_interval_is_fixed_and_ignores_paint_cost() -> None:
    field = FilamentField()
    assert field.atmosphere_ms() == 33
    field.set_load("camera")
    assert field.atmosphere_ms() == 50
    field.set_load("")
    field._paint_ms = 200.0  # the old pacing stretched to 100 ms on a slow cold paint
    assert field.atmosphere_ms() == 33
