"""Camera frame plus knuckle overlay. You look at this while we test tracking."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from arelis.spatial import HAND_BONES
from arelis.spatial.types import Hand
from arelis.ui.theme import color


def letterbox(widget: QWidget, image: QImage) -> QRect:
    if image.isNull() or widget.width() < 1 or widget.height() < 1:
        return QRect()
    iw, ih = image.width(), image.height()
    wr, hr = widget.width() / iw, widget.height() / ih
    scale = min(wr, hr)
    dw, dh = int(iw * scale), int(ih * scale)
    x = (widget.width() - dw) // 2
    y = (widget.height() - dh) // 2
    return QRect(x, y, dw, dh)


class HandPreview(QWidget):
    """Paints the live frame and, when present, 21 dots per hand."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image = QImage()
        self._hands: tuple[Hand, ...] = ()
        self._closed: frozenset[str] = frozenset()
        self._kinds: dict[str, str] = {}
        self._state = "idle"
        self._fps = 0.0
        self._live = False

    def set_frame(self, image: QImage) -> None:
        self._image = image
        self.update()

    def set_hands(
        self,
        hands: tuple[Hand, ...],
        closed: bool = False,
        state: str = "",
        fps: float = 0.0,
        closed_kinds: dict[str, str] | None = None,
        closed_labels: frozenset[str] | set[str] | None = None,
    ) -> None:
        self._hands = hands
        if closed_kinds is not None:
            self._kinds = {str(k): str(v) for k, v in closed_kinds.items()}
            self._closed = frozenset(self._kinds)
        elif closed_labels is not None:
            self._closed = frozenset(closed_labels)
            self._kinds = {name: "fist" for name in self._closed}
        elif closed:
            self._closed = frozenset(
                hand.label for hand in hands if getattr(hand, "label", "")
            )
            self._kinds = {name: "fist" for name in self._closed}
        else:
            self._closed = frozenset()
            self._kinds = {}
        self._state = (state or ("fist" if self._closed else "idle")).lower()
        self._fps = float(fps)
        self._live = True
        self.update()

    def clear_hands(self) -> None:
        self._hands = ()
        self._closed = frozenset()
        self._kinds = {}
        self._state = "idle"
        self._fps = 0.0
        self._live = False
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), color("bg0"))
        if self._image.isNull():
            painter.setPen(color("text_dim"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Camera")
            return
        dest = letterbox(self, self._image)
        if dest.isEmpty():
            return
        # Mirror the lab so it matches the world (operator left = screen left).
        painter.drawImage(dest, self._image.mirrored(True, False))
        if self._hands:
            for hand in self._hands:
                held = hand.label in self._closed
                bone = QPen(color("warn") if held else color("edge"))
                bone.setWidth(3 if held else 2)
                painter.setPen(bone)
                dot = QColor(color("text") if held else color("accent"))
                radius = 6 if held else 3
                pts = []
                for lm in hand.landmarks:
                    px = dest.x() + (1.0 - lm.x) * dest.width()
                    py = dest.y() + lm.y * dest.height()
                    pts.append((px, py))
                for a, b in HAND_BONES:
                    if a < len(pts) and b < len(pts):
                        painter.drawLine(
                            int(pts[a][0]), int(pts[a][1]), int(pts[b][0]), int(pts[b][1])
                        )
                painter.setBrush(dot)
                painter.setPen(Qt.PenStyle.NoPen)
                for px, py in pts:
                    painter.drawEllipse(
                        int(px) - radius, int(py) - radius, radius * 2 + 1, radius * 2 + 1
                    )
        if self._live:
            self._paint_banner(painter, dest)

    def _paint_banner(self, painter: QPainter, dest: QRect) -> None:
        n = len(self._hands)
        bits: list[str] = []
        for hand in self._hands:
            tag = hand.label[:1].upper() if hand.label else "?"
            if hand.label in self._closed:
                pose = self._kinds.get(hand.label, "fist").upper()
                bits.append(f"{tag} {pose}")
        label = " · ".join(bits) if bits else self._state.upper()
        text = f"{n} HAND{'S' if n != 1 else ''}   {self._fps:.0f} FPS   {label}"
        bar = QRect(dest.x(), dest.bottom() - 36, dest.width(), 36)
        painter.fillRect(bar, QColor(22, 13, 7, 210))
        painter.setPen(color("text"))
        font = QFont(painter.font())
        font.setPixelSize(18)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(bar, Qt.AlignmentFlag.AlignCenter, text)
