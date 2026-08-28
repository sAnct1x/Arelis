"""Composer attachment rail: Cursor-style tiles above the prompt, never inside it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arelis.attachments import resolve_staged_path
from arelis.ui.theme import COLORS

# One thumbnail height. Images keep their aspect (clamped); files are square.
# Not a METRICS control: this is a picture rail, not a button row.
ATTACH_TILE = 56
_MAX_ASPECT = 1.7
_RADIUS = 8.0
_ACCENT = QColor(COLORS["accent"])
_TEXT_DIM = QColor(COLORS["text_dim"])


def tile_pixel_size(src_w: int, src_h: int, *, height: int = ATTACH_TILE) -> tuple[int, int]:
    """Cover-crop target: same height, width from aspect, portrait becomes square."""
    if src_w <= 0 or src_h <= 0:
        return height, height
    aspect = src_w / src_h
    width = round(height * min(max(aspect, 1.0), _MAX_ASPECT))
    return width, height


def cover_crop_pixmap(source: QPixmap, width: int, height: int) -> QPixmap:
    """Scale to fill ``width``×``height`` and crop the center. Empty on failure."""
    if source.isNull() or width <= 0 or height <= 0:
        return QPixmap()
    pixmap = source
    if pixmap.width() > 2048 or pixmap.height() > 2048:
        pixmap = pixmap.scaled(
            2048,
            2048,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
    scaled = pixmap.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - width) // 2)
    y = max(0, (scaled.height() - height) // 2)
    return scaled.copy(x, y, width, height)


def _file_for_tile(item: dict[str, Any]) -> Path | None:
    for key in ("path", "source_path"):
        found = resolve_staged_path(str(item.get(key) or ""))
        if found is not None:
            return found
    return None


class _HScroll(QScrollArea):
    """Trackpad/wheel moves the rail sideways. Vertical scroll would be empty."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta()
        step = delta.x() if delta.x() else delta.y()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - step)
        event.accept()


