"""Her place in the base UI: a fixed band of the stage, under chat and tiles.

Not wired yet. The persona dock still hosts her at runtime; see
team/avatar-v14k/base-ui-plan.md for the steps that move her here.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

BAND_SHARE = 0.28
BAND_MIN = 300
BAND_MAX = 560


def persona_region(stage: QRect, home_band: QRect | None = None) -> QRect:
    """The right band she owns: about 28% of the width, 300-560 px, full height.

    In a Filament span the band sits at the right of the home desk, not the
    union of desks. On a stage narrower than the minimum she gets all of it.
    """
    area = home_band.intersected(stage) if home_band is not None else QRect(stage)
    if area.isEmpty():
        area = QRect(stage)
    width = min(area.width(), max(BAND_MIN, min(BAND_MAX, round(area.width() * BAND_SHARE))))
    return QRect(area.right() + 1 - width, area.top(), width, area.height())


class PersonaStage(QWidget):
    """Click-through, see-through host for her panel, as a child of the stage."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PersonaStage")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

    def host(self, panel: QWidget) -> None:
        self.layout().addWidget(panel)

    def place(self, stage: QRect, home_band: QRect | None = None) -> None:
        self.setGeometry(persona_region(stage, home_band))
