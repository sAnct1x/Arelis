"""Thumb–index aperture on whichever HWND the hand is over. Not a turn."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from arelis.ui.theme import color


class HandCursorOverlay(QWidget):
    """Click-through paint of one or two apertures. Parent is the live HWND."""

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._hands: list[tuple[float, float, float, float, bool]] = []
        self.hide()

    def set_apertures(
        self,
        items: list[tuple[tuple[float, float], tuple[float, float], bool]]
        | tuple[tuple[tuple[float, float], tuple[float, float], bool], ...],
    ) -> None:
        """Each row is (thumb, index, closed) in 0–1 of this widget."""
        self._hands = [
            (
                float(thumb[0]),
                float(thumb[1]),
                float(index[0]),
                float(index[1]),
                bool(closed),
            )
            for thumb, index, closed in items
        ]
        if self._hands:
            self.show()
            self.raise_()
        else:
            self.hide()
        self.update()

    def clear(self) -> None:
        self._hands = []
        self.hide()
        self.update()

    def sync_to_host(self) -> None:
        host = self.parentWidget()
        if host is None:
            return
        self.setGeometry(host.rect())

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        if not self._hands:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = max(1, self.width()), max(1, self.height())
        for tx, ty, ix, iy, closed in self._hands:
            p0 = QPoint(int(tx * w), int(ty * h))
            p1 = QPoint(int(ix * w), int(iy * h))
            mid = QPoint((p0.x() + p1.x()) // 2, (p0.y() + p1.y()) // 2)
            if closed:
                glow = QRadialGradient(QPointF(mid), 28.0)
                core = color("accent2")
                core.setAlpha(90)
                edge = color("accent")
                edge.setAlpha(0)
                glow.setColorAt(0.0, core)
                glow.setColorAt(1.0, edge)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(glow)
                painter.drawEllipse(mid, 28, 28)
                ink = color("text")
                painter.setBrush(ink)
                painter.drawEllipse(mid, 5, 5)
                continue
            ink = color("accent2")
            pen = QPen(ink)
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawLine(p0, p1)
            painter.setBrush(ink)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(p0, 3, 3)
            painter.drawEllipse(p1, 3, 3)


def attach_overlay(host: QWidget) -> HandCursorOverlay:
    overlay = getattr(host, "_hand_cursor", None)
    if isinstance(overlay, HandCursorOverlay):
        overlay.sync_to_host()
        return overlay
    overlay = HandCursorOverlay(host)
    overlay.sync_to_host()
    host._hand_cursor = overlay  # type: ignore[attr-defined]
    return overlay


def paint_on(
    host: QWidget,
    items: list[tuple[tuple[float, float], tuple[float, float], bool]],
) -> None:
    overlay = attach_overlay(host)
    overlay.sync_to_host()
    overlay.set_apertures(items)


def clear_on(host: QWidget | None) -> None:
    if host is None:
        return
    overlay = getattr(host, "_hand_cursor", None)
    if isinstance(overlay, HandCursorOverlay):
        overlay.clear()
