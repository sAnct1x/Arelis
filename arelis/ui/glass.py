from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QWidget

from arelis.ui.theme import GLASS

# Shared slow rim breath — driven by the main window atmosphere timer.
_rim_pulse_phase = 0.0


def set_rim_pulse_phase(phase: float) -> None:
    """Set global rim pulse phase in radians (shared across all GlassFrames)."""
    global _rim_pulse_phase
    _rim_pulse_phase = float(phase) % 6.283185307179586


def rim_pulse_phase() -> float:
    return _rim_pulse_phase


def advance_rim_pulse(dt_seconds: float = 0.1) -> float:
    """Advance pulse by wall time; returns new phase."""
    period = max(1.5, float(GLASS.get("rim_pulse_seconds", 6.0)))
    set_rim_pulse_phase(_rim_pulse_phase + (6.283185307179586 * dt_seconds / period))
    return _rim_pulse_phase


def _pulse_rim_alpha(lo: int | None = None, hi: int | None = None) -> int:
    lo_a = int(GLASS.get("rim_pulse_lo", 36) if lo is None else lo)
    hi_a = int(GLASS.get("rim_pulse_hi", 70) if hi is None else hi)
    t = (math.sin(_rim_pulse_phase) + 1.0) * 0.5
    return int(lo_a + (hi_a - lo_a) * t)


class GlassFrame(QFrame):
    """Void plate — opaque warm fill on floats, amber hairline rim."""

    def __init__(
        self,
        parent=None,
        *,
        object_name: str = "GlassPanel",
        fill_alpha: int | None = None,
        radius: float | None = None,
        pulse_rim: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self._fill_alpha = int(
            GLASS.get("fill_docked", 72) if fill_alpha is None else fill_alpha
        )
        self._radius = float(GLASS.get("radius", 12.0) if radius is None else radius)
        self._pulse_rim = bool(pulse_rim)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def set_fill_alpha(self, fill_alpha: int) -> None:
        """Raise/lower body opacity (floating docks use smoked fill)."""
        self._fill_alpha = max(0, min(255, int(fill_alpha)))
        self.update()

    def set_pulse_rim(self, enabled: bool) -> None:
        self._pulse_rim = bool(enabled)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        a = self._fill_alpha
        # Idle conversation stage is a hole in the void — no plate, no rim.
        if a <= 4:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)

        # Near-opaque floating plates: seal the body so other HWNDs (chat) cannot
        # composite through. Void is a color, not a transparent HWND.
        if a >= 240:
            painter.fillPath(path, QColor(10, 8, 6, 255))
        body = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        body.setColorAt(0.0, QColor(22, 16, 12, min(255, a + 10)))
        body.setColorAt(0.42, QColor(12, 10, 8, a))
        body.setColorAt(1.0, QColor(8, 6, 5, max(28, a - 10)))
        painter.fillPath(path, body)

        sheen = QLinearGradient(rect.topLeft(), rect.bottomRight())
        sheen.setColorAt(0.0, QColor(255, 217, 168, 16))
        sheen.setColorAt(0.28, QColor(255, 180, 87, 6))
        sheen.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillPath(path, sheen)

        # Floats need an edge you can see. Docked plates never get here (alpha 0).
        # No outer glow — that was the three-TV silhouette.
        rim_a = 28 if not self._pulse_rim else _pulse_rim_alpha(18, 36)
        pen = QPen(QColor(255, 180, 87, rim_a))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)


def fade_in_widget(widget: QWidget, duration_ms: int = 280) -> QPropertyAnimation:
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setOpacity(0.0)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration_ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.start()
    widget._arelis_fade_anim = anim
    return anim
