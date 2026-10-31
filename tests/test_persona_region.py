"""Her base-UI band: right side, about 28% wide, 300-560 px, full height, inside the stage."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect

from arelis.ui.persona_stage import FIGURE_ASPECT, fit_figure, persona_region, region_mode


@pytest.mark.parametrize(
    ("stage", "home", "want"),
    [
        (QRect(0, 0, 1600, 900), None, QRect(1152, 0, 448, 900)),
        (QRect(0, 40, 800, 600), None, QRect(500, 40, 300, 600)),
        (QRect(0, 0, 3840, 2000), None, QRect(3280, 0, 560, 2000)),
        (QRect(0, 0, 260, 400), None, QRect(80, 0, 180, 400)),
        (QRect(0, 0, 5760, 1080), QRect(1920, 0, 1920, 1080), QRect(3302, 0, 538, 1080)),
    ],
)
def test_band_sits_right_clamped_and_inside(stage: QRect, home: QRect | None, want: QRect) -> None:
    got = persona_region(stage, home)
    assert got == want
    assert stage.contains(got)


@pytest.mark.parametrize(
    ("stage", "home", "want"),
    [
        (QRect(0, 0, 1600, 900), None, QRect(0, 495, 202, 405)),
        (QRect(0, 0, 3840, 2160), None, QRect(0, 1188, 486, 972)),
        (QRect(0, 0, 5760, 1080), QRect(1920, 0, 1920, 1080), QRect(1920, 594, 243, 486)),
        (QRect(0, 0, 400, 200), None, QRect(0, 0, 100, 200)),
    ],
)
def test_filament_hub_sits_bottom_left_and_inside(stage, home, want) -> None:
    got = persona_region(stage, home, mode=region_mode("Filament"))
    assert got == want
    assert stage.contains(got)
    assert region_mode("night") == region_mode("sodium") == "band"


@pytest.mark.parametrize(
    "region",
    [QRect(0, 0, 448, 900), QRect(500, 40, 300, 160), QRect(0, 0, 90, 900), QRect(10, 10, 1, 1)],
)
def test_her_figure_scales_down_to_fit_and_is_never_cropped(region: QRect) -> None:
    got = fit_figure(QRect(0, 0, 640, 1280), region)
    assert region.contains(got)
    assert got.bottom() == region.bottom()
    assert abs(got.width() - got.height() * FIGURE_ASPECT) <= 1