class AttachmentTile(QWidget):
    """One rail tile: cover-cropped image, or a hairline file card. No grey fill."""

    remove_requested = Signal(str)

    def __init__(self, attachment: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AttachmentTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAutoFillBackground(False)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.attachment_id = str(attachment.get("id") or "")
        self._name = str(
            attachment.get("name") or Path(str(attachment.get("path") or "")).name or "file"
        )
        self._kind = str(attachment.get("kind") or "other")
        path = str(attachment.get("path") or "")
        source = str(attachment.get("source_path") or "")
        tip = path if not source else f"{path}\nfrom {source}"
        self.setToolTip(tip)

        self._image = False
        self._pixmap = QPixmap()
        file_path = _file_for_tile(attachment)
        if self._kind == "image" and file_path is not None:
            raw = QPixmap(str(file_path))
            if not raw.isNull():
                self._image = True
                width, height = tile_pixel_size(raw.width(), raw.height())
                dpr = max(1.0, float(self.devicePixelRatioF()))
                cropped = cover_crop_pixmap(
                    raw,
                    max(1, round(width * dpr)),
                    max(1, round(height * dpr)),
                )
                cropped.setDevicePixelRatio(dpr)
                self._pixmap = cropped
                self.setFixedSize(width, height)

        if not self._image:
            self.setFixedSize(ATTACH_TILE, ATTACH_TILE)

        btn = QToolButton(self)
        btn.setObjectName(
            "AttachmentTileRemoveOnPhoto" if self._image else "AttachmentTileRemove"
        )
        btn.setText("\u00d7")
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("Remove attachment")
        btn.setFixedSize(16, 16)
        btn.clicked.connect(lambda: self.remove_requested.emit(self.attachment_id))
        self._remove = btn

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._remove.move(self.width() - self._remove.width() - 3, 3)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(rect, _RADIUS, _RADIUS)
        painter.setClipPath(clip)
        if self._image and not self._pixmap.isNull():
            painter.drawPixmap(QRect(0, 0, self.width(), self.height()), self._pixmap)
        else:
            self._paint_file(painter, rect)
        painter.setClipping(False)
        hover = self.underMouse()
        rim = QColor(_ACCENT)
        rim.setAlpha(200 if hover else 110)
        painter.setPen(QPen(rim, 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, _RADIUS, _RADIUS)

    def _paint_file(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        mark = _kind_mark(self._kind)
        glyph = QFont(self.font())
        glyph.setPixelSize(13)
        glyph.setBold(True)
        painter.setFont(glyph)
        painter.setPen(_ACCENT)
        painter.drawText(
            QRectF(rect.left(), rect.top() + 8, rect.width(), 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            mark,
        )
        name_font = QFont(self.font())
        name_font.setPixelSize(10)
        painter.setFont(name_font)
        painter.setPen(_TEXT_DIM)
        metrics = QFontMetrics(name_font)
        elided = metrics.elidedText(
            self._name,
            Qt.TextElideMode.ElideMiddle,
            max(8, int(rect.width()) - 10),
        )
        painter.drawText(
            QRectF(rect.left() + 4, rect.bottom() - 18, rect.width() - 8, 16),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            elided,
        )


class AttachBar(QWidget):
    """Horizontal tile rail above the composer. Hidden when empty. Never grey."""

    remove_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("AttachBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(False)
        self._items: dict[str, dict[str, Any]] = {}
        self.setVisible(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 6)
        outer.setSpacing(0)

        scroll = _HScroll()
        scroll.setObjectName("AttachBarScroll")
        scroll.setWidgetResizable(False)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        scroll.setFixedHeight(ATTACH_TILE)
        self._scroll = scroll

        self._inner = QWidget()
        self._inner.setObjectName("AttachBarInner")
        self._inner.setAutoFillBackground(False)
        self._row = QHBoxLayout(self._inner)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(8)
        self._row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        scroll.setWidget(self._inner)
        outer.addWidget(scroll)

    def attachments(self) -> list[dict[str, Any]]:
        return list(self._items.values())

    def count(self) -> int:
        return len(self._items)

    def add_many(self, items: list[dict[str, Any]]) -> None:
        for item in items:
            aid = str(item.get("id") or "")
            if not aid or aid in self._items:
                continue
            self._items[aid] = dict(item)
            tile = AttachmentTile(item, self._inner)
            tile.remove_requested.connect(self.remove)
            self._row.addWidget(tile, 0, Qt.AlignmentFlag.AlignLeft)
        self._refresh()

    def remove(self, attachment_id: str) -> None:
        aid = str(attachment_id or "")
        self._items.pop(aid, None)
        for i in range(self._row.count() - 1, -1, -1):
            widget = self._row.itemAt(i).widget()
            if isinstance(widget, AttachmentTile) and widget.attachment_id == aid:
                self._row.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()
                break
        self._refresh()
        self.remove_requested.emit(aid)

    def clear(self) -> None:
        for i in range(self._row.count() - 1, -1, -1):
            widget = self._row.itemAt(i).widget()
            if isinstance(widget, AttachmentTile):
                self._row.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()
        self._items.clear()
        self._refresh()

    def _tiles(self) -> list[AttachmentTile]:
        found: list[AttachmentTile] = []
        for i in range(self._row.count()):
            widget = self._row.itemAt(i).widget()
            if isinstance(widget, AttachmentTile):
                found.append(widget)
        return found

    def _fit_inner(self) -> None:
        tiles = self._tiles()
        gap = self._row.spacing()
        width = sum(tile.width() for tile in tiles)
        if tiles:
            width += gap * (len(tiles) - 1)
        self._inner.setFixedSize(max(width, 1), ATTACH_TILE)

    def _refresh(self) -> None:
        self._fit_inner()
        n = len(self._items)
        self.setVisible(bool(n))
        self.setFixedHeight(ATTACH_TILE + 10 if n else 0)


class DropOverlay(QWidget):
    """Full-panel hint while dragging files over the conversation stage."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DropOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        label = QLabel("Drop files for Arelis")
        label.setObjectName("DropOverlayTitle")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        hint = QLabel("They will attach to your next message")
        hint.setObjectName("DropOverlayHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.hide()


def _kind_mark(kind: str) -> str:
    return {
        "text": "T",
        "data": "#",
        "pdf": "P",
        "image": "I",
        "other": "·",
    }.get(kind, "·")


AttachmentChip = AttachmentTile
