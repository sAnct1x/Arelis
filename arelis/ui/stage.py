from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from arelis.ui.theme import BLOOM, COLORS, color

# Idle orbit locks to this point so History/Thinking can overlay the void
# without shoving the face. paint_atmosphere uses the same ratios.
BLOOM_X = 0.50
BLOOM_Y = 0.44

_rng = random.Random(7)
_GRAIN = [
    (_rng.random(), _rng.random(), _rng.randint(5, 11))
    for _ in range(280)
]


def paint_atmosphere(
    painter: QPainter,
    rect: QRect,
    *,
    drift: float = 0.0,
) -> None:
    """Warm void: amber bloom in the middle, not a cold black field."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    w, h = rect.width(), rect.height()
    if w <= 0 or h <= 0:
        return

    painter.fillRect(rect, QColor(COLORS["bg0"]))

    cx = rect.left() + w * BLOOM_X
    cy = rect.top() + h * BLOOM_Y
    # Wide ellipse-ish bloom: a large disc plus a softer wider one.
    inner = QRadialGradient(QPointF(cx, cy), max(w, h) * 0.58)
    for stop, rgba in BLOOM["inner"]:
        inner.setColorAt(stop, QColor(*rgba))
    inner.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.fillRect(rect, inner)

    outer = QRadialGradient(QPointF(cx, cy), max(w, h) * 0.88)
    for stop, rgba in BLOOM["outer"]:
        outer.setColorAt(stop, QColor(*rgba))
    outer.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.fillRect(rect, outer)

    grain_r, grain_g, grain_b = BLOOM["grain"]
    painter.setPen(Qt.PenStyle.NoPen)
    for x, y, a in _GRAIN:
        dx = math.sin(drift * 0.12 + x * 4.0) * 0.3
        dy = math.cos(drift * 0.10 + y * 4.0) * 0.2
        painter.setBrush(QColor(grain_r, grain_g, grain_b, a))
        painter.drawRect(QRectF(rect.left() + x * w + dx, rect.top() + y * h + dy, 1.0, 1.0))

    vr, vg, vb, va = BLOOM["vignette"]
    vignette = QRadialGradient(QPointF(cx, cy), max(w, h) * 0.92)
    vignette.setColorAt(0.0, QColor(0, 0, 0, 0))
    vignette.setColorAt(0.70, QColor(0, 0, 0, 0))
    vignette.setColorAt(1.0, QColor(vr, vg, vb, va))
    painter.fillRect(rect, vignette)


def paint_corner_ticks(
    painter: QPainter, rect: QRect, *, inset: int = 28, length: int = 14
) -> None:
    """HTML-style amber corner ticks on the shell."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    tick = color("accent")
    tick.setAlpha(150)
    pen = QPen(tick)
    pen.setWidthF(1.15)
    painter.setPen(pen)
    left = rect.left() + inset
    t = rect.top() + inset
    r = rect.right() - inset
    b = rect.bottom() - inset
    painter.drawLine(left, t, left + length, t)
    painter.drawLine(left, t, left, t + length)
    painter.drawLine(r, t, r - length, t)
    painter.drawLine(r, t, r, t + length)
    painter.drawLine(left, b, left + length, b)
    painter.drawLine(left, b, left, b - length)
    painter.drawLine(r, b, r - length, b)
    painter.drawLine(r, b, r, b - length)


class StageBackground(QWidget):
    """Transparent host for central content; atmosphere is painted by the main window."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("StageRoot")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event: QPaintEvent) -> None:
        # Intentionally empty — full-bleed atmosphere comes from ArelisWindow.
        return
