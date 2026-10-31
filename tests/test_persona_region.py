"""Her base-UI band: right side, about 28% wide, 300-560 px, full height, inside the stage."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect

from arelis.ui.persona_stage import persona_region


@pytest.mark.parametrize(
    ("stage", "home", "want"),
    [
        (QRect(0, 0, 1600, 900), None, QRect(1152, 0, 448, 900)),
        (QRect(0, 40, 800, 600), None, QRect(500, 40, 300, 600)),
        (QRect(0, 0, 3840, 2000), None, QRect(3280, 0, 560, 2000)),
        (QRect(0, 0, 260, 400), None, QRect(0, 0, 260, 400)),
        (QRect(0, 0, 5760, 1080), QRect(1920, 0, 1920, 1080), QRect(3302, 0, 538, 1080)),
    ],
)
def test_band_sits_right_clamped_and_inside(stage: QRect, home: QRect | None, want: QRect) -> None:
    got = persona_region(stage, home)
    assert got == want
    assert stage.contains(got)
